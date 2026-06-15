"""Post-release regression suite for the public portal (open.overheid.nl).

A robust, HTTP-first health gate you run after shipping to prod. The checks are
DATA (see default_checks) so the suite can grow without code changes, and the
engine is structured so browser (Playwright) journeys can plug in later as just
another check `kind`.

Each check has a SEVERITY (critical | warning). A failed assertion on a critical
check FAILs the run; on a warning check it WARNs. Response-time-budget breaches
are always soft (warn). Overall verdict = FAIL > WARN > PASS — mirroring the cert
GRADE. Runs are persisted to SQLite (history + drill-in) and a FAIL alerts via
the same webhook/email used by the cert monitor. Never raises into a request.
"""
import asyncio
import json
import logging
import time
from contextlib import closing
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

import db
import notify
from certificates import audit_one
from config import settings
from portal import extract_meta

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "KIBANA-OO-Regression/1.0"}


# ── Models ───────────────────────────────────────────────────────────────────
_EVIDENCE_CAP = 500


def _cap(text: str | None) -> str | None:
    """Bound an evidence snippet so the DB never bloats and we never store a
    full body (e.g. a 6.5 MB PDF) or large payloads."""
    if not text:
        return text
    text = " ".join(text.split())  # collapse whitespace/newlines for compact storage
    return text if len(text) <= _EVIDENCE_CAP else text[:_EVIDENCE_CAP] + "…"


class CheckResult(BaseModel):
    id: str
    name: str
    severity: str            # critical | warning
    status: str              # pass | warn | fail
    detail: str = ""
    http_status: int | None = None
    response_ms: int | None = None
    # ── Drill-down evidence (so a verdict can be audited without re-running) ──
    url: str | None = None
    method: str | None = None
    expected: str | None = None   # human: "status 200; content-type text/html; text 'Open overheid'"
    actual: str | None = None     # human: "status 200; content-type text/html; 622 bytes"
    evidence: str | None = None   # bounded proof snippet (≤500 chars)


class RegressionRun(BaseModel):
    run_id: str
    started: str
    finished: str | None = None
    verdict: str             # PASS | WARN | FAIL | running
    trigger: str             # manual | ci
    target: str
    duration_ms: int | None = None
    total: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    checks: list[CheckResult] = []
    changes: list[str] = []  # informational "changed since last run" notes


# ── Default check suite (data-driven; verified against the live portal) ───────
def default_checks() -> list[dict]:
    base = settings.regression_target_url.rstrip("/")
    doc = settings.regression_known_doc_id
    host = httpx.URL(base).host
    api = settings.portal_meta_api.format(id=doc)
    return [
        {"id": "home", "name": "Homepage loads", "severity": "critical", "kind": "http",
         "url": f"{base}/", "expect_status": 200, "expect_content_type": "text/html",
         "expect_text": "Open overheid", "max_ms": 5000},
        {"id": "doc-page", "name": "Document page reachable", "severity": "critical", "kind": "http",
         "url": f"{base}/details/{doc}", "expect_status": 200, "expect_content_type": "text/html",
         "max_ms": 5000},
        {"id": "doc-file", "name": "Document file downloadable", "severity": "critical", "kind": "file",
         "url": f"{base}/documenten/{doc}", "expect_status": 200, "expect_content_type": "pdf",
         "max_ms": 8000},
        {"id": "api-meta", "name": "Openbaarmakingen API returns metadata", "severity": "critical",
         "kind": "api_meta", "url": api, "max_ms": 6000},
        {"id": "robots", "name": "robots.txt served", "severity": "warning", "kind": "http",
         "url": f"{base}/robots.txt", "expect_status": 200, "max_ms": 4000},
        {"id": "no-5xx", "name": "Unknown path returns no server error", "severity": "warning",
         "kind": "http", "url": f"{base}/__kibanaoo_regression_probe__", "expect_status_lt": 500,
         "max_ms": 5000},
        {"id": "tls", "name": "TLS certificate & chain healthy", "severity": "critical",
         "kind": "tls", "host": host},
    ]


# ── Check execution ───────────────────────────────────────────────────────────
def _verdict_for(severity: str) -> str:
    """A failed assertion FAILs a critical check and WARNs a warning check."""
    return "fail" if severity == "critical" else "warn"


