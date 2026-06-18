import { useEffect, useState, useCallback, useRef } from "react";
import TopNav from "./Nav";
import {
  fetchAlertsStatus, fetchAlertsHistory, putAlertToggle, putAlertConfig,
} from "./api";

// Beheer → Alerting (meldingen). Editorial "command center": a status hero, an
// env-scope control bar, and per-category env-matrices (PROD/ACC/TST columns) of
// severity-barred tiles with inline per-card toggles. Built on the dashboard
// design language (.panel, .switch, env colours, .dash-table). Viewing needs the
// `alerts` grant; mutations are super-admin-only (server-side → 403 surfaced).

const CATEGORIES = [
  ["environment", "Omgevingsstatus"],
  ["dlq", "Dead-letter queues"],
  ["certificate", "Certificaten & TLS"],
];
const CAT_META = {
  environment: { icon: "🌐", sub: "Beschikbaarheid van de sites" },
  dlq: { icon: "🐰", sub: "Vastgelopen berichten in queues" },
  certificate: { icon: "🔐", sub: "Geldigheid & vertrouwen van TLS" },
};
const ENVS = ["PROD", "ACC", "TST"];
const ENV_CLASS = { PROD: "prod", ACC: "acc", TST: "tst" };
const SEV_LABEL = { ok: "OK", warn: "WAARSCHUWING", critical: "KRITIEK" };

function Switch({ checked, onChange, disabled = false, label }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label}
            disabled={disabled} className={`switch${checked ? " is-on" : ""}`}
            onClick={() => !disabled && onChange(!checked)}>
      <span className="switch-knob" />
    </button>
  );
}

