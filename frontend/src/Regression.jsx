import { useState, useEffect, useCallback, useRef } from "react";
import { getJSON } from "./api";
import TopNav from "./Nav";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const STATUS_ICON = { pass: "✓", warn: "!", fail: "✗" };
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("nl-NL") : "");

function VerdictBadge({ verdict }) {
  const v = verdict || "—";
  const cls = v === "PASS" ? "ok" : v === "WARN" ? "warn" : v === "FAIL" ? "fail" : "running";
  return <span className={`reg-verdict reg-verdict--${cls}`}>{v === "running" ? "RUNNING…" : v}</span>;
}

// A small "48/50 ✓" reliability indicator over the recent runs.
function Reliability({ stat }) {
  if (!stat || !stat.total) return null;
  const bad = stat.failed > 0 ? "fail" : stat.warned > 0 ? "warn" : "ok";
  return (
    <span className={`reg-rel reg-rel--${bad}`} title={`Over the last ${stat.total} runs: ${stat.passed} pass · ${stat.warned} warn · ${stat.failed} fail`}>
      {stat.passed}/{stat.total} ✓
    </span>
  );
}

// One check row — click to reveal the drill-down evidence (url, expected vs actual, snippet).
function CheckRow({ c, stat }) {
  const [open, setOpen] = useState(false);
  const hasEvidence = c.url || c.expected || c.actual || c.evidence;
  return (
    <li className={`reg-check reg-check--${c.status}`}>
      <button
        type="button"
        className="reg-check-head"
        onClick={() => hasEvidence && setOpen((o) => !o)}
        aria-expanded={open}
        disabled={!hasEvidence}
      >
        <span className="reg-check-icon">{STATUS_ICON[c.status] || "·"}</span>
        <span className="reg-check-main">
          <span className="reg-check-name">
            {c.name}
            {c.severity === "critical" && <span className="reg-sev">critical</span>}
            <Reliability stat={stat} />
          </span>
          <span className="reg-check-detail">{c.detail}</span>
        </span>
        {c.response_ms != null && <span className="reg-check-ms">{c.response_ms} ms</span>}
        {hasEvidence && <span className="reg-check-caret">{open ? "▾" : "▸"}</span>}
      </button>
      {open && hasEvidence && (
        <dl className="reg-evidence">
          {c.url && (<><dt>URL</dt><dd>{c.method ? `${c.method} ` : ""}{c.url}</dd></>)}
          {c.expected && (<><dt>Expected</dt><dd>{c.expected}</dd></>)}
          {c.actual && (<><dt>Actual</dt><dd>{c.actual}</dd></>)}
          {c.evidence && (<><dt>Evidence</dt><dd><code className="reg-evidence-snippet">{c.evidence}</code></dd></>)}
        </dl>
      )}
    </li>
  );
}