def _expectation_str(cdef: dict) -> str:
    parts = []
    if "expect_status" in cdef:
        parts.append(f"status {cdef['expect_status']}")
    if "expect_status_lt" in cdef:
        parts.append(f"status < {cdef['expect_status_lt']}")
    if cdef.get("expect_content_type"):
        parts.append(f"content-type ~ {cdef['expect_content_type']}")
    if cdef.get("expect_text"):
        parts.append(f"text '{cdef['expect_text']}'")
    if cdef.get("max_ms"):
        parts.append(f"≤ {cdef['max_ms']} ms")
    return "; ".join(parts) or "reachable"


async def _run_http(cdef: dict, method: str) -> CheckResult:
    sev = cdef["severity"]
    res = CheckResult(id=cdef["id"], name=cdef["name"], severity=sev, status="pass",
                      url=cdef["url"], method=method, expected=_expectation_str(cdef))
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=cdef.get("max_ms", 8000) / 1000 + 5, headers=_UA,
                                     follow_redirects=True) as client:
            r = await client.request(method, cdef["url"])
            body = "" if method == "HEAD" else r.text
    except Exception as e:  # noqa: BLE001
        res.status = _verdict_for(sev)
        res.detail = f"request failed: {type(e).__name__}"
        res.actual = res.detail
        return res
    res.response_ms = int((time.monotonic() - t0) * 1000)
    res.http_status = r.status_code
    ct = r.headers.get("content-type", "")
    res.actual = f"status {r.status_code}; content-type {ct or '—'}; {len(r.content)} bytes; {res.response_ms} ms"
    res.evidence = _cap(body) if body else None

    problems: list[str] = []
    if "expect_status" in cdef and r.status_code != cdef["expect_status"]:
        problems.append(f"status {r.status_code}, expected {cdef['expect_status']}")
    if "expect_status_lt" in cdef and not (r.status_code < cdef["expect_status_lt"]):
        problems.append(f"status {r.status_code} (server error)")
    if cdef.get("expect_content_type") and cdef["expect_content_type"].lower() not in ct.lower():
        problems.append(f"content-type '{ct or '—'}'")
    if cdef.get("expect_text") and cdef["expect_text"].lower() not in body.lower():
        problems.append(f"missing text '{cdef['expect_text']}'")

    if problems:
        res.status = _verdict_for(sev)
        res.detail = "; ".join(problems)
    elif cdef.get("max_ms") and res.response_ms > cdef["max_ms"]:
        res.status = "warn"  # perf budget breach is always soft
        res.detail = f"slow: {res.response_ms} ms (budget {cdef['max_ms']} ms)"
    else:
        res.detail = f"{r.status_code} · {res.response_ms} ms"
    return res


async def _run_file(cdef: dict) -> CheckResult:
    """Verify a large file (e.g. the document PDF) is downloadable WITHOUT pulling
    the whole body: a streamed GET whose headers we read and then close. (HEAD is
    not supported by the portal's file endpoint — it 404s.)"""
    sev = cdef["severity"]
    res = CheckResult(id=cdef["id"], name=cdef["name"], severity=sev, status="pass",
                      url=cdef["url"], method="GET (stream)", expected=_expectation_str(cdef))
    t0 = time.monotonic()
    ct = ""
    clen = None
    try:
        async with httpx.AsyncClient(timeout=cdef.get("max_ms", 8000) / 1000 + 5, headers=_UA,
                                     follow_redirects=True) as client:
            async with client.stream("GET", cdef["url"]) as r:
                res.http_status = r.status_code
                ct = r.headers.get("content-type", "")
                clen = r.headers.get("content-length")
    except Exception as e:  # noqa: BLE001
        res.status = _verdict_for(sev)
        res.detail = f"request failed: {type(e).__name__}"
        res.actual = res.detail
        return res
    res.response_ms = int((time.monotonic() - t0) * 1000)
    res.actual = f"status {res.http_status}; content-type {ct or '—'}; {clen or '?'} bytes; {res.response_ms} ms"
    res.evidence = _cap(f"Content-Type: {ct}; Content-Length: {clen}")

    problems: list[str] = []
    if "expect_status" in cdef and res.http_status != cdef["expect_status"]:
        problems.append(f"status {res.http_status}, expected {cdef['expect_status']}")
    if cdef.get("expect_content_type") and cdef["expect_content_type"].lower() not in ct.lower():
        problems.append(f"content-type '{ct or '—'}'")
    if problems:
        res.status = _verdict_for(sev)
        res.detail = "; ".join(problems)
    elif cdef.get("max_ms") and res.response_ms > cdef["max_ms"]:
        res.status = "warn"
        res.detail = f"slow: {res.response_ms} ms (budget {cdef['max_ms']} ms)"
    else:
        res.detail = f"{res.http_status} · {ct.split(';')[0]} · {res.response_ms} ms"
    return res


