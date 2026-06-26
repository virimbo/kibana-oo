import { useEffect, useState, useCallback } from "react";
import TopNav from "./Nav";
import { fetchDlqIntel } from "./api";

// Beheer/Dashboard → DLQ Intelligentie. Read-only insight into WHY messages are
// stuck in each dead-letter queue: smart verdict, reason breakdown, age, trend,
// recommended action and a peeked sample. Built on the dashboard design system
// (.panel, .up-tile, severity colours, .dash-table). Needs the `rabbitmq` grant.
const SEV = { ok: "var(--success)", warn: "var(--warn)", critical: "var(--error)" };
const TILE = { ok: "up", warn: "warn", critical: "down" };

function age(s) {
  if (s == null) return "?";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}u`;
  return `${Math.floor(s / 86400)}d`;
}

export default function DlqIntelPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, aanleverCount, dlqCount,
}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setData(await fetchDlqIntel(token)); setError(null); }
    catch (e) { setError(String(e.message || e)); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const nav = (
    <TopNav active="dlq-intel" brandMark="🐰" brandName="DLQ Intelligentie"
            brandSub="Dead-letter queues · admin" can={can} isAdmin={isAdmin}
            username={username} onLogout={onLogout} onNavigate={onNavigate}
            llmProvider={llmProvider} onProviderChange={onProviderChange}
            aanleverCount={aanleverCount} dlqCount={dlqCount} />
  );

  if (data && data.enabled === false) {
    return <>{nav}<div className="chat-scroll"><div className="dash">
      <section className="panel gx-panel"><h3 className="gx-h2">🐰 DLQ Intelligentie</h3>
        <p className="muted">Uitgeschakeld (<code>DLQ_INTEL_ENABLED=false</code>).</p></section>
    </div></div></>;
  }
  if (!data) return <>{nav}<div className="chat-scroll"><div className="dash">
    <section className="panel"><p className="muted">Laden…</p></section></div></div></>;

  const queues = (data.queues || []).filter((q) => q.depth > 0);
  return <>{nav}<div className="chat-scroll"><div className="dash">
    {error && <div className="error" role="alert">{error}</div>}
    <div className="gx-pagehead">
      <span className="gx-eyebrow">RabbitMQ · DLQ</span>
      <h1 className="gx-h1">DLQ Intelligentie</h1>
    </div>
    <section className="panel gx-panel">
      <h3 className="gx-h2">🐰 DLQ Intelligentie</h3>
      <p className="muted set-intro">
        Waarom staan er berichten vast? Per queue: oorzaak, leeftijd, trend en
        aanbevolen actie. Alleen-lezen — berichten worden niet verwijderd of verplaatst.
      </p>
      {queues.length === 0 && <p className="muted">✓ Alle dead-letter queues zijn leeg — niets vastgelopen.</p>}
    </section>
    {queues.map((q) => (
      <section key={q.name} className={`panel gx-panel gx-stat-card up-tile up-tile--${TILE[q.severity]}`} style={{ marginBottom: 12 }}>
        <h3 className="gx-h2" style={{ color: SEV[q.severity], marginBottom: 10 }}>{q.headline}</h3>
        <div className="alerts-settings-row" style={{ gap: 28 }}>
          <div className="alerts-field"><label>Queue</label><b>{q.name}</b></div>
          <div className="alerts-field"><label className="gx-stat-label">Diepte</label><b className="gx-stat-num">{q.depth.toLocaleString("nl-NL")}</b></div>
          <div className="alerts-field"><label>Trend</label><b>{q.trend}</b></div>
          <div className="alerts-field"><label>Oudste</label><b>{age(q.oldest_age_seconds)}</b></div>
          <div className="alerts-field"><label>Consumers</label><b>{q.source_consumers ?? "—"}</b></div>
        </div>
        {q.action && <p style={{ marginTop: 10 }}>🛠️ <b>Actie:</b> {q.action}</p>}
        {q.reasons?.length > 0 && (
          <p className="muted">Oorzaken: {q.reasons.map((r) => `${r.reason} (${r.count}×)`).join(" · ")}</p>
        )}
        {q.sample?.length > 0 && (
          <table className="dash-table" style={{ marginTop: 8 }}>
            <thead><tr><th>Oorzaak</th><th>Bron</th><th>Routing</th><th>Leeftijd</th></tr></thead>
            <tbody>
              {q.sample.map((s, i) => (
                <tr key={i}><td>{s.reason}</td><td>{s.source}</td><td>{s.routing}</td><td>{age(s.age_seconds)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {!q.peeked && <p className="muted">⚠ Berichten konden niet gelezen worden — alleen telling beschikbaar.</p>}
      </section>
    ))}
  </div></div></>;
}
