import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";

function today() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Amsterdam",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function Delta({ pct }) {
  if (pct == null) return null;
  const up = pct > 0;
  return (
    <span className={`delta ${up ? "delta--up" : "delta--down"}`}>
      {up ? "▲" : "▼"} {Math.abs(pct)}%
    </span>
  );
}

export default function DashboardPage({ token, username, onLogout, onSwitchView }) {
  const [date, setDate] = useState(today());
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [briefingState, setBriefingState] = useState("idle"); // idle|loading|error

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getJSON(`/dashboard/summary?date=${date}`, token);
      setSnap(data);
      setLoadedAt(new Date());
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [date, token, onLogout]);

  useEffect(() => {
    load();
  }, [load]);

  const loadBriefing = useCallback(
    async (regenerate = false) => {
      setBriefingState("loading");
      try {
        const data = await getJSON(
          `/dashboard/briefing?date=${date}${regenerate ? "&regenerate=true" : ""}`,
          token
        );
        setBriefing(data.briefing);
        setBriefingState("idle");
      } catch {
        setBriefingState("error");
      }
    },
    [date, token]
  );

  // Auto-load the briefing once the numbers are in.
  useEffect(() => {
    if (snap) loadBriefing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap?.date]);

  const max = Math.max(1, ...((snap?.timeseries || []).map((b) => b.count)));

  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <div className="brand-text">
            <span className="brand-name">Monitoring</span>
            <span className="brand-sub">Critical issues · {date}</span>
          </div>
        </div>
        <div className="header-right">
          <button className="btn btn--ghost" onClick={onSwitchView}>
            Chat
          </button>
          <span className="header-user">{username}</span>
          <button className="btn btn--ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="chat-scroll">
        <div className="dash">
          <div className="dash-controls">
            <input
              type="date"
              className="control-select"
              value={date}
              max={today()}
              onChange={(e) => setDate(e.target.value)}
            />
            <button className="btn btn--ghost" onClick={load} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
            {loadedAt && (
              <span className="dash-asof">
                data as of {loadedAt.toLocaleTimeString()}
              </span>
            )}
          </div>

          {error && <div className="alert alert--error">{error}</div>}

          {snap && (
            <>
              <div className={`status-banner status-banner--${snap.status_level}`}>
                <strong>
                  {snap.status_level === "ok"
                    ? "All clear"
                    : snap.status_level === "degraded"
                    ? "Degraded"
                    : "Critical"}
                </strong>
                {snap.partial && <span className="dash-warn">partial data</span>}
              </div>

              <div className="kpis">
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.total} <Delta pct={snap.delta.pct_vs_previous} />
                  </span>
                  <span className="kpi-label">criticals today</span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.systems.filter((s) => s.count > 0).length}
                  </span>
                  <span className="kpi-label">systems affected</span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">{snap.delta.avg_7d}</span>
                  <span className="kpi-label">7-day avg</span>
                </div>
              </div>

              <section className="panel">
                <h3>Criticals over time</h3>
                <div className="spark">
                  {snap.timeseries.map((b, i) => (
                    <div
                      key={i}
                      className="spark-bar"
                      style={{ height: `${(b.count / max) * 100}%` }}
                      title={`${b.timestamp}: ${b.count}`}
                    />
                  ))}
                </div>
              </section>

              <section className="panel">
                <h3>By system</h3>
                <div className="tiles">
                  {snap.systems.map((s) => (
                    <div
                      key={s.data_view}
                      className={`tile ${s.available ? "" : "tile--down"}`}
                    >
                      <span className="tile-name">{s.label}</span>
                      <span className="tile-count">
                        {s.available ? s.count : "unavailable"}
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <h3>Top error signatures</h3>
                {snap.top_signatures.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <table className="dash-table">
                    <thead>
                      <tr><th>Signature</th><th>Count</th><th>First</th><th>Last</th></tr>
                    </thead>
                    <tbody>
                      {snap.top_signatures.map((s, i) => (
                        <tr key={i}>
                          <td>{s.signature}</td>
                          <td>{s.count}</td>
                          <td>{s.first_seen || "—"}</td>
                          <td>{s.last_seen || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="panel">
                <h3>Affected services</h3>
                {snap.affected_services.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <div className="tiles">
                    {snap.affected_services.map((s, i) => (
                      <div key={i} className="tile">
                        <span className="tile-name">{s.name}</span>
                        <span className="tile-count">{s.count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="panel">
                <h3>HTTP 5xx</h3>
                {snap.status_codes.length === 0 ? (
                  <p className="muted">No server errors.</p>
                ) : (
                  <>
                    <div className="tiles">
                      {snap.status_codes.map((s, i) => (
                        <div key={i} className="tile">
                          <span className="tile-name">{s.code}</span>
                          <span className="tile-count">{s.count}</span>
                        </div>
                      ))}
                    </div>
                    <ul className="url-list">
                      {snap.failing_urls.map((u, i) => (
                        <li key={i}>
                          <code>{u.url}</code> <span className="muted">{u.count}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              <section className="panel panel--ai">
                <div className="panel-head">
                  <h3>AI daily triage</h3>
                  <button
                    className="btn btn--ghost"
                    onClick={() => loadBriefing(true)}
                    disabled={briefingState === "loading"}
                  >
                    {briefingState === "loading" ? "Generating…" : "Regenerate"}
                  </button>
                </div>
                <p className="ai-disclosure">
                  AI-generated summary of the facts above. May contain
                  inaccuracies — verify critical findings in Kibana.
                </p>
                {briefingState === "error" ? (
                  <p className="muted">AI summary unavailable.</p>
                ) : briefing ? (
                  <div className="markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{briefing}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="muted">Analyzing…</p>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
