"""Grounded AI triage: turn a deterministic snapshot into a strict prompt and
generate a plain-language briefing. The LLM only narrates facts it is handed."""
import json

from llm import generate_answer
from monitoring import DashboardSnapshot

SYSTEM = (
    "You are KIBANA-OO's monitoring analyst. You are given EXACT facts computed "
    "from Elasticsearch about the critical issues in the selected time window. "
    "Write a short briefing for an administrator.\n"
    "Rules:\n"
    "- Use ONLY the facts provided. Do not invent services, causes, or numbers.\n"
    "- Cite the actual numbers from the facts.\n"
    "- If the facts are insufficient to determine a cause, say 'insufficient data'.\n"
    "- Lead with the single most important issue, then list the rest.\n"
    "- Be concise: a few sentences plus a short prioritized list."
)


def build_facts(snap: DashboardSnapshot) -> str:
    """Serialize the deterministic snapshot into the JSON facts the LLM narrates."""
    facts = {
        "period_minutes": snap.period_minutes,
        "window_start": snap.window_start,
        "window_end": snap.window_end,
        "data_view": snap.data_view,
        "total_criticals": snap.total,
        "status": snap.status_level,
        "vs_prior_period_count": snap.delta.previous,
        "vs_prior_period_pct": snap.delta.pct_vs_previous,
        "by_system": [{"system": s.label, "count": s.count, "available": s.available} for s in snap.systems],
        "top_error_signatures": snap.top_signatures,
        "affected_services": snap.affected_services,
        "http_5xx": snap.status_codes,
        "failing_urls": snap.failing_urls,
        "documents_not_found_404": {"total": snap.not_found_total, "top_urls": snap.not_found_urls},
        "nvs_documents_processed": snap.nvs_count,
        "data_partial": snap.partial,
    }
    return json.dumps(facts, indent=2, default=str)


TRACE_SYSTEM = (
    "You are KIBANA-OO's document-flow analyst. You are given EXACT facts about "
    "ONE document's journey through the publication pipeline (the services it "
    "passed, counts, errors, timing, and its official metadata).\n"
    "Rules:\n"
    "- Use ONLY the facts provided. Do not invent services, causes, or numbers.\n"
    "- Explain in plain language what happened to the document and whether the "
    "flow looks healthy.\n"
    "- If there are errors, name the service(s) where they occurred.\n"
    "- Be concise: 2-4 sentences.\n"
    "- End with a final line exactly of the form 'Verdict: HEALTHY' or "
    "'Verdict: NEEDS ATTENTION'."
)


def build_trace_facts(trace: dict) -> str:
    """Serialize a document trace into the JSON facts the LLM narrates. Includes
    the canonical lifecycle so the AI's story matches the deterministic verdict."""
    meta = trace.get("portal_meta") or {}
    life = trace.get("lifecycle") or {}
    facts = {
        "document_id": trace.get("id"),
        "official_title": trace.get("title"),
        "organization": meta.get("organization"),
        "document_type": meta.get("type"),
        "publication_status": meta.get("status"),
        "total_log_events": len(trace.get("events", [])),
        "errors": trace.get("errors"),
        "warnings": trace.get("warnings"),
        "first_seen": trace.get("first_seen"),
        "last_seen": trace.get("last_seen"),
        "lifecycle_verdict": life.get("headline"),
        "furthest_stage_reached": life.get("furthest_stage"),
        "next_pending_stage": life.get("next_stage"),
        "appears_stuck": life.get("stuck"),
        "problems": life.get("problems_total"),
        "pipeline_stages": [
            {
                "stage": s.get("name"),
                "reached": s.get("reached"),
                "status": s.get("status"),
                "events": s.get("events"),
                "time_in_stage": s.get("duration"),
                "problems": [f"{p['count']}× {p['explanation']}" for p in s.get("problems", [])],
            }
            for s in life.get("stages", [])
        ],
    }
    return json.dumps(facts, indent=2, default=str)


async def explain_trace(trace: dict, session: dict | None = None) -> str:
    """Plain-language, grounded explanation of one document's journey."""
    return await generate_answer(
        question="Explain what happened to this document as it moved through the pipeline, and whether anything looks wrong.",
        context=build_trace_facts(trace),
        system=TRACE_SYSTEM,
        session=session,
    )


async def generate_briefing(snap: DashboardSnapshot, session: dict | None = None) -> str:
    # Pass the grounding rules as the system message (not buried in the user
    # turn) so a small model treats them as authoritative. `session` carries the
    # per-session LLM provider preference.
    return await generate_answer(
        question="Summarize the critical issues in this window.",
        context=build_facts(snap),
        system=SYSTEM,
        session=session,
    )
