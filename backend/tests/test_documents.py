import pytest

import documents


def test_classify_action():
    assert documents.classify_action("Deleting document ronl-1") == "deleted"
    assert documents.classify_action("stored new document") == "created"
    assert documents.classify_action("Retrieving version 2 of x.pdf") == "updated"  # 'version' -> update
    assert documents.classify_action("retrieve document with path /smb/...") == "retrieved"
    assert documents.classify_action("something unrelated") == "other"


def test_extract_file():
    name, ftype = documents.extract_file("Retrieving version 1 of brief-aan-dgb.pdf for ronl-x")
    assert name == "brief-aan-dgb.pdf"
    assert ftype == "pdf"
    assert documents.extract_file("no file here") == (None, None)


def test_summarize_event(monkeypatch):
    monkeypatch.setattr(documents.settings, "doc_id_regex", r"ronl-[A-Za-z0-9-]+")
    monkeypatch.setattr(documents.settings, "doc_link_template", "https://open.overheid.nl/documenten/{id}")
    hit = {"_source": {
        "@timestamp": "2026-06-09T08:00:00Z",
        "level": "ERROR",
        "logger_name": "nl.overheid.koop.plooi.repository.storage.FilesystemStorage",
        "message": "delete document /smb/repo/ronl-archief-abc/1/brief.pdf",
    }}
    e = documents.summarize_event(hit)
    assert e["action"] == "deleted"
    assert e["status"] == "error"
    assert e["type"] == "pdf"
    assert e["doc_id"] == "ronl-archief-abc"
    assert e["link"] == "https://open.overheid.nl/documenten/ronl-archief-abc"
    assert e["service"] == "storage.FilesystemStorage"


@pytest.fixture
def patched(monkeypatch):
    async def fake_es(sid, index, body):
        if body.get("aggs"):  # timeseries
            return {"hits": {"total": {"value": 42}},
                    "aggregations": {"over_time": {"buckets": [
                        {"key_as_string": "2026-06-09T08:00:00Z", "doc_count": 30}]}}}
        return {"hits": {"hits": [  # feed
            {"_source": {"@timestamp": "t1", "level": "INFO",
                         "message": "stored document ronl-aaa /repo/brief.pdf"}},
            {"_source": {"@timestamp": "t2", "level": "ERROR",
                         "message": "delete document ronl-bbb /repo/besluit.xml"}},
            {"_source": {"@timestamp": "t3", "level": "INFO",
                         "message": "stored document ronl-aaa again /repo/brief.pdf"}}]}}

    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents.settings, "data_views", "logs-*")
    monkeypatch.setattr(documents.settings, "default_data_view", "logs-*")


async def test_build_document_activity(patched):
    a = await documents.build_document_activity("sid", 60, "logs-*")
    assert a.total == 42                 # from the timeseries agg
    assert len(a.events) == 3
    assert a.errors == 1                 # one ERROR
    assert a.unique_documents == 2       # ronl-aaa, ronl-bbb
    actions = {x["action"]: x["count"] for x in a.by_action}
    assert actions["created"] == 2 and actions["deleted"] == 1
    types = {x["type"]: x["count"] for x in a.by_type}
    assert types["pdf"] == 2 and types["xml"] == 1
    assert a.timeseries[0]["count"] == 30
