import elastic


def test_extract_doc_ids_finds_uuid_and_ronl():
    q = ("pls investigate why doc 5caff8b8-1c3e-4517-a95f-b21d8ca8746b was "
         "published twice, and also ronl-archief-abc123")
    ids = elastic.extract_doc_ids(q)
    assert "5caff8b8-1c3e-4517-a95f-b21d8ca8746b" in ids
    assert "ronl-archief-abc123" in ids


def test_extract_doc_ids_dedupes_and_orders():
    q = "id 5caff8b8-1c3e-4517-a95f-b21d8ca8746b again 5caff8b8-1c3e-4517-a95f-b21d8ca8746b"
    assert elastic.extract_doc_ids(q) == ["5caff8b8-1c3e-4517-a95f-b21d8ca8746b"]


def test_extract_doc_ids_empty_when_none():
    assert elastic.extract_doc_ids("are there any errors in the last hour?") == []
    assert elastic.extract_doc_ids("") == []


def test_search_by_document_id_builds_wide_window_id_query(monkeypatch):
    captured = {}

    async def fake_es(sid, index, body):
        captured["index"] = index
        captured["body"] = body
        return {"hits": {"hits": []}}

    monkeypatch.setattr(elastic, "_es_search", fake_es)

    import asyncio
    asyncio.run(elastic.search_by_document_id("sid", "5caff8b8-1c3e-4517-a95f-b21d8ca8746b",
                                              index="logs-*", size=200, days=30))
    f = captured["body"]["query"]["bool"]["filter"]
    qs = next(x for x in f if "query_string" in x)["query_string"]["query"]
    assert "5caff8b8-1c3e-4517-a95f-b21d8ca8746b" in qs
    assert captured["body"]["sort"][0]["@timestamp"]["order"] == "asc"  # oldest first
    assert captured["index"] == "logs-*"


async def test_collect_doc_events_searches_all_views_and_finds_doc_outside_selection(monkeypatch):
    """The exact bug: the doc's logs live in ds-prod5-koop-plooi*, not the
    selected logs-*. _collect_doc_events must search EVERY view, dedupe, and
    sort oldest-first so the audit finds the events anyway."""
    import main

    monkeypatch.setattr(main.settings, "data_views", "logs-*,ds-prod5-koop-plooi*")
    seen_indices = []

    async def fake(sid, doc_id, index, size, days):
        seen_indices.append(index)
        if index == "ds-prod5-koop-plooi*":
            return [
                {"timestamp": "2026-06-09T12:03:00Z", "message": "published ok", "index": "ds-x"},
                {"timestamp": "2026-06-09T11:41:00Z", "message": "pending invalid date", "index": "ds-x"},
                {"timestamp": "2026-06-09T11:41:00Z", "message": "pending invalid date", "index": "ds-x"},  # dup
            ]
        return []  # logs-* (selected) has nothing — the original failure

    monkeypatch.setattr(main, "search_by_document_id", fake)
    out = await main._collect_doc_events("sid", "5caff8b8-1c3e-4517-a95f-b21d8ca8746b")
    assert set(seen_indices) == {"logs-*", "ds-prod5-koop-plooi*"}  # searched ALL views
    assert [e["message"] for e in out] == ["pending invalid date", "published ok"]  # sorted asc + deduped


async def test_collect_doc_events_tolerates_a_failing_view(monkeypatch):
    import main

    monkeypatch.setattr(main.settings, "data_views", "logs-*,ds-prod5-koop-plooi*")

    async def fake(sid, doc_id, index, size, days):
        if index == "logs-*":
            raise RuntimeError("view down")
        return [{"timestamp": "t", "message": "ok", "index": "ds"}]

    monkeypatch.setattr(main, "search_by_document_id", fake)
    out = await main._collect_doc_events("sid", "ronl-x")
    assert len(out) == 1  # the failing view did not block the working one


async def test_fetch_generic_merges_and_tolerates_a_failing_query(monkeypatch):
    import main

    async def rl(sid, size, time_range_minutes, index):
        return [{"timestamp": "t2", "message": "recent log line"}]

    async def sl(sid, query, size, time_range_minutes, index):
        raise RuntimeError("keyword search failed")  # must not empty the context

    async def re_(sid, size, time_range_minutes, index):
        return [{"timestamp": "t1", "message": "an error happened"}]

    monkeypatch.setattr(main, "get_recent_logs", rl)
    monkeypatch.setattr(main, "search_logs", sl)
    monkeypatch.setattr(main, "get_recent_errors", re_)

    logs, errors = await main._fetch_generic("sid", "q", 15, "logs-*")
    assert [l["message"] for l in logs] == ["recent log line"]
    assert len(errors) == 1  # error query still contributed despite the failure


async def test_instant_response_streams_question_chunk_done():
    import main
    events = [e async for e in main._instant_response("no data here", display_question="hello")]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "question"
    assert "chunk" in kinds and kinds[-1] == "done"
    assert any(e.get("data") == "no data here" for e in events)


async def test_stream_response_never_ends_empty(monkeypatch):
    """If the model yields zero tokens, the user must still get a clear message
    (not a blank bubble that the frontend turns into a misleading fallback)."""
    import main

    async def empty_stream(question, context, session=None):
        return
        yield  # unreachable — makes this an (empty) async generator

    monkeypatch.setattr(main, "generate_answer_stream", empty_stream)
    events = [e async for e in main._stream_response("q", "ctx", [], {"llm_provider": "ollama"})]
    chunks = [e for e in events if e["event"] == "chunk"]
    assert len(chunks) == 1 and "empty response" in chunks[0]["data"].lower()
    assert events[-1]["event"] == "done"
