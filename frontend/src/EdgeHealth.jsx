import { useEffect, useState, useCallback } from "react";
import { fetchEdgeHealth } from "./api";

// Dashboard card: PROD edge/ingress HTTP health — HTTP 5xx, gateway errors
// (502/503/504), time-outs (504), elevated latency (p95) and pod restarts.
// Self-fetching; renders nothing when the feature is off (200 {enabled:false}),
// the user lacks the grant (403), or it can't load. Read-only. Built on the
// dashboard design system (.panel, .gx-* kit) with a small scoped .eh-* kit.

const CLS = { ok: "ok", warn: "warn", critical: "crit", unknown: "unk" };
const ICON = { ok: "✓", warn: "▲", critical: "⛔", unknown: "?" };
const OVERALL_LABEL = { ok: "OK", warn: "WAARSCHUWING", critical: "KRITIEK", unknown: "ONBEKEND" };

export default function EdgeHealthCard({ token }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchEdgeHealth(token));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [token]);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000); // refresh every minute
    return () => clearInterval(id);
  }, [load]);

  if (failed || !data || data.enabled === false) return null;

  const signals = data.signals || [];
  const overall = data.overall || "unknown";
  const reqs = data.total_requests;

  return (
    <section
      className={`panel gx-panel eh-card eh-card--${CLS[overall]}`}
      data-smartcard="card:edge-health"
      data-smartlabel="PROD — HTTP-fouten & latency"
      data-smartstatus={overall === "critical" ? "crit" : overall}
    >
      <div className="eh-head">
        <div>
          <span className="page-eyebrow gx-eyebrow">PROD · edge</span>
          <h3 className="gx-h3 eh-title">HTTP-fouten &amp; latency</h3>
        </div>
        <span className={`eh-badge eh-badge--${CLS[overall]}`}>{OVERALL_LABEL[overall]}</span>
      </div>

      <p className="eh-sub muted">
        Laatste {data.window_minutes} min
        {typeof reqs === "number" ? ` · ${reqs.toLocaleString("nl-NL")} requests` : ""}
      </p>

      <div className="eh-grid">
        {signals.map((s) => (
          <div key={s.key} className={`eh-tile eh-tile--${CLS[s.status] || "unk"}`}>
            <span className="eh-tile-top">
              <span className="eh-tile-icon" aria-hidden="true">{ICON[s.status] || "?"}</span>
              <span className="eh-tile-label">{s.label}</span>
            </span>
            <span className="eh-tile-metric">{s.metric}</span>
            {s.detail ? <span className="eh-tile-detail muted">{s.detail}</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
