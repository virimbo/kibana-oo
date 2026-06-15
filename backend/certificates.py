"""TLS certificate expiry. Two sources, merged:
  1. Kibana monitoring data (Heartbeat / Synthetics) — read-only discovery.
  2. An ACTIVE probe of configured public hosts — opens a TLS connection, reads
     the leaf certificate (even when the chain is untrusted, so the expiry is
     always visible) and reports trust / chain / hostname / expiry issues.
The active probe makes the countdown and any problems visible even when no
Heartbeat data exists. Read-only outbound TLS; the unverified read is ONLY to
display the certificate's own dates — trust is judged by a separate verified
handshake."""
import asyncio
import hashlib
import logging
import socket
import ssl
from datetime import datetime, timezone

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID, NameOID
from pydantic import BaseModel

from elastic import _es_search
from config import settings

logger = logging.getLogger(__name__)

# Status thresholds (days remaining).
WARNING_DAYS = 30
CRITICAL_DAYS = 14


class ChainCert(BaseModel):
    """One certificate in the served chain (chainsmith-style breakdown)."""
    position: str                   # leaf | intermediate | root
    subject: str | None = None
    issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    days_remaining: int | None = None
    expired: bool = False
    serial: str | None = None
    sha256: str | None = None
    sig_algorithm: str | None = None
    key_type: str | None = None     # e.g. "RSA 2048" / "EC secp384r1"
    self_signed: bool = False
    ocsp: str | None = None         # good | revoked | unknown | None (not checked)


class Finding(BaseModel):
    level: str                      # ok | note | warn | bad
    text: str


class Certificate(BaseModel):
    host: str
    common_name: str | None = None
    issuer: str | None = None
    not_after: str
    days_remaining: int
    status: str  # ok | warning | critical | expired
    issues: list[str] = []          # trust / chain / hostname / expiry problems
    source: str = "monitor"         # "monitor" (Kibana) | "probe" (active TLS check)
    reachable: bool = True          # False when the host could not be connected to
    # ── Comprehensive audit (active probe only) ──────────────────────────────
    grade: str | None = None        # OK | WARN | CRITICAL
    findings: list[Finding] = []    # graded, human-readable audit results
    chain: list[ChainCert] = []     # leaf → intermediate(s) → root
    chain_complete: bool | None = None
    contains_anchor: bool | None = None   # server also sends the root (should omit)
    tls_versions: dict[str, bool] | None = None  # {"TLS 1.0": False, ... "TLS 1.3": True}
    hsts: bool | None = None        # HTTP Strict-Transport-Security present
    san: list[str] = []             # subject alternative names on the leaf
    checked_at: str | None = None   # ISO timestamp of this audit


def _dig(d: object, *path: str):
    """Safely walk a nested dict by keys, returning None if any step is missing."""
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _parse_dt(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def cert_status(days_remaining: int) -> str:
    if days_remaining < 0:
        return "expired"
    if days_remaining < CRITICAL_DAYS:
        return "critical"
    if days_remaining < WARNING_DAYS:
        return "warning"
    return "ok"


def _query() -> dict:
    """Latest docs that carry a TLS certificate expiry (ECS or legacy field)."""
    return {
        "size": 200,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "minimum_should_match": 1,
                "should": [
                    {"exists": {"field": "tls.server.x509.not_after"}},
                    {"exists": {"field": "tls.certificate_not_valid_after"}},
                ],
            }
        },
        "_source": ["tls", "url", "monitor", "@timestamp"],
    }


def parse_certificates(hits: list[dict], now: datetime | None = None) -> list[Certificate]:
    now = now or datetime.now(timezone.utc)
    seen: set[str] = set()
    certs: list[Certificate] = []
    for hit in hits:
        src = hit.get("_source", {})
        expiry = _parse_dt(
            _dig(src, "tls", "server", "x509", "not_after")
            or _dig(src, "tls", "certificate_not_valid_after")
        )
        if expiry is None:
            continue
        host = (
            _dig(src, "url", "domain")
            or _dig(src, "monitor", "name")
            or _dig(src, "tls", "server", "x509", "subject", "common_name")
            or _dig(src, "url", "full")
            or "(unknown)"
        )
        if host in seen:  # hits are newest-first; keep the most recent per host
            continue
        seen.add(host)
        days = (expiry - now).days
        certs.append(
            Certificate(
                host=host,
                common_name=_dig(src, "tls", "server", "x509", "subject", "common_name"),
                issuer=(
                    _dig(src, "tls", "server", "x509", "issuer", "common_name")
                    or _dig(src, "tls", "server", "x509", "issuer", "distinguished_name")
                ),
                not_after=expiry.isoformat(),
                days_remaining=days,
                status=cert_status(days),
            )
        )
    certs.sort(key=lambda c: c.days_remaining)
    return certs


