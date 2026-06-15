"""Comprehensive TLS audit: the composite grading logic and the daily monitor's
alert de-duplication. Pure logic — no network."""
import cert_monitor
import notify
from certificates import Certificate, ChainCert, _grade_and_findings
from config import settings

MODERN_TLS = {"TLS 1.0": False, "TLS 1.1": False, "TLS 1.2": True, "TLS 1.3": True}


def _grade(**over):
    base = dict(
        days=60, trust=None, chain=[], contains_anchor=False, chain_complete=True,
        order_ok=True, ders=[], tls_versions=MODERN_TLS, hsts=True,
    )
    base.update(over)
    return _grade_and_findings(**base)


def test_healthy_chain_grades_ok():
    grade, findings = _grade()
    assert grade == "OK"
    assert any("correctly configured" in f.text for f in findings)


def test_untrusted_chain_is_critical():
    grade, _ = _grade(trust="self-signed / not trusted")
    assert grade == "CRITICAL"


def test_incomplete_chain_is_critical():
    grade, findings = _grade(chain_complete=False)
    assert grade == "CRITICAL"
    assert any("Incomplete chain" in f.text for f in findings)


def test_near_expiry_is_warn():
    assert _grade(days=20)[0] == "WARN"
    assert _grade(days=5)[0] == "CRITICAL"
    assert _grade(days=-1)[0] == "CRITICAL"


def test_contains_anchor_is_a_note_not_a_downgrade():
    grade, findings = _grade(contains_anchor=True)
    assert grade == "OK"  # harmless note must not lower the grade
    assert any(f.level == "note" and "anchor" in f.text for f in findings)


def test_legacy_protocol_is_warn():
    tls = {**MODERN_TLS, "TLS 1.0": True}
    assert _grade(tls_versions=tls)[0] == "WARN"


def test_missing_hsts_is_warn():
    assert _grade(hsts=False)[0] == "WARN"


def test_revoked_cert_is_critical():
    chain = [ChainCert(position="leaf", ocsp="revoked")]
    grade, findings = _grade(chain=chain)
    assert grade == "CRITICAL"
    assert any("REVOKED" in f.text for f in findings)


# ── Daily monitor alert de-duplication ───────────────────────────────────────

def _cert(host, grade, findings=()):
    return Certificate(
        host=host, not_after="2026-08-08T00:00:00+00:00", days_remaining=56,
        status="ok" if grade == "OK" else "warning", source="probe",
        grade=grade, findings=list(findings),
    )


def test_signature_changes_with_grade_and_findings():
    from certificates import Finding
    a = _cert("h", "WARN", [Finding(level="warn", text="HSTS header not set.")])
    b = _cert("h", "WARN", [Finding(level="warn", text="Legacy protocol enabled: TLS 1.0.")])
    assert cert_monitor._signature(a) != cert_monitor._signature(b)
    assert cert_monitor._signature(a) == cert_monitor._signature(a)


async def test_run_audit_once_alerts_once_per_problem(monkeypatch):
    from certificates import Finding
    cert_monitor._last_alert_sig.clear()
    monkeypatch.setattr(settings, "cert_alert_enabled", True)

    sent: list[str] = []

    async def fake_probe(now=None):
        return [_cert("open.overheid.nl", "CRITICAL",
                      [Finding(level="bad", text="Leaf certificate has EXPIRED.")])]

    async def fake_webhook(text):
        sent.append(text)
        return True

    monkeypatch.setattr(cert_monitor, "probe_certificates", fake_probe)
    monkeypatch.setattr(notify, "send_webhook", fake_webhook)
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: True)

    await cert_monitor.run_audit_once()
    assert len(sent) == 1            # first time → alerts
    await cert_monitor.run_audit_once()
    assert len(sent) == 1            # unchanged → no repeat alert


async def test_run_audit_once_no_alert_when_ok(monkeypatch):
    cert_monitor._last_alert_sig.clear()
    monkeypatch.setattr(settings, "cert_alert_enabled", True)
    sent: list[str] = []

    async def fake_probe(now=None):
        return [_cert("open.overheid.nl", "OK")]

    monkeypatch.setattr(cert_monitor, "probe_certificates", fake_probe)
    monkeypatch.setattr(notify, "send_webhook", lambda text: sent.append(text) or True)
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: True)

    await cert_monitor.run_audit_once()
    assert sent == []
