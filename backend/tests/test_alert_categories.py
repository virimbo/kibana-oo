"""New ES-fed alert categories: stuck documents (doc id + clickable link) and
per-service error-rate/5xx spikes. Fed by the background service-session so they
page unattended once credentials exist, and completely inert (no ES calls) when
there is no sid. No real network — health/snapshot dicts are injected directly."""
import asyncio

import alerts


# ── stuck documents ───────────────────────────────────────────────────────────
def _health(rows):
    return {"stuck_count": len(rows), "stuck": rows}


def test_normalize_stuck_docs_builds_doc_id_and_link_and_severity():
    health = _health([
        {"id": "1a7e-uuid", "verdict": "problem", "stuck_stage": "Publicatie",
         "title": "Besluit X", "link": "https://open.overheid.nl/details/1a7e-uuid"},
        {"id": "ronl-abc", "verdict": "stuck", "stuck_stage": "Indexatie",
         "title": "Nota Y", "link": None},
    ])
    items = alerts._normalize_stuck_docs(health)
    by_id = {it["doc_id"]: it for it in items}

    problem = by_id["1a7e-uuid"]
    assert problem["category"] == "document"
    assert problem["severity"] == "critical"           # verdict == problem
    assert problem["card_id"] == "document:PROD:1a7e-uuid"
    assert "vastgelopen bij Publicatie" == problem["status"]
    assert problem["link"] == "https://open.overheid.nl/details/1a7e-uuid"
    assert problem["stage"] == "Publicatie"
    assert problem["title"] == "Besluit X"

    stuck = by_id["ronl-abc"]
    assert stuck["severity"] == "warn"                  # verdict != problem
    # no health link → falls back to the doculoket template with the id
    assert "ronl-abc" in stuck["link"]


