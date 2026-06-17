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
