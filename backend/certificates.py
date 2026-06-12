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
import logging
import socket
import ssl
from datetime import datetime, timezone

from cryptography import x509
from cryptography.x509.oid import NameOID
from pydantic import BaseModel

from elastic import _es_search
from config import settings

logger = logging.getLogger(__name__)

# Status thresholds (days remaining).
WARNING_DAYS = 30
CRITICAL_DAYS = 14


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


def _probe_host_sync(host: str, port: int, timeout: float, now: datetime) -> Certificate:
    try:
        der = _leaf_certificate_der(host, port, timeout)
    except (ssl.SSLError, OSError) as e:
        return Certificate(
            host=host, not_after="", days_remaining=-99999, status="critical",
            issues=[f"could not connect ({type(e).__name__})"], source="probe", reachable=False,
        )
    cert = x509.load_der_x509_certificate(der)
    not_after = cert.not_valid_after_utc
    days = (not_after - now).days

    issues: list[str] = []
    if days < 0:
        issues.append("certificate EXPIRED")
    trust = _trust_issue(host, port, timeout)
    if trust:
        issues.append(trust)
    if cert.issuer == cert.subject and not any("self-signed" in i for i in issues):
        issues.append("self-signed certificate")

    status = cert_status(days)
    if issues and status == "ok":
        status = "warning"  # trust/chain problems are at least a warning even if not expiring
    return Certificate(
        host=host,
        common_name=_common_name(cert.subject),
        issuer=_common_name(cert.issuer),
        not_after=not_after.isoformat(),
        days_remaining=days,
        status=status,
        issues=issues,
        source="probe",
        reachable=True,
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
