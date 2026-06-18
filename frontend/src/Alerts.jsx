import { useEffect, useState, useCallback, useRef } from "react";
import TopNav from "./Nav";
import {
  fetchAlertsStatus, fetchAlertsHistory, putAlertToggle, putAlertConfig,
} from "./api";

// Beheer → Alerting (meldingen). Admin surface for the unified alert engine:
// master switch, scope toggles (category/env/card), recipients, cooldown,
// threshold and history. Built on the dashboard design language (.panel,
// .switch, .up-tile, env colours, .dash-table). Viewing needs the `alerts`
// grant; mutations are super-admin-only (enforced server-side → 403 surfaced).

const CATEGORIES = [
  ["environment", "Omgevingsstatus"],
  ["dlq", "Dead-letter queues"],
  ["certificate", "Certificaten & TLS"],
];
const ENVS = ["PROD", "ACC", "TST"];
const SEV_TILE = { ok: "up", warn: "warn", critical: "down" };
const ENV_CLASS = { PROD: "prod", ACC: "acc", TST: "tst" };

// Reusable on/off switch — same markup/styling as Settings' Toggle.
function Switch({ checked, onChange, disabled = false, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`switch${checked ? " is-on" : ""}`}
      onClick={() => !disabled && onChange(!checked)}
    >
      <span className="switch-knob" />
    </button>
  );
}

function Row({ label, hint, checked, onChange, disabled }) {
  return (
    <div className={`set-row${disabled ? " set-row--disabled" : ""}`}>
      <div className="set-row-text">
        <span className="set-row-label">{label}</span>
        {hint && <span className="set-row-hint">{hint}</span>}
      </div>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={label} />
    </div>
  );
}

function fmtTs(ts) {
  if (!ts) return "";
  return String(ts).replace("T", " ").replace(/\.\d+/, "").replace(/(\+00:00|Z)$/, " UTC");
}

