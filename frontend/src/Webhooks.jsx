import { useEffect, useState, useCallback } from "react";
import TopNav from "./Nav";
import {
  fetchWebhooks, createWebhook, updateWebhook, deleteWebhook, activateWebhook, testWebhook,
} from "./api";

// Beheer → Webhooks (Mattermost). Super-admin surface to keep several Mattermost
// incoming-webhook URLs side by side (ACC / TST / PROD) and switch the ACTIVE
// one — the one alerts post to — in one click, instead of editing .env and
// redeploying. Full URLs are never shown (masked); "Test" posts a real message.

const URL_RE = /^https?:\/\/\S+$/i;
const PRESETS = ["PROD", "ACC", "TST"];

function fmtTs(ts) {
  if (!ts) return "";
  return String(ts).replace("T", " ").replace(/\.\d+/, "").replace(/(\+00:00|Z)$/, " UTC");
}

export default function WebhooksPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = true, stuckCount, aanleverCount, dlqCount,
}) {
  const [items, setItems] = useState([]);
  const [fallback, setFallback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tests, setTests] = useState({});      // id -> {ok, status, error, pending}
  const [editId, setEditId] = useState(null);   // id being edited, or null = add form
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await fetchWebhooks(token);
      setItems(data.webhooks || []);
      setFallback(!!data.fallback_configured);
    } catch (e) {
      setError(e.message || "Laden mislukt");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const resetForm = () => { setEditId(null); setLabel(""); setUrl(""); };

  const startEdit = (w) => {
    setEditId(w.id); setLabel(w.label); setUrl("");  // url blank = keep existing
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const urlValid = url === "" ? editId != null : URL_RE.test(url.trim());
  const canSubmit = label.trim().length > 0 && urlValid && !busy;

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true); setError(null);
    try {
      if (editId != null) {
        const body = { label: label.trim() };
        if (url.trim()) body.url = url.trim();
        await updateWebhook(token, editId, body);
      } else {
        await createWebhook(token, { label: label.trim(), url: url.trim() });
      }
      resetForm();
      await load();
    } catch (e2) {
      setError(e2.message || "Opslaan mislukt");
    } finally {
      setBusy(false);
    }
  };

  const doActivate = async (id) => {
    setBusy(true); setError(null);
    try { await activateWebhook(token, id); await load(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const doDelete = async (w) => {
    if (!window.confirm(`Webhook "${w.label}" verwijderen?`)) return;
    setBusy(true); setError(null);
    try { await deleteWebhook(token, w.id); if (editId === w.id) resetForm(); await load(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const doTest = async (id) => {
    setTests((t) => ({ ...t, [id]: { pending: true } }));
    try {
      const r = await testWebhook(token, id);
      setTests((t) => ({ ...t, [id]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [id]: { ok: false, error: e.message } }));
    }
  };

  const active = items.find((w) => w.active);

  return (
    <>
      <TopNav
        active="admin" brandMark="🔗" brandName="Webhooks"
        brandSub="Beheer · Mattermost webhooks"
        can={can} isAdmin={isAdmin} username={username}
        onLogout={onLogout} onNavigate={onNavigate}
        llmProvider={llmProvider} onProviderChange={onProviderChange}
        stuckCount={stuckCount} aanleverCount={aanleverCount} dlqCount={dlqCount}
      />

      <div className="chat-scroll">
        <div className="dash">
          <section className="panel">
            <div>
              <span className="page-eyebrow gx-eyebrow">Beheer</span>
              <h2 className="gx-h2">Mattermost webhooks</h2>
            </div>
            <p className="muted set-intro">
              Beheer je Mattermost-webhooks (bijv. <strong>ACC</strong>, <strong>TST</strong>,{" "}
              <strong>PROD</strong>) op één plek. Meldingen gaan naar de <strong>actieve</strong>{" "}
              webhook — wissel met één klik, zonder de app opnieuw te hoeven uitrollen. Volledige
              URL's worden nooit getoond (alleen de laatste tekens), en met <strong>Test</strong>{" "}
              stuur je een echt proefbericht.
            </p>

            {/* Actieve webhook / fallback status */}
            <div className={`wh-banner wh-banner--${active ? "ok" : fallback ? "warn" : "crit"}`}>
              {active ? (
                <span>Actief: <strong>{active.label}</strong> — <code>{active.url}</code></span>
              ) : fallback ? (
                <span>Geen beheerde webhook actief — meldingen gebruiken de{" "}
                  <code>DIGEST_WEBHOOK_URL</code> uit <code>.env</code> (fallback).</span>
              ) : (
                <span>Geen webhook actief én geen <code>.env</code>-fallback — er worden{" "}
                  <strong>geen</strong> Mattermost-meldingen verstuurd.</span>
              )}
            </div>

            {error && <div className="wh-banner wh-banner--crit">{error}</div>}

            {/* Toevoegen / bewerken */}
            <form className="wh-form" onSubmit={submit}>
              <h3 className="gx-h3">{editId != null ? "Webhook bewerken" : "Webhook toevoegen"}</h3>
              <div className="wh-row">
                <label className="wh-field">
                  <span className="wh-flabel">Naam / omgeving</span>
                  <input className="wh-input" value={label} maxLength={40}
                         placeholder="PROD" onChange={(e) => setLabel(e.target.value)} />
                  <span className="wh-presets">
                    {PRESETS.map((p) => (
                      <button type="button" key={p} className="wh-chip" onClick={() => setLabel(p)}>{p}</button>
                    ))}
                  </span>
                </label>
                <label className="wh-field wh-grow">
                  <span className="wh-flabel">
                    Webhook-URL {editId != null && <em className="muted">(leeg = ongewijzigd laten)</em>}
                  </span>
                  <input className="wh-input" value={url} type="url"
                         placeholder="https://mattermost…/hooks/xxxxxxxxxxxxxxxxx"
                         onChange={(e) => setUrl(e.target.value)} />
                  {url && !urlValid && <span className="wh-err">Voer een geldige http(s)-URL in.</span>}
                </label>
              </div>
              <div className="wh-actions">
                <button type="submit" className="btn btn--primary" disabled={!canSubmit}>
                  {editId != null ? "Opslaan" : "Toevoegen"}
                </button>
                {editId != null && (
                  <button type="button" className="btn btn--ghost" onClick={resetForm} disabled={busy}>
                    Annuleren
                  </button>
                )}
              </div>
            </form>

            {/* Lijst */}
            {loading ? (
              <p className="muted">Laden…</p>
            ) : items.length === 0 ? (
              <p className="muted">Nog geen webhooks. Voeg er hierboven één toe — de eerste wordt
                automatisch actief.</p>
            ) : (
              <table className="dash-table wh-table">
                <thead>
                  <tr><th>Naam</th><th>URL (gemaskeerd)</th><th>Status</th><th>Gewijzigd</th><th></th></tr>
                </thead>
                <tbody>
                  {items.map((w) => {
                    const t = tests[w.id];
                    return (
                      <tr key={w.id} className={w.active ? "wh-active" : ""}>
                        <td><strong>{w.label}</strong></td>
                        <td><code className="wh-url">{w.url}</code></td>
                        <td>
                          {w.active
                            ? <span className="wh-badge">ACTIEF</span>
                            : <button className="wh-btn" onClick={() => doActivate(w.id)} disabled={busy}>
                                Activeer
                              </button>}
                        </td>
                        <td className="muted wh-ts">
                          {fmtTs(w.updated_at)}{w.updated_by ? ` · ${w.updated_by}` : ""}
                        </td>
                        <td className="wh-rowactions">
                          <button className="wh-btn" onClick={() => doTest(w.id)} disabled={t?.pending}>
                            {t?.pending ? "Testen…" : "Test"}
                          </button>
                          <button className="wh-btn" onClick={() => startEdit(w)} disabled={busy}>Bewerk</button>
                          <button className="wh-btn wh-btn--danger" onClick={() => doDelete(w)} disabled={busy}>
                            Verwijder
                          </button>
                          {t && !t.pending && (
                            <span className={`wh-test ${t.ok ? "ok" : "bad"}`}>
                              {t.ok ? `✓ verstuurd (${t.status})` : `✗ ${t.error || t.status || "mislukt"}`}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
