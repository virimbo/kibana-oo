"""Canonical document lifecycle for the Woo NVS pipeline.

The single source of truth that maps raw log services onto friendly, ordered
stages, classifies health from the *message* (not just the level), and rolls a
trace into a plain-language verdict a non-technical admin can read at a glance.

Mirrors docs/KIBANA-OO/Document lifecycle (pipeline).md — keep them in step.
"""
import re
from datetime import datetime, timezone

# ── Canonical stages, in order. `services` are lowercase substrings matched
# against the log service name. Edit here to track the real pipeline. ──────────
PIPELINE = [
    {"key": "intake", "name": "Intake", "icon": "📥",
     "desc": "Received at the front desk (DocuLoket / gateway).",
     "services": ["doculoket", "gateway", "aanlever"]},
    {"key": "storage", "name": "Storage", "icon": "🗄️",
     "desc": "Stored safely.",
     "services": ["documentopslag", "documentenopslag", "opslag", "storage"]},
    {"key": "virus", "name": "Virus scan", "icon": "🛡️",
     "desc": "Checked for viruses.",
     "services": ["antivirus", "virus"]},
    {"key": "processing", "name": "Processing", "icon": "⚙️",
     "desc": "Processing coordinated across services.",
     "services": ["orkestratie", "orchestratie", "verwerking"]},
    {"key": "publication", "name": "Publication", "icon": "📣",
     "desc": "Marked for publication.",
     "services": ["publicatiebeheer", "publicatie"]},
    {"key": "indexing", "name": "Indexing", "icon": "🔎",
     "desc": "Made searchable (indexed).",
     "services": ["indexatie", "indexer", "solr", "index"]},
    {"key": "export", "name": "Export", "icon": "📤",
     "desc": "Exported to downstream systems.",
     "services": ["export", "dpc"]},
    {"key": "live", "name": "Live", "icon": "🌐",
     "desc": "Live & searchable on open.overheid.nl.",
     "services": ["zoekportaal", "zoeken", "search", "portaal"]},
]
_STAGE_INDEX = {s["key"]: i for i, s in enumerate(PIPELINE)}
TERMINAL_KEY = PIPELINE[-1]["key"]

# A stage with no activity for this long, when the document hasn't finished, is
# considered "stuck". A single stage lasting longer than this is "slow".
STUCK_SECONDS = 4 * 3600  # 4 hours


def stage_for_service(service: str | None) -> str | None:
    """Map a raw log service name to a canonical stage key (or None)."""
    s = (service or "").lower()
    for stage in PIPELINE:
        if any(kw in s for kw in stage["services"]):
            return stage["key"]
    return None


# ── Message-aware problem detection (honest health) ───────────────────────────
# Order matters: the first match wins. Earlier = more specific / less severe.
_MESSAGE_RULES = [
    (re.compile(r"not.?found|404|geen .*gevonden", re.I), "not_found", "warning",
     "A lookup returned 'not found' — often a routine probe to the public API."),
    (re.compile(r"connection reset", re.I), "connection_reset", "warning",
     "The service briefly lost its connection to another service and retried."),
    (re.compile(r"broken pipe", re.I), "broken_pipe", "warning",
     "A data transfer was cut off part-way."),
    (re.compile(r"timed?.?out|timeout", re.I), "timeout", "warning",
     "A step took too long and timed out."),
    (re.compile(r"refused", re.I), "refused", "warning",
     "A connection was refused by another service."),
    (re.compile(r"\b5\d\d\b|internal server error", re.I), "server_error", "error",
     "A downstream service returned a server error."),
    (re.compile(r"exception|stacktrace|\bfatal\b|mislukt|\bfailed\b|failure", re.I), "failure", "error",
     "The service reported a failure."),
]
_SEV_RANK = {"ok": 0, "warning": 1, "error": 2}


def classify_message(message: str | None) -> dict | None:
    """Return {key, severity, explanation} for a problematic message, else None."""
    msg = message or ""
    for rx, key, sev, friendly in _MESSAGE_RULES:
        if rx.search(msg):
            return {"key": key, "severity": sev, "explanation": friendly}
    return None


def event_severity(level: str | None, message: str | None) -> str:
    """Honest severity from BOTH the log level and the message content."""
    if (level or "").upper() in ("ERROR", "FATAL", "CRITICAL"):
        return "error"
    prob = classify_message(message)
    if prob:
        return prob["severity"]
    if (level or "").upper() in ("WARN", "WARNING"):
        return "warning"
    return "ok"