async def _run_api_meta(cdef: dict) -> CheckResult:
    sev = cdef["severity"]
    res = CheckResult(id=cdef["id"], name=cdef["name"], severity=sev, status="pass",
                      url=cdef["url"], method="GET", expected="200 + a document title in the JSON")
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.portal_meta_timeout + 4,
                                     headers={**_UA, "Accept": "application/json"},
                                     follow_redirects=True) as client:
            r = await client.get(cdef["url"])
            res.http_status = r.status_code
            res.response_ms = int((time.monotonic() - t0) * 1000)
            r.raise_for_status()
            title = extract_meta(r.json()).get("title")
    except Exception as e:  # noqa: BLE001
        res.status = _verdict_for(sev)
        res.detail = f"API error: {type(e).__name__}"
        res.actual = res.detail
        return res
    res.actual = f"status {res.http_status}; title {'present' if title else 'missing'}; {res.response_ms} ms"
    res.evidence = _cap(f"title: {title}") if title else "no document title in payload"
    if not title:
        res.status = _verdict_for(sev)
        res.detail = "API responded but returned no document title"
    elif cdef.get("max_ms") and res.response_ms > cdef["max_ms"]:
        res.status = "warn"
        res.detail = f"slow: {res.response_ms} ms — title OK"
    else:
        res.detail = f"title: {title[:60]}"
    return res


async def _run_tls(cdef: dict) -> CheckResult:
    sev = cdef["severity"]
    res = CheckResult(id=cdef["id"], name=cdef["name"], severity=sev, status="pass",
                      url=f"https://{cdef['host']}", method="TLS", expected="grade OK or WARN (not CRITICAL)")
    t0 = time.monotonic()
    try:
        cert = await audit_one(cdef["host"])
    except Exception as e:  # noqa: BLE001
        res.status = _verdict_for(sev)
        res.detail = f"TLS probe failed: {type(e).__name__}"
        res.actual = res.detail
        return res
    res.response_ms = int((time.monotonic() - t0) * 1000)
    chain = " → ".join(c.position for c in (cert.chain or []))
    res.actual = f"grade {cert.grade}; {cert.days_remaining}d left; chain {chain or '—'}"
    res.evidence = _cap(
        f"GRADE {cert.grade}; leaf {cert.days_remaining}d; "
        + "; ".join(f"{f.level}:{f.text}" for f in (cert.findings or []))
    )
    if cert.grade == "CRITICAL" or not cert.reachable:
        res.status = "fail"
        res.detail = f"TLS grade {cert.grade or 'unreachable'} ({cert.days_remaining}d)"
    elif cert.grade == "WARN":
        res.status = "warn"
        res.detail = f"TLS grade WARN ({cert.days_remaining}d left)"
    else:
        res.detail = f"GRADE OK · {cert.days_remaining}d left"
    return res


async def _run_check(cdef: dict) -> CheckResult:
    kind = cdef["kind"]
    if kind == "http":
        return await _run_http(cdef, "GET")
    if kind == "file":
        return await _run_file(cdef)
    if kind == "api_meta":
        return await _run_api_meta(cdef)
    if kind == "tls":
        return await _run_tls(cdef)
    return CheckResult(id=cdef["id"], name=cdef["name"], severity=cdef["severity"],
                       status="warn", detail=f"unknown check kind '{kind}'")


# ── Run management (in-memory live progress + SQLite history) ─────────────────
_active: dict[str, RegressionRun] = {}
_latest_mem: RegressionRun | None = None
_tasks: set = set()
_seq = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    global _seq
    _seq += 1
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{_seq:03d}"


def is_running() -> bool:
    return any(r.verdict == "running" for r in _active.values())


async def start_run(trigger: str = "manual") -> str:
    """Begin a regression run in the background and return its id immediately.
    If a run is already in progress, returns that run's id (no double-run)."""
    for r in _active.values():
        if r.verdict == "running":
            return r.run_id
    run = RegressionRun(run_id=_new_run_id(), started=_now_iso(), verdict="running",
                        trigger=trigger, target=settings.regression_target_url)
    _active[run.run_id] = run
    task = asyncio.create_task(_execute(run.run_id))
    _tasks.add(task)                 # keep a strong ref so it isn't GC'd mid-run
    task.add_done_callback(_tasks.discard)
    return run.run_id


