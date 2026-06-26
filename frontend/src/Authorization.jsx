import { useState, useEffect, useCallback } from "react";
import { getJSON } from "./api";
import TopNav from "./Nav";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("nl-NL") : "");

// Super-admin-only: the user × feature authorisation matrix. Check a box to grant
// a user access to a card/tool; uncheck to revoke. Add users by email to
// pre-authorise them before their first login.
export default function AuthorizationPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange, can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [data, setData] = useState(null);     // { catalog, users, super_admins }
  const [extra, setExtra] = useState([]);     // emails added locally, no grants yet
  const [audit, setAudit] = useState([]);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await getJSON("/admin/grants", token);
      setData(d);
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    }
  }, [token, onLogout]);

  const loadAudit = useCallback(async () => {
    try {
      const d = await getJSON("/admin/grants/audit", token);
      setAudit(d.audit || []);
    } catch { /* non-fatal */ }
  }, [token]);

  useEffect(() => { load(); loadAudit(); }, [load, loadAudit]);

  const toggle = useCallback(async (user, feature, on) => {
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${BACKEND_URL}/admin/grants`, {
        method: on ? "POST" : "DELETE",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, feature }),
      });
      if (r.status === 401) return onLogout();
      if (!r.ok) throw new Error("update failed");
      await load();
      loadAudit();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [token, onLogout, load, loadAudit]);

  const addUser = () => {
    const e = email.trim().toLowerCase();
    if (!EMAIL_RE.test(e)) { setError("Enter a valid email address."); return; }
    const known = (data?.users || []).some((u) => u.username === e) || extra.includes(e);
    if (!known) setExtra((x) => [...x, e]);
    setEmail("");
    setError("");
  };

  if (!data) {
    return <Shell {...{ username, onLogout, onNavigate, llmProvider, onProviderChange, can, isAdmin, stuckCount, aanleverCount, dlqCount }}>
      <p className="muted">Laden…</p>
    </Shell>;
  }

  const rows = [
    ...data.users,
    ...extra.filter((e) => !data.users.some((u) => u.username === e)).map((e) => ({ username: e, features: [] })),
  ];

  return (
    <Shell {...{ username, onLogout, onNavigate, llmProvider, onProviderChange, can, isAdmin, stuckCount, aanleverCount, dlqCount }}>
      <section className="page-hero gx-pagehead">
        <div className="page-hero-main">
          <span className="page-eyebrow gx-eyebrow">BEHEER · AUTORISATIE</span>
          <h1 className="page-hero-h1 gx-h1">AUTORISATIE</h1>
        </div>
      </section>

      <section className="panel gx-panel">
        <h3 className="gx-h2">🔐 Autorisatie — wie mag wat</h3>
        <p className="muted set-intro">
          Vink een vakje aan om een gebruiker toegang te geven tot een kaart/tool; uitvinken om in te trekken.
          Nieuwe gebruikers staan standaard op <b>geen toegang</b> (behalve chat). Wijzigingen zijn direct actief.
        </p>

        {error && <div className="alert alert--error">{error}</div>}

        <div className="authz-add">
          <input
            type="email" placeholder="naam@organisatie.nl" value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addUser()}
          />
          <button type="button" className="btn btn--ghost" onClick={addUser}>+ Gebruiker toevoegen</button>
        </div>

        <div className="authz-scroll">
          <table className="authz-matrix">
            <thead>
              <tr>
                <th className="authz-user-h">Gebruiker</th>
                {data.catalog.map((f) => (
                  <th key={f.key} title={f.label}><span>{f.label}</span></th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.super_admins.map((s) => (
                <tr key={s} className="authz-super">
                  <td className="authz-user">{s} <span className="authz-tag">super</span></td>
                  {data.catalog.map((f) => (
                    <td key={f.key} className="authz-cell"><span title="Super admin heeft alle toegang">✓</span></td>
                  ))}
                </tr>
              ))}
              {rows.map((u) => (
                <tr key={u.username}>
                  <td className="authz-user">{u.username}</td>
                  {data.catalog.map((f) => {
                    const on = u.features.includes(f.key);
                    return (
                      <td key={f.key} className="authz-cell">
                        <input
                          type="checkbox" checked={on} disabled={busy}
                          onChange={(e) => toggle(u.username, f.key, e.target.checked)}
                          aria-label={`${f.label} voor ${u.username}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={data.catalog.length + 1} className="muted">Nog geen gebruikers — voeg er een toe via e-mail.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {audit.length > 0 && (
        <section className="panel gx-panel">
          <h3 className="gx-h2">Wijzigingslog</h3>
          <ul className="authz-audit">
            {audit.slice(0, 25).map((a, i) => (
              <li key={i}>
                <span className="authz-audit-when">{fmtWhen(a.ts)}</span>
                <span className={`authz-audit-act authz-audit-act--${a.action}`}>{a.action}</span>
                <span>{a.feature} → <b>{a.target_user}</b></span>
                <span className="muted">door {a.actor}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Shell>
  );
}

function Shell({ username, onLogout, onNavigate, llmProvider, onProviderChange, can, isAdmin, stuckCount, aanleverCount, dlqCount, children }) {
  return (
    <>
      <TopNav
        active="authorization"
        brandMark="🔐"
        brandName="Autorisatie"
        brandSub="Super admin · toegang per gebruiker & functie"
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
      <div className="chat-scroll"><div className="dash">{children}</div></div>
    </>
  );
}
