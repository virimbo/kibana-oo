"""SmartContextPanel — context intelligence engine.

Additive, read-only. Given a dashboard *card id*, it resolves the related
component, reads that component's note from the Obsidian vault (frontmatter +
TODO checkboxes), and optionally asks the existing LLM for a short analysis.

Design rules honoured here:
- **Read-only & sandboxed:** the vault is only ever *read*, and only from inside
  a single resolved root directory — a crafted component/card id can never escape
  it (OWASP A03 path traversal).
- **Graceful degradation:** a missing note, missing field or unreadable vault
  yields an empty/partial result, never an exception that breaks the panel.
- **No new dependency:** frontmatter is parsed by a tiny YAML-subset parser that
  only understands the controlled fields below (scalars + inline `[a, b]` lists).
- **No coupling to FROZEN code:** nothing here imports or touches the certificate
  modules; live per-card values (label/health) are supplied by the caller.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from cache import TTLCache
from config import settings

logger = logging.getLogger(__name__)

# ── Card → component registry ────────────────────────────────────────────────
# The single source of truth for which dashboard cards are "smart" and which
# vault component each maps to. A note becomes that component by carrying a
# matching `component:` value in its frontmatter. Adding a card = one line here.
REGISTRY: dict[str, str] = {
    # Hero strip
    "hero:status": "criticals",
    "hero:criticals": "criticals",
    "hero:risk": "documents-pipeline",
    "hero:aanlever": "aanleverfouten",
    "hero:dlq": "rabbitmq-queues",
    # "Needs attention" cards
    "card:aanleverfouten": "aanleverfouten",
    "card:dlq": "rabbitmq-queues",
    "card:certificates": "certificates",
    # Dead-letter / verwerkingsstraat queue tiles (all share the queues note;
    # the card supplies its own per-queue label + live health for the header).
    "queue:antivirus": "rabbitmq-queues",
    "queue:document-harvester": "rabbitmq-queues",
    "queue:documentopslag": "rabbitmq-queues",
    "queue:export": "rabbitmq-queues",
    "queue:indexatie": "rabbitmq-queues",
    "queue:orchestratie": "rabbitmq-queues",
    # Throughput & diagnostics
    "card:outcomes": "outcomes",
    "card:notfound": "criticals",
    "card:nvs": "documents-pipeline",
    "card:overtime": "criticals",
    "card:bysystem": "criticals",
    "card:signatures": "criticals",
    "card:services": "criticals",
    "card:http5xx": "criticals",
    "card:pipeline-health": "documents-pipeline",
    "card:aitriage": "criticals",
    # Uptime / availability board — every site tile resolves to the shared
    # availability component (the card supplies its own per-site label + state).
    "uptime:open.overheid.nl": "availability",
    "uptime:doculoket.overheid.nl": "availability",
    "uptime:admin (login)": "availability",
    "uptime:open-acc.overheid.nl": "availability",
    "uptime:doculoket-acc.overheid.nl": "availability",
    "uptime:gateway-zoek (test)": "availability",
}
# Any card id starting with this prefix maps to the availability component, so
# renaming a target in UPTIME_TARGETS still resolves without a code change.
_PREFIX_FALLBACK = {"uptime:": "availability"}

# Risk → a coarse health hint when the card supplies no live status.
_RISK_RANK = {"low": "ok", "medium": "warn", "high": "crit", "critical": "crit"}

# ── Vault location (sandbox root) ────────────────────────────────────────────


def _default_vault() -> Path:
    """Find docs/KIBANA-OO by walking up from this file (local dev). In a
    container, set SMART_CONTEXT_VAULT_PATH to the mounted vault instead."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "docs" / "KIBANA-OO"
        if cand.is_dir():
            return cand
    return Path()


def vault_root() -> Path:
    configured = (settings.smart_context_vault_path or "").strip()
    return Path(configured).resolve() if configured else _default_vault()


