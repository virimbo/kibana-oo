import TopNav from "./Nav";

// Admin landing hub ("Beheer"). A single entry point that gathers every
// management surface as a card, so the admin tools have one clear home and the
// list can grow without cluttering the header nav.
const CARDS = [
  {
    view: "settings",
    icon: "⚙",
    title: "Instellingen",
    subtitle: "Instellingen",
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
    subtitle: "Documenten",
    desc: "Documenten traceren (OVS/NVS), zoeken en vastgelopen publicaties opsporen.",
  },
  {
    view: "regression",
    icon: "🧪",
    title: "Regressietest",
    subtitle: "Regressietest",
    desc: "Na een release: controleer of open.overheid.nl nog werkt — beschikbaarheid, journeys, API en TLS.",
  },
  {
    view: "alerts",
    icon: "🔔",
    title: "Alerting",
    subtitle: "Alerting",
    desc: "E-mailmeldingen bij RED-status (omgevingen, DLQ, certificaten): aan/uit per kaart, ontvangers, cooldown en geschiedenis.",
  },
];

// Super-admin-only cards.
const SUPER_CARDS = [
  {
    view: "authorization",
    icon: "🔐",
    title: "Autorisatie",
    subtitle: "Autorisatie",
    desc: "Beheer wie toegang heeft tot welke kaarten en tools (gebruiker × functie-matrix).",
  },
  {
    view: "monitoring",
    icon: "📡",
    title: "Monitoring-config",
    subtitle: "Monitoring",
    desc: "Monitoring-targets en connections (Prometheus/Jaeger) beheren — secrets staan in .env.",
  },
  {
    view: "compliance",
    icon: "⚖️",
    title: "Compliance & Beveiliging",
    subtitle: "EU AI Act & security",
    desc: "Eerlijke inschatting: EU AI Act-risicoklasse (beperkt risico), transparantie, en de uitkomst van de security-check — met aandachtspunten.",
  },
];

export default function AdminPage({
  username,
  onLogout,
  onNavigate,
  llmProvider,
  onProviderChange,
  can = () => true,
  isSuper = false,
  isAdmin = true,
  stuckCount, aanleverCount, dlqCount,
}) {
  // Show only the cards this admin may use; super admin also gets Autorisatie.
  const cards = CARDS.filter((c) => can(c.view));
  if (isSuper) cards.push(...SUPER_CARDS);
  return (
    <>
      <TopNav
        active="admin"
        brandMark="🛠"
        brandName="Beheer"
        brandSub="Admin · beheer & instellingen"
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
          <section className="panel">
            <div>
              <span className="page-eyebrow gx-eyebrow">Beheer</span>
              <h2 className="gx-h2">Beheercentrum</h2>
            </div>
            <p className="muted set-intro">
              Beheercentrum (admin). Kies een onderdeel om te beheren.
            </p>

            <div className="admin-grid">
              {cards.map((c) => (
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
