import { useEffect, useState, useCallback } from "react";
import TopNav from "./Nav";
import {
  fetchAlertsStatus, fetchAlertsHistory, putAlertToggle, putAlertConfig,
} from "./api";

// Beheer → Alerting (meldingen). Admin surface to manage the unified alert engine:
// global/category/env/card toggles, recipients, cooldown, threshold and history.
// Viewing needs the `alerts` grant; mutations are super-admin-only (enforced
// server-side — a non-super save returns 403, surfaced as an inline error).
const SEV_COLOR = { ok: "#3fb950", warn: "#d29922", critical: "#f85149" };
const CATEGORIES = [
  ["environment", "Omgevingsstatus"],
  ["dlq", "Dead-letter queues"],
  ["certificate", "Certificaten & TLS"],
];
const ENVS = ["PROD", "ACC", "TST"];

export default function AlertsPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, aanleverCount, dlqCount,
}) {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [recipients, setRecipients] = useState("");

  const load = useCallback(async () => {
    try {
      const s = await fetchAlertsStatus(token);
      setStatus(s);
      if (s?.config?.recipients) setRecipients(s.config.recipients.join(", "));
      if (s?.enabled !== false) {
        const h = await fetchAlertsHistory(token);
        setHistory(h.history || []);
      }
      setError(null);
    } catch (e) { setError(String(e.message || e)); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const toggleOn = (scope, ref) => {
    const t = (status?.toggles || []).find((x) => x.scope === scope && x.ref === ref);
    return t ? !!t.enabled : true; // absence = ON
  };
  const setToggle = async (scope, ref, enabled) => {
    try { await putAlertToggle(token, { scope, ref, enabled }); load(); }
    catch (e) { setError(String(e.message || e)); }
  };
  const saveConfig = async (patch) => {
    try { await putAlertConfig(token, patch); load(); }
    catch (e) { setError(String(e.message || e)); }
  };

  const nav = (
    <TopNav
      active="alerts"
      brandMark="🔔"
      brandName="Alerting"
      brandSub="Meldingen"
      can={can}
      isAdmin={isAdmin}
      username={username}
      onLogout={onLogout}
      onNavigate={onNavigate}
      llmProvider={llmProvider}
      onProviderChange={onProviderChange}
      aanleverCount={aanleverCount}
      dlqCount={dlqCount}
    />
  );

  if (status && status.enabled === false) {
    return (
      <>
        {nav}
        <main className="page">
          <div className="card">
            Alerting is uitgeschakeld (<code>ALERTS_ENABLED=false</code>). Zet de
            functie aan in de omgeving om meldingen te beheren.
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      {nav}
      <main className="page alerts-page">
        <h2>🔔 Alerting (meldingen)</h2>
        {error && <div className="error" role="alert">{error}</div>}
        {!status && <div className="card">Laden…</div>}

        {status && (
          <>
            <section className="card">
              <label className="toggle-row">
                <input type="checkbox" checked={toggleOn("global", "")}
                       onChange={(e) => setToggle("global", "", e.target.checked)} />
                <strong>Alerting globaal ingeschakeld</strong>
              </label>
            </section>

            <section className="card">
              <h3>Categorieën</h3>
              {CATEGORIES.map(([key, label]) => (
                <label key={key} className="toggle-row">
                  <input type="checkbox" checked={toggleOn("category", key)}
                         onChange={(e) => setToggle("category", key, e.target.checked)} />
                  {label}
                </label>
              ))}
              <h3>Omgevingen</h3>
              {ENVS.map((env) => (
                <label key={env} className="toggle-row">
                  <input type="checkbox" checked={toggleOn("env", env)}
                         onChange={(e) => setToggle("env", env, e.target.checked)} />
                  {env}
                </label>
              ))}
            </section>

            <section className="card">
              <h3>Kaarten</h3>
              <ul className="alerts-cards">
                {(status.items || []).map((it) => (
                  <li key={it.card_id} className="toggle-row">
                    <input type="checkbox" checked={toggleOn("card", it.card_id)}
                           onChange={(e) => setToggle("card", it.card_id, e.target.checked)} />
                    <span style={{ color: SEV_COLOR[it.severity] || "#888" }}>●</span>
                    <span>[{it.env}] {it.name}</span>
                    <em>{it.status}</em>
                  </li>
                ))}
                {(status.items || []).length === 0 && <li>Geen kaarten beschikbaar.</li>}
              </ul>
            </section>

            <section className="card">
              <h3>Ontvangers</h3>
              <textarea value={recipients} rows={2} style={{ width: "100%" }}
                        placeholder="ops@example.com, beheer@example.com"
                        onChange={(e) => setRecipients(e.target.value)} />
              <button className="btn" onClick={() => saveConfig({
                recipients: recipients.split(",").map((s) => s.trim()).filter(Boolean),
              })}>Ontvangers opslaan</button>

              <h3>Instellingen</h3>
              <label>Cooldown (min):{" "}
                <input type="number" min={1} max={10080}
                       defaultValue={status.config.cooldown_minutes}
                       onBlur={(e) => saveConfig({ cooldown_minutes: Number(e.target.value) })} />
              </label>{"  "}
              <label>Drempel:{" "}
                <select defaultValue={status.config.severity_threshold}
                        onChange={(e) => saveConfig({ severity_threshold: e.target.value })}>
                  <option value="critical">critical (alleen rood)</option>
                  <option value="warn">warn (waarschuwing + rood)</option>
                </select>
              </label>
            </section>

            <section className="card">
              <h3>Alertgeschiedenis</h3>
              <table className="alerts-history">
                <thead><tr>
                  <th>Tijd</th><th>Kaart</th><th>Soort</th><th>Severity</th><th>Verzonden</th>
                </tr></thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={i}>
                      <td>{h.ts}</td><td>{h.card_id}</td><td>{h.kind}</td>
                      <td style={{ color: SEV_COLOR[h.severity] }}>{h.severity}</td>
                      <td>{h.delivered ? "✓" : "✗"}</td>
                    </tr>
                  ))}
                  {history.length === 0 && (
                    <tr><td colSpan={5}>Nog geen meldingen verzonden.</td></tr>
                  )}
                </tbody>
              </table>
            </section>
          </>
        )}
      </main>
    </>
  );
}