export default function AlertsPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, aanleverCount, dlqCount,
}) {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [recipients, setRecipients] = useState("");
  const [saved, setSaved] = useState(false);
  const savedTimer = useRef(null);

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

  const flashSaved = () => {
    setSaved(true);
    clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSaved(false), 1800);
  };

  const toggleOn = (scope, ref) => {
    const t = (status?.toggles || []).find((x) => x.scope === scope && x.ref === ref);
    return t ? !!t.enabled : true; // absence = ON
  };
  const setToggle = async (scope, ref, enabled) => {
    // optimistic: reflect immediately, reconcile on reload
    try { await putAlertToggle(token, { scope, ref, enabled }); load(); }
    catch (e) { setError(String(e.message || e)); }
  };
  const saveConfig = async (patch) => {
    try { await putAlertConfig(token, patch); await load(); flashSaved(); }
    catch (e) { setError(String(e.message || e)); }
  };

  const nav = (
    <TopNav
      active="alerts" brandMark="🔔" brandName="Alerting" brandSub="Meldingen · admin"
      can={can} isAdmin={isAdmin} username={username} onLogout={onLogout}
      onNavigate={onNavigate} llmProvider={llmProvider} onProviderChange={onProviderChange}
      aanleverCount={aanleverCount} dlqCount={dlqCount}
    />
  );

  // ── inert / loading / error shells ──
  if (status && status.enabled === false) {
    return (
      <>{nav}
        <div className="chat-scroll"><div className="dash">
          <section className="panel set-panel">
            <h3>🔔 Alerting (meldingen)</h3>
            <div className="alerts-banner alerts-banner--off">
              ⚠ Alerting staat uit (<code>ALERTS_ENABLED=false</code>). Zet de functie
              aan in de omgeving om meldingen te beheren.
            </div>
          </section>
        </div></div>
      </>
    );
  }
  if (!status) {
    return (<>{nav}<div className="chat-scroll"><div className="dash">
      <section className="panel set-panel"><p className="muted">Laden…</p></section>
    </div></div></>);
  }

  const items = status.items || [];
  const counts = items.reduce((a, it) => (a[it.severity] = (a[it.severity] || 0) + 1, a), {});
  const globalOn = toggleOn("global", "");

  return (
    <>{nav}
      <div className="chat-scroll"><div className="dash">

        {error && <div className="error" role="alert">{error}</div>}

        {/* ── Master / engine status ─────────────────────────── */}
        <section className="panel set-panel">
          <div className="alerts-hero">
            <div className="alerts-hero-text">
              <span className="alerts-hero-title">🔔 Alerting (meldingen)</span>
              <span className="alerts-hero-sub">
                E-mailmeldingen zodra een kaart RED wordt — omgevingen, dead-letter
                queues en certificaten. Slim ontdubbeld met cooldown en herstelmelding.
              </span>
            </div>
            <div className="alerts-pills">
              <span className={`alerts-pill ${counts.critical ? "alerts-pill--crit" : "alerts-pill--muted"}`}>
                <b>{counts.critical || 0}</b> kritiek
              </span>
              <span className={`alerts-pill ${counts.warn ? "alerts-pill--warn" : "alerts-pill--muted"}`}>
                <b>{counts.warn || 0}</b> waarschuwing
              </span>
              <span className="alerts-pill alerts-pill--ok"><b>{counts.ok || 0}</b> ok</span>
            </div>
          </div>
          <div style={{ marginTop: 6 }}>
            <Row
              label="Alerting globaal ingeschakeld"
              hint="Hoofdschakelaar. Uit = er gaan geen meldingen, monitoring blijft gewoon werken."
              checked={globalOn}
              onChange={(v) => setToggle("global", "", v)}
            />
          </div>
          {!globalOn && (
            <div className="alerts-banner alerts-banner--off" style={{ marginTop: 10 }}>
              ⚠ Globaal uitgeschakeld — er worden nu geen meldingen verstuurd.
            </div>
          )}
        </section>

        {/* ── Scope: categories + environments ───────────────── */}
        <section className={`panel set-panel${globalOn ? "" : " is-muted"}`}>
          <h3>Bereik</h3>
          <p className="muted set-intro">
            Een melding gaat alléén af als élk niveau aan staat: globaal · categorie ·
            omgeving · kaart. Zet een niveau uit om die hele tak te dempen.
          </p>
          <div className="alerts-scope-grid">
            <div className="alerts-scope-col">
              <h4>Categorieën</h4>
              {CATEGORIES.map(([key, label]) => (
                <Row key={key} label={label} checked={toggleOn("category", key)}
                     disabled={!globalOn}
                     onChange={(v) => setToggle("category", key, v)} />
              ))}
            </div>
            <div className="alerts-scope-col">
              <h4>Omgevingen</h4>
              {ENVS.map((env) => (
                <Row key={env} label={env} checked={toggleOn("env", env)}
                     disabled={!globalOn}
                     onChange={(v) => setToggle("env", env, v)} />
              ))}
            </div>
          </div>
        </section>

        {/* ── Per-card tiles ─────────────────────────────────── */}
        <section className="panel set-panel">
          <h3>Kaarten <span className="muted" style={{ fontWeight: 400 }}>· {items.length} bewaakt</span></h3>
          {items.length === 0 && <p className="alerts-empty">Geen kaarten beschikbaar.</p>}
          <div className="alerts-card-grid">
            {items.map((it) => {
              const on = toggleOn("card", it.card_id);
              const tile = SEV_TILE[it.severity] || "unk";
              const envc = ENV_CLASS[it.env] || "other";
              return (
                <div key={it.card_id}
                     className={`up-tile up-tile--${tile} alerts-tile${on && globalOn ? "" : " is-muted"}`}>
                  <div className="alerts-tile-head">
                    <span className={`env-badge env-badge--${envc}`}>{it.env}</span>
                    <span className={`up-tile-state up-tile-state--${tile}`}>
                      {it.severity.toUpperCase()}
                    </span>
                    <span className="alerts-tile-switch">
                      <Switch checked={on} disabled={!globalOn}
                              onChange={(v) => setToggle("card", it.card_id, v)}
                              label={`alert voor ${it.name}`} />
                    </span>
                  </div>
                  <span className="alerts-tile-name">{it.name}</span>
                  <span className="alerts-tile-status">{it.status}</span>
                </div>
              );
            })}
          </div>
        </section>

        {/* ── Recipients + settings ──────────────────────────── */}
        <section className="panel set-panel">
          <h3>Ontvangers &amp; instellingen</h3>
          <div className="alerts-form">
            {(status.config.recipients || []).length > 0 && (
              <div className="alerts-chips">
                {status.config.recipients.map((r) => (
                  <span key={r} className="alerts-chip">{r}</span>
                ))}
              </div>
            )}
            <textarea className="alerts-textarea" rows={2} value={recipients}
                      placeholder="ops@example.com, beheer@example.com"
                      onChange={(e) => setRecipients(e.target.value)} />
            <div className="alerts-save-row">
              <button className="btn btn--primary" onClick={() => saveConfig({
                recipients: recipients.split(",").map((s) => s.trim()).filter(Boolean),
              })}>Ontvangers opslaan</button>
              <span className={`alerts-saved${saved ? " is-shown" : ""}`}>✓ opgeslagen</span>
            </div>

            <div className="alerts-settings-row">
              <div className="alerts-field">
                <label htmlFor="al-th">Drempel</label>
                <select id="al-th" className="alerts-select"
                        value={status.config.severity_threshold}
                        onChange={(e) => saveConfig({ severity_threshold: e.target.value })}>
                  <option value="critical">critical · alleen rood</option>
                  <option value="warn">warn · waarschuwing + rood</option>
                </select>
              </div>
            </div>
            <p className="muted set-intro" style={{ marginTop: 4 }}>
              📨 Eén melding zodra iets stuk gaat, daarna stilte zolang het stuk blijft,
              en één herstelmelding zodra het weer OK is. (Bij verergering naar
              <em> critical</em> volgt eenmalig een escalatie.)
            </p>
          </div>
        </section>

        {/* ── History ────────────────────────────────────────── */}
        <section className="panel set-panel">
          <h3>Alertgeschiedenis</h3>
          {history.length === 0 ? (
            <p className="alerts-empty">Nog geen meldingen verzonden.</p>
          ) : (
            <div className="alerts-history-wrap">
              <table className="dash-table">
                <thead><tr>
                  <th>Tijd</th><th>Kaart</th><th>Soort</th><th>Severity</th><th>Verzonden</th>
                </tr></thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={i}>
                      <td className="alerts-ts">{fmtTs(h.ts)}</td>
                      <td>{h.card_id}</td>
                      <td><span className={`alert-kind alert-kind--${h.kind}`}>{h.kind}</span></td>
                      <td>
                        <span className={`alert-sev-dot alert-sev--${h.severity}`} />
                        {h.severity}
                      </td>
                      <td className={h.delivered ? "alerts-deliver--yes" : "alerts-deliver--no"}>
                        {h.delivered ? "✓" : "✗"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

      </div></div>
    </>
  );
}
