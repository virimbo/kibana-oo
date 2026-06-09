import { useState, useEffect, useCallback, useMemo } from "react";
import { getJSON } from "./api";
import { InfoTip } from "./Dashboard";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const PERIODS = [
  { value: 15, label: "Last 15 min" },
  { value: 30, label: "Last 30 min" },
  { value: 60, label: "Last 1 hour" },
  { value: 360, label: "Last 6 hours" },
  { value: 1440, label: "Last 24 hours" },
];
const DEFAULT_PERIOD = 60;
const DEFAULT_DATA_VIEW = "logs-*";
const FALLBACK_DATA_VIEWS = [
  { id: "logs-*", label: "All logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
];
const ACTIONS = ["created", "updated", "deleted", "retrieved", "other"];

const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString();
};
const fmtDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d)
    ? ""
    : new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" }).format(d);
};

function ActionBadge({ action }) {
  return <span className={`act act--${action}`}>{action}</span>;
}

export default function DocumentsPage({ token, username, onLogout, onNavigate }) {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [dataView, setDataView] = useState(DEFAULT_DATA_VIEW);
  const [dataViews, setDataViews] = useState(FALLBACK_DATA_VIEWS);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState(null);
  const [q, setQ] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");

  const runTrace = useCallback(async () => {
    const id = traceId.trim();
    if (!id) return;
    setTraceLoading(true);
    setTraceError("");
    setTrace(null);
    try {
      const d = await getJSON(
        `/dashboard/document-trace?id=${encodeURIComponent(id)}&data_view=${encodeURIComponent(dataView)}`,
        token
      );
      setTrace(d);
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setTraceError(e.message);
    } finally {
      setTraceLoading(false);
    }
  }, [traceId, dataView, token, onLogout]);

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
      const d = await getJSON(
        `/dashboard/documents?period=${period}&data_view=${encodeURIComponent(dataView)}`,
        token
      );
      setData(d);
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

  const events = data?.events || [];
  const max = Math.max(1, ...((data?.timeseries || []).map((b) => b.count)));

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return events.filter((e) => {
      if (actionFilter !== "all" && e.action !== actionFilter) return false;
      if (!needle) return true;
      return (
        (e.message || "").toLowerCase().includes(needle) ||
        (e.doc_id || "").toLowerCase().includes(needle) ||
        (e.filename || "").toLowerCase().includes(needle) ||
        (e.service || "").toLowerCase().includes(needle)
      );
    });
  }, [events, q, actionFilter]);

  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">▤</span>
          <div className="brand-text">
            <span className="brand-name">Documents · NVS</span>
            <span className="brand-sub">New pipeline (nieuwe verwerkingsstraat) · {dataView}</span>
          </div>
        </div>
        <div className="header-right">
          <button className="btn btn--ghost" onClick={() => onNavigate("chat")}>
            Chat
          </button>
          <button className="btn btn--ghost" onClick={() => onNavigate("dashboard")}>
            Dashboard
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
              <span className="control-label">Period</span>
              <select
                className="control-select"
                value={period}
                onChange={(e) => setPeriod(Number(e.target.value))}
                disabled={loading}
              >
                {PERIODS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="control">
              <span className="control-label">Data view</span>
              <select
                className="control-select"
                value={dataView}
                onChange={(e) => setDataView(e.target.value)}
                disabled={loading}
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
              <span className="dash-asof">data as of {loadedAt.toLocaleTimeString()}</span>
            )}
          </div>

          {error && <div className="alert alert--error">{error}</div>}

          {data && (
            <>
              <section className={`panel ${data.alert_level !== "ok" ? "panel--alert" : ""}`}>
                <h3>
                  Document health
                  <InfoTip text="Early warning: document errors in this window vs the prior period. A spike turns this red so you can act before users notice a broken or missing document." />
                </h3>
                {data.alert_level === "ok" ? (
                  <p className="pipe-ok">✓ No document errors in this window.</p>
                ) : (
                  <p className="pipe-alert">
                    ⚠ {data.errors} document error{data.errors === 1 ? "" : "s"} in this window
                    {data.error_pct_change != null && (
                      <>
                        {" · "}
                        <span className={`delta ${data.error_pct_change > 0 ? "delta--up" : "delta--down"}`}>
                          {data.error_pct_change > 0 ? "▲" : "▼"} {Math.abs(data.error_pct_change)}% vs prior period
                        </span>
                      </>
                    )}
                    {" — fix the failed documents below before users hit them."}
                  </p>
                )}
                {data.failed && data.failed.length > 0 && (
                  <ul className="doc-list">
                    {data.failed.map((f, i) => (
                      <li key={i}>
                        <span className="doc-row">
                          <span className={`act act--${f.action}`}>{f.action}</span>
                          {f.link ? (
                            <a href={f.link} target="_blank" rel="noreferrer" className="doc-link">
                              {f.doc_id || f.filename || "document"}
                            </a>
                          ) : (
                            <span className="doc-link doc-link--plain">{f.filename || f.doc_id || "document"}</span>
                          )}
                        </span>
                        <span className="doc-preview">{f.message}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="panel">
                <div className="panel-head">
                  <h3>
                    Trace a document
                    <InfoTip text="Enter a Plooi/document id (ronl-…) to see its full lifecycle across services — every step, status, and any errors — so you can find where its flow failed." />
                  </h3>
                </div>
                <form
                  className="trace-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    runTrace();
                  }}
                >
                  <input
                    className="feed-search trace-input"
                    placeholder="e.g. ronl-d9d80f3d0fb042bf7fd2eea4708b937f"
                    value={traceId}
                    onChange={(e) => setTraceId(e.target.value)}
                  />
                  <button className="btn btn--primary" type="submit" disabled={traceLoading || !traceId.trim()}>
                    {traceLoading ? "Tracing…" : "Trace"}
                  </button>
                </form>
                {traceError && <p className="muted">{traceError}</p>}
                {trace &&
                  (trace.found ? (
                    <>
                      <p className="muted trace-meta">
                        {trace.events.length} events for <code>{trace.id}</code>
                        {trace.errors > 0 && (
                          <span className="delta delta--up"> · {trace.errors} error{trace.errors === 1 ? "" : "s"}</span>
                        )}
                        {trace.link && (
                          <>
                            {" · "}
                            <a href={trace.link} target="_blank" rel="noreferrer" className="doc-link">
                              open on portal
                            </a>
                          </>
                        )}
                      </p>
                      <table className="dash-table feed-table">
                        <thead>
                          <tr>
                            <th>Time</th>
                            <th>Action</th>
                            <th>Status</th>
                            <th>Service</th>
                            <th>Message</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trace.events.map((e, i) => (
                            <tr key={i}>
                              <td className="feed-time">{fmtTime(e.timestamp)}</td>
                              <td><ActionBadge action={e.action} /></td>
                              <td>
                                <span className={`feed-status feed-status--${e.status}`} />
                                {e.status}
                              </td>
                              <td>{e.service || "—"}</td>
                              <td className="feed-msg" title={e.message}>{e.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  ) : (
                    <p className="muted">No events found for that id in this data view / period-independent search.</p>
                  ))}
              </section>

              <section className="panel">
                <h3>
                  Errors by source
                  <InfoTip text="Processing and mapping issues grouped by document source (bron) in this window — spot which feed is failing. Best-effort source detection (tunable)." />
                </h3>
                {!data.by_source || data.by_source.length === 0 ? (
                  <p className="muted">No processing or mapping issues in this window.</p>
                ) : (
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Processing errors</th>
                        <th>Mapping warnings</th>
                        <th>Mapping errors</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_source.map((r) => (
                        <tr key={r.source}>
                          <td>{r.source}</td>
                          <td className={r.processing_error ? "num-bad" : "num-zero"}>{r.processing_error}</td>
                          <td className={r.mapping_warning ? "num-warn" : "num-zero"}>{r.mapping_warning}</td>
                          <td className={r.mapping_error ? "num-bad" : "num-zero"}>{r.mapping_error}</td>
                          <td><strong>{r.total}</strong></td>
                        </tr>
                      ))}
                      <tr className="row-total">
                        <td><strong>Total</strong></td>
                        <td><strong>{data.by_source.reduce((s, r) => s + r.processing_error, 0)}</strong></td>
                        <td><strong>{data.by_source.reduce((s, r) => s + r.mapping_warning, 0)}</strong></td>
                        <td><strong>{data.by_source.reduce((s, r) => s + r.mapping_error, 0)}</strong></td>
                        <td><strong>{data.by_source.reduce((s, r) => s + r.total, 0)}</strong></td>
                      </tr>
                    </tbody>
                  </table>
                )}
              </section>

              <div className="kpis">
                <div className="kpi">
                  <span className="kpi-value">{data.total}</span>
                  <span className="kpi-label">
                    document events
                    <InfoTip text="Log events related to documents in the selected window (created, updated, deleted, retrieved)." />
                  </span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">{data.unique_documents}</span>
                  <span className="kpi-label">
                    unique documents
                    <InfoTip text="Distinct documents touched (by document id / filename) among the recent events shown." />
                  </span>
                </div>
                <div className="kpi">
                  <span className="kpi-value" style={{ color: data.errors > 0 ? "var(--error)" : undefined }}>
                    {data.errors}
                  </span>
                  <span className="kpi-label">
                    errors
                    <InfoTip text="Document events logged at ERROR level — failures worth investigating." />
                  </span>
                </div>
              </div>

              <section className="panel">
                <h3>By action <InfoTip text="What happened to documents — classified from the log text. 'other' = not yet classified (tunable)." /></h3>
                <div className="tiles">
                  {(data.by_action || []).map((a) => (
                    <div key={a.action} className="tile">
                      <span className="tile-name"><ActionBadge action={a.action} /></span>
                      <span className="tile-count">{a.count}</span>
                    </div>
                  ))}
                  {(!data.by_action || data.by_action.length === 0) && <p className="muted">No events.</p>}
                </div>
              </section>

              <section className="panel">
                <h3>By type <InfoTip text="Document file type, taken from the filename in the log (pdf, xml, …)." /></h3>
                <div className="tiles">
                  {(data.by_type || []).map((t) => (
                    <div key={t.type} className="tile">
                      <span className="tile-name">{t.type}</span>
                      <span className="tile-count">{t.count}</span>
                    </div>
                  ))}
                  {(!data.by_type || data.by_type.length === 0) && <p className="muted">No file types detected.</p>}
                </div>
              </section>

              <section className="panel">
                <h3>Activity over time</h3>
                <div className="spark">
                  {(data.timeseries || []).map((b, i) => (
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
                <div className="panel-head">
                  <h3>Activity feed <InfoTip text="Recent document events, newest first. Click a document to open it on open.overheid.nl. Filter by text or action." /></h3>
                  <div className="feed-filters">
                    <input
                      className="feed-search"
                      placeholder="Filter… (document, file, message)"
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                    />
                    <select
                      className="control-select"
                      value={actionFilter}
                      onChange={(e) => setActionFilter(e.target.value)}
                    >
                      <option value="all">All actions</option>
                      {ACTIONS.map((a) => (
                        <option key={a} value={a}>
                          {a}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {filtered.length === 0 ? (
                  <p className="muted">No matching document events.</p>
                ) : (
                  <table className="dash-table feed-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Time</th>
                        <th>Action</th>
                        <th>Type</th>
                        <th>Organization</th>
                        <th>Document</th>
                        <th>Status</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((e, i) => (
                        <tr key={i}>
                          <td className="feed-time">{fmtDate(e.timestamp)}</td>
                          <td className="feed-time">{fmtTime(e.timestamp)}</td>
                          <td><ActionBadge action={e.action} /></td>
                          <td>{e.type || "—"}</td>
                          <td>{e.org || <span className="muted">—</span>}</td>
                          <td>
                            {e.link ? (
                              <a href={e.link} target="_blank" rel="noreferrer" className="doc-link">
                                {e.doc_id || e.filename || "open"}
                              </a>
                            ) : (
                              <span className="muted">{e.filename || e.doc_id || "—"}</span>
                            )}
                          </td>
                          <td>
                            <span className={`feed-status feed-status--${e.status}`} />
                            {e.status}
                          </td>
                          <td className="feed-msg" title={e.message}>{e.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="muted feed-foot">
                  Showing {filtered.length} of {events.length} recent events. Action classification is
                  best-effort — tell me which labels look wrong and I'll tune it.
                </p>
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
