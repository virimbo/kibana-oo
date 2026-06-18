import TopNav from "./Nav";

// A reusable on/off switch.
function Toggle({ checked, onChange, label, hint, disabled = false }) {
  return (
    <div className={`set-row${disabled ? " set-row--disabled" : ""}`}>
      <div className="set-row-text">
        <span className="set-row-label">{label}</span>
        {hint && <span className="set-row-hint">{hint}</span>}
      </div>
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
    </div>
  );
}

// The AI providers the operator can choose between (excluding the "off" state,
// which is the master toggle).
const PROVIDERS = [
  {
    value: "ollama",
    name: "Ollama",
    kind: "local",
    hint: "Draait op je eigen infrastructuur — privé, er verlaat geen data het netwerk.",
  },
  {
    value: "mistral",
    name: "Mistral",
    kind: "cloud",
    hint: "Gehoste Mistral API — vereist MISTRAL_API_KEY en stuurt prompts naar buiten.",
  },
];

// Admin Settings tab — AI model management + feature toggles for the chat experience.
export default function SettingsPage({
  username,
  onLogout,
  onNavigate,
  llmProvider,
  selectedProvider,
  onProviderChange,
  settings,
  can = () => true,
  isAdmin = false,
  stuckCount, aanleverCount, dlqCount,
}) {
  const {
    aiEnabled, setAiEnabled,
    autocorrect, setAutocorrect,
    showWelcome, setShowWelcome,
    showHint, setShowHint,
    showSuggestions, setShowSuggestions,
    showCardDetails, setShowCardDetails,
    dashSections = {}, setDashSection = () => {},
  } = settings;

  // Dashboard blocks the admin can show/hide (all default on).
  const DASH_SECTIONS = [
    { key: "uptime", label: "Beschikbaarheid (environment status)", hint: "Het PROD/ACC/TEST up/down-overzicht bovenaan." },
    { key: "infra", label: "Infrastructuur (Grafana)", hint: "De Grafana deep-link-card(s)." },
    { key: "hero", label: "Overzichtstegels (hero)", hint: "De grote stat-tegels: Critical, Criticals, Docs at risk, Aanleverfouten, DLQ." },
    { key: "certs", label: "Certificaten & TLS", hint: "De cards voor certificaatvervaldatum / TLS-status." },
    { key: "dlq", label: "Dead-letter queues", hint: "De RabbitMQ DLQ queue-cards." },
    { key: "aanlever", label: "Aanleverfouten", hint: "De card voor afgewezen aanleveringen." },
  ];

  return (
    <>
      <TopNav
        active="settings"
        brandMark="⚙"
        brandName="Settings"
        brandSub="AI- & functie-toggles · admin"
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
          {/* ── Command-center hero ───────────────────────────── */}
          <section className="page-hero">
            <div className="page-hero-main">
              <span className="page-eyebrow">Beheer · Instellingen</span>
              <h1 className="page-hero-h1">⚙ Instellingen</h1>
              <p className="page-hero-lead">
                AI-assistent, chatfuncties en dashboard-indeling beheren.
                Wijzigingen worden direct toegepast en onthouden voor deze sessie.
              </p>
            </div>
          </section>

          {/* ── AI model management ─────────────────────────────── */}
          <section className="panel set-panel">
            <span className="page-eyebrow">Model & provider</span>
            <h3>🤖 AI-assistent</h3>
            <p className="muted set-intro">
              Zet de AI aan of uit, of kies welk model antwoordt. Als deze uit staat,
              vallen het dashboard, de chat en de documentanalyse terug op
              deterministische, data-only weergaven — er wordt niets naar een model gestuurd.
            </p>

            <Toggle
              checked={aiEnabled}
              onChange={setAiEnabled}
              label="AI-assistent inschakelen"
              hint="Hoofdschakelaar. Uit = nergens AI-commentaar; alle monitoring blijft werken."
            />

            <div className={`set-providers${aiEnabled ? "" : " set-providers--off"}`}>
              <span className="set-providers-label">Model provider</span>
              <div className="set-provider-grid" role="radiogroup" aria-label="AI model provider">
                {PROVIDERS.map((p) => {
                  const active = aiEnabled && selectedProvider === p.value;
                  return (
                    <button
                      key={p.value}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      disabled={!aiEnabled}
                      className={`set-provider-card${active ? " is-active" : ""}`}
                      data-provider={p.value}
                      onClick={() => onProviderChange(p.value)}
                    >
                      <span className="set-provider-dot" aria-hidden="true" />
                      <span className="set-provider-name">
                        {p.name} <em>{p.kind}</em>
                      </span>
                      <span className="set-provider-hint">{p.hint}</span>
                    </button>
                  );
                })}
              </div>
              {!aiEnabled && (
                <p className="muted set-providers-note">
                  AI staat uit — schakel deze hierboven in om een model te kiezen.
                </p>
              )}
            </div>
          </section>

          {/* ── Chat experience ─────────────────────────────────── */}
          <section className="panel set-panel">
            <span className="page-eyebrow">Gespreksinstellingen</span>
            <h3>Chatfuncties</h3>
            <p className="muted set-intro">
              Functies aan- of uitzetten. Wijzigingen worden direct toegepast en onthouden voor deze sessie.
            </p>

            <Toggle
              checked={autocorrect}
              onChange={setAutocorrect}
              disabled={!aiEnabled}
              label="Vragen automatisch corrigeren"
              hint="Corrigeert spelling & grammatica voor het versturen. IDs, codes en getallen blijven behouden. Vereist AI."
            />
            <Toggle
              checked={showSuggestions}
              onChange={setShowSuggestions}
              label="Snelle vragen tonen"
              hint="Startvragen met één klik (recente errors, latency, samenvatting…) in een lege chat."
            />
            <Toggle
              checked={showWelcome}
              onChange={setShowWelcome}
              label="Welkomstscherm tonen"
              hint="De introtitel, beschrijving en AI-disclosure in een lege chat."
            />
            <Toggle
              checked={showHint}
              onChange={setShowHint}
              label="Composer-hint tonen"
              hint="De regel 'Querying logs-* …' onder het berichtenvak."
            />
          </section>

          {/* ── Dashboard experience ────────────────────────────── */}
          <section className="panel set-panel">
            <span className="page-eyebrow">Dashboard-indeling</span>
            <h3>Dashboard-weergave</h3>
            <p className="muted set-intro">
              Dashboard-functies aan- of uitzetten. Wijzigingen worden direct toegepast en onthouden voor deze sessie.
            </p>

            <Toggle
              checked={showCardDetails}
              onChange={setShowCardDetails}
              label="Card-detailpaneel tonen (hover)"
              hint="Het rechterpaneel dat verschijnt als je over een dashboard-card hovert — component-info, runbook 'WAT TE DOEN NU', vault-TODOs en AI-analyse. Uit = geen hover-paneel."
            />

            <div className="set-subhead">Secties — hele blokken tonen of verbergen</div>
            {DASH_SECTIONS.map((s) => (
              <Toggle
                key={s.key}
                checked={dashSections[s.key] !== false}
                onChange={(v) => setDashSection(s.key, v)}
                label={s.label}
                hint={s.hint}
              />
            ))}
          </section>
        </div>
      </div>
    </>
  );
}