function rollup(list) {
  return list.reduce((a, it) => (a[it.severity] = (a[it.severity] || 0) + 1, a),
                     { ok: 0, warn: 0, critical: 0 });
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
    try { await putAlertToggle(token, { scope, ref, enabled }); load(); }
    catch (e) { setError(String(e.message || e)); }
  };
  const saveConfig = async (patch) => {
    try { await putAlertConfig(token, patch); await load(); flashSaved(); }
    catch (e) { setError(String(e.message || e)); }
  };

  const nav = (
    <TopNav active="alerts" brandMark="🔔" brandName="Alerting" brandSub="Meldingen · admin"
            can={can} isAdmin={isAdmin} username={username} onLogout={onLogout}
            onNavigate={onNavigate} llmProvider={llmProvider} onProviderChange={onProviderChange}
            aanleverCount={aanleverCount} dlqCount={dlqCount} />
  );

  if (status && status.enabled === false) {
    return <>{nav}<div className="chat-scroll"><div className="dash">
      <section className="panel"><h3>🔔 Alerting (meldingen)</h3>
        <div className="alerts-banner alerts-banner--off">
          ⚠ Alerting staat uit (<code>ALERTS_ENABLED=false</code>). Zet de functie aan
          in de omgeving om meldingen te beheren.
        </div></section>
    </div></div></>;
  }
  if (!status) {
    return <>{nav}<div className="chat-scroll"><div className="dash">
      <section className="panel"><p className="muted">Laden…</p></section></div></div></>;
  }

  const items = status.items || [];
  const counts = rollup(items);
  const globalOn = toggleOn("global", "");

  // group items: category → env → [items]
  const byCat = {};
  for (const it of items) {
    (byCat[it.category] ||= {});
    (byCat[it.category][it.env] ||= []).push(it);
  }

  const tileOff = (it, catOn) => !(toggleOn("card", it.card_id) && catOn && globalOn);

  return (
    <>{nav}
      <div className="chat-scroll"><div className="dash alerts-page">
        {error && <div className="error" role="alert">{error}</div>}

        {/* ── Command-center hero ───────────────────────────── */}
        <section className={`alerts-hero-wrap${globalOn ? "" : " is-paused"}`}>
          <div className="alerts-hero-main">
            <span className="alerts-eyebrow">Beheer · Meldingen</span>
            <h1 className="alerts-hero-h1">🔔 Alerting</h1>
            <p className="alerts-hero-lead">
              Eén melding zodra een kaart RED wordt — omgevingen, dead-letter queues
              en certificaten. Slim ontdubbeld: één keer DOWN, één keer hersteld.
            </p>
            <div className="alerts-master">
              <Switch label="Alerting globaal" checked={globalOn}
                      onChange={(v) => setToggle("global", "", v)} />
              <span className="alerts-master-label">
                {globalOn ? "Alerting staat AAN" : "Alerting is gepauzeerd"}
              </span>
            </div>
          </div>
          <div className="alerts-hero-stats">
            <div className={`alerts-stat alerts-stat--crit${counts.critical ? " is-live" : ""}`}>
              <span className="alerts-stat-num">{counts.critical}</span>
              <span className="alerts-stat-lbl">kritiek</span>
            </div>
            <div className={`alerts-stat alerts-stat--warn${counts.warn ? " is-live" : ""}`}>
              <span className="alerts-stat-num">{counts.warn}</span>
              <span className="alerts-stat-lbl">waarschuwing</span>
            </div>
            <div className="alerts-stat alerts-stat--ok">
              <span className="alerts-stat-num">{counts.ok}</span>
              <span className="alerts-stat-lbl">gezond</span>
            </div>
          </div>
        </section>

        {/* ── Env scope control bar ─────────────────────────── */}
        <section className="panel alerts-controlbar">
          <div className="alerts-controlbar-text">
            <span className="alerts-eyebrow">Bereik per omgeving</span>
            <span className="muted">Dempt een hele omgeving — over alle categorieën heen.</span>
          </div>
          <div className="alerts-env-switches">
            {ENVS.map((env) => (
              <div key={env} className={`alerts-envswitch alerts-envswitch--${ENV_CLASS[env]}${toggleOn("env", env) && globalOn ? "" : " is-off"}`}>
                <span className={`env-badge env-badge--${ENV_CLASS[env]}`}>{env}</span>
                <Switch label={`omgeving ${env}`} checked={toggleOn("env", env)}
                        disabled={!globalOn} onChange={(v) => setToggle("env", env, v)} />
              </div>
            ))}
          </div>
        </section>

        {/* ── Per-category env matrices ─────────────────────── */}
        {items.length === 0 && (
          <section className="panel"><p className="alerts-empty">Geen kaarten beschikbaar.</p></section>
        )}
        {CATEGORIES.map(([catKey, label]) => {
          const envMap = byCat[catKey];
          if (!envMap) return null;
          const meta = CAT_META[catKey];
          const catItems = Object.values(envMap).flat();
          const cc = rollup(catItems);
          const catOn = toggleOn("category", catKey);
          const envsHere = ENVS.filter((e) => envMap[e]?.length);
          return (
            <section key={catKey} className={`alerts-cat${catOn && globalOn ? "" : " is-muted"}`}>
              <header className="alerts-cat-head">
                <span className="alerts-cat-icon" aria-hidden="true">{meta.icon}</span>
                <div className="alerts-cat-titles">
                  <span className="alerts-eyebrow">{meta.sub}</span>
                  <h2 className="alerts-cat-title">{label}</h2>
                </div>
                <div className="alerts-cat-roll">
                  {cc.critical > 0 && <span className="alerts-pill alerts-pill--crit"><b>{cc.critical}</b> kritiek</span>}
                  {cc.warn > 0 && <span className="alerts-pill alerts-pill--warn"><b>{cc.warn}</b> waarschuwing</span>}
                  <span className="alerts-pill alerts-pill--ok"><b>{cc.ok}</b> ok</span>
                </div>
                <Switch label={`categorie ${label}`} checked={catOn}
                        disabled={!globalOn} onChange={(v) => setToggle("category", catKey, v)} />
              </header>

              <div className="alerts-envcols" data-cols={envsHere.length}>
                {envsHere.map((env) => {
                  const list = envMap[env];
                  const ec = rollup(list);
                  return (
                    <div key={env} className={`alerts-envcol alerts-envcol--${ENV_CLASS[env]}`}>
                      <div className="alerts-envcol-head">
                        <span className={`env-badge env-badge--${ENV_CLASS[env]}`}>{env}</span>
                        <span className="alerts-envcol-meta">
                          {ec.critical > 0 && <i className="dot dot--crit" />}
                          {ec.warn > 0 && <i className="dot dot--warn" />}
                          <span className="muted">{list.length}</span>
                        </span>
                      </div>
                      <div className="alerts-envcol-list">
                        {list.map((it, i) => (
                          <div key={it.card_id}
                               className={`alerts-mtile alerts-mtile--${it.severity}${tileOff(it, catOn) ? " is-off" : ""}`}
                               style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}>
                            <span className="alerts-mtile-bar" aria-hidden="true" />
                            <div className="alerts-mtile-body">
                              <div className="alerts-mtile-top">
                                <span className={`alerts-mtile-sev alerts-mtile-sev--${it.severity}`}>
                                  {SEV_LABEL[it.severity]}
                                </span>
                                <Switch label={`alert voor ${it.name}`}
                                        checked={toggleOn("card", it.card_id)} disabled={!globalOn}
                                        onChange={(v) => setToggle("card", it.card_id, v)} />
                              </div>
                              <span className="alerts-mtile-name" title={it.name}>{it.name}</span>
                              <span className="alerts-mtile-status">{it.status}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}

        {/* ── Recipients + settings ─────────────────────────── */}
        <section className="panel set-panel">
          <span className="alerts-eyebrow">Bezorging</span>
          <h3>Ontvangers &amp; instellingen</h3>
          <div className="alerts-form">
            {(status.config.recipients || []).length > 0 && (
              <div className="alerts-chips">
                {status.config.recipients.map((r) => <span key={r} className="alerts-chip">{r}</span>)}
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
                <select id="al-th" className="alerts-select" value={status.config.severity_threshold}
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

        {/* ── History ───────────────────────────────────────── */}
        <section className="panel set-panel">
          <span className="alerts-eyebrow">Spoor</span>
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
                      <td><span className={`alert-sev-dot alert-sev--${h.severity}`} />{h.severity}</td>
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
