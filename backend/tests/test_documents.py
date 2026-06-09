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


def test_detect_source(monkeypatch):
    monkeypatch.setattr(documents.settings, "processing_sources",
                        "aanleverloket,dpc,oep-ob,oep,plooi-api,ronl-archief,ronl,roo,woo-idx")
    assert documents.detect_source("ronl-archief-abc", "x") == "ronl-archief"  # longest prefix wins
    assert documents.detect_source("ronl-abc", "x") == "ronl"
    assert documents.detect_source(None, "ingest from woo-idx feed") == "woo-idx"
    assert documents.detect_source(None, "unrelated") == "other"


def test_classify_error_category():
    assert documents.classify_error_category("mapping failed for field x", "ERROR") == "mapping_error"
    assert documents.classify_error_category("mapping warning: unknown field", "WARN") == "mapping_warning"
    assert documents.classify_error_category("storage timeout", "ERROR") == "processing_error"


def test_build_source_errors(monkeypatch):
    monkeypatch.setattr(documents.settings, "processing_sources", "ronl-archief,ronl,woo-idx")
    hits = [
        {"_source": {"level": "ERROR", "message": "mapping failed for ronl-archief-1"}},
        {"_source": {"level": "WARN", "message": "mapping warning ronl-archief-2"}},
        {"_source": {"level": "ERROR", "message": "storage timeout for ronl-9"}},
    ]
    rows = {r["source"]: r for r in documents.build_source_errors(hits)}
    assert rows["ronl-archief"]["mapping_error"] == 1
    assert rows["ronl-archief"]["mapping_warning"] == 1
    assert rows["ronl-archief"]["total"] == 2
    assert rows["ronl"]["processing_error"] == 1


async def test_trace_document(monkeypatch):
    async def fake_es(sid, index, body):
        return {"hits": {"hits": [
            {"_source": {"@timestamp": "t1", "level": "INFO", "message": "ingest ronl-x besluit.pdf"}},
            {"_source": {"@timestamp": "t2", "level": "ERROR", "message": "indexing failed for ronl-x"}}]}}
    monkeypatch.setattr(documents, "_es_search", fake_es)
    monkeypatch.setattr(documents.settings, "data_views", "logs-*")
    monkeypatch.setattr(documents.settings, "default_data_view", "logs-*")
    trace = await documents.trace_document("sid", "ronl-x", "logs-*")
    assert trace["found"] is True
    assert trace["errors"] == 1
    assert len(trace["events"]) == 2
    assert trace["title"] == "besluit"                          # from "besluit.pdf"
    assert trace["doculoket_link"].endswith("/aanleveren/ronl-x")
    assert trace["portal_link"].endswith("/documenten/ronl-x")
    assert len(trace["stages"]) == 1                            # both events from "(unknown)" service
    assert trace["stages"][0]["events"] == 2
    assert trace["stages"][0]["errors"] == 1


@pytest.fixture
def patched(monkeypatch):
    async def fake_es(sid, index, body):
        if body.get("aggs"):  # timeseries
            return {"hits": {"total": {"value": 42}},
                    "aggregations": {"over_time": {"buckets": [
                        {"key_as_string": "2026-06-09T08:00:00Z", "doc_count": 30}]}}}
        size = body.get("size", 0)
        if size == 0:  # prior-period error count
            return {"hits": {"total": {"value": 1}}}
        if size == 20:  # failed-documents feed (current window errors)
            return {"hits": {"total": {"value": 2}, "hits": [
                {"_source": {"@timestamp": "t2", "level": "ERROR",
                             "message": "delete document ronl-bbb /repo/besluit.xml: timeout"}},
                {"_source": {"@timestamp": "t4", "level": "ERROR",
                             "message": "failed to store document ronl-ccc /repo/nota.pdf"}}]}}
        return {"hits": {"hits": [  # main feed
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
    assert a.unique_documents == 2       # ronl-aaa, ronl-bbb (from the feed)
    actions = {x["action"]: x["count"] for x in a.by_action}
    assert actions["created"] == 2 and actions["deleted"] == 1
    types = {x["type"]: x["count"] for x in a.by_type}
    assert types["pdf"] == 2 and types["xml"] == 1
    assert a.timeseries[0]["count"] == 30
    # proactive
    assert a.errors == 2                 # accurate count from the failed query
    assert a.errors_prior == 1
    assert a.error_pct_change == 100.0   # doubled -> spike
    assert a.alert_level == "critical"
    assert len(a.failed) == 2            # the specific failed documents
