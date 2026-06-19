import { useEffect, useState, useCallback } from "react";
import { fetchServiceHealth } from "./api";

// Dashboard card: backend-microservice health. Self-fetching; renders nothing when
// the feature is off (200 {enabled:false}) or the user lacks the grant. Built on the
// dashboard design system (.panel, severity colours, the provider-aware theme).
// Each service is a colour-barred tile (worst-endpoint verdict); click to expand its
// endpoints (path · state · HTTP code · latency). Read-only.

const VERDICT = {
  up:          { cls: "up",   icon: "✓", label: "up" },
  degraded:    { cls: "warn", icon: "▲", label: "traag" },
  unreachable: { cls: "unk",  icon: "?", label: "unreachable" },
  down:        { cls: "down", icon: "⛔", label: "down" },
};

const SVCH_INFO =
  "De backend-microservices van KOOP/Plooi (Harvester, Antivirus, Repository, " +
  "Search, DCN, Keycloak, Solr, RabbitMQ, …). Read-only HTTP-probe per service " +
  "(Spring-actuator + service/UI-endpoint): 5xx of actuator-DOWN = down (rood), " +
  "2xx–4xx incl. 401/403/405 = up (reageert), traag = degraded, connectie-fout = " +
  "unreachable (grijs — down óf geen VPN). Klik een tegel voor de losse endpoints.";

// Local InfoTip (same markup/CSS as the dashboard's) — inlined to avoid a circular
// import with Dashboard.jsx, which imports this card.
function InfoTip({ text }) {
  return (
    <span className="infotip" tabIndex={0} role="note" aria-label={text}>
      i
      <span className="infotip-pop">{text}</span>
    </span>
  );
}

function epPath(url) {
  try { const u = new URL(url); return u.host.split(".")[0] + u.pathname; }
  catch { return url; }
}

export default function ServiceHealthCard({ token }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try { setData(await fetchServiceHealth(token)); }
    catch { setData({ enabled: false }); }   // no grant / error → hide
  }, [token]);
  useEffect(() => { load(); }, [load]);

  if (!data || data.enabled === false) return null;

  const services = data.services || [];
  const s = data.summary || {};
  const hasProblem = (s.down || 0) + (s.unreachable || 0) + (s.degraded || 0) > 0;

  return (
    <section className={`panel${hasProblem ? " panel--alert" : ""}`}
             data-smartcard="card:service_health" data-smartlabel="Service health"
             data-smartstatus={s.verdict} data-smartenv="PROD">
      <h3>
        🧩 Service health <InfoTip text={SVCH_INFO} />
        <span className="svch-summary">
          {s.down > 0 && <span className="svch-pill svch-pill--down">⛔ {s.down} down</span>}
          {s.unreachable > 0 && <span className="svch-pill svch-pill--unk">? {s.unreachable} unreachable</span>}
          {s.degraded > 0 && <span className="svch-pill svch-pill--warn">▲ {s.degraded} traag</span>}
          <span className="svch-pill svch-pill--up">✓ {s.healthy}/{s.total} healthy</span>
        </span>
      </h3>

      <div className="svch-grid">
        {services.map((svc) => {
          const v = VERDICT[svc.verdict] || VERDICT.unreachable;
          const isOpen = open === svc.service;
          return (
            <div key={svc.service} className={`svch-tile svch-tile--${v.cls}${isOpen ? " is-open" : ""}`}>
              <button type="button" className="svch-tile-head"
                      onClick={() => setOpen(isOpen ? null : svc.service)}
                      aria-expanded={isOpen}>
                <span className="svch-tile-icon" aria-hidden="true">{v.icon}</span>
                <span className="svch-tile-name">{svc.service}</span>
                <span className={`svch-tile-state svch-tile-state--${v.cls}`}>{v.label}</span>
                <span className="svch-tile-caret" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <ul className="svch-eps">
                  {svc.endpoints.map((e, i) => {
                    const ev = VERDICT[e.state] || VERDICT.unreachable;
                    return (
                      <li key={i} className="svch-ep">
                        <span className={`svch-ep-dot svch-ep-dot--${ev.cls}`} />
                        <span className="svch-ep-path" title={e.url}>{epPath(e.url)}</span>
                        <span className="svch-ep-meta">
                          {e.health ? `actuator ${e.health}` : e.http_status ? `HTTP ${e.http_status}`
                            : (e.error || "—")}
                          {e.latency_ms != null ? ` · ${e.latency_ms} ms` : ""}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
        {services.length === 0 && <p className="muted">Geen services geconfigureerd.</p>}
      </div>
    </section>
  );
}
