import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import ProviderSwitcher from "./ProviderSwitcher";
import StuckBadge from "./StuckBadge";
import AanleverBadge from "./AanleverBadge";

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
  { id: "apm-*", label: "APM" },
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

// Reusable collapsible panel. Remembers its open/closed state per `id` across
// reloads. `summary` (a short node) is shown inline when collapsed so the panel
// still gives an at-a-glance signal without taking vertical space.
export function CollapsiblePanel({
  id,
  title,
  icon,
  info,
  summary,
  defaultCollapsed = false,
  alert = false,
  className = "",
  headerExtra,
  children,
}) {
  const key = `dash.collapse.${id}`;
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? defaultCollapsed : v === "1";
    } catch {
      return defaultCollapsed;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, collapsed ? "1" : "0");
    } catch {
      /* storage unavailable — non-fatal */
    }
  }, [key, collapsed]);

  return (
    <section
      className={`panel panel--collapsible${alert ? " panel--alert" : ""}${
        className ? ` ${className}` : ""
      }${collapsed ? " is-collapsed" : ""}`}
    >
      <h3 className="panel-toggle">
        <button
          type="button"
          className="collapse-btn"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
          title={collapsed ? `Show ${title}` : `Hide ${title}`}
        >
          <span className={`chev ${collapsed ? "" : "chev--open"}`} aria-hidden="true">▸</span>
          {icon ? `${icon} ` : ""}
          {title}
        </button>
        {info && <InfoTip text={info} />}
        {collapsed && summary && <span className="panel-collapsed-summary">{summary}</span>}
        {!collapsed && headerExtra}
      </h3>
      {!collapsed && children}
    </section>
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

function fmtDur(secs) {
  if (secs == null) return "—";
  const s = Math.round(secs);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// ─── Pipeline outcomes card ───────────────────────────────────────────────
const OC_META = {
  published: { label: "Published", icon: "🟢", cls: "ok" },
  updated: { label: "Updated", icon: "🔵", cls: "info" },
  withdrawn: { label: "Withdrawn", icon: "🟠", cls: "warn" },
  failed: { label: "Failed", icon: "🔴", cls: "err" },
  in_progress: { label: "In progress", icon: "⏳", cls: "muted" },
};
const OC_ORDER = ["published", "updated", "withdrawn", "failed", "in_progress"];

function PipeSplit({ by, outcome }) {
  const parts = [];
  for (const p of ["NVS", "OVS", "—"]) {
    const n = by?.[p]?.[outcome] || 0;
    if (n) parts.push(`${p} ${n}`);
  }
  return parts.length ? <span className="oc-split">{parts.join(" · ")}</span> : null;
}

const OUTCOMES_INFO =
  "What actually happened to documents in this window, split by pipeline (OVS/NVS): published, updated, withdrawn (ingetrokken), and failed to publish (system error). 'Failed' is reconciled against open.overheid.nl, so a document that is in fact live is never counted as a failure. Click a tile to see the exact documents.";

function OutcomesCard({ data, onNavigate }) {
  const [open, setOpen] = useState(null); // which outcome's drill list is shown

  const sr = data?.success_rate;
  const srCls = sr == null ? "muted" : sr >= 95 ? "ok" : sr >= 80 ? "warn" : "err";

  const summary =
    data && sr != null ? (
      <span className={`panel-collapsed-summary--inline panel-collapsed-summary--${srCls}`}>
        {sr}% success · {data.throughput} through · {data.backlog} in progress
      </span>
    ) : null;

  if (!data) {
    return (
      <CollapsiblePanel id="outcomes" title="Pipeline outcomes" icon="📊" info={OUTCOMES_INFO}>
        <p className="muted">Loading…</p>
      </CollapsiblePanel>
    );
  }

  const t = data.totals || {};

  return (
    <CollapsiblePanel
      id="outcomes"
      title="Pipeline outcomes"
      icon="📊"
      info={OUTCOMES_INFO}
      summary={summary}
    >
      <div className="oc-headline">
        <div className={`oc-kpi oc-kpi--${srCls}`}>
          <span className="oc-kpi-num">{sr == null ? "—" : `${sr}%`}</span>
          <span className="oc-kpi-label">
            publish success rate <Delta pct={data.trend?.throughput_pct} />
          </span>
        </div>
        <ul className="oc-facts">
          <li>
            <b>{data.throughput}</b> through · <b>{data.publish_failures}</b> failed{" "}
            <Delta pct={data.trend?.failed_pct} />
          </li>
          <li><b>{data.backlog}</b> in progress (backlog)</li>
          <li>
            time-to-publish p50 <b>{fmtDur(data.latency?.p50_seconds)}</b> · p95{" "}
            <b>{fmtDur(data.latency?.p95_seconds)}</b>
          </li>
        </ul>
      </div>

      <div className="oc-tiles">
        {OC_ORDER.map((o) => {
          const meta = OC_META[o];
          const n = t[o] || 0;
          return (
            <button
              key={o}
              className={`oc-tile oc-tile--${meta.cls} ${open === o ? "is-open" : ""}`}
              onClick={() => setOpen(open === o ? null : o)}
              disabled={!n}
              title={n ? "Click to list these documents" : "None in this window"}
            >
              <span className="oc-tile-top">{meta.icon} {meta.label}</span>
              <span className="oc-tile-num">{n}</span>
              <PipeSplit by={data.by_pipeline} outcome={o} />
            </button>
          );
        })}
      </div>

      {!open && (
        <p className="muted oc-hint">
          ▸ Click a tile to list its documents — then click one to trace it, or open it on open.overheid.nl ↗
        </p>
      )}

      {open &&
        (data.drill?.[open]?.length ? (
          <ul className="oc-drill">
            {data.drill[open].map((d) => (
              <li
                key={d.id}
                className="oc-drill-row"
                role="button"
                tabIndex={0}
                onClick={() => onNavigate("documents", d.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onNavigate("documents", d.id)}
                title="Click to trace this document"
              >
                <span
                  className={`oc-pill oc-pill--${
                    d.pipeline === "NVS" ? "nvs" : d.pipeline === "OVS" ? "ovs" : "unk"
                  }`}
                  title="Processing pipeline (OVS = oude, NVS = nieuwe verwerkingsstraat)"
                >
                  {d.pipeline || "—"}
                </span>
                <span className="oc-drill-main">
                  <span className="oc-drill-title">{d.title}</span>
                  <span className="oc-drill-meta">
                    {d.service && <span>{d.service}</span>}
                    {d.stage && <span> · {d.stage}</span>}
                    {d.when && <span> · 🕓 {d.when}</span>}
                  </span>
                </span>
                {d.link && (
                  <a
                    className="oc-drill-link"
                    href={d.link}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    title="Open on open.overheid.nl"
                  >
                    ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted oc-drill-empty">No documents to show for “{OC_META[open].label}”.</p>
        ))}

      <p className="muted oc-foot">
        Window: last {data.period_minutes} min · {data.documents} document
        {data.documents === 1 ? "" : "s"}
        {data.reconciled_live > 0 &&
          ` · ${data.reconciled_live} reclassified live via open.overheid.nl`}
      </p>
    </CollapsiblePanel>
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

// ─── Certificate card with full chain & TLS audit ─────────────────────────
const FINDING_MARK = { ok: "✓", note: "ℹ", warn: "!", bad: "✗" };

// Urgency class for a days-remaining countdown: 🔴 < 14d, 🟠 < 30d, 🟢 otherwise.
function certDaysClass(days, expired) {
  if (expired || days == null || days < 0) return "expired";
  if (days < 14) return "crit";
  if (days < 30) return "warn";
  return "ok";
}

function GradeBadge({ grade }) {
  if (!grade) return null;
  const cls = grade === "OK" ? "ok" : grade === "WARN" ? "warn" : "crit";
  return <span className={`cert-grade cert-grade--${cls}`}>GRADE {grade}</span>;
}

function CertCard({ c }) {
  const [open, setOpen] = useState(false);
  const hasAudit = c.source === "probe" && ((c.chain && c.chain.length) || (c.findings && c.findings.length));
  const enabledTls = c.tls_versions
    ? Object.entries(c.tls_versions).filter(([, v]) => v).map(([k]) => k)
    : [];

  return (
    <div className={`cert-card cert-card--${c.status}`}>
      <span className="cert-host">
        {c.host}
        {c.source === "probe" && <span className="cert-tag" title="Checked live by KIBANA-OO">live</span>}
        <GradeBadge grade={c.grade} />
      </span>
      <span className="cert-days">
        {!c.reachable
          ? "Unreachable"
          : c.days_remaining < 0
          ? "EXPIRED"
          : `${c.days_remaining} day${c.days_remaining === 1 ? "" : "s"} left`}
      </span>
      {c.not_after && <span className="cert-meta">expires {fmtDate(c.not_after)}</span>}
      {c.issuer && <span className="cert-meta">issued by {c.issuer}</span>}
      {c.issues && c.issues.length > 0 && (
        <span className="cert-issues">
          {c.issues.map((iss, i) => (
            <span key={i} className="cert-issue">⚠ {iss}</span>
          ))}
        </span>
      )}

      {hasAudit && (
        <button
          type="button"
          className="cert-audit-toggle"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          {open ? "▾ Hide chain & TLS audit" : "▸ Full chain & TLS audit"}
        </button>
      )}

      {open && hasAudit && (
        <div className="cert-audit">
          {c.findings && c.findings.length > 0 && (
            <ul className="cert-findings">
              {c.findings.map((f, i) => (
                <li key={i} className={`cert-finding cert-finding--${f.level}`}>
                  <span className="cert-finding-mark">{FINDING_MARK[f.level] || "·"}</span> {f.text}
                </li>
              ))}
            </ul>
          )}

          <div className="cert-audit-meta">
            <span>TLS: {enabledTls.length ? enabledTls.join(", ") : "—"}</span>
            {c.hsts != null && <span> · HSTS {c.hsts ? "on" : "off"}</span>}
            {c.checked_at && <span> · checked {new Date(c.checked_at).toLocaleString("nl-NL")}</span>}
          </div>

          {c.chain && c.chain.length > 0 && (
            <div className="cert-chain">
              {c.chain.map((cc, i) => (
                <div key={i} className={`cert-chain-cert cert-chain-cert--${cc.position}`}>
                  <span className="cert-chain-pos">{cc.position}</span>
                  <div className="cert-chain-body">
                    <span className="cert-chain-subj">{cc.subject || "—"}</span>
                    <span className="cert-chain-row">issuer: {cc.issuer || "—"}</span>
                    <span className="cert-chain-row">
                      valid {fmtDate(cc.not_before)} → {fmtDate(cc.not_after)}
                      <span className={`cert-days-pill cert-days-pill--${certDaysClass(cc.days_remaining, cc.expired)}`}>
                        {cc.expired || cc.days_remaining < 0
                          ? "EXPIRED"
                          : `${cc.days_remaining} days left`}
                      </span>
                    </span>
                    <span className="cert-chain-row muted">
                      {cc.key_type}
                      {cc.sig_algorithm ? ` · ${cc.sig_algorithm}` : ""}
                    </span>
                    {cc.ocsp && (
                      <span className={`cert-chain-row cert-ocsp--${cc.ocsp}`}>OCSP: {cc.ocsp}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Aanleverfouten card: documents rejected at delivery, by publisher ─────
const AANLEVER_INFO =
  "Documents rejected at delivery (aanlevering) and NOT published — the doculoket 'Aanleverfouten'. The errored document never reaches open.overheid.nl, so this is detected in the logs and reconciled: it auto-resolves the moment the corrected document is published. Grouped by publisher so you know who to contact; click a title to trace it, ↗ to open it in doculoket, ✓ to dismiss.";

function AanleverfoutenCard({ data, onAck, onNavigate }) {
  if (!data) {
    return (
      <section className="panel">
        <h3>📦 Aanleverfouten <InfoTip text={AANLEVER_INFO} /></h3>
        <p className="muted">Laden…</p>
      </section>
    );
  }
  if (!data.count) {
    return (
      <section className="panel">
        <h3>📦 Aanleverfouten <InfoTip text={AANLEVER_INFO} /></h3>
        <p className="pipe-ok">✓ Geen openstaande aanleverfouten — alles is correct aangeleverd.</p>
      </section>
    );
  }
  return (
    <section className="panel panel--alert">
      <h3>📦 Aanleverfouten <InfoTip text={AANLEVER_INFO} /></h3>
      <p className="pipe-alert">{data.headline} — herstel en lever opnieuw aan.</p>

      {data.by_type && data.by_type.length > 0 && (
        <div className="aanlever-types">
          {data.by_type.map((t) => (
            <span key={t.type} className="aanlever-type">{t.type} · {t.count}</span>
          ))}
        </div>
      )}

      <div className="aanlever-groups">
        {data.groups.map((g) => (
          <div key={g.publisher} className="aanlever-group">
            <div className="aanlever-group-head">
              <span className="aanlever-pub">{g.publisher}</span>
              <span className="aanlever-pub-count">{g.count}</span>
            </div>
            <ul className="aanlever-list">
              {g.incidents.map((inc) => (
                <li key={inc.doc_id} className="aanlever-row">
                  <span className={`aanlever-tag aanlever-tag--${inc.is_new ? "new" : "old"}`}>
                    {inc.is_new ? "NIEUW" : "open"}
                  </span>
                  <span className="aanlever-main">
                    <span
                      className="aanlever-title"
                      role="button"
                      tabIndex={0}
                      onClick={() => onNavigate("documents", inc.doc_id)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onNavigate("documents", inc.doc_id)}
                      title="Trace dit document"
                    >
                      {inc.title || inc.doc_id}
                    </span>
                    <span className="aanlever-meta">
                      {inc.error_type}
                      {inc.service ? ` · ${inc.service}` : ""}
                      {inc.message ? ` · ${inc.message}` : ""}
                    </span>
                  </span>
                  <span className="aanlever-actions">
                    {inc.link && (
                      <a
                        className="aanlever-link"
                        href={inc.link}
                        target="_blank"
                        rel="noreferrer"
                        title="Open in doculoket om te herstellen"
                      >
                        ↗
                      </a>
                    )}
                    <button
                      type="button"
                      className="aanlever-ack"
                      onClick={() => onAck(inc.doc_id)}
                      title="Afhandelen / negeren"
                    >
                      ✓
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function DashboardPage({ token, username, onLogout, onNavigate, llmProvider, onProviderChange, aiEnabled = true, stuckCount, aanleverCount }) {
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
  const [health, setHealth] = useState(null); // documents at risk (stuck / critical)
  const [outcomes, setOutcomes] = useState(null); // throughput/failures by outcome & pipeline
  const [aanlever, setAanlever] = useState(null); // delivery rejections (aanleverfouten)
  const [digestMsg, setDigestMsg] = useState("");

  // Aanleverfouten — documents rejected at delivery/intake, grouped by publisher.
  const loadAanlever = useCallback(() => {
    getJSON("/dashboard/aanleverfouten", token)
      .then(setAanlever)
      .catch(() => setAanlever(null));
  }, [token]);
  useEffect(() => { loadAanlever(); }, [loadAanlever]);

  const ackAanlever = useCallback(
    async (docId) => {
      try {
        await fetch(`${BACKEND_URL}/dashboard/aanleverfouten/${encodeURIComponent(docId)}/ack`, {
          method: "POST", headers: { Authorization: `Bearer ${token}` },
        });
        loadAanlever();
      } catch { /* non-fatal */ }
    },
    [token, loadAanlever]
  );

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

  // Documents at risk (cannot publish / stuck / hanging) — proactive, so the
  // admin acts before users report it.
  useEffect(() => {
    let active = true;
    getJSON(`/dashboard/pipeline-health?data_view=${encodeURIComponent(dataView)}`, token)
      .then((d) => active && setHealth(d))
      .catch(() => active && setHealth(null));
    return () => {
      active = false;
    };
  }, [dataView, token]);

  // Document outcomes (published / updated / withdrawn / failed) by pipeline.
  useEffect(() => {
    let active = true;
    setOutcomes(null);
    getJSON(
      `/dashboard/outcomes?period=${period}&data_view=${encodeURIComponent(dataView)}`,
      token
    )
      .then((d) => active && setOutcomes(d))
      .catch(() => active && setOutcomes(null));
    return () => {
      active = false;
    };
  }, [period, dataView, token]);

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

  // Auto-load the briefing once the numbers for this window are in — but only
  // when AI is enabled, so an off switch makes zero AI calls.
  useEffect(() => {
    if (snap && aiEnabled) loadBriefing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap?.period_minutes, snap?.data_view, aiEnabled]);

  // Email / webhook the at-risk digest now (uses the live session).
  const sendDigest = useCallback(async () => {
    setDigestMsg("Sending…");
    try {
      const r = await fetch(
        `${BACKEND_URL}/dashboard/digest/send?data_view=${encodeURIComponent(dataView)}`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } }
      );
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "send failed");
      if (!d.configured) {
        setDigestMsg("⚙ No email/webhook configured yet — set SMTP_* or DIGEST_WEBHOOK_URL in .env.");
      } else if (d.sent) {
        setDigestMsg(`✓ Sent${d.email ? " · email" : ""}${d.webhook ? " · webhook" : ""}.`);
      } else {
        setDigestMsg("⚠ Delivery failed — check the SMTP / webhook settings.");
      }
    } catch (e) {
      setDigestMsg(`⚠ ${e.message}`);
    }
  }, [dataView, token]);

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
          <AanleverBadge count={aanleverCount} onNavigate={onNavigate} />
          <StuckBadge count={stuckCount} onNavigate={onNavigate} />
          {onProviderChange && (
            <ProviderSwitcher value={llmProvider} onChange={onProviderChange} />
          )}
          <button className="btn btn--ghost" onClick={() => onNavigate("chat")}>
            Chat
          </button>
          <button className="btn btn--ghost" onClick={() => onNavigate("documents")}>
            Documents
          </button>
          <button className="btn btn--ghost" onClick={() => onNavigate("admin")} title="Beheer (admin)">
            Beheer
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

          {health && (() => {
            const atRisk = health.stuck || [];
            const critical = atRisk.filter((d) => d.verdict === "problem").length;
            return atRisk.length > 0 ? (
              <section className="panel panel--alert">
                <h3>
                  🚨 Documents needing attention
                  <InfoTip text="Documents that are NOT yet live on open.overheid.nl — errored (cannot be published) or stuck/hanging in a service. Surfaced proactively so you act before users report it. Click a document to trace exactly where it failed." />
                </h3>
                <p className="pipe-alert">
                  {atRisk.length} document{atRisk.length === 1 ? "" : "s"} at risk
                  {critical > 0 ? ` · ${critical} critical` : ""} — act before users notice.
                </p>
                <div className="digest-bar">
                  <button className="btn btn--ghost" onClick={sendDigest} title="Email / Slack this list now">
                    📧 Send me this digest
                  </button>
                  {digestMsg && <span className="digest-msg">{digestMsg}</span>}
                </div>
                <ul className="stuck-list">
                  {atRisk.map((d) => (
                    <li
                      key={d.id}
                      className="stuck-row"
                      role="button"
                      tabIndex={0}
                      onClick={() => onNavigate("documents", d.id)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onNavigate("documents", d.id)}
                      title="Click to trace this document"
                    >
                      <span className={`stuck-badge stuck-badge--${d.verdict}`}>
                        {d.verdict === "problem" ? "⛔ CRITICAL" : "🕒"} {d.stuck_stage}
                      </span>
                      <span className="stuck-main">
                        <span className="stuck-title">{d.title || d.id}</span>
                        <span className="stuck-head">{d.headline}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                {health.confirmed_published > 0 && (
                  <p className="muted pipe-confirmed">
                    ✓ {health.confirmed_published} other document{health.confirmed_published === 1 ? "" : "s"} had hiccups but {health.confirmed_published === 1 ? "is" : "are"} already published &amp; readable — not at risk.
                  </p>
                )}
              </section>
            ) : (
              <section className="panel">
                <h3>
                  🚦 Documents pipeline
                  <InfoTip text="Proactive check: are any documents failing to reach open.overheid.nl? Updates automatically." />
                </h3>
                <p className="pipe-ok">✓ No documents at risk — everything is reaching open.overheid.nl.</p>
              </section>
            );
          })()}

          <AanleverfoutenCard data={aanlever} onAck={ackAanlever} onNavigate={onNavigate} />

          <CollapsiblePanel
            id="certs"
            title="Certificate & TLS health"
            info="Security (TLS) certificate status for the key sites. The app actively checks open.overheid.nl and doculoket.overheid.nl directly — expiry countdown plus any trust, chain, hostname or expiry problems — and also shows anything Kibana monitors. Green: >30 days & trusted; amber: under 30 days or a warning; red: under 14 days, expired, or not trusted."
            summary={(() => {
              if (!certs || certs.length === 0) return null;
              const problems = certs.filter(
                (c) => (c.issues && c.issues.length) || c.status === "critical" || c.status === "expired"
              );
              const min = certs
                .filter((c) => c.reachable && c.days_remaining != null)
                .reduce((m, c) => Math.min(m, c.days_remaining), Infinity);
              return (
                <span
                  className={`panel-collapsed-summary--inline panel-collapsed-summary--${
                    problems.length ? "err" : "ok"
                  }`}
                >
                  {Number.isFinite(min) ? `${min} days min` : "checked"}
                  {problems.length
                    ? ` · ⚠ ${problems.length} issue${problems.length === 1 ? "" : "s"}`
                    : " · all healthy"}
                </span>
              );
            })()}
          >
            {certs === null ? (
              <p className="muted">Checking…</p>
            ) : certs.length === 0 ? (
              <p className="muted">
                No certificate data yet — the active probe could not reach the
                configured hosts, and Kibana has no TLS monitoring data.
              </p>
            ) : (
              (() => {
                const problems = certs.filter((c) => (c.issues && c.issues.length) || c.status === "critical" || c.status === "expired");
                return (
                  <>
                    {problems.length > 0 && (
                      <div className="alert alert--error cert-warning">
                        ⚠ <b>{problems.length} certificate issue{problems.length === 1 ? "" : "s"} need attention:</b>{" "}
                        {problems.map((c) => c.host).join(", ")}.
                      </div>
                    )}
                    <div className="cert-cards">
                      {certs.map((c) => (
                        <CertCard key={c.host} c={c} />
                      ))}
                    </div>
                  </>
                );
              })()
            )}
          </CollapsiblePanel>

          <OutcomesCard data={outcomes} onNavigate={onNavigate} />

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

              <CollapsiblePanel
                id="notfound"
                title="Documents not found (404)"
                alert={snap.not_found_total > 0}
                info="Pages or documents a user requested but that returned “file not found”. High counts usually mean broken links or removed/missing content on the site."
                summary={
                  <span
                    className={`panel-collapsed-summary--inline panel-collapsed-summary--${
                      snap.not_found_total > 0 ? "warn" : "ok"
                    }`}
                  >
                    {snap.not_found_total > 0
                      ? `${snap.not_found_total} not found`
                      : "none"}
                  </span>
                }
              >
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
              </CollapsiblePanel>

              <Pipelines nvs={snap.nvs_count} nvsDocs={snap.nvs_docs} onNavigate={onNavigate} />

              <CollapsiblePanel
                id="overtime"
                title="Criticals over time"
                info="When issues happened — each bar is a time bucket; taller means more criticals then. A single tall bar = a spike."
              >
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
              </CollapsiblePanel>

              <CollapsiblePanel
                id="bysystem"
                title="By system"
                info="Critical issues per data view (system). The highlighted tile is the one you're currently viewing; “unavailable” means that system couldn't be reached this load."
              >
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
              </CollapsiblePanel>

              <CollapsiblePanel
                id="signatures"
                title="Top error signatures"
                info="The most frequent error types, with when each was first and last seen. A burst between two close times often points to one root cause."
                summary={
                  <span className="panel-collapsed-summary--inline">
                    {snap.top_signatures.length} signature
                    {snap.top_signatures.length === 1 ? "" : "s"}
                  </span>
                }
              >
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
              </CollapsiblePanel>

              <CollapsiblePanel
                id="services"
                title="Affected services"
                info="The services (applications) emitting the most critical issues in this window — where to look first."
                summary={
                  <span className="panel-collapsed-summary--inline">
                    {snap.affected_services.length} service
                    {snap.affected_services.length === 1 ? "" : "s"}
                  </span>
                }
              >
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
              </CollapsiblePanel>

              <CollapsiblePanel
                id="http5xx"
                title="HTTP 5xx"
                alert={snap.status_codes.length > 0}
                info="Server errors — the site failed to respond properly (status 500–599). Listed with the URLs that failed. Different from 404, which means the page wasn't found."
                summary={
                  <span
                    className={`panel-collapsed-summary--inline panel-collapsed-summary--${
                      snap.status_codes.length > 0 ? "err" : "ok"
                    }`}
                  >
                    {snap.status_codes.length > 0
                      ? `${snap.status_codes.reduce((n, s) => n + s.count, 0)} server errors`
                      : "none"}
                  </span>
                }
              >
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
              </CollapsiblePanel>

              {aiEnabled && (
              <CollapsiblePanel
                id="aitriage"
                title="AI daily triage"
                className="panel--ai"
                info="An AI-written summary of the facts shown above (counts, signatures, services). It only describes those numbers — it can still phrase things wrong, so verify anything important in Kibana."
                headerExtra={
                  <button
                    className="btn btn--ghost panel-header-action"
                    onClick={() => loadBriefing(true)}
                    disabled={briefingState === "loading"}
                  >
                    {briefingState === "loading" ? "Generating…" : "Regenerate"}
                  </button>
                }
              >
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
              </CollapsiblePanel>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
