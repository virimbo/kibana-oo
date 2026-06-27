import { useEffect, useState, useCallback } from "react";
import { fetchMonitoring } from "./api";

// Dashboard card: admin-configured monitoring targets (Monitoring registry).
// Self-fetching; renders nothing when the feature is off (200 {enabled:false})
// or the user lacks the grant. Built on the dashboard design system (.panel,
// the svch-* tile look, the gx kit). Each target is a colour-barred tile
// (its live status); click to expand its detail. Read-only.

// Maps a target status → the shared severity colour classes ServiceHealth uses
// (up/warn/down/unk), so the existing CSS styles the tiles — no new colours.
const VERDICT = {
  ok:          { cls: "up",   icon: "✓",  label: "ok" },
  warn:        { cls: "warn", icon: "▲",  label: "warn" },
  stale:       { cls: "warn", icon: "▲",  label: "stale" },
  down:        { cls: "down", icon: "⛔", label: "down" },
  unreachable: { cls: "unk",  icon: "?",  label: "unreachable" },
  unknown:     { cls: "unk",  icon: "?",  label: "unknown" },
};

// Worst-first ranking, so the card's overall status + alert state reflect the
// most severe target across all environments.
const SEVERITY = ["down", "unreachable", "stale", "warn", "ok"];
const RANK = { down: 5, unreachable: 4, stale: 3, warn: 2, ok: 1, unknown: 0 };

const ENV_ORDER = ["prod", "acc", "na"];
const ENV_LABEL = { prod: "PROD", acc: "ACC", na: "Overig" };

const MON_INFO =
  "Door beheerders ingestelde monitoring-targets per omgeving (PROD/ACC). " +
  "Per target wordt een bron bewaakt — logs, traces, metrics of http — en " +
  "de live status getoond: ok (groen), warn/stale (oranje), down (rood), " +
  "unreachable/unknown (grijs). De coverage-regel vat per omgeving samen welke " +
  "signaal-dimensies dekking hebben. Klik een tegel voor de details.";

// Local InfoTip (same markup/CSS as the dashboard's) — inlined to avoid a
// circular import with Dashboard.jsx, which imports this card.
function InfoTip({ text }) {
  return (
    <span className="infotip" tabIndex={0} role="note" aria-label={text}>
      i
      <span className="infotip-pop">{text}</span>
    </span>
  );
}

// Render a target's detail blob as a compact, human-readable line. Mirrors
// ServiceHealth's endpoint meta: show whatever the backend supplied.
function detailLine(d) {
  if (!d || typeof d !== "object") return "—";
  const parts = [];
  if (d.age_min != null) {
    parts.push(`age ${d.age_min} min${d.threshold != null ? ` / ${d.threshold} min` : ""}`);
  }
  if (d.traces != null) parts.push(`traces ${d.traces}`);
  if (d.value != null) parts.push(`value ${d.value}`);
  if (d.http != null) parts.push(`HTTP ${d.http}`);
  if (d.error) parts.push(d.error);
  return parts.length ? parts.join(" · ") : "—";
}

export default function MonitoringCard({ token }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try { setData(await fetchMonitoring(token)); }
    catch { setData({ enabled: false }); }   // no grant / error → hide
  }, [token]);
  useEffect(() => { load(); }, [load]);

  if (!data || data.enabled === false) return null;

  const byEnv = data.by_env || {};
  const coverage = data.coverage || {};
  const envs = Object.keys(byEnv);

  const allTargets = envs.flatMap((env) => byEnv[env] || []);
  const worst = allTargets.reduce(
    (acc, t) => ((RANK[t.status] || 0) > (RANK[acc] || 0) ? t.status : acc),
    "ok"
  );
  const hasProblem = allTargets.some((t) =>
    ["down", "stale", "unreachable"].includes(t.status)
  );

  // Coverage dimensions to show per env, in a stable order.
  const COV_DIMS = ["logs", "traces", "metrics", "http"];

  return (
    <section className={`panel${hasProblem ? " panel--alert" : ""}`}
             data-smartcard="card:monitoring" data-smartlabel="Monitoring"
             data-smartstatus={worst} data-smartenv="PROD">
      <h3>
        <span className="gx-h2">📡 Monitoring</span> <InfoTip text={MON_INFO} />
      </h3>

      {Object.keys(coverage).length > 0 && (
        <div className="mon-coverage">
          {Object.keys(coverage)
            .sort((a, b) => ENV_ORDER.indexOf(a) - ENV_ORDER.indexOf(b))
            .map((env) => {
              const cov = coverage[env] || {};
              const pct = cov.score != null ? Math.round(cov.score * 100) : null;
              return (
                <span key={env} className="gx-pill mon-cov-pill">
                  {ENV_LABEL[env] || env.toUpperCase()}
                  {pct != null ? ` ${pct}%` : ""}
                  {COV_DIMS.filter((d) => cov[d] != null).map((d) => (
                    <span key={d} className="mon-cov-dim">
                      {" · "}{d} {cov[d] === "ok" ? "✓" : "✗"}
                    </span>
                  ))}
                </span>
              );
            })}
        </div>
      )}

      {envs.length === 0 ? (
        <p className="muted">Geen monitoring-targets geconfigureerd.</p>
      ) : (
        envs
          .sort((a, b) => ENV_ORDER.indexOf(a) - ENV_ORDER.indexOf(b))
          .map((env) => {
            const targets = byEnv[env] || [];
            if (!targets.length) return null;
            return (
              <div key={env} className="mon-env">
                <div className="mon-env-head">{ENV_LABEL[env] || env.toUpperCase()}</div>
                <div className="svch-grid">
                  {targets.map((t) => {
                    const v = VERDICT[t.status] || VERDICT.unknown;
                    const key = `${env}:${t.id}`;
                    const isOpen = open === key;
                    return (
                      <div key={key} className={`svch-tile svch-tile--${v.cls}${isOpen ? " is-open" : ""}`}>
                        <button type="button" className="svch-tile-head"
                                onClick={() => setOpen(isOpen ? null : key)}
                                aria-expanded={isOpen}>
                          <span className="svch-tile-icon" aria-hidden="true">{v.icon}</span>
                          <span className="svch-tile-name">
                            {t.name} <span className="mon-tile-type">{t.type}</span>
                          </span>
                          <span className={`svch-tile-state svch-tile-state--${v.cls}`}>{v.label}</span>
                          <span className="svch-tile-caret" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                        </button>
                        {isOpen && (
                          <ul className="svch-eps">
                            <li className="svch-ep">
                              <span className={`svch-ep-dot svch-ep-dot--${v.cls}`} />
                              <span className="svch-ep-meta">{detailLine(t.detail)}</span>
                            </li>
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
      )}
    </section>
  );
}
