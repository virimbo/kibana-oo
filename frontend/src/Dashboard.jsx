import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import ProviderSwitcher from "./ProviderSwitcher";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const PERIODS = [
  { value: 15, label: "Last 15 min" },
  { value: 30, label: "Last 30 min" },
  { value: 60, label: "Last 1 hour" },
  { value: 360, label: "Last 6 hours" },
  { value: 1440, label: "Last 24 hours" },
];

// Defaults requested by the operator.
const DEFAULT_PERIOD = 15;
const DEFAULT_DATA_VIEW = "logs-*";

const FALLBACK_DATA_VIEWS = [
  { id: "logs-*", label: "All logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
];

const periodLabel = (v) => PERIODS.find((p) => p.value === v)?.label || `${v} min`;

const fmtDate = (iso) =>
  new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(
    new Date(iso)
  );

export function InfoTip({ text }) {
  return (
    <span className="infotip" tabIndex={0} role="note" aria-label={text}>
      i
      <span className="infotip-pop">{text}</span>
    </span>
  );
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

const isNewAction = (a) => /new|create|aanmaak|nieuw|insert/i.test(a || "");

function Pipelines({ nvs, nvsDocs, onNavigate }) {
  return (
    <section className="panel">
      <h3>
        Verwerkingsstraat — NVS (new pipeline)
        <InfoTip text="Documents processed via the new pipeline (NVS, nieuwe verwerkingsstraat) in this window. The old pipeline (OVS) is not present in this monitoring data. Open the Documents tab for the full per-document flow." />
      </h3>
      <div className="pipe-row">
        <div className="pipe pipe--nvs">
          <span className="pipe-label">NVS · documents processed</span>
          <span className="pipe-count">{nvs}</span>
        </div>
      </div>
      {nvs === 0 && (
        <p className="muted">No documents processed via NVS in this window.</p>
      )}
      {nvsDocs && nvsDocs.length > 0 && (
        <div className="pipe-docs">
          <p className="pipe-docs-title">Recent NVS documents — click to open on open.overheid.nl:</p>
          <ul className="doc-list">
            {nvsDocs.slice(0, 10).map((d, i) => (
              <li key={i}>
                <span className="doc-row">
                  {d.action && (
                    <span className={`doc-action doc-action--${isNewAction(d.action) ? "new" : "update"}`}>
                      {d.action}
                    </span>
                  )}
                  {d.link ? (
                    <a href={d.link} target="_blank" rel="noreferrer" className="doc-link">
                      {d.label}
                    </a>
                  ) : (
                    <span className="doc-link doc-link--plain">{d.label}</span>
                  )}
                </span>
                {d.preview && <span className="doc-preview">{d.preview}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {onNavigate && (
        <button className="btn btn--ghost trace-toggle" onClick={() => onNavigate("documents")}>
          Open Documents tab for full document flow →
        </button>
      )}
    </section>
  );
}

export default function DashboardPage({ token, username, onLogout, onNavigate, llmProvider, onProviderChange }) {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [dataView, setDataView] = useState(DEFAULT_DATA_VIEW);
  const [dataViews, setDataViews] = useState(FALLBACK_DATA_VIEWS);
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [briefingState, setBriefingState] = useState("idle"); // idle|loading|error
  const [certs, setCerts] = useState(null); // null = loading

  // Certificate expiry — read from Kibana monitoring data, independent of the metrics.
  useEffect(() => {
    let active = true;
    getJSON("/dashboard/certificates", token)
      .then((d) => active && setCerts(d.certificates || []))
      .catch(() => active && setCerts([]));
    return () => {
      active = false;
    };
  }, [token]);

  // Load the data-view list for the dropdown (single source of truth).
  useEffect(() => {
    let active = true;
    fetch(`${BACKEND_URL}/data-views`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (active && d && Array.isArray(d.data_views) && d.data_views.length) {
          setDataViews(d.data_views);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getJSON(
        `/dashboard/summary?period=${period}&data_view=${encodeURIComponent(dataView)}`,
        token
      );
      setSnap(data);
      setLoadedAt(new Date());
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [period, dataView, token, onLogout]);

  useEffect(() => {
    load();
  }, [load]);

  const loadBriefing = useCallback(
    async (regenerate = false) => {
      setBriefingState("loading");
      try {
        const data = await getJSON(
          `/dashboard/briefing?period=${period}&data_view=${encodeURIComponent(dataView)}${
            regenerate ? "&regenerate=true" : ""
          }`,
          token
        );
        setBriefing(data.briefing);
        setBriefingState("idle");
      } catch {
        setBriefingState("error");
      }
    },
    [period, dataView, token]
  );

  // Auto-load the briefing once the numbers for this window are in.
  useEffect(() => {
    if (snap) loadBriefing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap?.period_minutes, snap?.data_view]);

  const max = Math.max(1, ...((snap?.timeseries || []).map((b) => b.count)));

  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <div className="brand-text">
            <span className="brand-name">Monitoring</span>
            <span className="brand-sub">
              Critical issues · {periodLabel(period)} · {dataView}
            </span>
          </div>
        </div>
        <div className="header-right">
          {onProviderChange && (
            <ProviderSwitcher value={llmProvider} onChange={onProviderChange} />
          )}
          <button className="btn btn--ghost" onClick={() => onNavigate("chat")}>
            Chat
          </button>
          <button className="btn btn--ghost" onClick={() => onNavigate("documents")}>
            Documents
          </button>
          <button className="btn btn--ghost" onClick={() => onNavigate("settings")} title="Settings">
            ⚙
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
            <label className="control">
              <span className="control-label">
                Period <InfoTip text="How far back to analyze — a rolling window ending now (e.g. the last 15 minutes)." />
              </span>
              <select
                className="control-select"
                value={period}
                onChange={(e) => setPeriod(Number(e.target.value))}
                disabled={loading}
                title="Rolling time window to analyze"
              >
                {PERIODS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="control">
              <span className="control-label">
                Data view <InfoTip text="Which Elasticsearch dataset to analyze. “logs-*” is everything; the others narrow to a specific system." />
              </span>
              <select
                className="control-select"
                value={dataView}
                onChange={(e) => setDataView(e.target.value)}
                disabled={loading}
                title="Elasticsearch data view to analyze"
              >
                {dataViews.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label && v.label !== v.id ? `${v.id} — ${v.label}` : v.id}
                  </option>
                ))}
              </select>
            </label>

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

          <section className="panel">
            <h3>
              Certificate expiry
              <InfoTip text="Days until each site's security (TLS) certificate expires, read from Kibana monitoring — not by opening the site. Green: >30 days; amber: under 30; red: under 14 or already expired." />
            </h3>
            {certs === null ? (
              <p className="muted">Checking…</p>
            ) : certs.length === 0 ? (
              <p className="muted">
                No certificate data found in Kibana. This usually means TLS/uptime
                monitoring (Heartbeat or Synthetics) isn't set up for these sites yet —
                ask your Kibana admin to enable it, and the cards will appear here.
              </p>
            ) : (
              <div className="cert-cards">
                {certs.map((c) => (
                  <div key={c.host} className={`cert-card cert-card--${c.status}`}>
                    <span className="cert-host">{c.host}</span>
                    <span className="cert-days">
                      {c.days_remaining < 0
                        ? "Expired"
                        : `${c.days_remaining} day${c.days_remaining === 1 ? "" : "s"} left`}
                    </span>
                    <span className="cert-meta">expires {fmtDate(c.not_after)}</span>
                    {c.issuer && <span className="cert-meta">issued by {c.issuer}</span>}
                  </div>
                ))}
              </div>
            )}
          </section>

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
                  <span className="kpi-label">
                    criticals · {periodLabel(period).toLowerCase()}
                    <InfoTip text="Error-level logs, server errors (HTTP 5xx) and APM errors in the selected window. The arrow compares to the period just before it." />
                  </span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.systems.filter((s) => s.count > 0).length}
                  </span>
                  <span className="kpi-label">
                    systems affected
                    <InfoTip text="How many of your data views had at least one critical issue in this window." />
                  </span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">{snap.delta.previous}</span>
                  <span className="kpi-label">
                    prior period
                    <InfoTip text="The same count in the immediately preceding window — the baseline for the change arrow." />
                  </span>
                </div>
              </div>

              <section className="panel panel--alert">
                <h3>
                  Documents not found (404)
                  <InfoTip text="Pages or documents a user requested but that returned “file not found”. High counts usually mean broken links or removed/missing content on the site." />
                </h3>
                {snap.not_found_total === 0 ? (
                  <p className="muted">
                    No “not found” errors in this window — every requested page resolved.
                  </p>
                ) : (
                  <>
                    <p className="notfound-total">
                      <strong>{snap.not_found_total}</strong> request
                      {snap.not_found_total === 1 ? "" : "s"} returned “not found”.
                    </p>
                    {snap.not_found_urls.length > 0 && (
                      <ul className="url-list">
                        {snap.not_found_urls.map((u) => {
                          const href = /^https?:\/\//.test(u.url)
                            ? u.url
                            : `${snap.portal_base || ""}${u.url}`;
                          return (
                            <li key={u.url}>
                              {snap.portal_base || /^https?:\/\//.test(u.url) ? (
                                <a href={href} target="_blank" rel="noreferrer">
                                  <code>{u.url}</code>
                                </a>
                              ) : (
                                <code>{u.url}</code>
                              )}{" "}
                              <span className="muted">{u.count}×</span>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </>
                )}
              </section>

              <Pipelines nvs={snap.nvs_count} nvsDocs={snap.nvs_docs} onNavigate={onNavigate} />

              <section className="panel">
                <h3>
                  Criticals over time
                  <InfoTip text="When issues happened — each bar is a time bucket; taller means more criticals then. A single tall bar = a spike." />
                </h3>
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
                <h3>
                  By system
                  <InfoTip text="Critical issues per data view (system). The highlighted tile is the one you're currently viewing; “unavailable” means that system couldn't be reached this load." />
                </h3>
                <div className="tiles">
                  {snap.systems.map((s) => (
                    <div
                      key={s.data_view}
                      className={`tile ${s.available ? "" : "tile--down"} ${
                        s.data_view === snap.data_view ? "tile--active" : ""
                      }`}
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
                <h3>
                  Top error signatures
                  <InfoTip text="The most frequent error types, with when each was first and last seen. A burst between two close times often points to one root cause." />
                </h3>
                {snap.top_signatures.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <table className="dash-table">
                    <thead>
                      <tr><th>Signature</th><th>Count</th><th>First</th><th>Last</th></tr>
                    </thead>
                    <tbody>
                      {snap.top_signatures.map((s) => (
                        <tr key={s.signature}>
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
                <h3>
                  Affected services
                  <InfoTip text="The services (applications) emitting the most critical issues in this window — where to look first." />
                </h3>
                {snap.affected_services.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <div className="tiles">
                    {snap.affected_services.map((s) => (
                      <div key={s.name} className="tile">
                        <span className="tile-name">{s.name}</span>
                        <span className="tile-count">{s.count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="panel">
                <h3>
                  HTTP 5xx
                  <InfoTip text="Server errors — the site failed to respond properly (status 500–599). Listed with the URLs that failed. Different from 404, which means the page wasn't found." />
                </h3>
                {snap.status_codes.length === 0 ? (
                  <p className="muted">No server errors.</p>
                ) : (
                  <>
                    <div className="tiles">
                      {snap.status_codes.map((s) => (
                        <div key={s.code} className="tile">
                          <span className="tile-name">{s.code}</span>
                          <span className="tile-count">{s.count}</span>
                        </div>
                      ))}
                    </div>
                    <ul className="url-list">
                      {snap.failing_urls.map((u) => (
                        <li key={u.url}>
                          <code>{u.url}</code> <span className="muted">{u.count}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              <section className="panel panel--ai">
                <div className="panel-head">
                  <h3>
                    AI daily triage
                    <InfoTip text="An AI-written summary of the facts shown above (counts, signatures, services). It only describes those numbers — it can still phrase things wrong, so verify anything important in Kibana." />
                  </h3>
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
