"""Grounded AI triage: turn a deterministic snapshot into a strict prompt and
generate a plain-language briefing. The LLM only narrates facts it is handed."""
import json

from llm import generate_answer
from monitoring import DashboardSnapshot

SYSTEM = (
    "You are KIBANA-OO's monitoring analyst. You are given EXACT facts computed "
    "from Elasticsearch about today's critical issues. Write a short briefing for "
    "an administrator.\n"
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
        "date": snap.date,
        "total_criticals": snap.total,
        "status": snap.status_level,
        "vs_previous_day_pct": snap.delta.pct_vs_previous,
        "vs_7day_avg_pct": snap.delta.pct_vs_avg,
        "by_system": [{"system": s.label, "count": s.count, "available": s.available} for s in snap.systems],
        "top_error_signatures": snap.top_signatures,
        "affected_services": snap.affected_services,
        "http_5xx": snap.status_codes,
        "failing_urls": snap.failing_urls,
        "data_partial": snap.partial,
    }
    return json.dumps(facts, indent=2, default=str)


async def generate_briefing(snap: DashboardSnapshot) -> str:
    # Pass the grounding rules as the system message (not buried in the user
    # turn) so a small model treats them as authoritative.
    return await generate_answer(
        question="Summarize today's critical issues.",
        context=build_facts(snap),
        system=SYSTEM,
    )