async def _execute(run_id: str) -> None:
    global _latest_mem
    run = _active[run_id]
    checks = default_checks()
    run.total = len(checks)
    t0 = time.monotonic()
    for cdef in checks:
        try:
            res = await _run_check(cdef)
        except Exception as e:  # noqa: BLE001 — a check must never crash the run
            res = CheckResult(id=cdef.get("id", "?"), name=cdef.get("name", "?"),
                              severity=cdef.get("severity", "warning"), status="warn",
                              detail=f"check crashed: {type(e).__name__}")
        run.checks.append(res)

    run.passed = sum(1 for c in run.checks if c.status == "pass")
    run.warned = sum(1 for c in run.checks if c.status == "warn")
    run.failed = sum(1 for c in run.checks if c.status == "fail")
    run.verdict = "FAIL" if run.failed else "WARN" if run.warned else "PASS"
    run.duration_ms = int((time.monotonic() - t0) * 1000)
    run.finished = _now_iso()

    try:
        prev = await asyncio.to_thread(_latest_finished_sync)
        run.changes = _diff(prev, run)
        await asyncio.to_thread(_save_sync, run)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Regression persistence failed: {e}")

    _latest_mem = run
    _active.pop(run_id, None)

    if run.verdict == "FAIL" and settings.regression_alert_enabled:
        try:
            await _alert(run)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Regression alert failed: {e}")
    logger.info(f"Regression run {run_id}: {run.verdict} "
                f"({run.passed} pass / {run.warned} warn / {run.failed} fail)")


def _diff(prev: RegressionRun | None, cur: RegressionRun) -> list[str]:
    """Informational notes on what changed since the last run. Never affects the
    verdict — open.overheid.nl content changes constantly, so a diff is a signal,
    not a gate."""
    notes: list[str] = []
    if prev is None:
        return ["First recorded run — no previous run to compare."]
    if prev.verdict != cur.verdict:
        notes.append(f"Overall verdict changed: {prev.verdict} → {cur.verdict}.")
    prev_by_id = {c.id: c for c in prev.checks}
    for c in cur.checks:
        p = prev_by_id.get(c.id)
        if p and p.status != c.status:
            notes.append(f"'{c.name}': {p.status} → {c.status}.")
    return notes or ["No change in check outcomes since the previous run."]


async def _alert(run: RegressionRun) -> None:
    failed = [c for c in run.checks if c.status == "fail"]
    lines = [f"⛔ Regression FAILED for {run.target}", ""]
    for c in failed:
        lines.append(f"• {c.name} — {c.detail}")
    lines.append("")
    lines.append(f"{run.passed} passed · {run.warned} warning · {run.failed} failed.")
    lines.append("Open the dashboard → Beheer → Regressietest.")
    text = "\n".join(lines)
    await notify.send_webhook(text)
    await asyncio.to_thread(notify.send_email,
                            f"⛔ open.overheid.nl regression FAILED ({run.failed})",
                            "<pre>" + text.replace("<", "&lt;") + "</pre>", text)


