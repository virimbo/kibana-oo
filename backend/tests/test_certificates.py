from datetime import datetime, timezone

import pytest

import certificates


NOW = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)


def _hit(source):
    return {"_source": source}


def test_parse_ecs_certificate():
    hits = [_hit({
        "@timestamp": "2026-06-08T11:00:00Z",
        "url": {"domain": "open.overheid.nl"},
        "tls": {"server": {"x509": {
            "not_after": "2026-08-08T12:02:21Z",
            "subject": {"common_name": "open.overheid.nl"},
            "issuer": {"common_name": "certSIGN Web CA"},
        }}},
    })]
    certs = certificates.parse_certificates(hits, now=NOW)
    assert len(certs) == 1
    c = certs[0]
    assert c.host == "open.overheid.nl"
    assert c.issuer == "certSIGN Web CA"
    assert c.days_remaining == 61  # 8 Jun -> 8 Aug
    assert c.status == "ok"


def test_parse_legacy_field_and_status_thresholds():
    hits = [
        _hit({"monitor": {"name": "soon"},
              "tls": {"certificate_not_valid_after": "2026-06-18T12:00:00Z"}}),   # 10 days
        _hit({"monitor": {"name": "verysoon"},
              "tls": {"certificate_not_valid_after": "2026-06-22T12:00:00Z"}}),   # 14 days
        _hit({"monitor": {"name": "expired"},
              "tls": {"certificate_not_valid_after": "2026-06-01T12:00:00Z"}}),   # -7 days
    ]
    by_host = {c.host: c for c in certificates.parse_certificates(hits, now=NOW)}
    assert by_host["soon"].status == "critical"      # < 14
    assert by_host["verysoon"].status == "warning"   # 14..29
    assert by_host["expired"].status == "expired"    # < 0


def test_dedup_and_sort_by_soonest():
    hits = [
        _hit({"url": {"domain": "a.nl"}, "@timestamp": "2026-06-08T11:00:00Z",
              "tls": {"server": {"x509": {"not_after": "2026-09-08T12:00:00Z"}}}}),  # newest a.nl
        _hit({"url": {"domain": "a.nl"}, "@timestamp": "2026-06-07T11:00:00Z",
              "tls": {"server": {"x509": {"not_after": "2026-07-01T12:00:00Z"}}}}),  # older a.nl, ignored
        _hit({"url": {"domain": "b.nl"}, "@timestamp": "2026-06-08T10:00:00Z",
              "tls": {"server": {"x509": {"not_after": "2026-06-20T12:00:00Z"}}}}),  # b.nl sooner
    ]
    certs = certificates.parse_certificates(hits, now=NOW)
    assert [c.host for c in certs] == ["b.nl", "a.nl"]  # soonest first
    assert len(certs) == 2  # a.nl de-duplicated to its newest doc


def test_ignores_docs_without_expiry():
    hits = [_hit({"url": {"domain": "x.nl"}, "tls": {"server": {"x509": {}}}})]
    assert certificates.parse_certificates(hits, now=NOW) == []


async def test_fetch_certificates_merges_indices_and_skips_errors(monkeypatch):
    async def fake_es(sid, index, body):
        if index == "heartbeat-*":
            return {"hits": {"hits": [_hit({
                "url": {"domain": "open.overheid.nl"},
                "tls": {"server": {"x509": {"not_after": "2026-08-08T12:02:21Z"}}},
            })]}}
        raise RuntimeError("no such index")  # synthetics-* missing -> skipped

    monkeypatch.setattr(certificates, "_es_search", fake_es)
    monkeypatch.setattr(certificates.settings, "cert_index", "heartbeat-*,synthetics-*")
    certs = await certificates.fetch_certificates("sid", now=NOW)
    assert len(certs) == 1
    assert certs[0].host == "open.overheid.nl"