# ── Active TLS probe ─────────────────────────────────────────────────────────
def _common_name(name: x509.Name) -> str | None:
    try:
        attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
        return attrs[0].value if attrs else None
    except Exception:  # noqa: BLE001
        return None


def _leaf_certificate_der(host: str, port: int, timeout: float) -> bytes:
    """The server's leaf certificate as DER, read WITHOUT verification so we can
    always show its dates — even when the chain is untrusted or incomplete."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False              # we only read the cert's own dates here…
    ctx.verify_mode = ssl.CERT_NONE         # …trust is judged separately in _trust_issue
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def _trust_issue(host: str, port: int, timeout: float) -> str | None:
    """Do a fully-verified handshake; return a human label for the trust problem,
    or None when the certificate is trusted and the hostname matches."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return None
    except ssl.SSLCertVerificationError as e:
        msg = (getattr(e, "verify_message", "") or str(e)).lower()
        if "self" in msg and "signed" in msg:
            return "self-signed / not trusted"
        if "unable to get local issuer" in msg or "incomplete" in msg:
            return "incomplete certificate chain"
        if "hostname mismatch" in msg or ("host" in msg and "match" in msg):
            return "hostname mismatch"
        if "expired" in msg:
            return "certificate expired"
        return "certificate not trusted"
    except (ssl.SSLError, OSError):
        return None  # connection-level problem is reported separately by the leaf read


