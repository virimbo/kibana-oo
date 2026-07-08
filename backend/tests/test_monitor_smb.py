"""Tests for the SMB (Windows/CIFS, port 445) monitoring checker.

The real SMB I/O (`_smb_probe`) can't run without a live server, so it's
monkeypatched; these tests cover the async wrapper's plumbing: config →
probe args, password resolved from the .env var named by secret_ref, the
latency→warn rule, and input validation. Plus registry wiring.
"""
import monitor_checkers as mc


def _target(**cfg):
    base = {"host": "fs01", "share": "aanlever", "username": "svc_mon", "secret_ref": "SMB_PW"}
    base.update(cfg)
    return {"type": "smb", "config": base}


async def test_registered_with_expected_fields():
    assert "smb" in mc.CHECKERS
    names = {f["name"] for f in mc.CHECKERS["smb"]["fields"]}
    assert {"host", "share", "port", "username", "secret_ref", "write_test", "encrypt"} <= names
    assert mc.types_schema()["smb"]["fields"]  # exposed to the UI form builder


async def test_missing_host_is_unreachable():
    res = await mc._check_smb({"type": "smb", "config": {"share": "x"}}, None)
    assert res["status"] == "unreachable" and res["detail"]["error"] == "geen host"


async def test_missing_share_is_unreachable():
    res = await mc._check_smb({"type": "smb", "config": {"host": "fs01"}}, None)
    assert res["status"] == "unreachable" and res["detail"]["error"] == "geen share"


async def test_ok_passes_through_and_resolves_password(monkeypatch):
    seen = {}

    def fake_probe(host, share, port, username, password, domain, path,
                   write_test, write_dir, encrypt, timeout):
        seen.update(host=host, share=share, port=port, username=username,
                    password=password, encrypt=encrypt)
        return {"status": "ok", "detail": {"entries": 3}, "latency_ms": 40}

    monkeypatch.setattr(mc, "_smb_probe", fake_probe)
    monkeypatch.setenv("SMB_PW", "s3cret")
    res = await mc._check_smb(_target(port=445), None)
    assert res["status"] == "ok"
    assert seen["password"] == "s3cret"          # resolved from the env var, not stored
    assert seen["host"] == "fs01" and seen["share"] == "aanlever" and seen["port"] == 445
    assert seen["encrypt"] is True                # security-first default


async def test_latency_warn_downgrades_ok_to_warn(monkeypatch):
    monkeypatch.setattr(mc, "_smb_probe",
                        lambda *a, **k: {"status": "ok", "detail": {}, "latency_ms": 900})
    monkeypatch.setenv("SMB_PW", "x")
    res = await mc._check_smb(_target(latency_warn_ms=200), None)
    assert res["status"] == "warn" and res["detail"]["slow"] is True


async def test_latency_warn_not_applied_when_fast(monkeypatch):
    monkeypatch.setattr(mc, "_smb_probe",
                        lambda *a, **k: {"status": "ok", "detail": {}, "latency_ms": 50})
    monkeypatch.setenv("SMB_PW", "x")
    res = await mc._check_smb(_target(latency_warn_ms=200), None)
    assert res["status"] == "ok"


async def test_down_status_is_not_touched_by_latency_rule(monkeypatch):
    monkeypatch.setattr(mc, "_smb_probe",
                        lambda *a, **k: {"status": "down", "detail": {"stage": "session"}, "latency_ms": None})
    monkeypatch.setenv("SMB_PW", "x")
    res = await mc._check_smb(_target(latency_warn_ms=10), None)
    assert res["status"] == "down"


async def test_run_check_wraps_probe_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(mc, "_smb_probe", boom)
    monkeypatch.setenv("SMB_PW", "x")
    # run_check is the framework entrypoint; a checker must never raise out.
    res = await mc.run_check(_target(), None)
    assert res["status"] == "unreachable" and "kaboom" in res["detail"]["error"]