def parse_ts(ts: str | None):
    """Parse an ISO-8601 log timestamp (tolerating a trailing 'Z') to an aware
    datetime, or None if it's missing/unparseable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# Backwards-compatible internal alias (used throughout this module).
_parse = parse_ts


def _fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds < 0:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m} min"
    return f"{m // 60}h {m % 60}m"


def is_published(status: str | None) -> bool:
    """True when the public portal says the document is actually live. This is
    GROUND TRUTH — it overrides any log-derived 'stuck' guess."""
    s = (status or "").lower()
    return "gepubliceerd" in s or "published" in s or s == "live"


def build_pipeline_view(events: list[dict], now: datetime | None = None,
                        published: bool = False) -> dict:
    """Roll a document's log events into the canonical lifecycle: every stage,
    in order, with reached/status/duration/problems — plus a plain-language
    verdict. `events` items need: timestamp, service, message, severity.

    `published` is authoritative truth from open.overheid.nl: if the document is
    live there, it is NOT stuck — the terminal stage is marked reached (confirmed)
    even when the logs we scanned don't show it."""
    now = now or datetime.now(timezone.utc)

    buckets: dict[str, list[dict]] = {s["key"]: [] for s in PIPELINE}
    for e in events:
        key = stage_for_service(e.get("service"))
        if key:
            buckets[key].append(e)

    live_idx = len(PIPELINE) - 1
    # Publication is confirmed live but the logs don't show the final stage.
    confirmed_live = published and not buckets[PIPELINE[live_idx]["key"]]

    reached_indices = [i for i, s in enumerate(PIPELINE) if buckets[s["key"]]]
    if confirmed_live:
        reached_indices.append(live_idx)
    furthest = max(reached_indices) if reached_indices else -1

    stages_out: list[dict] = []
    for i, s in enumerate(PIPELINE):
        evs = buckets[s["key"]]
        forced = confirmed_live and i == live_idx
        reached = bool(evs) or forced
        problems: dict[str, dict] = {}
        worst = 0
        for e in evs:
            worst = max(worst, _SEV_RANK.get(e.get("severity", "ok"), 0))
            prob = classify_message(e.get("message"))
            if prob:
                p = problems.setdefault(prob["key"], {**prob, "count": 0})
                p["count"] += 1
        times = sorted(t for t in (_parse(e.get("timestamp")) for e in evs) if t)
        first, last = (times[0], times[-1]) if times else (None, None)
        dur = (last - first).total_seconds() if first and last else None

        if not reached:
            status = "missing"
        elif worst == 2:
            status = "error"
        elif worst == 1 or problems:
            status = "warning"
        else:
            status = "ok"

        stages_out.append({
            "key": s["key"], "name": s["name"], "icon": s["icon"], "desc": s["desc"],
            "reached": reached,
            "confirmed": forced,  # reached per open.overheid.nl, not the logs
            "current": i == furthest and i < live_idx,
            "status": status,
            "events": len(evs),
            "first_seen": first.isoformat() if first else None,
            "last_seen": last.isoformat() if last else None,
            "duration": _fmt_duration(dur),
            "slow": bool(dur and dur > STUCK_SECONDS),
            "problems": sorted(problems.values(), key=lambda p: -p["count"]),
        })

    return _assess(stages_out, furthest, events, now, published)


def _assess(stages_out, furthest, events, now, published=False) -> dict:
    """Roll the per-stage view into one plain-language verdict. Publication status
    is ground truth and overrides any 'stuck' guess."""
    terminal_reached = stages_out[-1]["reached"]
    last_times = sorted(t for t in (_parse(e.get("timestamp")) for e in events) if t)
    overall_last = last_times[-1] if last_times else None
    worst = max((_SEV_RANK.get(s["status"], 0) for s in stages_out if s["reached"]), default=0)
    furthest_stage = stages_out[furthest] if furthest >= 0 else None

    totals: dict[str, dict] = {}
    for s in stages_out:
        for p in s["problems"]:
            t = totals.setdefault(p["key"], {**p, "count": 0})
            t["count"] += p["count"]
    problem_phrase = ", ".join(f"{t['count']}× {t['key'].replace('_', ' ')}"
                               for t in sorted(totals.values(), key=lambda p: -p["count"]))

    gap = (now - overall_last).total_seconds() if overall_last else None
    # A published document is NEVER stuck — it's live and readable on the portal.
    stuck = bool(not published and not terminal_reached and gap is not None and gap > STUCK_SECONDS)

    if published:
        if totals or worst >= 1:
            verdict = "warnings"
            headline = f"✅ Published & live on open.overheid.nl — but had warnings on the way ({problem_phrase})."
        else:
            verdict = "published"
            headline = "✅ Published & live on open.overheid.nl."
    elif not furthest_stage:
        verdict, headline = "unknown", "No pipeline activity found for this document."
    elif worst == 2:
        verdict = "problem"
        headline = f"⛔ A problem occurred at {furthest_stage['name']} — not yet live."
    elif terminal_reached and worst <= 1 and not totals:
        verdict, headline = "healthy", "✅ Healthy & complete — the document is live and searchable."
    elif terminal_reached:
        verdict = "warnings"
        headline = f"⚠️ Completed with warnings ({problem_phrase})."
    elif stuck:
        verdict = "stuck"
        headline = f"🕒 Not live yet — stuck at {furthest_stage['name']}, no progress for {_fmt_duration(gap)}."
    else:
        verdict = "in_progress"
        headline = f"⏳ In progress — currently at {furthest_stage['name']}."

    nxt = next((s for s in stages_out if not s["reached"]), None)
    return {
        "stages": stages_out,
        "verdict": verdict,
        "headline": headline,
        "published": published,
        "furthest_stage": furthest_stage["name"] if furthest_stage else None,
        "next_stage": nxt["name"] if nxt else None,
        "reached_count": sum(1 for s in stages_out if s["reached"]),
        "total_stages": len(stages_out),
        "problems_total": sorted(totals.values(), key=lambda p: -p["count"]),
        "stuck": stuck,
    }
