import documents


def _hit(ts, service, msg):
    return {"_source": {"@timestamp": ts, "message": msg, "level": "INFO",
                        "service": {"name": service}}}


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


async def test_pipeline_health_empty_is_clean(monkeypatch):
    async def fake_es(sid, index, body):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(documents, "_es_search", fake_es)
    res = await documents.build_pipeline_health("sid")
    assert res["stuck_count"] == 0
    assert res["documents_scanned"] == 0
    assert res["total_warnings"] == 0
