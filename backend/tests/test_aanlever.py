"""Aanleverfouten monitor: detection/classification, candidate parsing (incl. the
UUID case), durable incident lifecycle, reconciliation, and grouping. ES + portal
are mocked — no real network."""
from datetime import datetime, timedelta, timezone

import pytest

import aanlever as A
from config import settings

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
UUID = "6bf250a3-5462-4581-8066-d52cedbced39"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "aanlever_alert_enabled", False)
    monkeypatch.setattr(settings, "aanlever_settle_minutes", 0)  # no settle wait in tests
    yield


def _hit(msg, level="ERROR", org="Ministerie X", ts="2026-06-16T08:00:00+00:00"):
    return {"_index": "ds-prod5-koop-plooi", "_source": {
        "@timestamp": ts, "message": msg, "level": level, "organisatie": org}}


# ── Classification & detection ────────────────────────────────────────────────
def test_error_type_from_message():
    assert A._error_type("Document afgekeurd: schema ongeldig")[0] == "schema"
    assert A._error_type("validatie mislukt")[1] == "Validatie"
    assert A._error_type("iets anders")[0] == "aanleverfout"


def test_is_aanlever_event_matches_pattern_and_service():
    assert A._is_aanlever_event({"message": "Aanleverfout gevonden", "severity": "error"})
    assert A._is_aanlever_event({"message": "x", "severity": "error", "service": "doculoket"})
    assert not A._is_aanlever_event({"message": "all good", "severity": "ok", "service": "indexer"})


def test_parse_candidates_extracts_uuid_and_publisher():
    hits = [_hit(f"Aanleverfout: document {UUID} is afgekeurd (schema)")]
    cands = A.parse_candidates(hits)
    assert UUID in cands
    c = cands[UUID]
    assert c["portal_uuid"] == UUID
    assert c["publisher"] == "Ministerie X"
    assert c["error_key"] == "schema"


# ── Incident lifecycle ────────────────────────────────────────────────────────
def _cand(doc_id=UUID, publisher="Ministerie X", error_type="Schema", first="2026-06-16T08:00:00+00:00"):
    return {"doc_id": doc_id, "portal_uuid": doc_id, "publisher": publisher,
            "error_key": "schema", "error_type": error_type, "message": "afgekeurd",
            "service": "doculoket", "link": f"https://doculoket/{doc_id}", "title": "Doc",
            "first_error_at": first, "last_error_at": first}


def test_upsert_is_new_once_then_refresh():
    assert A._upsert_open_sync(_cand(), NOW) is True       # new
    assert A._upsert_open_sync(_cand(), NOW) is False      # refresh, not new
    assert A._count_open_sync() == 1


def test_resolve_and_acknowledge():
    A._upsert_open_sync(_cand(), NOW)
    assert A._ack_sync(UUID, NOW) is True
    assert A._count_open_sync() == 0                        # acknowledged → hidden
    # a reopened error after resolve counts as new again
    A._resolve_sync(UUID, "published", NOW)
    assert A._upsert_open_sync(_cand(), NOW) is True


def test_view_groups_by_publisher_and_flags_new():
    incs = [
        {"publisher": "Min A", "error_type": "Schema", "first_detected": NOW.isoformat()},
        {"publisher": "Min A", "error_type": "Validatie", "first_detected": "2026-06-10T00:00:00+00:00"},
        {"publisher": "Min B", "error_type": "Schema", "first_detected": NOW.isoformat()},
    ]
    view = A._view(incs, NOW)
    assert view["count"] == 3
    assert len(view["groups"]) == 2
    assert view["new_count"] == 2                           # the two with recent first_detected
    assert view["groups"][0]["publisher"] == "Min A"        # most incidents first


# ── Scan: detect → reconcile → persist ────────────────────────────────────────
async def test_scan_opens_incident_when_not_published(monkeypatch):
    old_ts = (NOW - timedelta(hours=2)).isoformat()
    hits = [_hit(f"Aanleverfout {UUID} afgekeurd", ts=old_ts)]

    async def fake_es(sid, dv, body):
        return {"hits": {"hits": hits}}

    async def fake_meta(uuid):
        return None  # not published

    monkeypatch.setattr(A, "_es_search", fake_es)
    monkeypatch.setattr(A, "fetch_document_meta", fake_meta)
    view = await A.scan("sid", now=NOW)
    assert view["count"] == 1
    assert view["groups"][0]["publisher"] == "Ministerie X"


async def test_scan_resolves_when_published(monkeypatch):
    old_ts = (NOW - timedelta(hours=2)).isoformat()
    A._upsert_open_sync(_cand(first=old_ts), NOW)           # pre-existing open incident
    assert A._count_open_sync() == 1

    async def fake_es(sid, dv, body):
        return {"hits": {"hits": [_hit(f"Aanleverfout {UUID} afgekeurd", ts=old_ts)]}}

    async def fake_meta(uuid):
        return {"status": "gepubliceerd", "title": "Doc"}   # now published → fixed

    monkeypatch.setattr(A, "_es_search", fake_es)
    monkeypatch.setattr(A, "fetch_document_meta", fake_meta)
    view = await A.scan("sid", now=NOW)
    assert view["count"] == 0                                # auto-resolved
