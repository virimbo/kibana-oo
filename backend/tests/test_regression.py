"""Regression suite: verdict aggregation (FAIL>WARN>PASS), per-check evaluation,
change-diff, and persistence. Network is mocked — no real call to the portal."""
import asyncio

import httpx
import pytest

import regression as R
from certificates import Certificate
from config import settings
from regression import CheckResult, RegressionRun


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "regression_alert_enabled", False)
    R._active.clear()
    R._latest_mem = None
    yield


def _mk(run_id, verdict, started, check_status="pass"):
    return RegressionRun(
        run_id=run_id, started=started, finished=started, verdict=verdict,
        trigger="manual", target="x", total=1,
        passed=1 if check_status == "pass" else 0,
        warned=1 if check_status == "warn" else 0,
        failed=1 if check_status == "fail" else 0,
        checks=[CheckResult(id="c1", name="Homepage", severity="critical", status=check_status,
                            url="https://x/", method="GET", expected="status 200",
                            actual="status 200", evidence="<title>Open overheid</title>")],
    )


async def _run_to_completion():
    for _ in range(200):
        r = await R.latest_run()
        if r and r.verdict != "running":
            return r
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish")


def _patch_client(monkeypatch, transport):
    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("verify", None)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


# ── Verdict aggregation ───────────────────────────────────────────────────────
# Drive _execute directly (no background create_task) so the verdict logic is
# tested deterministically without leaking pending tasks across tests.
async def _execute_with(monkeypatch, checks, fake_run_check):
    monkeypatch.setattr(R, "default_checks", lambda: checks)
    monkeypatch.setattr(R, "_run_check", fake_run_check)
    run = RegressionRun(run_id="test-run", started=R._now_iso(), verdict="running",
                        trigger="manual", target="x")
    R._active[run.run_id] = run
    await R._execute(run.run_id)
    return R._latest_mem


async def test_all_pass_is_pass(monkeypatch):
    async def fake(cdef):
        return CheckResult(id=cdef["id"], name=cdef["name"], severity=cdef["severity"], status="pass")

    run = await _execute_with(monkeypatch, [
        {"id": "a", "name": "A", "severity": "critical", "kind": "x"},
        {"id": "b", "name": "B", "severity": "warning", "kind": "x"},
    ], fake)
    assert run.verdict == "PASS" and run.passed == 2 and run.failed == 0


async def test_critical_failure_is_fail_warning_is_warn(monkeypatch):
    async def fake(cdef):
        st = "fail" if cdef["id"] == "crit" else "warn"
        return CheckResult(id=cdef["id"], name=cdef["name"], severity=cdef["severity"], status=st)

    run = await _execute_with(monkeypatch, [
        {"id": "crit", "name": "C", "severity": "critical", "kind": "x"},
        {"id": "warn", "name": "W", "severity": "warning", "kind": "x"},
    ], fake)
    assert run.verdict == "FAIL" and run.failed == 1 and run.warned == 1


async def test_only_warnings_is_warn(monkeypatch):
    async def fake(cdef):
        return CheckResult(id=cdef["id"], name=cdef["name"], severity="warning", status="warn")

    run = await _execute_with(monkeypatch, [
        {"id": "w", "name": "W", "severity": "warning", "kind": "x"},
    ], fake)
    assert run.verdict == "WARN"


async def test_no_double_run(monkeypatch):
    monkeypatch.setattr(R, "default_checks", lambda: [{"id": "a", "name": "A", "severity": "warning", "kind": "x"}])

    async def slow(cdef):
        await asyncio.sleep(0.05)
        return CheckResult(id="a", name="A", severity="warning", status="pass")

    monkeypatch.setattr(R, "_run_check", slow)
    first = await R.start_run()
    second = await R.start_run()           # while the first is still running
    assert first == second                 # same run, not a second one
    await asyncio.gather(*R._tasks)        # drain the background task cleanly


# ── Per-check evaluation ──────────────────────────────────────────────────────
async def test_http_status_mismatch_fails_critical(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(500, text="boom")))
    res = await R._run_http(
        {"id": "h", "name": "Home", "severity": "critical", "url": "https://x/", "expect_status": 200}, "GET")
    assert res.status == "fail" and "500" in res.detail


async def test_http_missing_text_fails(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(200, text="nope")))
    res = await R._run_http(
        {"id": "h", "name": "Home", "severity": "critical", "url": "https://x/",
         "expect_status": 200, "expect_text": "Open overheid"}, "GET")
    assert res.status == "fail" and "Open overheid" in res.detail


