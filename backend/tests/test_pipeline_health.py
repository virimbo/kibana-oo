from datetime import datetime, timedelta, timezone

import documents
import incidents


def _hit(ts, service, msg):
    return {"_source": {"@timestamp": ts, "message": msg, "level": "INFO",
                        "service": {"name": service}}}


NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _hit_at(dt, service, msg):
    return _hit(dt.strftime("%Y-%m-%dT%H:%M:%SZ"), service, msg)


def _use_views(monkeypatch):
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")


async def test_pipeline_health_finds_stuck_docs(monkeypatch):
    uid = "5caff8b8-1c3e-4517-a95f-b21d8ca8746b"
    hits = [
        _hit("2026-06-09T12:15:00Z", "gateway-service", f"404 NOT_FOUND {uid} openbaarmakingen/api"),
        _hit("2026-06-09T13:01:06Z", "msvc-documentopslag", f"Connection reset by peer {uid}"),
    ]

    async def fake_es(sid, index, body):
        # the doc's logs live in one (data-bearing) view; others are empty
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def not_published(doc_id):
        return None   # portal can't confirm it's live → stays flagged

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", not_published)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")

    res = await documents.build_pipeline_health("sid")

    assert res["documents_scanned"] == 1
    assert res["stuck_count"] == 1
    stuck = res["stuck"][0]
    assert stuck["id"] == uid
    assert stuck["stuck_stage"] == "Storage"
    assert stuck["verdict"] == "stuck"

    by_name = {s["name"]: s for s in res["stage_health"]}
    assert by_name["Storage"]["warnings"] >= 1   # connection reset surfaced
    assert by_name["Intake"]["warnings"] >= 1     # 404 surfaced
    assert res["total_warnings"] >= 2


async def test_pipeline_health_ignores_docs_without_real_trouble(monkeypatch):
    """The 453-stuck fix: a document whose later-stage logs are just outside the
    window (only clean front-door events, or the routine 404 probe) is NOT
    flagged — only genuine trouble signals count."""
    uid = "11111111-1111-4111-8111-111111111111"
    clean = [
        _hit("2026-06-09T12:15:00Z", "gateway-service",
             f"404 NOT_FOUND No static resource openbaarmakingen/api {uid}"),
        _hit("2026-06-09T12:16:00Z", "msvc-documentopslag", f"stored ok {uid}"),
    ]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": clean if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        return None

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")

    res = await documents.build_pipeline_health("sid")
    assert res["documents_scanned"] == 1
    assert res["stuck_count"] == 0   # routine 404 + clean storage = not at risk


async def test_pipeline_health_drops_published_documents(monkeypatch):
    """The key fix: a document that LOOKS stuck in the logs but is actually
    published on open.overheid.nl is NOT reported as stuck."""
    uid = "5caff8b8-1c3e-4517-a95f-b21d8ca8746b"
    hits = [
        _hit("2026-06-09T12:15:00Z", "gateway-service", f"404 NOT_FOUND {uid}"),
        _hit("2026-06-09T13:01:06Z", "msvc-documentopslag", f"Connection reset by peer {uid}"),
    ]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def published(doc_id):
        return {"status": "gepubliceerd", "title": "Besluit X", "link": "https://open.overheid.nl/x"}

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", published)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")

    res = await documents.build_pipeline_health("sid")
    assert res["stuck_count"] == 0              # not stuck — it's live
    assert res["confirmed_published"] == 1       # the false alarm was caught


async def test_pipeline_health_titles_ronl_docs_from_logs(monkeypatch):
    """ronl- documents can't be resolved by the portal (UUID-only), so their
    title falls back to the document filename seen in the logs."""
    rid = "ronl-archief-0639bd49-4913-4492-ac1c-ee30993068a9"
    hits = [_hit("2026-06-09T10:00:00Z", "msvc-indexatie", f"indexing {rid} Jaarverslag-2025.pdf")]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        return None  # portal can't resolve a ronl id

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")

    res = await documents.build_pipeline_health("sid")
    assert res["stuck_count"] == 1                       # stalled late (Indexing)
    assert res["stuck"][0]["id"] == rid
    assert res["stuck"][0]["title"] == "Jaarverslag-2025"  # from the log filename


def test_portal_id_extracts_embedded_uuid():
    assert documents._portal_id("ronl-archief-0639bd49-4913-4492-ac1c-ee30993068a9") \
        == "0639bd49-4913-4492-ac1c-ee30993068a9"
    assert documents._portal_id("5caff8b8-1c3e-4517-a95f-b21d8ca8746b") \
        == "5caff8b8-1c3e-4517-a95f-b21d8ca8746b"
    assert documents._portal_id("no-uuid-here") == "no-uuid-here"


