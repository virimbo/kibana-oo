"""Infra / Grafana deep-links — additive, read-only.

Returns an admin-configured list of external dashboard links (Grafana, etc.) so the
frontend can show one-click "jump to Grafana" cards. We store only URLs — no
credentials, no tokens, no proxying — so there is no new auth/secret surface; the
admin authenticates to Grafana with their own SSO in a new tab.
"""
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/infra")


def parse_links() -> list[dict]:
    """`name | url | env?` per line → [{name, url, host, env}]. Only http(s) URLs."""
    links: list[dict] = []
    for raw in (settings.grafana_links or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[1]:
            continue
        url = parts[1]
        if not (url.startswith("https://") or url.startswith("http://")):
            continue  # only real web links — never javascript:/data: etc.
        name = parts[0] or url
        env = parts[2].upper() if len(parts) > 2 and parts[2] else ""
        links.append({"name": name, "url": url, "host": urlparse(url).netloc, "env": env})
    return links


@router.get("/links")
def links(session: dict = Depends(require_feature("grafana"))):
    return {"links": parse_links()}