def test_normalize_stuck_docs_caps_and_summarizes(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alert_stuck_docs_max", 2)
    rows = [{"id": f"d{i}", "verdict": "stuck", "stuck_stage": "Intake"}
            for i in range(5)]
    items = alerts._normalize_stuck_docs(_health(rows))
    # 2 capped items + 1 summary item
    assert len(items) == 3
    summary = items[-1]
    assert summary["name"] == "overige"
    assert "3" in summary["status"]                     # 5 - 2 = 3 remaining


def test_normalize_stuck_docs_empty_health_is_no_items():
    assert alerts._normalize_stuck_docs(None) == []
    assert alerts._normalize_stuck_docs({}) == []
    assert alerts._normalize_stuck_docs({"stuck": []}) == []


# ── per-service error rate ─────────────────────────────────────────────────────
def _snap(services):
    return {"affected_services": services}


def test_normalize_error_rate_thresholds(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alert_errorrate_min", 50)
    monkeypatch.setattr(settings, "alert_errorrate_crit", 200)
    snap = _snap([
        {"name": "harvester", "count": 300},   # >= crit → critical
        {"name": "search", "count": 80},        # >= min  → warn
        {"name": "quiet", "count": 10},         # < min   → skipped
    ])
    items = alerts._normalize_error_rate(snap)
    by_name = {it["name"]: it for it in items}
    assert "quiet" not in by_name
    assert by_name["harvester"]["severity"] == "critical"
    assert by_name["harvester"]["card_id"] == "errorrate:PROD:harvester"
    assert by_name["harvester"]["status"] == "300 errors"
    assert by_name["search"]["severity"] == "warn"
    assert by_name["search"]["category"] == "errorrate"


def test_normalize_error_rate_empty_snapshot_is_no_items():
    assert alerts._normalize_error_rate(None) == []
    assert alerts._normalize_error_rate({}) == []
    assert alerts._normalize_error_rate({"affected_services": []}) == []


# ── _collect: sid gates the ES-fed categories ─────────────────────────────────
def _stub_session_less(monkeypatch):
    """Make the three session-less monitors return nothing (no network)."""
    import cert_monitor
    import rabbitmq_dlq
    import uptime

    async def _no_uptime():
        return {"enabled": False}

    async def _no_dlq():
        return {"configured": False}

    monkeypatch.setattr(uptime, "latest", _no_uptime)
    monkeypatch.setattr(rabbitmq_dlq, "latest", _no_dlq)
    monkeypatch.setattr(cert_monitor, "latest", lambda: ([], None))


def test_collect_none_returns_only_session_less_and_makes_no_es_calls(monkeypatch):
    """sid=None → the ES-fed collectors are skipped entirely: dashboard's cached
    health/snapshot are never touched, and no document/errorrate items appear."""
    _stub_session_less(monkeypatch)
    import dashboard

    async def _boom(*a, **k):
        raise AssertionError("ES call must not happen when sid is None")

    monkeypatch.setattr(dashboard, "get_cached_health", _boom)
    monkeypatch.setattr(dashboard, "get_cached_snapshot", _boom)

    items = asyncio.run(alerts._collect(None))
    cats = {it["category"] for it in items}
    assert "document" not in cats
    assert "errorrate" not in cats


def test_collect_with_sid_includes_es_fed_items(monkeypatch):
    """A real sid → the ES-fed collectors run and their items are included."""
    _stub_session_less(monkeypatch)
    import dashboard

    async def _health(sid, dv):
        return _health_dict()

    def _health_dict():
        return {"stuck": [{"id": "docX", "verdict": "problem",
                           "stuck_stage": "Publicatie", "title": "T",
                           "link": "https://open.overheid.nl/details/docX"}]}

    async def _snap(sid, minutes, dv, *a, **k):
        return {"affected_services": [{"name": "harvester", "count": 999}]}

    monkeypatch.setattr(dashboard, "get_cached_health", _health)
    monkeypatch.setattr(dashboard, "get_cached_snapshot", _snap)

    items = asyncio.run(alerts._collect("sid-123"))
    by_card = {it["card_id"]: it for it in items}
    assert "document:PROD:docX" in by_card
    assert by_card["document:PROD:docX"]["severity"] == "critical"
    assert "errorrate:PROD:harvester" in by_card
    assert by_card["errorrate:PROD:harvester"]["severity"] == "critical"


def test_collect_with_sid_never_raises_on_es_failure(monkeypatch):
    """A failure in either ES-fed collector yields no items but never breaks the
    pass — the session-less categories still return."""
    _stub_session_less(monkeypatch)
    import dashboard

    async def _boom(*a, **k):
        raise RuntimeError("cluster down")

    monkeypatch.setattr(dashboard, "get_cached_health", _boom)
    monkeypatch.setattr(dashboard, "get_cached_snapshot", _boom)

    items = asyncio.run(alerts._collect("sid-123"))   # must not raise
    cats = {it["category"] for it in items}
    assert "document" not in cats and "errorrate" not in cats


# ── Mattermost payload: document card carries id + clickable link ─────────────
def test_mattermost_document_card_has_doc_id_and_link():
    import alerts_mattermost
    item = alerts._item("document", "PROD", "docX", "critical",
                        status="vastgelopen bij Publicatie")
    item["doc_id"] = "docX"
    item["link"] = "https://open.overheid.nl/details/docX"
    item["stage"] = "Publicatie"
    a = alerts_mattermost.payload(item, "new", "ok", "http://d/", "FB-OO:Anton")["attachments"][0]
    fields = {f["title"]: f["value"] for f in a["fields"]}
    assert "Document" in fields
    assert "[docX](https://open.overheid.nl/details/docX)" == fields["Document"]
    # the metric stays prominent in the title / pretext
    assert "vastgelopen bij Publicatie" in a["title"]
    assert "vastgelopen bij Publicatie" in a["pretext"]


def test_mattermost_document_uses_doc_category_icon():
    import alerts_mattermost
    item = alerts._item("document", "PROD", "docX", "warn", status="vastgelopen bij Intake")
    item["doc_id"] = "docX"
    item["link"] = "https://doculoket.overheid.nl/#/aanleveren/docX"
    a = alerts_mattermost.payload(item, "new", "ok", "http://d/", "S")["attachments"][0]
    cat_field = next(f for f in a["fields"] if f["title"] == "Categorie")
    assert "📄" in cat_field["value"]


def test_email_document_carries_id_and_link():
    import alerts_email
    item = alerts._item("document", "PROD", "docX", "critical",
                        status="vastgelopen bij Publicatie")
    item["doc_id"] = "docX"
    item["link"] = "https://open.overheid.nl/details/docX"
    _, _, text = alerts_email.render(item, "new", "ok", "https://dash/")
    assert "docX" in text
    assert "https://open.overheid.nl/details/docX" in text


def test_api_valid_categories_includes_new_ones():
    import alerts_api
    assert "document" in alerts_api._VALID_CATEGORIES
    assert "errorrate" in alerts_api._VALID_CATEGORIES
