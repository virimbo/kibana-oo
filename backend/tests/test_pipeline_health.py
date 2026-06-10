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

    monkeypatch.setattr(documents, "_es_search", fake_es)
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


async def test_pipeline_health_empty_is_clean(monkeypatch):
    async def fake_es(sid, index, body):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(documents, "_es_search", fake_es)
    res = await documents.build_pipeline_health("sid")
    assert res["stuck_count"] == 0
    assert res["documents_scanned"] == 0
    assert res["total_warnings"] == 0