async def test_pipeline_health_resolves_ronl_title_via_embedded_uuid(monkeypatch):
    """A ronl-archief-<uuid> id is resolved on the portal via its embedded UUID,
    giving the official title (and publication status)."""
    rid = "ronl-archief-0639bd49-4913-4492-ac1c-ee30993068a9"
    hits = [_hit("2026-06-09T10:00:00Z", "msvc-indexatie", f"indexing {rid}")]
    seen = {}

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        seen["id"] = doc_id
        return {"status": "concept", "title": "Aanbiedingsbrief X",
                "link": "https://open.overheid.nl/documenten/0639bd49"}

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")

    res = await documents.build_pipeline_health("sid")
    assert seen["id"] == "0639bd49-4913-4492-ac1c-ee30993068a9"  # looked up the embedded UUID
    assert res["stuck_count"] == 1
    assert res["stuck"][0]["title"] == "Aanbiedingsbrief X"


async def test_pipeline_health_empty_is_clean(monkeypatch):
    async def fake_es(sid, index, body):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(documents, "_es_search", fake_es)
    res = await documents.build_pipeline_health("sid")
    assert res["stuck_count"] == 0
    assert res["documents_scanned"] == 0
    assert res["total_warnings"] == 0


# ── Settle time + durable incident tracking (the false-positive fix) ──────────

async def test_settle_time_skips_recently_active_document(monkeypatch):
    """A document with a problem at Intake that is STILL emitting events (last
    seen minutes ago) is in motion, not an incident — it must NOT be flagged.
    This is the fix for the 'failed at Intake' rows that clear in a few minutes."""
    uid = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    hits = [_hit_at(NOW - timedelta(minutes=5), "gateway-service", f"failed to process {uid}")]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        return None

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    _use_views(monkeypatch)

    res = await documents.build_pipeline_health("sid", now=NOW)
    assert res["documents_scanned"] == 1
    assert res["stuck_count"] == 0          # still moving → not an incident (yet)


async def test_flagged_only_after_settle_and_persisted(monkeypatch):
    """The same document, now SILENT past the settle window and not live, is a
    genuine incident — flagged and stored as open."""
    uid = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
    hits = [_hit_at(NOW - timedelta(hours=2), "gateway-service", f"failed to process {uid}")]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        return None

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    _use_views(monkeypatch)

    res = await documents.build_pipeline_health("sid", now=NOW)
    assert res["stuck_count"] == 1
    assert res["stuck"][0]["id"] == uid
    assert res["stuck"][0]["verdict"] == "problem"
    assert res["stuck"][0]["open_since"]                 # age is surfaced

    rows = await incidents.open_incidents()
    assert len(rows) == 1 and rows[0]["doc_id"] == uid


async def test_incident_survives_window_then_clears_when_published(monkeypatch):
    """An incident stays OPEN across scans — even after the document falls out of
    the 24h scan window — until the portal confirms it published, then clears.
    This is the 'stays for days until solved' guarantee."""
    uid = "cccccccc-3333-4333-8333-cccccccccccc"
    silent = [_hit_at(NOW - timedelta(hours=2), "gateway-service", f"failed to process {uid}")]
    portal = {"live": False}

    async def meta(doc_id):
        return ({"status": "gepubliceerd", "title": "Doc C", "link": "https://open.overheid.nl/c"}
                if portal["live"] else None)

    _use_views(monkeypatch)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)

    # Scan 1 — document present & failing → opens an incident.
    async def es_with(sid, index, body):
        return {"hits": {"hits": silent if index == "ds-prod5-koop-plooi*" else []}}
    monkeypatch.setattr(documents, "_es_search", es_with)
    res1 = await documents.build_pipeline_health("sid", now=NOW)
    assert res1["stuck_count"] == 1

    # Scan 2 (a day later) — the document has fallen OUT of the scan window (no
    # hits) but is still not live → the incident must remain open.
    async def es_empty(sid, index, body):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(documents, "_es_search", es_empty)
    res2 = await documents.build_pipeline_health("sid", now=NOW + timedelta(days=1))
    assert res2["documents_scanned"] == 0
    assert res2["stuck_count"] == 1                       # STILL listed — not solved
    assert res2["stuck"][0]["id"] == uid
    assert "d" in res2["stuck"][0]["open_since"]          # ~1 day old

    # Scan 3 — the portal now reports it published → auto-resolved, list clears.
    portal["live"] = True
    res3 = await documents.build_pipeline_health("sid", now=NOW + timedelta(days=1, hours=1))
    assert res3["stuck_count"] == 0


