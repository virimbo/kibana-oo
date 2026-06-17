"""Infra / Grafana deep-links: link parsing (fields, env, scheme allowlist) and
the endpoint shape."""
import pytest

import infra_api as api
from config import settings


def test_parse_links_fields_host_and_env(monkeypatch):
    monkeypatch.setattr(settings, "grafana_links",
        "CNPG | https://grafana-prod.cicd.s15m.nl/d/x?orgId=49 | PROD\n"
        "# a comment\n"
        "Bare | https://g.example/d/y\n")
    links = api.parse_links()
    assert links[0] == {"name": "CNPG", "url": "https://grafana-prod.cicd.s15m.nl/d/x?orgId=49",
                        "host": "grafana-prod.cicd.s15m.nl", "env": "PROD"}
    assert links[1]["env"] == "" and links[1]["host"] == "g.example"


def test_parse_links_rejects_non_http_scheme(monkeypatch):
    monkeypatch.setattr(settings, "grafana_links",
        "Bad | javascript:alert(1) | PROD\n"
        "Data | data:text/html;base64,xxx\n"
        "Good | https://ok.example/d/z\n")
    links = api.parse_links()
    assert len(links) == 1 and links[0]["name"] == "Good"


def test_parse_links_skips_malformed(monkeypatch):
    monkeypatch.setattr(settings, "grafana_links", "no pipe here\n| https://only-url.example\nName |\n")
    # "no pipe here" → no url; "| url" → empty name falls back to url; "Name |" → no url
    links = api.parse_links()
    assert len(links) == 1 and links[0]["url"] == "https://only-url.example"


def test_links_endpoint_returns_list(monkeypatch):
    monkeypatch.setattr(settings, "grafana_links", "CNPG | https://g.example/d/x | PROD")
    out = api.links(session={})
    assert out["links"][0]["name"] == "CNPG"


def test_default_link_is_the_cnpg_dashboard():
    # The shipped default points at the CloudNativePG Grafana dashboard.
    links = api.parse_links()
    assert any("cloudnative" in l["url"].lower() for l in links)
    assert all(l["url"].startswith("https://") for l in links)
