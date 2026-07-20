"""SmartContextPanel engine + API: frontmatter/TODO parsing, vault assembly,
sandbox confinement, feature-flag gating, and input sanitisation. No network."""
import asyncio

import pytest
from fastapi import HTTPException

import context_api as api
import context_engine as engine
from config import settings


@pytest.fixture(autouse=True)
def _vault(tmp_path, monkeypatch):
    """Point the engine at an isolated temp vault and reset its index cache."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(settings, "smart_context_vault_path", str(vault))
    monkeypatch.setattr(settings, "smart_context_enabled", True)
    engine._index_cache.clear()
    engine._ai_cache.clear()
    yield vault
    engine._index_cache.clear()


def _note(vault, name, text):
    (vault / name).write_text(text, encoding="utf-8")


# ── parsing ──────────────────────────────────────────────────────────────────
def test_parse_note_scalars_and_lists():
    meta, body = engine.parse_note(
        "---\ntitle: X\ncomponent: foo\ndependencies: [A, B, C]\nrisk: low\n---\n# Body\ntext"
    )
    assert meta["title"] == "X"
    assert meta["component"] == "foo"
    assert meta["dependencies"] == ["A", "B", "C"]
    assert meta["risk"] == "low"
    assert "# Body" in body


def test_parse_note_handles_crlf_and_no_frontmatter():
    meta, body = engine.parse_note("no front matter here\n- [ ] x")
    assert meta == {}
    assert "no front matter" in body
    meta2, _ = engine.parse_note("---\r\ncomponent: bar\r\n---\r\nbody")
    assert meta2["component"] == "bar"


def test_parse_todos_extracts_done_state_and_ignores_prose():
    todos = engine.parse_todos("intro\n- [ ] open one\n- [x] done one\n- not a task\n* [X] starred")
    assert {"text": "open one", "done": False} in todos
    assert {"text": "done one", "done": True} in todos
    assert {"text": "starred", "done": True} in todos
    assert len(todos) == 3


def test_component_ids_string_or_list():
    assert engine._component_ids({"component": "Foo"}) == ["foo"]
    assert engine._component_ids({"component": ["A", "B"]}) == ["a", "b"]
    assert engine._component_ids({}) == []


# ── assembly ─────────────────────────────────────────────────────────────────
def test_assemble_reads_component_note(_vault, monkeypatch):
    _note(_vault, "comp.md",
          "---\ntitle: My Comp\ncomponent: test-comp\n"
          "purpose-business: doel\ndependencies: [RabbitMQ, Opslag]\nrisk: low\n---\n"
          "- [ ] taak een\n- [x] klaar\n")
    monkeypatch.setitem(engine.REGISTRY, "card:test", "test-comp")

    info = engine.assemble("card:test")
    assert info["component"] == "My Comp"
    assert info["purpose_business"] == "doel"
    assert info["dependencies"] == ["RabbitMQ", "Opslag"]
    assert info["risk"] == "low"
    assert info["documented"] is True
    assert {"text": "taak een", "done": False} in info["todos"]


def test_assemble_label_and_status_override(_vault, monkeypatch):
    monkeypatch.setitem(engine.REGISTRY, "card:test", "missing-comp")
    info = engine.assemble("card:test", label="Document-Harvester", status="healthy")
    # No note for the component → degrades, but card-supplied values still show.
    assert info["component"] == "Document-Harvester"
    assert info["health"] == "healthy"
    assert info["documented"] is False
    assert info["todos"] == []


def test_assemble_unknown_card_raises_keyerror():
    with pytest.raises(KeyError):
        engine.assemble("card:does-not-exist")


# ── sandbox confinement ──────────────────────────────────────────────────────
def test_index_ignores_notes_outside_vault(tmp_path, _vault, monkeypatch):
    # A note OUTSIDE the configured vault must never be indexed.
    outside = tmp_path / "outside.md"
    outside.write_text("---\ncomponent: secret\n---\n- [ ] leak\n", encoding="utf-8")
    monkeypatch.setitem(engine.REGISTRY, "card:secret", "secret")
    info = engine.assemble("card:secret")
    assert info["documented"] is False  # not found — confinement holds


# ── API gating + sanitisation ────────────────────────────────────────────────
def test_card_endpoint_flag_off_returns_disabled(monkeypatch):
    monkeypatch.setattr(settings, "smart_context_enabled", False)
    assert api.card("card:dlq", None, None, session={}) == {"enabled": False}
    assert api.registry(session={}) == {"enabled": False, "cards": {}}


def test_card_endpoint_unknown_card_404(monkeypatch):
    with pytest.raises(HTTPException) as ei:
        api.card("card:nope", None, None, session={})
    assert ei.value.status_code == 404


def test_registry_endpoint_lists_cards():
    out = api.registry(session={})
    assert out["enabled"] is True
    assert "card:dlq" in out["cards"]


def test_sanitize_strips_control_chars_and_caps_length():
    assert api._sanitize("Doc\x00ument\nHarvester") == "DocumentHarvester"
    assert api._sanitize(None) is None
    assert len(api._sanitize("x" * 500)) == api._MAX_LABEL


# ── AI degradation (no network) ──────────────────────────────────────────────
def test_ai_disabled_returns_disabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "none")
    info = {"card_id": "card:dlq", "component": "X", "health": "ok", "todos": []}
    out = asyncio.run(engine.analyze(info, session=None))
    assert out == {"enabled": False}


def test_card_ai_endpoint_ai_off(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "none")
    out = asyncio.run(api.card_ai("card:dlq", None, None, session={}))
    assert out == {"enabled": False}


# ── runbook actions ("WAT TE DOEN NU") ───────────────────────────────────────
import datetime as _dt  # noqa: E402


def _runbook(_vault, body="## Bij DOWN\n- PROD: bel iedereen\n- ACC: bel Firas\n- TST: bel Anton\n"
             "## Bij certificaat bijna verlopen\n- PROD: vernieuw cert\n", updated="2026-06-17"):
    _vault.joinpath("runbook.md").write_text(
        f"---\ntitle: RB\ncomponent: runbook-actions\nbijgewerkt: {updated}\n---\n{body}",
        encoding="utf-8")
    engine._index_cache.clear()


def test_parse_runbook_conditions_and_env_normalisation(_vault):
    _runbook(_vault)
    rb = engine.parse_runbook()
    assert rb["conditions"]["down"] == {"PROD": "bel iedereen", "ACC": "bel Firas", "TEST": "bel Anton"}
    assert rb["conditions"]["cert"] == {"PROD": "vernieuw cert"}
    assert rb["updated"] == "2026-06-17"


def test_runbook_action_lookup_and_missing(_vault):
    _runbook(_vault)
    assert engine.runbook_action("down", "TST") == "bel Anton"   # TST → TEST
    assert engine.runbook_action("down", "acc") == "bel Firas"   # case-insensitive
    assert engine.runbook_action("cert", "ACC") is None          # not defined


def test_runbook_stale_flag():
    assert engine._runbook_stale("2020-01-01", today=_dt.date(2026, 6, 17)) is True
    assert engine._runbook_stale("2026-06-01", today=_dt.date(2026, 6, 17)) is False
    assert engine._runbook_stale(None) is False
    assert engine._runbook_stale("not-a-date") is False


def test_derive_condition():
    assert engine._derive_condition("uptime:x", "down") == ("down", True)
    assert engine._derive_condition("uptime:x", "degraded") == ("down", False)
    assert engine._derive_condition("uptime:x", "unreachable") == ("down", False)
    assert engine._derive_condition("uptime:x", "up") == (None, False)
    assert engine._derive_condition("cert:x", "critical") == ("cert", True)
    assert engine._derive_condition("cert:x", "warning") == ("cert", False)
    assert engine._derive_condition("cert:x", "ok") == (None, False)


def test_assemble_includes_action_when_down(_vault, monkeypatch):
    _runbook(_vault)
    monkeypatch.setitem(engine.REGISTRY, "uptime:acc-site", "availability")
    info = engine.assemble("uptime:acc-site", label="open-acc", status="down", env="ACC")
    a = info["action"]
    assert a and a["text"] == "bel Firas" and a["urgent"] is True and a["missing"] is False
    assert a["condition"] == "down" and a["env"] == "ACC"


def test_assemble_action_missing_when_no_rule(_vault):
    _runbook(_vault)
    info = engine.assemble("cert:open-acc.overheid.nl", label="open-acc", status="critical", env="ACC")
    a = info["action"]
    assert a and a["condition"] == "cert" and a["missing"] is True and a["text"] is None


def test_assemble_no_action_when_healthy(_vault):
    _runbook(_vault)
    info = engine.assemble("cert:open.overheid.nl", label="open", status="ok", env="PROD")
    assert info["action"] is None


def test_runbook_on_demand_reflects_edits_without_cache(_vault):
    _runbook(_vault, body="## Bij DOWN\n- ACC: oude tekst\n")
    assert engine.runbook_action("down", "ACC") == "oude tekst"
    # Edit the SAME note and do NOT clear any cache — on-demand must pick it up.
    _vault.joinpath("runbook.md").write_text(
        "---\ntitle: RB\ncomponent: runbook-actions\n---\n## Bij DOWN\n- ACC: nieuwe tekst\n",
        encoding="utf-8")
    assert engine.runbook_action("down", "ACC") == "nieuwe tekst"


def test_runbook_ignores_non_env_lines(_vault):
    _runbook(_vault, body="## Bij DOWN\n- PROD: bel\n- Stap 1: herstart\n- random: tekst\n")
    assert engine.parse_runbook()["conditions"]["down"] == {"PROD": "bel"}


def test_runbook_robust_headings_and_plain_lines(_vault):
    _runbook(_vault, body="## ENVIRONMENT STATUS\nPROD : bel iedereen\nACC : bel firas\n"
                          "## CERTIFICATES\nTST : bel anton\n")
    rb = engine.parse_runbook()
    assert rb["conditions"]["down"] == {"PROD": "bel iedereen", "ACC": "bel firas"}
    assert rb["conditions"]["cert"] == {"TEST": "bel anton"}


# ── Runbook procedures surfaced by live card status ──────────────────────────

def test_clean_step_strips_markdown_and_wikilinks():
    assert engine._clean_step("1. **Bevestig** de storing") == "Bevestig de storing"
    assert engine._clean_step("- zie [[Monitoring dashboard|het dashboard]]") == "zie het dashboard"
    assert engine._clean_step("2) check `/actuator/health`") == "check /actuator/health"


def test_runbook_procedure_surfaced_for_cert_card(_vault, monkeypatch):
    _note(_vault, "runbook.md",
          "---\ncomponent: runbook-actions\nbijgewerkt: 2026-07-16\n---\n\n"
          "## Bij certificaat bijna verlopen\n"
          "- PROD: Vernieuw het certificaat voor de vervaldatum.\n\n"
          "## Procedure - certificaat bijna verlopen / verlopen\n"
          "1. Bepaal de urgentie via de kaart.\n"
          "2. Vraag een nieuw certificaat aan bij de CA (zie [[Certificaten en TLS]]).\n"
          "3. Zie ter referentie TOPdesk-verzoek: KOOP25080900\n")
    rb = engine.parse_runbook()
    assert "cert" in rb["procedures"]
    steps = rb["procedures"]["cert"]["steps"]
    assert any("TOPdesk" in s for s in steps)
    assert "[[" not in " ".join(steps)          # wiki-link brackets cleaned
    # the WHOLE cert card in a bad state now surfaces the procedure
    a = engine._build_action("card:certificates", "warn", "PROD")
    assert a["condition"] == "cert"
    assert a["text"] == "Vernieuw het certificaat voor de vervaldatum."   # one-liner still works
    assert a["procedure"]["title"].lower().startswith("certificaat")
    assert any("KOOP25080900" in s for s in a["procedure"]["steps"])       # the real TOPdesk ref
    assert a["missing"] is False


def test_no_condition_no_action_when_healthy():
    assert engine._build_action("card:certificates", "ok", "PROD") is None


def test_ai_context_includes_runbook_procedure_for_prioritisation():
    info = {
        "component": "Cert", "health": "crit", "risk": "high",
        "action": {"condition": "cert", "urgent": True, "env": "PROD",
                   "text": "Vernieuw het certificaat.",
                   "procedure": {"title": "certificaat verlopen",
                                 "steps": ["Bepaal urgentie via de kaart", "Vraag nieuw certificaat aan"]}},
    }
    ctx = engine._ai_context(info)
    assert "Conditie: cert (URGENT)" in ctx
    assert "Runbook-actie (PROD): Vernieuw het certificaat." in ctx
    assert "Runbook-procedure" in ctx and "Bepaal urgentie via de kaart" in ctx


def test_ai_context_includes_live_detail_metric():
    info = {"component": "Cert", "health": "warn",
            "detail": "minimaal 19 dagen tot verval over 4 host(s)"}
    ctx = engine._ai_context(info)
    assert "Live meting: minimaal 19 dagen tot verval over 4 host(s)" in ctx
    # assemble threads the detail through
    import context_api  # noqa: F401
    doc = engine.assemble("card:certificates", status="warn", detail="minimaal 19 dagen tot verval")
    assert doc["detail"] == "minimaal 19 dagen tot verval"
