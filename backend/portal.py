"""Best-effort enrichment from the public open.overheid.nl open-data API.

Operational logs carry only a document's id and filenames — never its official
title or publication metadata. The public "openbaarmakingen" API does. Given a
Plooi publication id (a UUID), this resolves the authoritative title,
organization, document type, Woo category, status, publication date and file
info, plus the canonical portal link.

It is deliberately non-fatal: any network/parse failure returns ``None`` so
callers degrade gracefully, and results (including misses) are cached to avoid
hammering the public API.
"""
import re

import httpx

from cache import TTLCache
from config import settings

# Only UUID publication ids resolve on the public portal; internal ids (ronl-…)
# are not addressable there, so we skip the lookup for them.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

_meta_cache = TTLCache(ttl=settings.portal_meta_ttl)


def is_portal_id(plooi_id: str | None) -> bool:
    return bool(plooi_id) and bool(_UUID_RE.match(plooi_id.strip()))


def _dig(obj, *path):
    """Safely walk nested dicts/lists. Integer keys index lists. Returns None
    if any step is missing rather than raising."""
    cur = obj
    for key in path:
        if isinstance(key, int):
            if isinstance(cur, list) and -len(cur) <= key < len(cur):
                cur = cur[key]
            else:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
        if cur is None:
            return None
    return cur


def extract_meta(payload: dict) -> dict:
    """Pull the human-meaningful fields out of an openbaarmakingen API payload.

    Tolerant of missing branches — every field falls back to None. Title prefers
    the official title, then the first file's name."""
    doc = payload.get("document", {}) if isinstance(payload, dict) else {}
    versies = payload.get("versies") if isinstance(payload, dict) else None
    v0 = versies[0] if isinstance(versies, list) and versies else {}
    file0 = _dig(v0, "bestanden", 0) or {}

    title = _dig(doc, "titelcollectie", "officieleTitel") or file0.get("bestandsnaam")
    return {
        "title": title,
        "organization": _dig(doc, "verantwoordelijke", "label") or _dig(doc, "publisher", "label"),
        "type": _dig(doc, "classificatiecollectie", "documentsoorten", 0, "label"),
        "category": _dig(doc, "classificatiecollectie", "informatiecategorieen", 0, "label"),
        "status": _dig(payload, "plooiIntern", "publicatiestatus"),
        "published": v0.get("openbaarmakingsdatum"),
        "pages": file0.get("paginas"),
        "size_bytes": file0.get("grootte"),
        "mime": file0.get("mime-type"),
        "link": doc.get("pid"),  # canonical persistent link; filled below if absent
    }


async def fetch_document_meta(plooi_id: str) -> dict | None:
    """Resolve official metadata for a UUID publication id. Cached and non-fatal:
    returns None for non-UUID ids, unreachable API, 4xx/5xx, or unparseable JSON.
    Misses are negatively cached to protect the public API."""
    pid = (plooi_id or "").strip()
    if not is_portal_id(pid):
        return None

    cached = _meta_cache.get(pid)
    if cached is not None:
        return cached or None  # {} == negative cache -> None

    url = settings.portal_meta_api.format(id=pid)
    try:
        async with httpx.AsyncClient(timeout=settings.portal_meta_timeout) as client:
            resp = await client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "KIBANA-OO/1.0"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        _meta_cache.set(pid, {})  # negative-cache so we don't retry every trace
        return None

    meta = extract_meta(payload)
    if not meta.get("link"):
        meta["link"] = settings.portal_details_template.format(id=pid)
    _meta_cache.set(pid, meta)
    return meta
