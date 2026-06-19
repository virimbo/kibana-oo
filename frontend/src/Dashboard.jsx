import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import TopNav from "./Nav";
import TimeRange, { timeParams, rangeLabel, loadRange, saveRange } from "./TimeRange";
import SmartContextPanel from "./SmartContextPanel";
import UptimeBoard from "./UptimeBoard";
import ServiceHealthCard from "./ServiceHealth";
import InfraLinks from "./InfraLinks";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const DEFAULT_DATA_VIEW = "logs-*";

const FALLBACK_DATA_VIEWS = [
  { id: "logs-*", label: "Alle logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
  { id: "apm-*", label: "APM" },
];

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
  subtitle,
  summary,
  defaultCollapsed = false,
  alert = false,
  className = "",
  headerExtra,
  cardId,        // SmartContextPanel: when set, marks this panel as "smart"
  cardLabel,
  cardStatus,
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
      {...(cardId
        ? { "data-smartcard": cardId, "data-smartlabel": cardLabel || title, "data-smartstatus": cardStatus }
        : {})}
    >
      <h3 className="panel-toggle">
        <button
          type="button"
          className="collapse-btn"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
          title={collapsed ? `Toon ${title}` : `Verberg ${title}`}
        >
          <span className={`chev ${collapsed ? "" : "chev--open"}`} aria-hidden="true">▸</span>
          {icon ? `${icon} ` : ""}
          {title}
        </button>
        {info && <InfoTip text={info} />}
        {collapsed && summary && <span className="panel-collapsed-summary">{summary}</span>}
        {!collapsed && headerExtra}
      </h3>
      {!collapsed && subtitle && <p className="panel-subtitle">{subtitle}</p>}
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
  published: { label: "Gepubliceerd", icon: "🟢", cls: "ok" },
  updated: { label: "Bijgewerkt", icon: "🔵", cls: "info" },
  withdrawn: { label: "Ingetrokken", icon: "🟠", cls: "warn" },
  failed: { label: "Mislukt", icon: "🔴", cls: "err" },
  in_progress: { label: "In behandeling", icon: "⏳", cls: "muted" },
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
  "Wat er daadwerkelijk met documenten in dit venster is gebeurd, gesplitst per pipeline (OVS/NVS): gepubliceerd, bijgewerkt, ingetrokken en niet gepubliceerd (system error). 'Mislukt' wordt afgestemd op open.overheid.nl, zodat een document dat in werkelijkheid live staat nooit als mislukt wordt geteld. Klik op een tegel om de exacte documenten te zien.";

function OutcomesCard({ data, onNavigate }) {
  const [open, setOpen] = useState(null); // which outcome's drill list is shown

  const sr = data?.success_rate;
  const srCls = sr == null ? "muted" : sr >= 95 ? "ok" : sr >= 80 ? "warn" : "err";

  const summary =
    data && sr != null ? (
      <span className={`panel-collapsed-summary--inline panel-collapsed-summary--${srCls}`}>
        {sr}% succes · {data.throughput} verwerkt · {data.backlog} in behandeling
      </span>
    ) : null;

  if (!data) {
    return (
      <CollapsiblePanel id="outcomes" title="Pipeline-uitkomsten" icon="📊" info={OUTCOMES_INFO}>
        <p className="muted">Laden…</p>
      </CollapsiblePanel>
    );
  }

  const t = data.totals || {};

  return (
    <CollapsiblePanel
      id="outcomes"
      title="Pipeline-uitkomsten"
      icon="📊"
      info={OUTCOMES_INFO}
      cardId="card:outcomes"
      subtitle="Hoeveel documenten in dit venster zijn gepubliceerd, bijgewerkt, ingetrokken of mislukt — en het publicatie-succespercentage."
      summary={summary}
    >
      <div className="oc-headline">
        <div className={`oc-kpi oc-kpi--${srCls}`}>
          <span className="oc-kpi-num">{sr == null ? "—" : `${sr}%`}</span>
          <span className="oc-kpi-label">
            publicatie-succespercentage <Delta pct={data.trend?.throughput_pct} />
          </span>
        </div>
        <ul className="oc-facts">
          <li>
            <b>{data.throughput}</b> verwerkt · <b>{data.publish_failures}</b> mislukt{" "}
            <Delta pct={data.trend?.failed_pct} />
          </li>
          <li><b>{data.backlog}</b> in behandeling (backlog)</li>
          <li>
            tijd-tot-publicatie p50 <b>{fmtDur(data.latency?.p50_seconds)}</b> · p95{" "}
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
              title={n ? "Klik om deze documenten te tonen" : "Geen in dit venster"}
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
          ▸ Klik op een tegel om de documenten te tonen — klik er vervolgens op om te tracen, of open het op open.overheid.nl ↗
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
                title="Klik om dit document te tracen"
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
                    title="Open op open.overheid.nl"
                  >
                    ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted oc-drill-empty">No documents to show for &ldquo;{OC_META[open].label}&rdquo;.</p>
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
    <section className="panel" data-smartcard="card:nvs" data-smartlabel="Verwerkingsstraat — NVS">
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

// Derive the environment (PROD/ACC/TEST) from a cert host, so the cards can be
// grouped into the same env columns as the uptime board. Display-only; the cert
// data + CertCard rendering are unchanged.
const CERT_ENV_ORDER = ["PROD", "ACC", "TEST"];
function certEnv(host) {
  const h = (host || "").toLowerCase();
  if (/-acc\.|\bacc\./.test(h)) return "ACC";
  if (/tst|test\d|\.test\./.test(h)) return "TEST";
  return "PROD";
}

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
        {c.source === "probe" && <span className="cert-tag" title="Live gecontroleerd door Open Overheid - Monitoring">live</span>}
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
  "Documenten die bij aanlevering zijn geweigerd en NIET gepubliceerd — de doculoket 'Aanleverfouten'. Het document met de error bereikt open.overheid.nl nooit, dus dit wordt in de logs gedetecteerd en verzoend: het lost automatisch op zodra het gecorrigeerde document is gepubliceerd. Gegroepeerd per publisher zodat je weet wie je moet benaderen; klik op een titel om te tracen, ↗ om in doculoket te openen, ✓ om af te handelen.";

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
      <section className="panel" data-smartcard="card:aanleverfouten" data-smartlabel="Aanleverfouten" data-smartstatus="ok">
        <h3>📦 Aanleverfouten <InfoTip text={AANLEVER_INFO} /></h3>
        <p className="pipe-ok">✓ Geen openstaande aanleverfouten — alles is correct aangeleverd.</p>
      </section>
    );
  }
  return (
    <section className="panel panel--alert" data-smartcard="card:aanleverfouten" data-smartlabel="Aanleverfouten" data-smartstatus="warn">
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

// ─── RabbitMQ dead-letter queues card ──────────────────────────────────────
const DLQ_INFO =
  "RabbitMQ dead-letter queues (*.dlq). Een niet-lege DLQ betekent dat berichten niet verwerkt konden worden en vastzitten. Elke DLQ is gekoppeld aan zijn source queue: heeft de source 0 consumers, dan wordt niets gedraind (critical). Alleen-lezen via de RabbitMQ Management API; op de achtergrond gepolld en alert wanneer een DLQ volloopt.";

function dlqAge(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (isNaN(ms) || ms < 0) return "";
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}

function DlqCard({ data, onNavigate }) {
  if (!data || data.configured === false) {
    return (
      <section className="panel">
        <h3>🐰 Dead-letter queues <InfoTip text={DLQ_INFO} /></h3>
        <p className="muted">
          {data && data.configured === false
            ? "Niet geconfigureerd — stel RABBITMQ_USER / RABBITMQ_PASSWORD in .env in."
            : "Loading…"}
        </p>
      </section>
    );
  }
  if (data.error) {
    return (
      <section className="panel panel--alert">
        <h3>🐰 Dead-letter queues <InfoTip text={DLQ_INFO} /></h3>
        <p className="pipe-alert">⚠ {data.error}.</p>
      </section>
    );
  }
  const dlqs = data.dlqs || [];
  const counts = { ok: 0, warn: 0, critical: 0 };
  dlqs.forEach((d) => { counts[d.severity] = (counts[d.severity] || 0) + 1; });
  const hasProblem = counts.warn + counts.critical > 0;
  const ICON = { ok: "✓", warn: "⚠", critical: "⛔" };
  const shortName = (d) => (d.source || d.name).split("-in.")[0].split("msvc-").pop() || d.name;

  return (
    <section className={`panel${hasProblem ? " panel--alert" : ""}`}
             data-smartcard="card:dlq" data-smartlabel="Dead-letter queues">
      <h3>
        🐰 Dead-letter queues <InfoTip text={DLQ_INFO} />
        <span className="dlq-summary">
          {counts.critical > 0 && <span className="dlq-pill dlq-pill--critical">⛔ {counts.critical} critical</span>}
          {counts.warn > 0 && <span className="dlq-pill dlq-pill--warn">⚠ {counts.warn} warning</span>}
          <span className="dlq-pill dlq-pill--ok">✓ {counts.ok}/{dlqs.length} healthy</span>
        </span>
        {onNavigate && (
          <button type="button" className="btn btn--ghost"
                  style={{ marginLeft: "auto", fontSize: 12 }}
                  onClick={() => onNavigate("dlq-intel")}>
            🔍 Intelligentie
          </button>
        )}
      </h3>

      <div className="dlq-grid">
        {dlqs.map((d) => (
          <div key={d.name} className={`dlq-tile dlq-tile--${d.severity}`} title={d.name}
               data-smartcard={`queue:${shortName(d).toLowerCase().replace(/\s+/g, "-")}`}
               data-smartlabel={shortName(d)}
               data-smartstatus={d.severity}>
            <div className="dlq-tile-top">
              <span className="dlq-tile-icon" aria-hidden="true">{ICON[d.severity]}</span>
              <span className="dlq-tile-num">{d.depth.toLocaleString("nl-NL")}</span>
            </div>
            <div className="dlq-tile-name" title={d.name}>{shortName(d)}</div>
            <div className="dlq-tile-meta">
              {d.depth === 0
                ? "leeg"
                : `${d.depth.toLocaleString("nl-NL")} stuck${d.first_seen ? ` · ${dlqAge(d.first_seen)}` : ""}`}
            </div>
            <div className={`dlq-tile-cons${d.source_consumers === 0 ? " dlq-tile-cons--none" : ""}`}>
              {d.source_consumers === 0
                ? "⛔ geen consumer"
                : d.source_consumers != null
                ? `▶ ${d.source_consumers} consumer${d.source_consumers === 1 ? "" : "s"}`
                : "—"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// A collapsible dashboard *zone*: the section header (with its fading divider)
// becomes a toggle that shows/hides the whole group of cards beneath it. The
// open/closed choice is remembered per `id` across reloads, like
// CollapsiblePanel but one level up — so power users can fold away what they
// don't watch and the page remembers their layout.
function DashZone({ id, title, eyebrow, alert = false, defaultCollapsed = false, children }) {
  const key = `dash.zone.${id}`;
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
    <section className={`dash-zone${collapsed ? " is-collapsed" : ""}`}>
      <h2 className={`dash-section${alert ? " dash-section--alert" : ""}`}>
        {eyebrow && <span className="dash-section-eyebrow">{eyebrow}</span>}
        <button
          type="button"
          className="dash-section-toggle"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
          title={collapsed ? `${title} tonen` : `${title} verbergen`}
        >
          <span className={`chev ${collapsed ? "" : "chev--open"}`} aria-hidden="true">▸</span>
          {title}
        </button>
      </h2>
      {!collapsed && children}
    </section>
  );
}

// Tiny inline trend line for a hero tile — pure SVG, no deps. Draws a soft
// filled area under a stroked line so a quick "is it climbing?" read is instant.
function Sparkline({ points }) {
  if (!points || points.length < 2) return null;
  const max = Math.max(1, ...points);
  const w = 100, h = 22, n = points.length;
  const step = w / (n - 1);
  const line = points
    .map((p, i) => `${(i * step).toFixed(1)},${(h - (p / max) * (h - 2) - 1).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="hero-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <polygon className="hero-spark-area" points={`0,${h} ${line} ${w},${h}`} />
      <polyline className="hero-spark-line" points={line} />
    </svg>
  );
}

// ─── Hero: system health at a glance (control-tower row) ───────────────────
function HeroStat({ tone, value, label, desc, hint, onClick, skeleton, spark, cardId }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className={`hero-stat hero-stat--${tone}${onClick ? " hero-stat--clickable" : ""}`}
         onClick={onClick} title={hint}
         {...(cardId ? { "data-smartcard": cardId, "data-smartlabel": label, "data-smartstatus": tone } : {})}>
      <span className="hero-stat-value">
        {skeleton ? <span className="skel skel--value" /> : value}
      </span>
      <span className="hero-stat-label">{label}</span>
      {desc && <span className="hero-stat-desc">{desc}</span>}
      {!skeleton && spark && <Sparkline points={spark} />}
    </Tag>
  );
}

// Plain-language stat tiles so an admin reads the whole system in one glance.
// Each tile: a coloured value, a short label, and a one-line "what is this".
// (TLS certificate health is intentionally NOT here — it has its own detailed
// card lower down, so duplicating it would only add noise.)
function HeroStrip({ snap, health, aanlever, dlq, can, onNavigate }) {
  const stats = [];

  if (can("dashboard")) {
    const lvl = snap?.status_level;
    const tone = lvl === "ok" ? "ok" : lvl === "degraded" ? "warn" : lvl ? "crit" : "muted";
    stats.push({ key: "status", cardId: "hero:status", tone, skeleton: !snap,
      value: lvl === "ok" ? "Alles OK" : lvl === "degraded" ? "Verminderd" : lvl ? "Kritiek" : "—",
      label: "Systeemstatus", desc: "Algehele health, dit venster",
      hint: "Het hoofdoordeel voor de geselecteerde periode: Alles OK, Verminderd of Kritiek — op basis van het aantal gevonden kritieke issues." });
    stats.push({ key: "crit", cardId: "hero:criticals", tone: !snap ? "muted" : snap.total > 0 ? "crit" : "ok", skeleton: !snap,
      value: snap ? snap.total : "—", label: "Kritieke meldingen", desc: "Error logs, 5xx & APM errors",
      hint: "Totaal aantal error-level log entries, HTTP 5xx server errors en APM errors in het geselecteerde venster. De mini-grafiek toont de trend over de periode.",
      spark: (snap?.timeseries || []).map((b) => b.count) });
  }
  if (can("pipeline_health")) {
    // Distinguish genuinely at-risk (verdict "problem" — cannot publish) from the
    // large "still being processed" backlog. Only the former is alarming; the
    // pending total is shown as calm context so management isn't scared by a big
    // number that is mostly normal throughput.
    const list = health?.stuck || [];
    const problems = list.filter((d) => d.verdict === "problem").length;
    const pending = health?.stuck_count || 0;
    stats.push({ key: "risk", cardId: "hero:risk", tone: problems > 0 ? "crit" : "ok",
      value: health ? problems : "—", skeleton: health === null,
      label: "Docs met risico",
      desc: pending > 0 ? `van ${pending.toLocaleString("nl-NL")} nog in verwerking` : "alles gepubliceerd",
      hint: "Documenten met een echt probleem (kunnen niet gepubliceerd worden) — deze vereisen actie. Het 'nog in verwerking'-totaal zijn documenten die normaal door de pipeline bewegen; de meeste publiceren prima. Klik om te tracen.",
      onClick: (problems > 0 || pending > 0) ? () => onNavigate("documents") : undefined });
  }
  if (can("aanleverfouten")) {
    const n = aanlever?.count;
    stats.push({ key: "aanlever", cardId: "hero:aanlever", tone: n > 0 ? "warn" : "ok", value: aanlever ? (n || 0) : "—", skeleton: aanlever === null,
      label: "Aanleverfouten", desc: "Geweigerd bij aanlevering",
      hint: "Documenten die bij aanlevering door een publisher zijn geweigerd — ze zijn nooit de pipeline ingegaan en moeten opnieuw worden aangeleverd." });
  }
  if (can("rabbitmq") && dlq && dlq.configured !== false) {
    const n = dlq.count || 0;
    stats.push({ key: "dlq", cardId: "hero:dlq", tone: n > 0 ? "warn" : "ok", value: n,
      label: "Dead-letter queues", desc: "Vastgelopen RabbitMQ-berichten",
      hint: "RabbitMQ dead-letter queues die nu berichten bevatten — werk dat niet verwerkt kon worden en wacht; niets draint het." });
  }

  if (!stats.length) return null;
  return (
    <div className="hero-strip">
      {stats.map((s) => <HeroStat key={s.key} {...s} />)}
    </div>
  );
}

export default function DashboardPage({ token, username, onLogout, onNavigate, llmProvider, onProviderChange, aiEnabled = true, showCardDetails = true, dashSections = {}, can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount }) {
  // A dashboard section is visible unless explicitly switched off in Settings.
  const showSec = (key) => dashSections[key] !== false;
  const [range, setRange] = useState(loadRange);
  const onRangeChange = (r) => { setRange(r); saveRange(r); };
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
  const [dlq, setDlq] = useState(null);           // RabbitMQ dead-letter queues
  const [digestMsg, setDigestMsg] = useState("");

  // Aanleverfouten — documents rejected at delivery/intake, grouped by publisher.
  const loadAanlever = useCallback(() => {
    getJSON("/dashboard/aanleverfouten", token)
      .then(setAanlever)
      .catch(() => setAanlever(null));
  }, [token]);
  useEffect(() => { loadAanlever(); }, [loadAanlever]);

  // RabbitMQ dead-letter queues (only if granted).
  useEffect(() => {
    if (!can("rabbitmq")) return;
    let active = true;
    getJSON("/dashboard/dlq", token).then((d) => active && setDlq(d)).catch(() => active && setDlq(null));
    return () => { active = false; };
  }, [token, can]);

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
      `/dashboard/outcomes?${timeParams(range)}&data_view=${encodeURIComponent(dataView)}`,
      token
    )
      .then((d) => active && setOutcomes(d))
      .catch(() => active && setOutcomes(null));
    return () => {
      active = false;
    };
  }, [timeParams(range), dataView, token]);

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
        `/dashboard/summary?${timeParams(range)}&data_view=${encodeURIComponent(dataView)}`,
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
  }, [timeParams(range), dataView, token, onLogout]);

  useEffect(() => {
    load();
  }, [load]);

  const loadBriefing = useCallback(
    async (regenerate = false) => {
      setBriefingState("loading");
      try {
        const data = await getJSON(
          `/dashboard/briefing?${timeParams(range)}&data_view=${encodeURIComponent(dataView)}${
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
    [timeParams(range), dataView, token]
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
      <TopNav
        active="dashboard"
        brandMark="◆"
        brandName="Monitoring"
        brandSub={`Critical issues · ${rangeLabel(range)} · ${dataView}`}
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
          <div className="dash-controls">
            <span className="page-eyebrow" style={{ width: "100%", marginBottom: -4 }}>Bereik & databron</span>
            <label className="control">
              <span className="control-label">
                Period <InfoTip text="A quick preset (rolling window ending now) or a custom from→to range — pick any dates, including very old data." />
              </span>
              <TimeRange value={range} onChange={onRangeChange} disabled={loading} />
            </label>

            <label className="control">
              <span className="control-label">
                Dataweergave <InfoTip text={'Welke Elasticsearch-dataset te analyseren. \u201Clogs-*\u201D is alles; de andere beperken tot een specifiek systeem.'} />
              </span>
              <select
                className="control-select"
                value={dataView}
                onChange={(e) => setDataView(e.target.value)}
                disabled={loading}
                title="Elasticsearch data view om te analyseren"
              >
                {dataViews.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label && v.label !== v.id ? `${v.id} — ${v.label}` : v.id}
                  </option>
                ))}
              </select>
            </label>

            <button className="btn btn--ghost" onClick={load} disabled={loading}>
              {loading ? "Vernieuwen…" : "Vernieuwen"}
            </button>
            {loadedAt && (
              <span className="dash-asof">
                data as of {loadedAt.toLocaleTimeString()}
              </span>
            )}
          </div>

          {error && <div className="alert alert--error">{error}</div>}

          {showSec("uptime") && can("uptime") && <UptimeBoard token={token} />}
          {showSec("service_health") && can("service_health") && <ServiceHealthCard token={token} />}

          {showSec("infra") && can("grafana") && (
            <DashZone id="infra" title="Infrastructuur" eyebrow="Grafana & servers">
              <InfraLinks token={token} />
            </DashZone>
          )}

          {showSec("hero") && (
            <HeroStrip snap={snap} health={health} aanlever={aanlever} dlq={dlq} can={can} onNavigate={onNavigate} />
          )}

          <DashZone id="attention" title="Vereist aandacht" eyebrow="Actie vereist" alert>

          {showSec("aanlever") && can("aanleverfouten") && <AanleverfoutenCard data={aanlever} onAck={ackAanlever} onNavigate={onNavigate} />}

          {showSec("dlq") && can("rabbitmq") && <DlqCard data={dlq} onNavigate={onNavigate} />}

          {showSec("certs") && can("certificates") && (
          <CollapsiblePanel
            id="certs"
            cardId="card:certificates"
            title="Certificate & TLS health"
            info="Security (TLS) certificaatstatus voor de belangrijkste sites. De app controleert open.overheid.nl en doculoket.overheid.nl actief en direct — expiry-countdown plus eventuele trust-, chain-, hostname- of expiry-problemen — en toont ook wat Kibana monitort. Groen: >30 dagen & trusted; oranje: onder 30 dagen of een warning; rood: onder 14 dagen, verlopen of niet trusted."
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
                    <div className="env-columns">
                      {CERT_ENV_ORDER.map((env) => {
                        const list = certs.filter((c) => certEnv(c.host) === env);
                        if (!list.length) return null;
                        return (
                          <div key={env} className={`env-col env-col--${env.toLowerCase()}`}>
                            <div className="env-col-head">
                              {env}
                              <span className="env-col-count">{list.length}</span>
                            </div>
                            <div className="env-col-body">
                              {list.map((c) => (
                                <div
                                  key={c.host}
                                  data-smartcard={`cert:${c.host}`}
                                  data-smartlabel={c.host}
                                  data-smartstatus={c.status}
                                  data-smartenv={env}
                                >
                                  <CertCard c={c} />
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </>
                );
              })()
            )}
          </CollapsiblePanel>
          )}
          </DashZone>

          <DashZone id="throughput" title="Throughput & outcomes" eyebrow="Documentverwerking">
          {can("outcomes") && <OutcomesCard data={outcomes} onNavigate={onNavigate} />}
          </DashZone>

          {snap && (
            <>
              <DashZone id="overview" title="Overzicht & diagnostiek" eyebrow="Logs & fouten">
              <div className={`status-banner status-banner--${snap.status_level}`}>
                <strong>
                  {snap.status_level === "ok"
                    ? "Alles OK"
                    : snap.status_level === "degraded"
                    ? "Verminderd"
                    : "Kritiek"}
                </strong>
                {snap.partial && <span className="dash-warn">gedeeltelijke data</span>}
              </div>

              <div className="kpis">
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.total} <Delta pct={snap.delta.pct_vs_previous} />
                  </span>
                  <span className="kpi-label">
                    criticals · {rangeLabel(range).toLowerCase()}
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
                cardId="card:notfound"
                title="Documenten niet gevonden (404)"
                alert={snap.not_found_total > 0}
                subtitle={'Pages users opened that returned \u201Cnot found\u201D \u2014 usually broken links or removed content. High numbers hurt the user experience.'}
                info={'Pages or documents a user requested but that returned \u201Cfile not found\u201D. High counts usually mean broken links or removed/missing content on the site.'}
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
                    No "not found" errors in this window — every requested page resolved.
                  </p>
                ) : (
                  <>
                    <p className="notfound-total">
                      <strong>{snap.not_found_total}</strong> request
                      {snap.not_found_total === 1 ? "" : "s"} returned "not found".
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
                cardId="card:overtime"
                title="Kritieke meldingen over tijd"
                info="Wanneer issues optraden — elke bar is een time bucket; hoger betekent meer criticals toen. Eén hoge bar = een spike."
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
                cardId="card:bysystem"
                title="By system"
                info={'Critical issues per data view (system). The highlighted tile is the one you\u2019re currently viewing; \u201Cunavailable\u201D means that system couldn\u2019t be reached this load.'}
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
                cardId="card:signatures"
                title="Top error signatures"
                info="De meest voorkomende error-types, met wanneer elk voor het eerst en laatst gezien is. Een burst tussen twee dicht op elkaar liggende tijden wijst vaak op één root cause."
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
                cardId="card:services"
                title="Affected services"
                info="De services (applicaties) die de meeste kritieke issues uitzenden in dit venster — waar je eerst moet kijken."
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
                cardId="card:http5xx"
                title="HTTP 5xx"
                alert={snap.status_codes.length > 0}
                subtitle="Server errors (status 500–599): de site zelf reageerde niet, met de URLs die het lieten afweten. Ernstiger dan een 404 — dit is de server, niet een ontbrekende pagina."
                info="Server errors — de site reageerde niet goed (status 500–599). Vermeld met de URLs die faalden. Anders dan 404, wat betekent dat de pagina niet gevonden is."
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

              {can("pipeline_health") && health && (() => {
                const atRisk = health.stuck || [];
                const critical = atRisk.filter((d) => d.verdict === "problem").length;
                return atRisk.length > 0 ? (
                  <section className="panel panel--alert" data-smartcard="card:pipeline-health" data-smartlabel="Documents needing attention" data-smartstatus="crit">
                    <h3>
                      🚨 Documents needing attention
                      <InfoTip text="Documenten die nog NIET live staan op open.overheid.nl — errored (kunnen niet gepubliceerd worden) of stuck/hangend in een service. Proactief getoond zodat je handelt voordat gebruikers het melden. Klik op een document om precies te tracen waar het misging." />
                    </h3>
                    <p className="pipe-alert">
                      {atRisk.length} document{atRisk.length === 1 ? "" : "s"} met risico
                      {critical > 0 ? ` · ${critical} critical` : ""} — handel voordat gebruikers het merken.
                    </p>
                    <div className="digest-bar">
                      <button className="btn btn--ghost" onClick={sendDigest} title="Deze lijst nu e-mailen / Slacken">
                        📧 Stuur mij deze digest
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
                          title="Klik om dit document te tracen"
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
                        ✓ {health.confirmed_published} ander document{health.confirmed_published === 1 ? "" : "s"} had hiccups maar {health.confirmed_published === 1 ? "is" : "are"} al gepubliceerd &amp; leesbaar — geen risico.
                      </p>
                    )}
                  </section>
                ) : (
                  <section className="panel" data-smartcard="card:pipeline-health" data-smartlabel="Documents pipeline" data-smartstatus="ok">
                    <h3>
                      🚦 Documents pipeline
                      <InfoTip text="Proactive check: are any documents failing to reach open.overheid.nl? Updates automatically." />
                    </h3>
                    <p className="pipe-ok">✓ Geen documenten met risico — alles bereikt open.overheid.nl.</p>
                  </section>
                );
              })()}

              </DashZone>

              {aiEnabled && (
              <DashZone id="ai" title="AI insights" eyebrow="Kunstmatige intelligentie">
              <CollapsiblePanel
                id="aitriage"
                cardId="card:aitriage"
                title="AI daily triage"
                className="panel--ai"
                info="Een door AI geschreven samenvatting van de feiten hierboven (counts, signatures, services). Het beschrijft alleen die cijfers — het kan dingen nog steeds verkeerd verwoorden, dus verifieer iets belangrijks altijd in Kibana."
                headerExtra={
                  <button
                    className="btn btn--ghost panel-header-action"
                    onClick={() => loadBriefing(true)}
                    disabled={briefingState === "loading"}
                  >
                    {briefingState === "loading" ? "Genereren…" : "Opnieuw genereren"}
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
              </DashZone>
              )}
            </>
          )}
        </div>
      </div>

      {showCardDetails && can("smart_context") && (
        <SmartContextPanel token={token} aiEnabled={aiEnabled} lang="nl" />
      )}
    </>
  );
}
