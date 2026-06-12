"""Pipeline Outcomes: per-document outcome classification, OVS/NVS split, portal
reconciliation of the 'failed' set, success rate, backlog, latency, and trend."""
from datetime import datetime, timedelta, timezone

import documents

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)

# Distinct UUIDs so each document groups on its own.
A = "aaaaaaaa-0000-4000-8000-000000000001"   # published (2 events → has latency)
B = "bbbbbbbb-0000-4000-8000-000000000002"   # updated (republication)
C = "cccccccc-0000-4000-8000-000000000003"   # withdrawn, OVS
D = "dddddddd-0000-4000-8000-000000000004"   # failed (system error, not live)
E = "eeeeeeee-0000-4000-8000-000000000005"   # in progress (still moving)
F = "ffffffff-0000-4000-8000-000000000006"   # logs say failed, but portal says LIVE
P = "11111111-0000-4000-8000-000000000007"   # previous window: a publication


def _hit(dt, service, msg):
    return {"_index": "ds-prod5-koop-plooi-2026.06",
            "_source": {"@timestamp": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "message": msg, "level": "INFO", "service": {"name": service}}}


def _parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# Current window [NOW-60, NOW); previous [NOW-120, NOW-60).
EVENTS = [
    _hit(NOW - timedelta(minutes=40), "gateway-service", f"received {A}"),
    _hit(NOW - timedelta(minutes=30), "zoekportaal", f"gepubliceerd live {A}"),
    _hit(NOW - timedelta(minutes=25), "zoekportaal", f"herpublicatie {B}"),
    _hit(NOW - timedelta(minutes=20), "publicatiebeheer", f"OVS ingetrokken {C}"),
    _hit(NOW - timedelta(minutes=50), "gateway-service", f"failed to process {D}"),
    _hit(NOW - timedelta(minutes=5), "gateway-service", f"processing {E}"),
    _hit(NOW - timedelta(minutes=50), "gateway-service", f"failed to process {F}"),
    # previous window
    _hit(NOW - timedelta(minutes=90), "zoekportaal", f"gepubliceerd live {P}"),
]


def _windowed_es(events):
    async def fake_es(sid, index, body):
        if index != "ds-prod5-koop-plooi*":
            return {"hits": {"hits": []}}
        rng = body["query"]["bool"]["filter"][0]["range"]["@timestamp"]
        gte, lt = _parse(rng["gte"]), _parse(rng["lt"])
        hits = [h for h in events if gte <= _parse(h["_source"]["@timestamp"]) < lt]
        return {"hits": {"hits": hits}}
    return fake_es


async def _published_only_F(doc_id):
    if doc_id == F:
        return {"status": "gepubliceerd", "title": "Doc F", "link": "https://open.overheid.nl/f"}
    return None


def _setup(monkeypatch):
    monkeypatch.setattr(documents, "_es_search", _windowed_es(EVENTS))
    monkeypatch.setattr(documents, "fetch_document_meta", _published_only_F)
    monkeypatch.setattr(documents.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")


async def test_outcomes_counts_and_split(monkeypatch):
    _setup(monkeypatch)
    res = await documents.build_pipeline_outcomes("sid", 60, "logs-*", now=NOW)

    t = res["totals"]
    assert t["published"] == 2     # A + F (reconciled live)
    assert t["updated"] == 1       # B
    assert t["withdrawn"] == 1     # C
    assert t["failed"] == 1        # D only — F moved to published
    assert t["in_progress"] == 1   # E

    assert res["by_pipeline"]["OVS"]["withdrawn"] == 1
    assert res["by_pipeline"]["NVS"]["published"] == 2
    assert res["by_pipeline"]["NVS"]["failed"] == 1
    assert res["reconciled_live"] == 1


async def test_outcomes_success_rate_backlog_and_trend(monkeypatch):
    _setup(monkeypatch)
    res = await documents.build_pipeline_outcomes("sid", 60, "logs-*", now=NOW)

    assert res["throughput"] == 3          # published(2) + updated(1)
    assert res["publish_failures"] == 1
    assert res["backlog"] == 1
    assert res["success_rate"] == 75.0     # 3 / (3 + 1)
    # previous window had 1 publication → +200%
    assert res["trend"]["prev_throughput"] == 1
    assert res["trend"]["throughput_pct"] == 200.0


async def test_outcomes_latency_and_drilldown(monkeypatch):
    _setup(monkeypatch)
    res = await documents.build_pipeline_outcomes("sid", 60, "logs-*", now=NOW)

    # A spanned intake→live over 10 minutes → one latency sample of 600s.
    assert res["latency"]["samples"] == 1
    assert res["latency"]["p50_seconds"] == 600.0

    pub = res["drill"]["published"]
    assert any(r["id"] == A for r in pub)
    row = next(r for r in pub if r["id"] == A)
    assert row["link"].endswith(A) or "open.overheid.nl" in row["link"]
    assert row["when"].startswith("2026-06-12")


async def test_outcomes_empty_window_is_clean(monkeypatch):
    async def empty_es(sid, index, body):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(documents, "_es_search", empty_es)
    res = await documents.build_pipeline_outcomes("sid", 60, "logs-*", now=NOW)
    assert res["documents"] == 0
    assert res["throughput"] == 0
    assert res["success_rate"] is None
    assert res["backlog"] == 0