def _served_chain_der(host: str, port: int, timeout: float) -> tuple[list[bytes], str | None]:
    """Every certificate the server SENDS (leaf → intermediate(s) → maybe root),
    as DER, plus the negotiated TLS version. Unverified so it works even when the
    chain is broken. Python 3.13's get_unverified_chain() may yield bytes or
    objects with public_bytes() — handle both."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            version = tls.version()
            ders: list[bytes] = []
            try:
                for entry in tls.get_unverified_chain() or []:
                    if isinstance(entry, (bytes, bytearray)):
                        ders.append(bytes(entry))
                    elif hasattr(entry, "public_bytes"):
                        ders.append(entry.public_bytes(ssl.DER))
            except (AttributeError, ssl.SSLError):
                pass
            if not ders:  # fall back to the leaf only
                leaf = tls.getpeercert(binary_form=True)
                if leaf:
                    ders.append(leaf)
            return ders, version


def _subject_str(name: x509.Name) -> str | None:
    cn = _common_name(name)
    try:
        org = name.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        org_val = org[0].value if org else None
    except Exception:  # noqa: BLE001
        org_val = None
    if cn and org_val:
        return f"{cn} ({org_val})"
    return cn or org_val


def _key_type(cert: x509.Certificate) -> str | None:
    try:
        key = cert.public_key()
        if isinstance(key, rsa.RSAPublicKey):
            return f"RSA {key.key_size}"
        if isinstance(key, ec.EllipticCurvePublicKey):
            return f"EC {key.curve.name}"
        return type(key).__name__
    except Exception:  # noqa: BLE001
        return None


def _san_list(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        return ext.value.get_values_for_type(x509.DNSName)
    except Exception:  # noqa: BLE001
        return []


def _weak_signature(cert: x509.Certificate) -> bool:
    try:
        alg = cert.signature_hash_algorithm
        return isinstance(alg, (hashes.SHA1, hashes.MD5))
    except Exception:  # noqa: BLE001
        return False


def _build_chain(ders: list[bytes], now: datetime) -> list[ChainCert]:
    """Parse each served certificate into a ChainCert, classifying leaf / root /
    intermediate by position and self-signedness."""
    out: list[ChainCert] = []
    for i, der in enumerate(ders):
        try:
            cert = x509.load_der_x509_certificate(der)
        except Exception:  # noqa: BLE001
            continue
        self_signed = cert.issuer == cert.subject
        if i == 0:
            position = "leaf"
        elif self_signed:
            position = "root"
        else:
            position = "intermediate"
        not_after = cert.not_valid_after_utc
        out.append(ChainCert(
            position=position,
            subject=_subject_str(cert.subject),
            issuer=_subject_str(cert.issuer),
            not_before=cert.not_valid_before_utc.isoformat(),
            not_after=not_after.isoformat(),
            days_remaining=(not_after - now).days,
            expired=not_after < now,
            serial=f"0x{cert.serial_number:x}",
            sha256=hashlib.sha256(der).hexdigest(),
            sig_algorithm=getattr(cert.signature_algorithm_oid, "_name", None),
            key_type=_key_type(cert),
            self_signed=self_signed,
        ))
    return out


def _chain_order_ok(ders: list[bytes]) -> bool:
    """Each certificate must be issued by the next one in the served order."""
    try:
        certs = [x509.load_der_x509_certificate(d) for d in ders]
    except Exception:  # noqa: BLE001
        return True
    return all(certs[i].issuer == certs[i + 1].subject for i in range(len(certs) - 1))


def _tls_version_support(host: str, port: int, timeout: float) -> dict[str, bool]:
    """Which TLS versions the server accepts. Old versions enabled = a finding."""
    versions = {
        "TLS 1.0": ssl.TLSVersion.TLSv1,
        "TLS 1.1": ssl.TLSVersion.TLSv1_1,
        "TLS 1.2": ssl.TLSVersion.TLSv1_2,
        "TLS 1.3": ssl.TLSVersion.TLSv1_3,
    }
    out: dict[str, bool] = {}
    for label, ver in versions.items():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.minimum_version = ver
            ctx.maximum_version = ver
        except ValueError:
            out[label] = False  # this build refuses to even offer the version
            continue
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    out[label] = tls.version() is not None
        except Exception:  # noqa: BLE001
            out[label] = False
    return out


def _hsts_enabled(host: str, port: int, timeout: float) -> bool | None:
    """True when the host sends a Strict-Transport-Security header."""
    try:
        url = f"https://{host}{'' if port == 443 else f':{port}'}/"
        resp = httpx.get(url, timeout=timeout, follow_redirects=False, verify=True)
        return "strict-transport-security" in {k.lower() for k in resp.headers}
    except Exception:  # noqa: BLE001
        return None


def _ocsp_check(cert: x509.Certificate, issuer: x509.Certificate, timeout: float) -> str | None:
    """Best-effort OCSP revocation check. Returns good | revoked | unknown, or
    None when the certificate advertises no OCSP responder. Never raises."""
    try:
        aia = cert.extensions.get_extension_for_oid(
            ExtensionOID.AUTHORITY_INFORMATION_ACCESS
        ).value
        urls = [
            d.access_location.value
            for d in aia
            if d.access_method == AuthorityInformationAccessOID.OCSP
        ]
        if not urls:
            return None
        req = ocsp.OCSPRequestBuilder().add_certificate(cert, issuer, hashes.SHA1()).build()
        resp = httpx.post(
            urls[0],
            content=req.public_bytes(serialization.Encoding.DER),
            headers={"Content-Type": "application/ocsp-request"},
            timeout=timeout,
        )
        resp.raise_for_status()
        ocsp_resp = ocsp.load_der_ocsp_response(resp.content)
        if ocsp_resp.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            return "unknown"
        if ocsp_resp.certificate_status == ocsp.OCSPCertStatus.GOOD:
            return "good"
        if ocsp_resp.certificate_status == ocsp.OCSPCertStatus.REVOKED:
            return "revoked"
        return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _annotate_ocsp(ders: list[bytes], chain: list[ChainCert], timeout: float) -> None:
    """Fill in each chain entry's OCSP status. Each cert's issuer is the next one
    in the served chain; the root (self-signed) is skipped."""
    try:
        certs = [x509.load_der_x509_certificate(d) for d in ders]
    except Exception:  # noqa: BLE001
        return
    if len(certs) != len(chain):  # parsing desynced — don't risk wrong pairings
        return
    for i, entry in enumerate(chain):
        if entry.position == "root" or i + 1 >= len(certs):
            continue
        entry.ocsp = _ocsp_check(certs[i], certs[i + 1], timeout)


def _grade_and_findings(
    *, days: int, trust: str | None, chain: list[ChainCert], contains_anchor: bool,
    chain_complete: bool, order_ok: bool, ders: list[bytes],
    tls_versions: dict[str, bool], hsts: bool | None,
) -> tuple[str, list[Finding]]:
    """Compute a composite grade (OK/WARN/CRITICAL) with chainsmith-style findings.
    `bad` ⇒ CRITICAL, `warn` ⇒ WARN, otherwise OK. `note`/`ok` never downgrade."""
    f: list[Finding] = []

    # Trust / chain validity (the heart of it).
    if trust:
        level = "bad"
        f.append(Finding(level=level, text=f"Chain not trusted: {trust}."))
    elif not chain_complete:
        f.append(Finding(level="bad", text="Incomplete chain — a required intermediate is missing."))
    elif not order_ok:
        f.append(Finding(level="warn", text="Certificates are served out of order."))
    else:
        f.append(Finding(level="ok", text="Served chain is correctly configured."))

    if contains_anchor:
        f.append(Finding(level="note", text="Server also sends the root CA (anchor) — harmless, but should be omitted."))

    # Expiry (leaf).
    if days < 0:
        f.append(Finding(level="bad", text="Leaf certificate has EXPIRED."))
    elif days < CRITICAL_DAYS:
        f.append(Finding(level="bad", text=f"Leaf expires in {days} days."))
    elif days < WARNING_DAYS:
        f.append(Finding(level="warn", text=f"Leaf expires in {days} days."))
    else:
        f.append(Finding(level="ok", text=f"Leaf valid for {days} more days."))

    # Revocation.
    revoked = [c for c in chain if c.ocsp == "revoked"]
    if revoked:
        f.append(Finding(level="bad", text="A certificate in the chain is REVOKED (OCSP)."))
    elif any(c.ocsp == "good" for c in chain):
        f.append(Finding(level="ok", text="Revocation OK (OCSP: good)."))

    # Key / signature strength.
    for c in chain:
        if c.key_type and c.key_type.startswith("RSA ") and c.key_type[4:].isdigit() and int(c.key_type[4:]) < 2048:
            f.append(Finding(level="warn", text=f"Weak key on {c.position}: {c.key_type}."))
    try:
        for d in ders:
            if _weak_signature(x509.load_der_x509_certificate(d)):
                f.append(Finding(level="warn", text="Weak signature algorithm (SHA-1/MD5) in the chain."))
                break
    except Exception:  # noqa: BLE001
        pass

    # Protocol hygiene.
    if tls_versions:
        legacy = [v for v in ("TLS 1.0", "TLS 1.1") if tls_versions.get(v)]
        if legacy:
            f.append(Finding(level="warn", text=f"Legacy protocol enabled: {', '.join(legacy)}."))
        elif tls_versions.get("TLS 1.3") or tls_versions.get("TLS 1.2"):
            f.append(Finding(level="ok", text="Only modern TLS (1.2/1.3) is enabled."))

    if hsts is True:
        f.append(Finding(level="ok", text="HSTS enabled."))
    elif hsts is False:
        f.append(Finding(level="warn", text="HSTS header not set."))

    if any(x.level == "bad" for x in f):
        grade = "CRITICAL"
    elif any(x.level == "warn" for x in f):
        grade = "WARN"
    else:
        grade = "OK"
    return grade, f


def _probe_host_sync(host: str, port: int, timeout: float, now: datetime) -> Certificate:
    """Comprehensive active audit of one host: served chain breakdown, trust,
    completeness, anchor/order, revocation (OCSP), protocol versions, HSTS, and a
    composite grade — the chainsmith + SSL-Labs style check, in one card."""
    try:
        ders, _tls_version = _served_chain_der(host, port, timeout)
    except (ssl.SSLError, OSError) as e:
        return Certificate(
            host=host, not_after="", days_remaining=-99999, status="critical",
            issues=[f"could not connect ({type(e).__name__})"], source="probe", reachable=False,
            grade="CRITICAL", checked_at=now.isoformat(),
        )
    if not ders:
        return Certificate(
            host=host, not_after="", days_remaining=-99999, status="critical",
            issues=["no certificate presented"], source="probe", reachable=False,
            grade="CRITICAL", checked_at=now.isoformat(),
        )

    leaf = x509.load_der_x509_certificate(ders[0])
    not_after = leaf.not_valid_after_utc
    days = (not_after - now).days

    issues: list[str] = []
    if days < 0:
        issues.append("certificate EXPIRED")
    trust = _trust_issue(host, port, timeout)
    if trust:
        issues.append(trust)
    if leaf.issuer == leaf.subject and not any("self-signed" in i for i in issues):
        issues.append("self-signed certificate")

    # ── Comprehensive audit ──────────────────────────────────────────────────
    chain = _build_chain(ders, now)
    contains_anchor = any(c.position == "root" for c in chain)
    order_ok = _chain_order_ok(ders)
    chain_complete = trust is None or "incomplete" not in (trust or "").lower()
    extras_timeout = min(timeout, 4.0)  # keep the slow network extras snappy
    if settings.cert_check_revocation:
        _annotate_ocsp(ders, chain, extras_timeout)
    tls_versions = _tls_version_support(host, port, extras_timeout)
    hsts = _hsts_enabled(host, port, extras_timeout)
    san = _san_list(leaf)

    grade, findings = _grade_and_findings(
        days=days, trust=trust, chain=chain, contains_anchor=contains_anchor,
        chain_complete=chain_complete, order_ok=order_ok, ders=ders,
        tls_versions=tls_versions, hsts=hsts,
    )

    status = cert_status(days)
    if grade == "CRITICAL" and status == "ok":
        status = "critical"
    elif grade == "WARN" and status == "ok":
        status = "warning"

    return Certificate(
        host=host,
        common_name=_common_name(leaf.subject),
        issuer=_common_name(leaf.issuer),
        not_after=not_after.isoformat(),
        days_remaining=days,
        status=status,
        issues=issues,
        source="probe",
        reachable=True,
        grade=grade,
        findings=findings,
        chain=chain,
        chain_complete=chain_complete,
        contains_anchor=contains_anchor,
        tls_versions=tls_versions,
        hsts=hsts,
        san=san,
        checked_at=now.isoformat(),
    )


def _parse_probe_target(raw: str) -> tuple[str, int]:
    raw = raw.strip()
    if ":" in raw:
        host, _, port = raw.rpartition(":")
        if port.isdigit():
            return host, int(port)
    return raw, 443


async def probe_certificates(now: datetime | None = None) -> list[Certificate]:
    """Actively probe each configured public host's TLS certificate."""
    now = now or datetime.now(timezone.utc)
    targets = [_parse_probe_target(h) for h in settings.cert_probe_hosts.split(",") if h.strip()]
    timeout = settings.cert_probe_timeout
    results = await asyncio.gather(
        *(asyncio.to_thread(_probe_host_sync, host, port, timeout, now) for host, port in targets),
        return_exceptions=True,
    )
    out: list[Certificate] = []
    for res, (host, _) in zip(results, targets):
        if isinstance(res, Exception):
            logger.warning(f"Certificate probe failed for {host}: {res}")
            out.append(Certificate(
                host=host, not_after="", days_remaining=-99999, status="critical",
                issues=["probe failed"], source="probe", reachable=False,
            ))
        else:
            out.append(res)
    return out


async def fetch_certificates(sid: str, now: datetime | None = None) -> list[Certificate]:
    """Active probe of the configured public hosts MERGED with Kibana monitoring
    data. The probe is authoritative for its hosts (it's live); Kibana fills in
    any other monitored hosts. Sorted most-urgent first."""
    now = now or datetime.now(timezone.utc)
    indices = [i.strip() for i in settings.cert_index.split(",") if i.strip()]
    probe_task = probe_certificates(now)
    monitor_task = asyncio.gather(
        *(_es_search(sid, idx, _query()) for idx in indices), return_exceptions=True
    )
    probed, monitor_results = await asyncio.gather(probe_task, monitor_task)

    hits: list[dict] = []
    for res in monitor_results:
        if not isinstance(res, Exception):
            hits.extend(res.get("hits", {}).get("hits", []))
    monitored = parse_certificates(hits, now)

    by_host = {c.host.lower(): c for c in monitored}
    for c in probed:                # active probe wins over stale monitoring data
        by_host[c.host.lower()] = c

    merged = list(by_host.values())
    # Most urgent first: problems and soonest expiry at the top.
    merged.sort(key=lambda c: (not c.issues, c.days_remaining))
    return merged