# ── SQLite persistence (shared app DB, table per feature; hybrid schema) ──────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS regression_runs (
    run_id      TEXT PRIMARY KEY,
    started     TEXT NOT NULL,
    finished    TEXT,
    verdict     TEXT NOT NULL,
    trigger     TEXT,
    target      TEXT,
    duration_ms INTEGER,
    total       INTEGER, passed INTEGER, warned INTEGER, failed INTEGER,
    changes     TEXT
);
CREATE TABLE IF NOT EXISTS regression_checks (
    run_id      TEXT NOT NULL,
    ordinal     INTEGER,
    check_id    TEXT, name TEXT, severity TEXT, status TEXT, detail TEXT,
    http_status INTEGER, response_ms INTEGER,
    url TEXT, method TEXT, expected TEXT, actual TEXT, evidence TEXT,
    FOREIGN KEY(run_id) REFERENCES regression_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_regression_started ON regression_runs(started DESC);
CREATE INDEX IF NOT EXISTS idx_regression_checks_run ON regression_checks(run_id);
CREATE INDEX IF NOT EXISTS idx_regression_checks_id ON regression_checks(check_id);
"""


def _conn():
    """Shared app DB connection with the regression tables ensured."""
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def _save_sync(run: RegressionRun) -> None:
    with closing(_conn()) as c:
        c.execute(
            """INSERT OR REPLACE INTO regression_runs
               (run_id, started, finished, verdict, trigger, target, duration_ms,
                total, passed, warned, failed, changes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run.run_id, run.started, run.finished, run.verdict, run.trigger, run.target,
             run.duration_ms, run.total, run.passed, run.warned, run.failed,
             json.dumps(run.changes)),
        )
        c.execute("DELETE FROM regression_checks WHERE run_id = ?", (run.run_id,))
        c.executemany(
            """INSERT INTO regression_checks
               (run_id, ordinal, check_id, name, severity, status, detail,
                http_status, response_ms, url, method, expected, actual, evidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(run.run_id, i, ch.id, ch.name, ch.severity, ch.status, ch.detail,
              ch.http_status, ch.response_ms, ch.url, ch.method, ch.expected, ch.actual, ch.evidence)
             for i, ch in enumerate(run.checks)],
        )
        _prune(c, settings.regression_history_cap)
        c.commit()


def _prune(conn, cap: int) -> None:
    """Failure-aware retention: keep at most `cap` runs; delete oldest PASS first
    so WARN/FAIL records survive longest, and never delete the most recent run.
    Child check rows cascade-delete (foreign_keys=ON)."""
    n = conn.execute("SELECT COUNT(*) FROM regression_runs").fetchone()[0]
    if n <= cap:
        return
    latest = conn.execute("SELECT run_id FROM regression_runs ORDER BY started DESC LIMIT 1").fetchone()[0]
    conn.execute(
        """DELETE FROM regression_runs WHERE run_id IN (
               SELECT run_id FROM regression_runs WHERE run_id != ?
               ORDER BY CASE verdict WHEN 'PASS' THEN 0 ELSE 1 END ASC, started ASC
               LIMIT ?
           )""",
        (latest, n - cap),
    )


def _row_to_run(conn, run_row) -> RegressionRun:
    checks = conn.execute(
        "SELECT * FROM regression_checks WHERE run_id = ? ORDER BY ordinal", (run_row["run_id"],)
    ).fetchall()
    return RegressionRun(
        run_id=run_row["run_id"], started=run_row["started"], finished=run_row["finished"],
        verdict=run_row["verdict"], trigger=run_row["trigger"], target=run_row["target"],
        duration_ms=run_row["duration_ms"], total=run_row["total"], passed=run_row["passed"],
        warned=run_row["warned"], failed=run_row["failed"],
        changes=json.loads(run_row["changes"] or "[]"),
        checks=[CheckResult(
            id=r["check_id"], name=r["name"], severity=r["severity"], status=r["status"],
            detail=r["detail"] or "", http_status=r["http_status"], response_ms=r["response_ms"],
            url=r["url"], method=r["method"], expected=r["expected"], actual=r["actual"],
            evidence=r["evidence"],
        ) for r in checks],
    )


def _latest_finished_sync() -> RegressionRun | None:
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM regression_runs ORDER BY started DESC LIMIT 1").fetchone()
        return _row_to_run(c, row) if row else None


def _list_sync(limit: int) -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute(
            """SELECT run_id, started, finished, verdict, trigger, duration_ms,
                      total, passed, warned, failed
               FROM regression_runs ORDER BY started DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _get_sync(run_id: str) -> RegressionRun | None:
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM regression_runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_run(c, row) if row else None


def _reliability_sync(limit: int) -> list[dict]:
    """Per-check pass/warn/fail counts over the last `limit` runs — the payoff of
    the normalized schema: spot a flaky check at a glance."""
    with closing(_conn()) as c:
        rows = c.execute(
            """SELECT check_id, name,
                      SUM(status='pass') AS passed,
                      SUM(status='warn') AS warned,
                      SUM(status='fail') AS failed,
                      COUNT(*) AS total
               FROM regression_checks
               WHERE run_id IN (SELECT run_id FROM regression_runs ORDER BY started DESC LIMIT ?)
               GROUP BY check_id, name ORDER BY name""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Public accessors (async; used by the API) ─────────────────────────────────
async def latest_run() -> RegressionRun | None:
    # While a run is in _active (running, or finished but mid-persist), serve it
    # from memory — avoids racing a concurrent DB write with a DB read.
    if _active:
        return list(_active.values())[-1]
    if _latest_mem is not None:
        return _latest_mem
    return await asyncio.to_thread(_latest_finished_sync)


async def get_run(run_id: str) -> RegressionRun | None:
    if run_id in _active:
        return _active[run_id]
    return await asyncio.to_thread(_get_sync, run_id)


async def list_runs(limit: int = 20) -> list[dict]:
    return await asyncio.to_thread(_list_sync, limit)


async def reliability(limit: int = 50) -> list[dict]:
    return await asyncio.to_thread(_reliability_sync, limit)
