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
from datetime import date
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
    "card:grafana": "grafana",
    "card:service_health": "service-health",
    # Uptime / availability board — every site tile resolves to the shared
    # availability component (the card supplies its own per-site label + state).
    "uptime:open.overheid.nl": "availability",
    "uptime:doculoket.overheid.nl": "availability",
    "uptime:admin (login)": "availability",
    "uptime:open-acc.overheid.nl": "availability",
    "uptime:doculoket-acc.overheid.nl": "availability",
    "uptime:gateway-zoek (test)": "availability",
}
# Any card id starting with this prefix maps to the given component, so renaming a
# target (uptime) or host (cert) still resolves without a code change.
_PREFIX_FALLBACK = {"uptime:": "availability", "cert:": "certificates"}

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
    "bijgewerkt", "eigenaar",  # runbook note: last-reviewed date + owner
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


def assemble(card_id: str, label: str | None = None, status: str | None = None,
             env: str | None = None) -> dict:
    """Build the panel's fast (non-AI) payload for a card. `label`/`status`/`env`
    are display-only values the card already shows (sanitised by the API layer)."""
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
        "action": _build_action(card_id, status, env),
    }


# ── Runbook actions ("WAT TE DOEN NU") ───────────────────────────────────────
_RUNBOOK_COMPONENT = "runbook-actions"
_ENV_ALIASES = {
    "PROD": "PROD", "PRODUCTIE": "PROD", "PRODUCTION": "PROD",
    "ACC": "ACC", "ACCEPTATIE": "ACC", "ACCEPTANCE": "ACC",
    "TEST": "TEST", "TST": "TEST",
}
_KNOWN_ENVS = {"PROD", "ACC", "TEST"}  # only these are treated as action lines
_CONDITION_LABEL = {"down": "Bij DOWN", "cert": "Bij certificaat bijna verlopen",
                    "service": "Bij service down"}


def _normalize_env(env: str | None) -> str | None:
    if not env:
        return None
    key = env.strip().upper()
    return _ENV_ALIASES.get(key, key)


def _condition_from_heading(text: str) -> str | None:
    """Map a heading to a card condition. Robust to natural phrasing/typos."""
    t = text.lower()
    if "cert" in t:  # certificaat / certificate(s)
        return "cert"
    if "service" in t or "microservice" in t:  # backend services — checked before
        return "service"                       # "down" so "Bij service down" → service
    if any(k in t for k in ("down", "environment", "environtmant", "omgeving",
                            "status", "beschikbaar", "uptime")):
        return "down"
    return None


def _find_runbook_path() -> Path | None:
    """Locate the note declaring `component: runbook-actions`, scanning fresh so a
    moved/renamed note is still found."""
    root = vault_root()
    if not root or not root.is_dir():
        return None
    for path in sorted(root.rglob("*.md")):
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, _ = parse_note(text)
        if _RUNBOOK_COMPONENT in _component_ids(meta):
            return resolved
    return None


def parse_runbook() -> dict:
    """Read the runbook note FRESH from disk on every call (on-demand) — an edit in
    Obsidian shows on the next panel open, no cache and no restart.

    Returns {conditions: {cond: {ENV: action}}, updated, owner, note}. A heading is
    a condition; lines `ENV: action` (bullet optional) where ENV is a known env
    (PROD/ACC/TEST, aliases) are per-env actions — prose/steps are ignored."""
    empty = {"conditions": {}, "updated": None, "owner": None, "note": None}
    path = _find_runbook_path()
    if not path:
        return empty
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return empty
    meta, body = parse_note(text)
    conditions: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = _condition_from_heading(line.lstrip("#").strip())
            if current:
                conditions.setdefault(current, {})
            continue
        if not current or ":" not in line:
            continue
        item = line.lstrip("-*").strip()  # bullet optional
        env, _, action = item.partition(":")
        env_n = _normalize_env(env)
        action = action.strip()
        if env_n in _KNOWN_ENVS and action:
            conditions[current][env_n] = action
    return {"conditions": conditions, "updated": meta.get("bijgewerkt"),
            "owner": meta.get("eigenaar"), "note": path.stem}


def runbook_action(condition: str, env: str | None) -> str | None:
    """The action string for a (condition, env), or None if not defined."""
    return parse_runbook()["conditions"].get(condition, {}).get(_normalize_env(env) or "")


def _runbook_stale(updated: str | None, today: date | None = None) -> bool:
    if not updated:
        return False
    try:
        d = date.fromisoformat(str(updated).strip())
    except ValueError:
        return False
    ref = today or date.today()
    return (ref - d).days > settings.smart_context_runbook_stale_days


def _derive_condition(card_id: str, status: str | None) -> tuple[str | None, bool]:
    """(condition, urgent) from the card type + its live status, else (None, False)."""
    s = (status or "").strip().lower()
    if card_id.startswith("uptime:") and s in ("down", "degraded", "unreachable"):
        return "down", s == "down"
    if card_id.startswith("card:service_health") and s in ("down", "degraded", "unreachable"):
        return "service", s == "down"
    if card_id.startswith("cert:") and s in ("warning", "critical", "expired"):
        return "cert", s in ("critical", "expired")
    return None, False


def _build_action(card_id: str, status: str | None, env: str | None) -> dict | None:
    """The 'WAT TE DOEN NU' payload, or None when the card is healthy."""
    condition, urgent = _derive_condition(card_id, status)
    if not condition:
        return None
    rb = parse_runbook()
    norm_env = _normalize_env(env)
    text = rb["conditions"].get(condition, {}).get(norm_env or "")
    return {
        "text": text or None,
        "label": _CONDITION_LABEL.get(condition, condition),
        "condition": condition,
        "env": norm_env,
        "urgent": urgent,
        "missing": not text,
        "runbook_updated": rb["updated"],
        "runbook_stale": _runbook_stale(rb["updated"]),
        "note": rb["note"],
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
