"""Active TLS certificate probe: expiry countdown + trust/chain/expiry issues,
and the merge with Kibana monitoring data. No real network — the leaf cert and
trust verdict are injected; certs are built in-memory with cryptography."""
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

import pytest

import certificates as C

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Neutralise the slow network extras so the probe tests stay hermetic; the
    served chain and trust verdict are injected per test."""
    monkeypatch.setattr(C, "_tls_version_support", lambda h, p, t: {
        "TLS 1.0": False, "TLS 1.1": False, "TLS 1.2": True, "TLS 1.3": True,
    })
    monkeypatch.setattr(C, "_hsts_enabled", lambda h, p, t: True)
    monkeypatch.setattr(C.settings, "cert_check_revocation", False)


def _chain(der, tls="TLSv1.3"):
    """Mimic _served_chain_der's (list[DER], version) return for a single leaf."""
    return ([der], tls)


def _make_der(host, not_after, self_signed=True, issuer_cn=None):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    issuer = subject if self_signed else x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn or "Test CA")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_after - timedelta(days=90))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


def test_probe_self_signed_expiring_soon(monkeypatch):
    der = _make_der("open.overheid.nl", NOW + timedelta(days=5), self_signed=True)
    monkeypatch.setattr(C, "_served_chain_der", lambda h, p, t: _chain(der))
    monkeypatch.setattr(C, "_trust_issue", lambda h, p, t: "self-signed / not trusted")

    c = C._probe_host_sync("open.overheid.nl", 443, 6.0, NOW)
    assert c.reachable is True
    assert c.days_remaining == 5
    assert c.status == "critical"          # < 14 days
    assert c.source == "probe"
    assert any("self-signed" in i for i in c.issues)


def test_probe_expired_certificate(monkeypatch):
    der = _make_der("doculoket.overheid.nl", NOW - timedelta(days=2), self_signed=False, issuer_cn="Real CA")
    monkeypatch.setattr(C, "_served_chain_der", lambda h, p, t: _chain(der))
    monkeypatch.setattr(C, "_trust_issue", lambda h, p, t: "certificate expired")

    c = C._probe_host_sync("doculoket.overheid.nl", 443, 6.0, NOW)
    assert c.days_remaining < 0
    assert c.status == "expired"
    assert any("EXPIRED" in i for i in c.issues)


def test_probe_trusted_and_healthy(monkeypatch):
    der = _make_der("open.overheid.nl", NOW + timedelta(days=200), self_signed=False, issuer_cn="DigiCert")
    monkeypatch.setattr(C, "_served_chain_der", lambda h, p, t: _chain(der))
    monkeypatch.setattr(C, "_trust_issue", lambda h, p, t: None)

    c = C._probe_host_sync("open.overheid.nl", 443, 6.0, NOW)
    assert c.status == "ok"
    assert c.grade == "OK"
    assert c.issues == []
    assert c.issuer == "DigiCert"


def test_probe_unreachable_host(monkeypatch):
    def boom(h, p, t):
        raise OSError("connection refused")
    monkeypatch.setattr(C, "_served_chain_der", boom)

    c = C._probe_host_sync("nope.example", 443, 6.0, NOW)
    assert c.reachable is False
    assert c.status == "critical"
    assert any("could not connect" in i for i in c.issues)


async def test_fetch_merges_probe_over_monitor(monkeypatch):
    der = _make_der("open.overheid.nl", NOW + timedelta(days=200), self_signed=False, issuer_cn="CA")
    monkeypatch.setattr(C, "_served_chain_der", lambda h, p, t: _chain(der))
    monkeypatch.setattr(C, "_trust_issue", lambda h, p, t: None)
    monkeypatch.setattr(C.settings, "cert_probe_hosts", "open.overheid.nl")

    async def fake_es(sid, idx, body):
        return {"hits": {"hits": [
            {"_source": {
                "@timestamp": "2026-06-01T00:00:00Z",
                "url": {"domain": "other.nl"},
                "tls": {"server": {"x509": {"not_after": (NOW + timedelta(days=10)).isoformat()}}},
            }},
        ]}}

    monkeypatch.setattr(C, "_es_search", fake_es)
    certs = await C.fetch_certificates("sid", now=NOW)
    hosts = [c.host for c in certs]
    assert "open.overheid.nl" in hosts and "other.nl" in hosts
    # both healthy → soonest-expiry first: other.nl (10d) before open.overheid.nl (200d)
    assert hosts.index("other.nl") < hosts.index("open.overheid.nl")
