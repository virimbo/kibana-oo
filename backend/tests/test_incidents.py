"""The durable incident store: open, refresh, resolve, ordering, and the
stable first_detected that makes an incident's age meaningful. Each test gets an
isolated temp DB via the autouse fixture in conftest.py."""
from datetime import datetime, timedelta, timezone

import incidents

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _rec(did, verdict="problem", stage="Intake"):
    return {
        "id": did, "verdict": verdict, "headline": "A problem occurred",
        "stuck_stage": stage, "title": "Doc", "link": "https://open.overheid.nl/x",
        "events": 3, "last_seen": "2026-06-12T10:00:00Z", "stage_index": 0,
        "data_view": "logs-*",
    }


async def test_upsert_open_then_list():
    await incidents.upsert_open(_rec("a"), NOW)
    rows = await incidents.open_incidents()
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "a"
    assert rows[0]["status"] == "open"
    assert rows[0]["first_detected"] == NOW.isoformat()


async def test_first_detected_is_stable_across_refreshes():
    await incidents.upsert_open(_rec("a"), NOW)
    later = NOW + timedelta(hours=5)
    await incidents.upsert_open(_rec("a"), later)
    rows = await incidents.open_incidents()
    assert len(rows) == 1                                  # still one incident
    assert rows[0]["first_detected"] == NOW.isoformat()    # age anchored to first sight
    assert rows[0]["last_detected"] == later.isoformat()


async def test_resolve_removes_from_open_list():
    await incidents.upsert_open(_rec("a"), NOW)
    assert await incidents.resolve("a", "published", NOW) is True
    assert await incidents.open_incidents() == []


async def test_resolve_unknown_is_noop():
    assert await incidents.resolve("ghost", "published", NOW) is False


async def test_open_incidents_oldest_first():
    await incidents.upsert_open(_rec("old"), NOW)
    await incidents.upsert_open(_rec("new"), NOW + timedelta(hours=1))
    rows = await incidents.open_incidents()
    assert [r["doc_id"] for r in rows] == ["old", "new"]


async def test_resolved_incident_can_reopen():
    await incidents.upsert_open(_rec("a"), NOW)
    await incidents.resolve("a", "progressed", NOW)
    assert await incidents.open_incidents() == []
    # the same document goes stuck again → it shows up as open once more
    await incidents.upsert_open(_rec("a"), NOW + timedelta(days=2))
    rows = await incidents.open_incidents()
    assert len(rows) == 1 and rows[0]["status"] == "open"
    assert rows[0]["resolution"] is None