async def test_http_no_5xx_passes_on_401(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(401)))
    res = await R._run_http(
        {"id": "n", "name": "Unknown", "severity": "warning", "url": "https://x/x",
         "expect_status_lt": 500}, "GET")
    assert res.status == "pass"


async def test_file_check_passes_with_pdf(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")))
    res = await R._run_file({"id": "f", "name": "File", "severity": "critical",
                             "url": "https://x/doc", "expect_status": 200, "expect_content_type": "pdf"})
    assert res.status == "pass" and res.http_status == 200


async def test_file_check_fails_on_404(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(
        lambda req: httpx.Response(404, headers={"content-type": "application/json"})))
    res = await R._run_file({"id": "f", "name": "File", "severity": "critical",
                             "url": "https://x/doc", "expect_status": 200, "expect_content_type": "pdf"})
    assert res.status == "fail"


async def test_api_meta_passes_with_title(monkeypatch):
    ok = {"document": {"titelcollectie": {"officieleTitel": "BZ duurzaamheidsverslag"}}}
    _patch_client(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(200, json=ok)))
    res = await R._run_api_meta({"id": "api", "name": "API", "severity": "critical", "url": "https://x/api"})
    assert res.status == "pass" and "BZ" in res.detail


async def test_api_meta_fails_without_title(monkeypatch):
    _patch_client(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    res = await R._run_api_meta({"id": "api", "name": "API", "severity": "critical", "url": "https://x/api"})
    assert res.status == "fail"


async def test_tls_grade_maps_to_status(monkeypatch):
    async def fake_audit(host, port=443, now=None):
        return Certificate(host=host, not_after="", days_remaining=53, status="ok",
                           reachable=True, grade="CRITICAL")
    monkeypatch.setattr(R, "audit_one", fake_audit)
    res = await R._run_tls({"id": "tls", "name": "TLS", "severity": "critical", "host": "x"})
    assert res.status == "fail"


# ── Change diff (informational) ───────────────────────────────────────────────
# ── Persistence: evidence, drill-down, prune, reliability ─────────────────────
def test_save_and_get_preserves_evidence(monkeypatch):
    R._save_sync(_mk("r1", "PASS", "2026-06-15T10:00:00+00:00"))
    got = R._get_sync("r1")
    assert got is not None and len(got.checks) == 1
    c = got.checks[0]
    assert c.url == "https://x/" and c.expected == "status 200"
    assert c.evidence == "<title>Open overheid</title>"


def test_prune_drops_oldest_pass_first_keeps_failures_and_latest(monkeypatch):
    monkeypatch.setattr(settings, "regression_history_cap", 3)
    R._save_sync(_mk("t1", "PASS", "2026-06-15T10:00:01+00:00"))
    R._save_sync(_mk("t2", "PASS", "2026-06-15T10:00:02+00:00"))
    R._save_sync(_mk("t3", "FAIL", "2026-06-15T10:00:03+00:00", "fail"))
    R._save_sync(_mk("t4", "PASS", "2026-06-15T10:00:04+00:00"))
    R._save_sync(_mk("t5", "PASS", "2026-06-15T10:00:05+00:00"))
    ids = {r["run_id"] for r in R._list_sync(50)}
    assert ids == {"t3", "t4", "t5"}      # 3 kept
    assert "t3" in ids                     # the FAIL survived
    assert "t5" in ids                     # the most recent survived
    # child rows of pruned runs cascade-deleted
    assert R._get_sync("t1") is None


def test_reliability_counts_per_check(monkeypatch):
    R._save_sync(_mk("a", "PASS", "2026-06-15T10:00:01+00:00", "pass"))
    R._save_sync(_mk("b", "FAIL", "2026-06-15T10:00:02+00:00", "fail"))
    R._save_sync(_mk("c", "PASS", "2026-06-15T10:00:03+00:00", "pass"))
    rel = R._reliability_sync(50)
    row = next(r for r in rel if r["check_id"] == "c1")
    assert row["total"] == 3 and row["passed"] == 2 and row["failed"] == 1


def test_diff_first_run_has_note():
    cur = RegressionRun(run_id="1", started="t", verdict="PASS", trigger="manual", target="x")
    assert "First recorded run" in R._diff(None, cur)[0]


def test_diff_reports_status_change():
    prev = RegressionRun(run_id="1", started="t", verdict="PASS", trigger="manual", target="x",
                         checks=[CheckResult(id="a", name="A", severity="critical", status="pass")])
    cur = RegressionRun(run_id="2", started="t", verdict="FAIL", trigger="manual", target="x",
                        checks=[CheckResult(id="a", name="A", severity="critical", status="fail")])
    notes = R._diff(prev, cur)
    assert any("pass → fail" in n for n in notes)
    assert any("PASS → FAIL" in n for n in notes)
