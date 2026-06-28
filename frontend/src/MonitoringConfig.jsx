import { useState, useEffect, useCallback } from "react";
import TopNav from "./Nav";
import {
  fetchMonitorTypes,
  fetchMonitorConnections,
  addMonitorConnection,
  deleteMonitorConnection,
  fetchMonitorTargets,
  addMonitorTarget,
  patchMonitorTarget,
  deleteMonitorTarget,
  testMonitorTarget,
  discoverMonitor,
} from "./api";

// Super-admin-only: the Monitoring Targets registry. Operators add connections
// (Prometheus/Jaeger) and targets (http, log-freshness, jaeger-traces,
// prometheus-query). Secrets live in `.env` — only the secret_ref NAME is shown
// here, never a secret value.

const ENVIRONMENTS = ["prod", "acc", "test", "na"];
const ENV_LABEL = { prod: "PROD", acc: "ACC", test: "TEST", na: "Overig" };
const CONNECTION_KINDS = ["prometheus", "jaeger"];

// A reusable on/off switch (mirrors Settings.jsx).
function Switch({ checked, onChange, label, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`switch${checked ? " is-on" : ""}`}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      aria-label={label}
    >
      <span className="switch-knob" />
    </button>
  );
}

// Render one form field from a type field descriptor into the local config map.
function Field({ field, value, onChange }) {
  const { name, label, kind, options, required } = field;
  const id = `mon-field-${name}`;
  const lbl = label || name;

  if (kind === "bool") {
    return (
      <label className="mon-field mon-field--inline" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>{lbl}</span>
      </label>
    );
  }

  return (
    <label className="mon-field" htmlFor={id}>
      <span className="mon-field-label">
        {lbl}
        {required ? " *" : ""}
      </span>
      {kind === "select" ? (
        <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— kies —</option>
          {(options || []).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : kind === "int" || kind === "float" ? (
        <input
          id={id}
          type="number"
          step={kind === "float" ? "any" : "1"}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={value ?? ""}
          placeholder={kind === "list-int" ? "bijv. 200, 204, 301" : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}

// Build the outgoing config object from the raw field values + the type schema,
// coercing kinds (int/float → number, bool → bool, list-int → [int]).
function buildConfig(fields, values) {
  const out = {};
  for (const f of fields) {
    const raw = values[f.name];
    if (raw === undefined || raw === "" || raw === null) continue;
    if (f.kind === "int") out[f.name] = parseInt(raw, 10);
    else if (f.kind === "float") out[f.name] = parseFloat(raw);
    else if (f.kind === "bool") out[f.name] = !!raw;
    else if (f.kind === "list-int") {
      out[f.name] = String(raw)
        .split(",")
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !Number.isNaN(n));
    } else out[f.name] = raw;
  }
  return out;
}

// Seed raw field values from an existing config (e.g. a discover suggestion).
function seedValues(config) {
  const out = {};
  for (const [k, v] of Object.entries(config || {})) {
    out[k] = Array.isArray(v) ? v.join(", ") : v;
  }
  return out;
}

export default function MonitoringConfig({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [types, setTypes] = useState({});
  const [connections, setConnections] = useState([]);
  const [targets, setTargets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Connection add form
  const [connForm, setConnForm] = useState({ kind: "prometheus", name: "", base_url: "", secret_ref: "" });

  // Target add form
  const [showForm, setShowForm] = useState(false);
  const [tType, setTType] = useState("");
  const [tName, setTName] = useState("");
  const [tEnv, setTEnv] = useState("prod");
  const [tConn, setTConn] = useState("");
  const [tValues, setTValues] = useState({});
  const [suggestions, setSuggestions] = useState(null);

  // Per-row test results: { [targetId]: {status, detail, latency_ms} }
  const [testResults, setTestResults] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [ty, co, ta] = await Promise.all([
        fetchMonitorTypes(token),
        fetchMonitorConnections(token),
        fetchMonitorTargets(token),
      ]);
      setTypes(ty || {});
      setConnections(co || []);
      setTargets(ta || []);
      setError("");
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [token, onLogout]);

  useEffect(() => { load(); }, [load]);

  // ── Connections ──────────────────────────────────────────────────────────
  const addConn = async () => {
    if (!connForm.name.trim() || !connForm.base_url.trim()) {
      setError("Vul naam en base_url in voor de connection.");
      return;
    }
    setBusy(true);
    try {
      await addMonitorConnection(token, {
        kind: connForm.kind,
        name: connForm.name.trim(),
        base_url: connForm.base_url.trim(),
        secret_ref: connForm.secret_ref.trim() || undefined,
        enabled: 1,
      });
      setConnForm({ kind: "prometheus", name: "", base_url: "", secret_ref: "" });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeConn = async (id) => {
    setBusy(true);
    try {
      await deleteMonitorConnection(token, id);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // ── Targets ──────────────────────────────────────────────────────────────
  const patchTarget = async (id, patch) => {
    setBusy(true);
    try {
      await patchMonitorTarget(token, id, patch);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeTarget = async (id) => {
    setBusy(true);
    try {
      await deleteMonitorTarget(token, id);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (t) => {
    setTestResults((r) => ({ ...r, [t.id]: { status: "…", detail: "test loopt" } }));
    try {
      const res = await testMonitorTarget(token, {
        type: t.type,
        config: t.config || {},
        connection_id: t.connection_id ?? undefined,
      });
      setTestResults((r) => ({ ...r, [t.id]: res }));
    } catch (e) {
      setTestResults((r) => ({ ...r, [t.id]: { status: "error", detail: e.message } }));
    }
  };

  const resetForm = () => {
    setTType(""); setTName(""); setTEnv("prod"); setTConn(""); setTValues({}); setSuggestions(null);
  };

  const submitTarget = async () => {
    if (!tType) { setError("Kies een type voor de target."); return; }
    if (!tName.trim()) { setError("Vul een naam in voor de target."); return; }
    const fields = types[tType]?.fields || [];
    setBusy(true);
    try {
      await addMonitorTarget(token, {
        name: tName.trim(),
        type: tType,
        environment: tEnv,
        connection_id: tConn ? Number(tConn) : undefined,
        config: buildConfig(fields, tValues),
        enabled: 1,
        alert_enabled: 1,
      });
      resetForm();
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runDiscover = async () => {
    if (!tConn) { setError("Kies eerst een connection om te discoveren."); return; }
    try {
      const res = await discoverMonitor(token, Number(tConn));
      setSuggestions(res?.suggestions || []);
    } catch (e) {
      setError(e.message);
    }
  };

  const applySuggestion = (s) => {
    setTType(s.type || "");
    setTName(s.name || "");
    setTEnv(s.environment || "prod");
    if (s.connection_id != null) setTConn(String(s.connection_id));
    setTValues(seedValues(s.config));
    setSuggestions(null);
  };

  // Group targets by environment.
  const grouped = ENVIRONMENTS.map((env) => ({
    env,
    rows: targets.filter((t) => (t.environment || "na") === env),
  })).filter((g) => g.rows.length > 0);

  const typeKeys = Object.keys(types);
  const activeFields = tType ? (types[tType]?.fields || []) : [];

  return (
    <>
      <TopNav
        active="monitoring"
        brandMark="📡"
        brandName="Monitoring"
        brandSub="Super admin · monitoring-targets & connections"
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
          <section className="page-hero gx-pagehead">
            <div className="page-hero-main">
              <span className="page-eyebrow gx-eyebrow">• BEHEER · MONITORING</span>
              <h1 className="page-hero-h1 gx-h1">MONITORING</h1>
              <p className="page-hero-lead muted">
                Monitoring-targets beheren — voeg connections (Prometheus/Jaeger) en targets toe.
                Secrets staan in <code>.env</code>; hier wordt alleen de naam (secret_ref) getoond,
                nooit een waarde.
              </p>
            </div>
          </section>

          {error && <div className="alert alert--error">{error}</div>}
          {loading && <p className="muted">Laden…</p>}

          {/* ── Connections ─────────────────────────────────────── */}
          <section className="panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Connections</span>
            <h3 className="gx-h2">🔌 Connections</h3>
            <p className="muted set-intro">
              Endpoints van Prometheus/Jaeger. Een credential hoort in <code>.env</code> —
              verwijs er hier alleen naar met de secret_ref naam.
            </p>

            {connections.length === 0 && !loading ? (
              <p className="muted">Geen connections.</p>
            ) : (
              <table className="mon-table">
                <thead>
                  <tr>
                    <th>Soort</th><th>Naam</th><th>Base URL</th><th>Secret</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {connections.map((c) => (
                    <tr key={c.id}>
                      <td>{c.kind}</td>
                      <td>{c.name}</td>
                      <td className="mon-mono">{c.base_url}</td>
                      <td>{c.secret_ref ? <span className="mon-badge">via .env: {c.secret_ref}</span> : <span className="muted">—</span>}</td>
                      <td>
                        <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => removeConn(c.id)}>
                          Verwijder
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="mon-addrow">
              <select
                value={connForm.kind}
                onChange={(e) => setConnForm((f) => ({ ...f, kind: e.target.value }))}
                aria-label="Connection kind"
              >
                {CONNECTION_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
              <input
                type="text" placeholder="name" value={connForm.name}
                onChange={(e) => setConnForm((f) => ({ ...f, name: e.target.value }))}
              />
              <input
                type="text" placeholder="base_url (https://…)" value={connForm.base_url}
                onChange={(e) => setConnForm((f) => ({ ...f, base_url: e.target.value }))}
              />
              <input
                type="text" placeholder="secret_ref (naam in .env, optioneel)" value={connForm.secret_ref}
                onChange={(e) => setConnForm((f) => ({ ...f, secret_ref: e.target.value }))}
              />
              <button type="button" className="gx-cta" disabled={busy} onClick={addConn}>
                Toevoegen
              </button>
            </div>
          </section>

          {/* ── Targets ─────────────────────────────────────────── */}
          <section className="panel gx-panel">
            <div className="mon-panel-head">
              <div>
                <span className="page-eyebrow gx-eyebrow">Targets</span>
                <h3 className="gx-h2">🎯 Targets</h3>
              </div>
              <button
                type="button"
                className="gx-cta"
                onClick={() => { setShowForm((s) => !s); if (showForm) resetForm(); }}
              >
                {showForm ? "Sluiten" : "+ Target"}
              </button>
            </div>

            {/* Add target form */}
            {showForm && (
              <div className="mon-form">
                <div className="mon-form-grid">
                  <label className="mon-field">
                    <span className="mon-field-label">Type *</span>
                    <select value={tType} onChange={(e) => { setTType(e.target.value); setTValues({}); }}>
                      <option value="">— kies type —</option>
                      {typeKeys.map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </label>
                  <label className="mon-field">
                    <span className="mon-field-label">Name *</span>
                    <input type="text" value={tName} onChange={(e) => setTName(e.target.value)} />
                  </label>
                  <label className="mon-field">
                    <span className="mon-field-label">Environment</span>
                    <select value={tEnv} onChange={(e) => setTEnv(e.target.value)}>
                      {ENVIRONMENTS.map((env) => <option key={env} value={env}>{ENV_LABEL[env]}</option>)}
                    </select>
                  </label>
                  <label className="mon-field">
                    <span className="mon-field-label">Connection (voor jaeger/prometheus)</span>
                    <select value={tConn} onChange={(e) => setTConn(e.target.value)}>
                      <option value="">— geen —</option>
                      {connections.map((c) => (
                        <option key={c.id} value={c.id}>{c.name} ({c.kind})</option>
                      ))}
                    </select>
                  </label>
                </div>

                {tConn && (
                  <div className="mon-discover">
                    <button type="button" className="btn btn--ghost" onClick={runDiscover}>
                      Discover
                    </button>
                    {suggestions && suggestions.length === 0 && (
                      <span className="muted">Geen suggesties.</span>
                    )}
                    {suggestions && suggestions.length > 0 && (
                      <ul className="mon-suggestions">
                        {suggestions.map((s, i) => (
                          <li key={i}>
                            <span>{s.name} <em className="muted">({s.type} · {s.environment})</em></span>
                            <button type="button" className="btn btn--ghost" onClick={() => applySuggestion(s)}>
                              Voeg toe
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {activeFields.length > 0 && (
                  <div className="mon-form-grid">
                    {activeFields.map((f) => (
                      <Field
                        key={f.name}
                        field={f}
                        value={tValues[f.name]}
                        onChange={(v) => setTValues((vals) => ({ ...vals, [f.name]: v }))}
                      />
                    ))}
                  </div>
                )}

                <div className="mon-form-actions">
                  <button type="button" className="gx-cta" disabled={busy} onClick={submitTarget}>
                    Target opslaan
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => { resetForm(); setShowForm(false); }}>
                    Annuleren
                  </button>
                </div>
              </div>
            )}

            {targets.length === 0 && !loading ? (
              <p className="muted">Geen targets.</p>
            ) : (
              grouped.map((g) => (
                <div key={g.env} className="mon-envgroup">
                  <div className="mon-envhead">{ENV_LABEL[g.env]}</div>
                  <table className="mon-table">
                    <thead>
                      <tr>
                        <th>Naam</th><th>Type</th><th>Status</th>
                        <th>Aan</th><th>Alert</th><th></th><th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.rows.map((t) => {
                        const res = testResults[t.id];
                        return (
                          <tr key={t.id}>
                            <td>{t.name}</td>
                            <td className="mon-mono">{t.type}</td>
                            <td>
                              {res ? (
                                <span className={`mon-chip mon-chip--${String(res.status).toLowerCase()}`}>
                                  {res.status}{res.latency_ms != null ? ` · ${res.latency_ms}ms` : ""}
                                </span>
                              ) : <span className="muted">—</span>}
                            </td>
                            <td>
                              <Switch
                                checked={!!t.enabled}
                                disabled={busy}
                                label={`Enabled ${t.name}`}
                                onChange={(v) => patchTarget(t.id, { enabled: v ? 1 : 0 })}
                              />
                            </td>
                            <td>
                              <Switch
                                checked={!!t.alert_enabled}
                                disabled={busy}
                                label={`Alert ${t.name}`}
                                onChange={(v) => patchTarget(t.id, { alert_enabled: v ? 1 : 0 })}
                              />
                            </td>
                            <td>
                              <button type="button" className="btn btn--ghost" onClick={() => runTest(t)}>
                                Test
                              </button>
                            </td>
                            <td>
                              <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => removeTarget(t.id)}>
                                Verwijder
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))
            )}
          </section>
        </div>
      </div>
    </>
  );
}
