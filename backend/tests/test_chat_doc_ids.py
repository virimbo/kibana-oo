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
