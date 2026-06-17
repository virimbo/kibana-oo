import { useState, useEffect, useCallback } from "react";
import { getJSON } from "./api";

// Beschikbaarheid / environment status — the prominent top-of-dashboard board.
// One card per site, grouped PROD / ACC / TEST, polling the cached backend view.

const STATE_META = {
  up:          { cls: "up",   icon: "✓", label: "UP" },
  degraded:    { cls: "warn", icon: "▲", label: "TRAAG" },
  down:        { cls: "down", icon: "⛔", label: "DOWN" },
  unreachable: { cls: "unk",  icon: "⚪", label: "ONBEREIKBAAR" },
};

const REFRESH_MS = 30000;

function ago(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (isNaN(ms) || ms < 0) return "";
  const m = Math.round(ms / 60000);
  if (m < 1) return "zojuist";
  if (m < 60) return `${m} min geleden`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}u ${m % 60}m geleden` : `${Math.floor(h / 24)}d geleden`;
}

// Tiny status sparkline — one bar per recent check, coloured by state.
function StatusSpark({ history }) {
  if (!history || history.length < 2) return null;
  return (
    <span className="up-spark" aria-hidden="true">
      {history.slice(-20).map((s, i) => (
        <span key={i} className={`up-spark-bar up-spark-bar--${STATE_META[s]?.cls || "unk"}`} />
      ))}
    </span>
  );
}

function SiteCard({ s, env }) {
  const meta = STATE_META[s.state] || STATE_META.unreachable;
  return (
    <div
      className={`up-tile up-tile--${meta.cls}`}
      data-smartcard={`uptime:${s.name}`}
      data-smartlabel={s.name}
      data-smartstatus={s.state}
      data-smartenv={env}
      title={s.url}
    >
      <div className="up-tile-top">
        <span className="up-tile-icon" aria-hidden="true">{meta.icon}</span>
        <span className={`up-tile-state up-tile-state--${meta.cls}`}>{meta.label}</span>
        {s.latency_ms != null && <span className="up-tile-ms">{s.latency_ms} ms</span>}
      </div>
      <div className="up-tile-name" title={s.name}>{s.name}</div>
      <div className="up-tile-meta">
        {s.http_status ? `HTTP ${s.http_status}` : (s.error || "geen reactie")}
        {s.uptime_pct != null && <> · {s.uptime_pct}% up</>}
      </div>
      <div className="up-tile-foot">
        <StatusSpark history={s.history} />
        <span className="up-tile-ago">
          {s.state === "down" && s.since ? `down sinds ${ago(s.since)}` : ago(s.checked_at)}
        </span>
      </div>
    </div>
  );
}

export default function UptimeBoard({ token }) {
  const [data, setData] = useState(null); // null=loading, {enabled:false}=off

  const load = useCallback(() => {
    getJSON("/dashboard/uptime/status", token)
      .then(setData)
      .catch(() => setData({ enabled: false }));
  }, [token]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (!data || data.enabled === false) return null; // disabled / no perms / loading-first-paint

  const sum = data.summary || {};
  const headCls = sum.verdict === "ok" ? "ok" : sum.verdict === "down" ? "down" : "warn";
  const headText =
    sum.down > 0 ? `⛔ ${sum.down} down`
    : sum.degraded > 0 ? `⚠ ${sum.degraded} traag`
    : sum.unreachable > 0 ? `⚪ ${sum.unreachable} onbereikbaar · ✓ ${sum.up}/${sum.total} up`
    : `✓ ${sum.up}/${sum.total} up`;

  return (
    <section className="dash-zone up-zone">
      <h2 className="dash-section up-section">
        <span className="up-section-title">🌐 Beschikbaarheid — Environment status</span>
        <span className={`up-rollup up-rollup--${headCls}`}>{headText}</span>
      </h2>

      <div className="env-columns">
        {(data.groups || []).map((g) => (
          <div key={g.env} className={`env-col env-col--${g.env.toLowerCase()}`}>
            <div className="env-col-head">
              {g.env}
              <span className="env-col-count">{g.sites.length}</span>
            </div>
            <div className="env-col-body">
              {g.sites.map((s) => <SiteCard key={s.name} s={s} env={g.env} />)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
