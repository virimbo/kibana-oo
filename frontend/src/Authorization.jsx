import { useState, useEffect, useCallback } from "react";
import { getJSON, fetchUsers, approveUser, suspendUser } from "./api";
import TopNav from "./Nav";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("nl-NL") : "");

// Status pill — reuse the alerts pill palette: approved→ok/green, pending→warn/amber,
// suspended→muted/grey. (super shown as a neutral muted pill, no toggle.)
const STATUS_PILL = {
  approved: { cls: "alerts-pill--ok", label: "Goedgekeurd" },
  pending: { cls: "alerts-pill--warn", label: "In afwachting" },
  suspended: { cls: "alerts-pill--muted", label: "Geblokkeerd" },
  super: { cls: "alerts-pill--muted", label: "Super admin" },
};
function StatusPill({ status }) {
  const p = STATUS_PILL[status] || STATUS_PILL.pending;
  return <span className={`alerts-pill ${p.cls}`}>{p.label}</span>;
}

// Reuses the shared .switch toggle (same markup as Alerts/Settings).
function Switch({ checked, onChange, disabled = false, label }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label}
            disabled={disabled} className={`switch${checked ? " is-on" : ""}`}
            onClick={() => !disabled && onChange(!checked)}>
      <span className="switch-knob" />
    </button>
  );
}

// Super-admin-only: the user × feature authorisation matrix. Check a box to grant
// a user access to a card/tool; uncheck to revoke. Add users by email to
// pre-authorise them before their first login.
export default function AuthorizationPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange, can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [data, setData] = useState(null);     // { catalog, users, super_admins }
  const [users, setUsers] = useState([]);     // approval registry: status per user
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

  const loadUsers = useCallback(async () => {
    try {
      const u = await fetchUsers(token);
      setUsers(Array.isArray(u) ? u : []);
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      /* non-fatal: approval registry is additive to the matrix */
    }
  }, [token, onLogout]);

  const loadAudit = useCallback(async () => {
    try {
      const d = await getJSON("/admin/grants/audit", token);
      setAudit(d.audit || []);
    } catch { /* non-fatal */ }
  }, [token]);

  useEffect(() => { load(); loadAudit(); loadUsers(); }, [load, loadAudit, loadUsers]);

  // Approve / suspend a user, then refetch both the registry and the matrix so
  // status pills, toggles and grants all stay consistent.
  const setApproval = useCallback(async (user, approve) => {
    setBusy(true);
    setError("");
    try {
      if (approve) await approveUser(token, user);
      else await suspendUser(token, user);
      await loadUsers();
      load();
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [token, onLogout, loadUsers, load]);

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
      loadUsers();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [token, onLogout, load, loadAudit, loadUsers]);

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

  const statusByUser = Object.fromEntries(users.map((u) => [u.username, u.status]));
  const statusOf = (name) => statusByUser[name] || "pending";
  const pendingUsers = users.filter((u) => u.status === "pending" && !u.is_super);

  return (
    <Shell {...{ username, onLogout, onNavigate, llmProvider, onProviderChange, can, isAdmin, stuckCount, aanleverCount, dlqCount }}>
      <section className="page-hero gx-pagehead">
        <div className="page-hero-main">
          <span className="page-eyebrow gx-eyebrow">BEHEER · AUTORISATIE</span>
          <h1 className="page-hero-h1 gx-h1">AUTORISATIE</h1>
        </div>
      </section>

      <section className="panel gx-panel">
        <h3 className="gx-h2">⏳ In afwachting van goedkeuring{pendingUsers.length > 0 ? ` (${pendingUsers.length})` : ""}</h3>
        <p className="muted set-intro">
          Nieuwe gebruikers die zich aanmelden hebben <b>geen toegang</b> totdat je ze hier goedkeurt.
        </p>
        {pendingUsers.length === 0 ? (
          <p className="muted">Geen gebruikers in afwachting.</p>
        ) : (
          <ul className="authz-pending">
            {pendingUsers.map((u) => (
              <li key={u.username} className="authz-pending-row">
                <span className="authz-pending-user">{u.username}</span>
                <span className="muted authz-pending-when">{fmtWhen(u.first_seen)}</span>
                <button type="button" className="gx-cta authz-approve" disabled={busy}
                        onClick={() => setApproval(u.username, true)}>Goedkeuren</button>
              </li>
            ))}
          </ul>
        )}
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
                <th className="authz-status-h">Status</th>
                {data.catalog.map((f) => (
                  <th key={f.key} title={f.label}><span>{f.label}</span></th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.super_admins.map((s) => (
                <tr key={s} className="authz-super">
                  <td className="authz-user">{s} <span className="authz-tag">super</span></td>
                  <td className="authz-cell authz-status"><StatusPill status="super" /></td>
                  {data.catalog.map((f) => (
                    <td key={f.key} className="authz-cell"><span title="Super admin heeft alle toegang">✓</span></td>
                  ))}
                </tr>
              ))}
              {rows.map((u) => (
                <tr key={u.username} className={statusOf(u.username) === "suspended" ? "authz-suspended" : ""}>
                  <td className="authz-user">{u.username}</td>
                  <td className="authz-cell authz-status">
                    <StatusPill status={statusOf(u.username)} />
                    <Switch checked={statusOf(u.username) === "approved"} disabled={busy}
                            label={`Toegang voor ${u.username}`}
                            onChange={(on) => setApproval(u.username, on)} />
                  </td>
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
                <tr><td colSpan={data.catalog.length + 2} className="muted">Nog geen gebruikers — voeg er een toe via e-mail.</td></tr>
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
