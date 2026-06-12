import ProviderSwitcher from "./ProviderSwitcher";
import StuckBadge from "./StuckBadge";

// Admin landing hub ("Beheer"). A single entry point that gathers every
// management surface as a card, so the admin tools have one clear home and the
// list can grow without cluttering the header nav.
const CARDS = [
  {
    view: "settings",
    icon: "⚙",
    title: "Instellingen",
    subtitle: "Settings",
    desc: "AI-assistent aan/uit, model kiezen (Ollama / Mistral) en chat-functies beheren.",
  },
  {
    view: "dashboard",
    icon: "📊",
    title: "Monitoring",
    subtitle: "Dashboard",
    desc: "Kritieke issues, certificaat- & TLS-status en pipeline-uitkomsten in één oogopslag.",
  },
  {
    view: "documents",
    icon: "📄",
    title: "Documenten",
    subtitle: "Documents",
    desc: "Documenten traceren (OVS/NVS), zoeken en vastgelopen publicaties opsporen.",
  },
];

export default function AdminPage({
  username,
  onLogout,
  onNavigate,
  llmProvider,
  onProviderChange,
  stuckCount,
}) {
  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">🛠</span>
          <div className="brand-text">
            <span className="brand-name">Beheer</span>
            <span className="brand-sub">Admin · beheer &amp; instellingen</span>
          </div>
        </div>
        <div className="header-right">
          <StuckBadge count={stuckCount} onNavigate={onNavigate} />
          <ProviderSwitcher value={llmProvider} onChange={onProviderChange} />
          <button className="btn btn--ghost" onClick={() => onNavigate("chat")}>Chat</button>
          <button className="btn btn--ghost" onClick={() => onNavigate("dashboard")}>Dashboard</button>
          <button className="btn btn--ghost" onClick={() => onNavigate("documents")}>Documents</button>
          <span className="header-user">{username}</span>
          <button className="btn btn--ghost" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <div className="chat-scroll">
        <div className="dash">
          <section className="panel">
            <h3>🛠 Beheer</h3>
            <p className="muted set-intro">
              Beheercentrum (admin). Kies een onderdeel om te beheren.
            </p>

            <div className="admin-grid">
              {CARDS.map((c) => (
                <button
                  key={c.view}
                  type="button"
                  className="admin-card"
                  onClick={() => onNavigate(c.view)}
                >
                  <span className="admin-card-icon" aria-hidden="true">{c.icon}</span>
                  <span className="admin-card-title">
                    {c.title} <em>{c.subtitle}</em>
                  </span>
                  <span className="admin-card-desc">{c.desc}</span>
                  <span className="admin-card-go" aria-hidden="true">→</span>
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
