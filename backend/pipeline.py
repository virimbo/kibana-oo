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


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


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


def build_pipeline_view(events: list[dict], now: datetime | None = None) -> dict:
    """Roll a document's log events into the canonical lifecycle: every stage,
    in order, with reached/status/duration/problems — plus a plain-language
    verdict. `events` items need: timestamp, service, message, severity."""
    now = now or datetime.now(timezone.utc)

    # bucket events per canonical stage
    buckets: dict[str, list[dict]] = {s["key"]: [] for s in PIPELINE}
    for e in events:
        key = stage_for_service(e.get("service"))
        if key:
            buckets[key].append(e)

    reached_indices = [i for i, s in enumerate(PIPELINE) if buckets[s["key"]]]
    furthest = max(reached_indices) if reached_indices else -1

    stages_out: list[dict] = []
    for i, s in enumerate(PIPELINE):
        evs = buckets[s["key"]]
        reached = bool(evs)
        # aggregate problems with counts
        problems: dict[str, dict] = {}
        worst = 0
        for e in evs:
            sev = e.get("severity", "ok")
            worst = max(worst, _SEV_RANK.get(sev, 0))
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
            "current": i == furthest and i < len(PIPELINE) - 1,
            "status": status,
            "events": len(evs),
            "first_seen": first.isoformat() if first else None,
            "last_seen": last.isoformat() if last else None,
            "duration": _fmt_duration(dur),
            "slow": bool(dur and dur > STUCK_SECONDS),
            "problems": sorted(problems.values(), key=lambda p: -p["count"]),
        })

    return _assess(stages_out, furthest, events, now)


def _assess(stages_out, furthest, events, now) -> dict:
    """Roll the per-stage view into one plain-language verdict."""
    terminal_reached = stages_out[-1]["reached"]
    last_times = sorted(t for t in (_parse(e.get("timestamp")) for e in events) if t)
    overall_last = last_times[-1] if last_times else None

    worst = max((_SEV_RANK.get(s["status"], 0) for s in stages_out if s["reached"]), default=0)
    furthest_stage = stages_out[furthest] if furthest >= 0 else None

    gap = (now - overall_last).total_seconds() if overall_last else None
    stuck = bool(not terminal_reached and gap is not None and gap > STUCK_SECONDS)

    # total problem counts for the headline
    totals: dict[str, dict] = {}
    for s in stages_out:
        for p in s["problems"]:
            t = totals.setdefault(p["key"], {**p, "count": 0})
            t["count"] += p["count"]
    problem_phrase = ", ".join(f"{t['count']}× {t['key'].replace('_', ' ')}"
                               for t in sorted(totals.values(), key=lambda p: -p["count"]))

    if not furthest_stage:
        verdict, headline = "unknown", "No pipeline activity found for this document."
    elif worst == 2:
        verdict = "problem"
        headline = f"⛔ A problem occurred at {furthest_stage['name']}."
    elif terminal_reached and worst <= 1 and not totals:
        verdict, headline = "healthy", "✅ Healthy & complete — the document is live and searchable."
    elif terminal_reached:
        verdict = "warnings"
        headline = f"⚠️ Completed with warnings ({problem_phrase})."
    elif stuck:
        verdict = "stuck"
        headline = f"🕒 Appears stuck at {furthest_stage['name']} — no progress for {_fmt_duration(gap)}."
    else:
        verdict = "in_progress"
        headline = f"⏳ In progress — currently at {furthest_stage['name']}."

    nxt = next((s for s in stages_out if not s["reached"]), None)
    return {
        "stages": stages_out,
        "verdict": verdict,
        "headline": headline,
        "furthest_stage": furthest_stage["name"] if furthest_stage else None,
        "next_stage": nxt["name"] if nxt else None,
        "reached_count": sum(1 for s in stages_out if s["reached"]),
        "total_stages": len(stages_out),
        "problems_total": sorted(totals.values(), key=lambda p: -p["count"]),
        "stuck": stuck,
    }