def test_detect_pipeline_markers_then_fallback():
    assert documents._detect_pipeline([{"service": "msvc", "message": "via NVS pipeline"}]) == "NVS"
    assert documents._detect_pipeline([{"service": "x", "message": "oude verwerkingsstraat run"}]) == "OVS"
    # No explicit marker, but the service maps onto the canonical NVS lifecycle.
    assert documents._detect_pipeline([{"service": "msvc-documentopslag", "message": "stored"}]) == "NVS"
    # Nothing recognizable → honest unknown, not a guess.
    assert documents._detect_pipeline([{"service": "weird", "message": "nothing"}]) == "—"


def test_detect_pipeline_reliable_by_dedicated_field(monkeypatch):
    """With a dedicated field configured, classification is authoritative — and
    returns '—' (not a guess) when the field doesn't identify a pipeline."""
    monkeypatch.setattr(documents.settings, "pipeline_field", "labels.pipeline")
    assert documents._detect_pipeline([{"pipeline_raw": "NVS-prod"}]) == "NVS"
    assert documents._detect_pipeline([{"pipeline_raw": "the OVS lane"}]) == "OVS"
    # configured but unmatched → honest unknown, NOT guessed from the service
    assert documents._detect_pipeline([{"pipeline_raw": "", "service": "msvc-documentopslag"}]) == "—"


def test_detect_pipeline_reliable_by_index(monkeypatch):
    """The index / data-stream is a structural, reliable signal."""
    monkeypatch.setattr(documents.settings, "pipeline_nvs_index", "koop-plooi")
    monkeypatch.setattr(documents.settings, "pipeline_ovs_index", "koop-sp")
    assert documents._detect_pipeline([{"index": "ds-prod5-koop-plooi-2026.06"}]) == "NVS"
    assert documents._detect_pipeline([{"index": "ds-prod5-koop-sp"}]) == "OVS"
    # trusted signal set, but this index belongs to neither → unknown, not a guess
    assert documents._detect_pipeline([{"index": "logs-x", "service": "msvc-documentopslag"}]) == "—"


def test_incident_service_picks_latest_event():
    evs = [
        {"service": "gateway-service", "timestamp": "2026-06-12T10:00:00Z"},
        {"service": "msvc-indexatie", "timestamp": "2026-06-12T11:00:00Z"},
    ]
    assert documents._incident_service(evs) == "msvc-indexatie"


async def test_pipeline_health_row_has_rich_fields(monkeypatch):
    """Each at-risk row carries the extra columns the UI shows: service, pipeline,
    a plain-language status, and a formatted last-activity date/time."""
    uid = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"
    hits = [_hit_at(NOW - timedelta(hours=2), "msvc-documentopslag", f"failed to store {uid}")]

    async def fake_es(sid, index, body):
        return {"hits": {"hits": hits if index == "ds-prod5-koop-plooi*" else []}}

    async def meta(doc_id):
        return None

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)
    _use_views(monkeypatch)

    res = await documents.build_pipeline_health("sid", now=NOW)
    row = res["stuck"][0]
    assert row["service"] == "msvc-documentopslag"
    assert row["pipeline"] == "NVS"
    assert row["status_label"] == "Error — stopped"   # 'problem' verdict
    assert row["last_seen_label"].startswith("2026-06-12")


async def test_incident_clears_when_document_progresses(monkeypatch):
    """If a flagged document later shows up healthy/progressed within the scan
    window, its incident auto-resolves and drops off the list."""
    uid = "dddddddd-4444-4444-8444-dddddddddddd"
    failing = [_hit_at(NOW - timedelta(hours=2), "gateway-service", f"failed to process {uid}")]

    async def meta(doc_id):
        return None

    _use_views(monkeypatch)
    monkeypatch.setattr(documents, "fetch_document_meta", meta)

    async def es_failing(sid, index, body):
        return {"hits": {"hits": failing if index == "ds-prod5-koop-plooi*" else []}}
    monkeypatch.setattr(documents, "_es_search", es_failing)
    res1 = await documents.build_pipeline_health("sid", now=NOW)
    assert res1["stuck_count"] == 1

    # Later scan: the document is now seen flowing cleanly all the way to live.
    progressed = [
        _hit_at(NOW + timedelta(hours=1), "msvc-documentopslag", f"stored ok {uid}"),
        _hit_at(NOW + timedelta(hours=2), "zoekportaal", f"live {uid}"),
    ]

    async def es_progressed(sid, index, body):
        return {"hits": {"hits": progressed if index == "ds-prod5-koop-plooi*" else []}}
    monkeypatch.setattr(documents, "_es_search", es_progressed)
    res2 = await documents.build_pipeline_health("sid", now=NOW + timedelta(hours=3))
    assert res2["stuck_count"] == 0                       # recovered → cleared