// One full run: verdict, per-check results (drill-down), and the change notes.
function RunDetail({ run, rel }) {
  if (!run) return null;
  return (
    <div className="reg-run">
      <div className="reg-run-head">
        <VerdictBadge verdict={run.verdict} />
        <span className="reg-run-counts">
          <b className="reg-ok">{run.passed} passed</b> ·{" "}
          <b className="reg-warn">{run.warned} warning</b> ·{" "}
          <b className="reg-fail">{run.failed} failed</b>
        </span>
        <span className="reg-run-meta">
          {run.trigger === "ci" ? "CI" : "manual"}
          {run.duration_ms != null ? ` · ${(run.duration_ms / 1000).toFixed(1)}s` : ""}
          {run.finished ? ` · ${fmtWhen(run.finished)}` : run.started ? ` · started ${fmtWhen(run.started)}` : ""}
        </span>
      </div>

      <ul className="reg-checks">
        {(run.checks || []).map((c) => <CheckRow key={c.id} c={c} stat={rel[c.id]} />)}
        {run.verdict === "running" && (run.checks || []).length < (run.total || 0) && (
          <li className="reg-check reg-check--running">
            <span className="reg-check-head" style={{ cursor: "default" }}>
              <span className="reg-check-icon">⏳</span>
              <span className="reg-check-main">
                <span className="reg-check-name">Running… {(run.checks || []).length}/{run.total}</span>
              </span>
            </span>
          </li>
        )}
      </ul>

      {run.changes && run.changes.length > 0 && (
        <div className="reg-changes">
          <span className="reg-changes-title">Since last run</span>
          <ul>
            {run.changes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function RegressionPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange, can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [run, setRun] = useState(null);       // currently displayed run (latest or a selected history item)
  const [history, setHistory] = useState([]);
  const [rel, setRel] = useState({});         // check_id -> {passed,warned,failed,total}
  const [running, setRunning] = useState(false);
  const [viewingId, setViewingId] = useState(null); // non-null when viewing a past run
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  const loadLatest = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/latest", token);
      const r = d && d.run === null ? null : d;
      if (!viewingId) setRun(r);
      setRunning(!!r && r.verdict === "running");
      return r;
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    }
  }, [token, onLogout, viewingId]);

  const loadHistory = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/runs?limit=15", token);
      setHistory(d.runs || []);
    } catch { /* non-fatal */ }
  }, [token]);

  const loadReliability = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/reliability?limit=50", token);
      setRel(Object.fromEntries((d.checks || []).map((c) => [c.check_id, c])));
    } catch { /* non-fatal */ }
  }, [token]);

  useEffect(() => {
    loadLatest();
    loadHistory();
    loadReliability();
    return () => clearInterval(pollRef.current);
  }, [loadLatest, loadHistory, loadReliability]);

  // Poll for live progress while a run is in flight.
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!running) return;
    pollRef.current = setInterval(async () => {
      const r = await loadLatest();
      if (r && r.verdict !== "running") {
        clearInterval(pollRef.current);
        setRunning(false);
        loadHistory();
        loadReliability();
      }
    }, 1500);
    return () => clearInterval(pollRef.current);
  }, [running, loadLatest, loadHistory, loadReliability]);

  const runNow = useCallback(async () => {
    setError("");
    setViewingId(null);
    try {
      const r = await fetch(`${BACKEND_URL}/dashboard/regression/run`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.status === 401) return onLogout();
      if (!r.ok) throw new Error("could not start run");
      setRunning(true);
      loadLatest();
    } catch (e) {
      setError(e.message);
    }
  }, [token, onLogout, loadLatest]);

  const viewRun = useCallback(async (id) => {
    try {
      const d = await getJSON(`/dashboard/regression/runs/${id}`, token);
      setViewingId(id);
      setRun(d);
    } catch (e) {
      setError(e.message);
    }
  }, [token]);

  const backToLatest = useCallback(() => {
    setViewingId(null);
    loadLatest();
  }, [loadLatest]);

  return (
    <>
      <TopNav
        active="regression"
        brandMark="🧪"
        brandName="Regressietest"
        brandSub="open.overheid.nl · post-release health gate"
        can={can}
        isAdmin={isAdmin}
        username={username}
        onLogout={onLogout}
        onNavigate={onNavigate}
        llmProvider={llmProvider}
        onProviderChange={onProviderChange}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
      />

      <div className="chat-scroll">
        <div className="dash">
          <section className="panel">
            <div className="reg-bar">
              <div>
                <h3 style={{ marginBottom: 4 }}>🧪 Regressietest — open.overheid.nl</h3>
                <p className="muted" style={{ margin: 0 }}>
                  Run this after a prod release to confirm the public portal still works:
                  availability, key journeys, content via the openbaarmakingen API, and TLS.
                </p>
              </div>
              <button className="btn" onClick={runNow} disabled={running}>
                {running ? "Running…" : "▶ Run regression test"}
              </button>
            </div>

            {error && <div className="alert alert--error">{error}</div>}

            {viewingId && (
              <button className="btn btn--ghost reg-back" onClick={backToLatest}>← Back to latest</button>
            )}

            {run ? (
              <RunDetail run={run} rel={rel} />
            ) : (
              <p className="muted">No runs yet — click “Run regression test” to start the first one.</p>
            )}
          </section>

          {history.length > 0 && (
            <section className="panel">
              <h3>Run history</h3>
              <ul className="reg-history">
                {history.map((h) => (
                  <li
                    key={h.run_id}
                    className={`reg-history-row${h.run_id === (viewingId || (run && run.run_id)) ? " is-active" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => viewRun(h.run_id)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && viewRun(h.run_id)}
                  >
                    <VerdictBadge verdict={h.verdict} />
                    <span className="reg-history-when">{fmtWhen(h.finished || h.started)}</span>
                    <span className="reg-history-counts muted">
                      {h.passed}✓ {h.warned}! {h.failed}✗
                      {h.duration_ms != null ? ` · ${(h.duration_ms / 1000).toFixed(1)}s` : ""}
                      {h.trigger === "ci" ? " · CI" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