# ── Frontmatter + TODO parsing (dependency-free, controlled subset) ──────────
_SCALAR_FIELDS = {
    "title", "component", "purpose-business", "purpose-technical",
    "risk", "owner", "health", "last-incident",
}
_LIST_FIELDS = {"dependencies", "related", "component"}
_TODO_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_inline_list(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [_strip_quotes(p) for p in inner.split(",") if p.strip()]


def parse_note(text: str) -> tuple[dict, str]:
    """Split a note into (frontmatter dict, body). Tolerates CRLF and absent
    frontmatter. `component`/`dependencies`/`related` may be scalars or lists."""
    lines = text.splitlines()
    meta: dict = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
            raw = lines[i]
            if ":" not in raw:
                continue
            key, _, val = raw.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key in _LIST_FIELDS and (val.startswith("[") or "," in val):
                meta[key] = _parse_inline_list(val)
            elif key in _SCALAR_FIELDS or key in _LIST_FIELDS:
                meta[key] = _strip_quotes(val)
    body = "\n".join(lines[body_start:])
    return meta, body


def parse_todos(body: str) -> list[dict]:
    """Every Markdown task line `- [ ] ...` / `- [x] ...` in the body."""
    todos: list[dict] = []
    for line in body.splitlines():
        m = _TODO_RE.match(line)
        if m:
            todos.append({"text": m.group(2).strip(), "done": m.group(1).lower() == "x"})
    return todos


def _component_ids(meta: dict) -> list[str]:
    comp = meta.get("component")
    if isinstance(comp, list):
        return [c.strip().lower() for c in comp if c.strip()]
    if isinstance(comp, str) and comp.strip():
        return [comp.strip().lower()]
    return []


# ── Vault index (cached, re-scanned on TTL) ──────────────────────────────────
_index_cache = TTLCache(ttl=max(30, settings.dashboard_cache_ttl))


def _build_index() -> dict[str, dict]:
    """{component_id: {meta, body, todos, file}} for every annotated note."""
    root = vault_root()
    index: dict[str, dict] = {}
    if not root or not root.is_dir():
        logger.warning("SmartContext: vault root not found (%s)", root)
        return index
    for path in root.rglob("*.md"):
        # Confinement: ignore anything that resolves outside the root (symlinks).
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = parse_note(text)
        ids = _component_ids(meta)
        if not ids:
            continue
        entry = {"meta": meta, "body": body, "todos": parse_todos(body),
                 "title": meta.get("title") or path.stem, "file": path.stem}
        for cid in ids:
            index.setdefault(cid, entry)
    return index


def _get_index() -> dict[str, dict]:
    cached = _index_cache.get("idx")
    if cached is None:
        cached = _build_index()
        _index_cache.set("idx", cached)
    return cached


# ── Public: card info assembly ───────────────────────────────────────────────
def _resolve_component(card_id: str) -> str | None:
    """Card id → component id, via the explicit registry then prefix fallback."""
    if card_id in REGISTRY:
        return REGISTRY[card_id]
    for prefix, component in _PREFIX_FALLBACK.items():
        if card_id.startswith(prefix):
            return component
    return None


def is_known_card(card_id: str) -> bool:
    return _resolve_component(card_id) is not None


def registry_map() -> dict[str, str]:
    return dict(REGISTRY)


def assemble(card_id: str, label: str | None = None, status: str | None = None) -> dict:
    """Build the panel's fast (non-AI) payload for a card. `label`/`status` are
    display-only values the card already shows (sanitised by the API layer)."""
    component_id = _resolve_component(card_id)
    if component_id is None:
        raise KeyError(card_id)  # caller returns 404
    entry = _get_index().get(component_id)
    meta = entry["meta"] if entry else {}

    name = label or meta.get("title") or component_id.replace("-", " ").title()
    risk = (meta.get("risk") or "").strip().lower() or None
    health = (status or meta.get("health") or _RISK_RANK.get(risk or "", "unknown"))

    doc = None
    if entry:
        # An Obsidian deep-link the admin can click to open the source note.
        doc = {"title": entry["title"], "note": entry["file"]}

    return {
        "enabled": True,
        "card_id": card_id,
        "component_id": component_id,
        "component": name,
        "purpose_business": meta.get("purpose-business"),
        "purpose_technical": meta.get("purpose-technical"),
        "dependencies": meta.get("dependencies") if isinstance(meta.get("dependencies"), list) else [],
        "related": meta.get("related") if isinstance(meta.get("related"), list) else [],
        "risk": risk,
        "owner": meta.get("owner"),
        "health": health,
        "last_incident": meta.get("last-incident"),
        "todos": entry["todos"] if entry else [],
        "doc": doc,
        "documented": entry is not None,
    }


# ── Public: AI analysis (lazy, best-effort) ──────────────────────────────────
_ai_cache = TTLCache(ttl=300)

_AI_SYSTEM = (
    "Je bent een observability-expert die een beheerder helpt. Antwoord in het "
    "Nederlands, kort en concreet, met deze kopjes (Markdown, vetgedrukt): "
    "**Huidige toestand**, **Trend**, **Risico**, **Mogelijke impact**, "
    "**Aanbevolen acties**. Verzin geen cijfers; baseer je uitsluitend op de "
    "aangeleverde feiten. Maximaal ~120 woorden."
)


def _ai_context(info: dict) -> str:
    parts = [f"Component: {info.get('component')}"]
    if info.get("purpose_business"):
        parts.append(f"Doel (business): {info['purpose_business']}")
    if info.get("purpose_technical"):
        parts.append(f"Doel (technisch): {info['purpose_technical']}")
    if info.get("dependencies"):
        parts.append("Afhankelijkheden: " + ", ".join(info["dependencies"]))
    if info.get("health"):
        parts.append(f"Huidige status (live): {info['health']}")
    if info.get("risk"):
        parts.append(f"Risiconiveau: {info['risk']}")
    open_todos = [t["text"] for t in info.get("todos", []) if not t["done"]]
    if open_todos:
        parts.append("Openstaande taken: " + "; ".join(open_todos))
    return "\n".join(parts)


async def analyze(info: dict, session: dict | None = None) -> dict:
    """Short LLM analysis of a card. Returns {enabled:false} when AI is off, and
    degrades to {enabled:false} on any LLM error so the panel never breaks."""
    import llm  # local import: keeps engine importable even if llm changes

    if not llm.ai_enabled(session):
        return {"enabled": False}

    cache_key = f"{info.get('card_id')}:{info.get('health')}:{llm.provider_model(session)[0]}"
    cached = _ai_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        text = await llm.generate_answer(
            question="Analyseer dit component voor de beheerder.",
            context=_ai_context(info),
            system=_AI_SYSTEM,
            session=session,
        )
    except Exception as e:  # noqa: BLE001 — best-effort; degrade quietly
        logger.warning("SmartContext AI analysis failed: %s", e)
        return {"enabled": False}

    provider, model = llm.provider_model(session)
    result = {"enabled": True, "analysis": (text or "").strip(), "provider": provider, "model": model}
    if not result["analysis"]:
        return {"enabled": False}
    _ai_cache.set(cache_key, result)
    return result
