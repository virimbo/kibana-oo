import { useCallback, useEffect, useState } from "react";
import TopNav from "./Nav";
import { fetchObservability } from "./api";

// Beheer → Observability. A plain-language overview of the critical monitoring
// signals for the KOOP/Plooi document-publishing platform: is data still flowing
// in, do documents reach open.overheid.nl, are deliveries rejected, and are there
// errors? Each signal is explained for a non-technical admin, with what-to-do.
// Read-only roll-up of facts the dashboard already computes (backend reuses the
// cached snapshot/health + aanlever scan).

const DEFAULT_DATA_VIEW = "logs-*";
const DEFAULT_PERIOD = 60;

// Map a backend status to the shared .alerts-pill classes + a friendly label.
const PILL = {
  ok: { cls: "alerts-pill--ok", label: "OK" },
  warn: { cls: "alerts-pill--warn", label: "Let op" },
  crit: { cls: "alerts-pill--crit", label: "Kritiek" },
  unknown: { cls: "alerts-pill--unknown", label: "Onbekend" },
};

function Pill({ status }) {
  const p = PILL[status] || PILL.unknown;
  return <span className={`alerts-pill ${p.cls} obs-pill`}>{p.label}</span>;
}

function SignalCard({ s }) {
  return (
    <article className={`gx-panel obs-card obs-card--${s.status || "unknown"}`}>
      <header className="obs-card-head">
        <h3 className="gx-h2 obs-card-title">{s.title}</h3>
        <Pill status={s.status} />
      </header>
      <p className="obs-metric">{s.metric}</p>
      {s.note && <p className="obs-note muted">{s.note}</p>}
      <dl className="obs-explain">
        <dt>Wat is dit?</dt>
        <dd>{s.what}</dd>
        <dt>Waarom kritiek?</dt>
        <dd>{s.why}</dd>
        <dt>Wat te doen?</dt>
        <dd>{s.action}</dd>
      </dl>
    </article>
  );
}

export default function ObservabilityPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchObservability(token, DEFAULT_DATA_VIEW, DEFAULT_PERIOD);
      setData(res);
      setError("");
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [token, onLogout]);

  useEffect(() => { load(); }, [load]);

  const overall = data?.overall;
  const signals = data?.signals || [];

  return (
    <>
      <TopNav
        active="observability"
        brandMark="📈"
        brandName="Observability"
        brandSub="Beheer · datastroom & gezondheid"
        can={can} isAdmin={isAdmin} username={username} onLogout={onLogout}
        onNavigate={onNavigate} llmProvider={llmProvider} onProviderChange={onProviderChange}
        stuckCount={stuckCount} aanleverCount={aanleverCount} dlqCount={dlqCount}
      />
      <div className="chat-scroll">
        <div className="dash">
          <section className="page-hero gx-pagehead">
            <div className="page-hero-main">
              <span className="page-eyebrow gx-eyebrow">• BEHEER · OBSERVABILITY</span>
              <h1 className="page-hero-h1 gx-h1">OBSERVABILITY</h1>
              <p className="page-hero-lead muted">
                De belangrijkste monitoring-signalen van het publicatieplatform in
                gewone taal: <b>stroomt de data nog binnen</b>, <b>bereiken documenten
                open.overheid.nl</b>, <b>worden aanleveringen geweigerd</b> en <b>zijn er
                fouten</b>? Bij elk signaal staat wat het betekent en wat je moet doen.
              </p>
            </div>
            <button type="button" className="btn btn--ghost obs-refresh" onClick={load} disabled={loading}>
              {loading ? "Vernieuwen…" : "↻ Vernieuwen"}
            </button>
          </section>

          {error && <div className="alert alert--error">{error}</div>}

          {overall && (
            <section className={`gx-panel obs-banner obs-banner--${overall.status || "unknown"}`}>
              <span className="obs-banner-dot" aria-hidden="true" />
              <div className="obs-banner-body">
                <span className="page-eyebrow gx-eyebrow">Algemene status</span>
                <p className="obs-banner-headline">{overall.headline}</p>
              </div>
              <Pill status={overall.status} />
            </section>
          )}

          {loading && !data && <p className="muted">Laden…</p>}
          {!loading && !error && signals.length === 0 && (
            <p className="muted">Geen signalen beschikbaar.</p>
          )}

          <div className="obs-grid">
            {signals.map((s) => <SignalCard key={s.key} s={s} />)}
          </div>
        </div>
      </div>
    </>
  );
}
