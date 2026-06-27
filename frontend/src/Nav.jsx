import ProviderSwitcher from "./ProviderSwitcher";
import AanleverBadge from "./AanleverBadge";
import DlqBadge from "./DlqBadge";

// ─── Shared top navigation ───────────────────────────────────────────────────
// One elegant, permission-aware bar used by every page. Replaces the per-page
// headers that had drifted apart (different items, order and gating). Benefits:
//   • Consistent everywhere — the menu never moves between pages.
//   • Shows where you are — the active destination is highlighted (and Beheer
//     sub-pages light up "Beheer" so you never feel lost).
//   • Deny-by-default — a destination only appears if can()/isAdmin allows it.

const NavIcon = {
  chat: (p) => (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  dashboard: (p) => (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  ),
  documents: (p) => (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M8 13h8M8 17h8" />
    </svg>
  ),
  admin: (p) => (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <line x1="4" y1="21" x2="4" y2="14" />
      <line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" />
      <line x1="20" y1="12" x2="20" y2="3" />
      <line x1="1" y1="14" x2="7" y2="14" />
      <line x1="9" y1="8" x2="15" y2="8" />
      <line x1="17" y1="16" x2="23" y2="16" />
    </svg>
  ),
};

const PRIMARY = [
  { view: "chat", label: "Chat" },
  { view: "dashboard", label: "Dashboard", feature: "dashboard" },
  { view: "documents", label: "Documenten", feature: "documents" },
  { view: "admin", label: "Beheer", adminOnly: true },
];

// Sub-pages reached from the Beheer hub keep "Beheer" lit as the active section.
const BEHEER_SUB = new Set(["admin", "settings", "regression", "authorization", "alerts", "dlq-intel", "monitoring"]);

function initials(name) {
  const parts = (name || "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name || "?").slice(0, 2).toUpperCase();
}

export default function TopNav({
  active,
  brandMark,
  brandName,
  brandSub,
  can = () => true,
  isAdmin = false,
  username,
  onLogout,
  onNavigate,
  llmProvider,
  onProviderChange,
  aanleverCount,
  dlqCount,
  status, // optional { tone, label } — used by Chat for the connection pill
}) {
  const activeTop = BEHEER_SUB.has(active) ? "admin" : active;
  const items = PRIMARY.filter((i) =>
    i.adminOnly ? isAdmin : i.feature ? can(i.feature) : true
  );

  return (
    <header className="header">
      <button
        type="button"
        className="brand brand--btn"
        onClick={() => onNavigate("chat")}
        title="Open Overheid - Monitoring — naar Chat"
      >
        <span className="brand-mark">{brandMark}</span>
        <div className="brand-text">
          <span className="brand-name">{brandName}</span>
          {brandSub && <span className="brand-sub">{brandSub}</span>}
        </div>
      </button>

      <nav className="topnav" aria-label="Primary">
        {items.map((i) => {
          const Ico = NavIcon[i.view];
          const isActive = activeTop === i.view;
          return (
            <button
              key={i.view}
              type="button"
              className={`topnav-link${isActive ? " is-active" : ""}`}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onNavigate(i.view)}
            >
              {Ico && <Ico />}
              <span>{i.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="header-right">
        {status && (
          <span className={`status status--${status.tone}`}>
            <span className="status-dot" />
            {status.label}
          </span>
        )}
        <DlqBadge count={dlqCount} onNavigate={onNavigate} />
        <AanleverBadge count={aanleverCount} onNavigate={onNavigate} />
        {onProviderChange && (
          <ProviderSwitcher value={llmProvider} onChange={onProviderChange} />
        )}
        <div className="user-chip" title={username}>
          <span className="user-avatar" aria-hidden="true">{initials(username)}</span>
          <span className="user-name">{username}</span>
        </div>
        <button className="btn btn--ghost" onClick={onLogout}>
          Afmelden
        </button>
      </div>
    </header>
  );
}
