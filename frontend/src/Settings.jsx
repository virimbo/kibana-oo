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
    hint: "Runs on your own infrastructure — private, no data leaves the network.",
  },
  {
    value: "mistral",
    name: "Mistral",
    kind: "cloud",
    hint: "Hosted Mistral API — needs MISTRAL_API_KEY and sends prompts off-site.",
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
    { key: "uptime", label: "Beschikbaarheid (environment status)", hint: "The PROD/ACC/TEST up/down board at the top." },
    { key: "infra", label: "Infrastructuur (Grafana)", hint: "The Grafana deep-link card(s)." },
    { key: "hero", label: "Overzichtstegels (hero)", hint: "The big stat tiles: Critical, Criticals, Docs at risk, Aanleverfouten, DLQ." },
    { key: "certs", label: "Certificaten & TLS", hint: "The certificate-expiry / TLS-health cards." },
    { key: "dlq", label: "Dead-letter queues", hint: "The RabbitMQ DLQ queue cards." },
    { key: "aanlever", label: "Aanleverfouten", hint: "The delivery-rejection card." },
  ];

  return (
    <>
      <TopNav
        active="settings"
        brandMark="⚙"
        brandName="Settings"
        brandSub="AI & feature toggles · admin"
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
          {/* ── AI model management ─────────────────────────────── */}
          <section className="panel set-panel">
            <h3>🤖 AI assistant</h3>
            <p className="muted set-intro">
              Turn the AI on or off, or choose which model answers. When off, the
              dashboard, chat and document analysis fall back to deterministic,
              data-only views — nothing is sent to any model.
            </p>

            <Toggle
              checked={aiEnabled}
              onChange={setAiEnabled}
              label="Enable AI assistant"
              hint="Master switch. Off = no AI commentary anywhere; all monitoring still works."
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
                  AI is switched off — enable it above to pick a model.
                </p>
              )}
            </div>
          </section>

          {/* ── Chat experience ─────────────────────────────────── */}
          <section className="panel set-panel">
            <h3>Chat experience</h3>
            <p className="muted set-intro">
              Toggle features on or off. Changes apply immediately and are remembered for this session.
            </p>

            <Toggle
              checked={autocorrect}
              onChange={setAutocorrect}
              disabled={!aiEnabled}
              label="Auto-correct questions"
              hint="Fix spelling & grammar before sending. IDs, codes and numbers are preserved. Needs AI."
            />
            <Toggle
              checked={showSuggestions}
              onChange={setShowSuggestions}
              label="Show quick questions"
              hint="One-click starter questions (recent errors, latency, summary…) on an empty chat."
            />
            <Toggle
              checked={showWelcome}
              onChange={setShowWelcome}
              label="Show welcome screen"
              hint="The intro title, description and AI disclosure on an empty chat."
            />
            <Toggle
              checked={showHint}
              onChange={setShowHint}
              label="Show composer hint"
              hint="The 'Querying logs-* …' line under the message box."
            />
          </section>

          {/* ── Dashboard experience ────────────────────────────── */}
          <section className="panel set-panel">
            <h3>Dashboard experience</h3>
            <p className="muted set-intro">
              Toggle dashboard features on or off. Changes apply immediately and are remembered for this session.
            </p>

            <Toggle
              checked={showCardDetails}
              onChange={setShowCardDetails}
              label="Show card detail panel (hover)"
              hint="The right-side panel that appears when you hover a dashboard card — component info, runbook 'WAT TE DOEN NU', vault TODOs and AI analysis. Off = no hover panel."
            />

            <div className="set-subhead">Sections — show or hide whole blocks</div>
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
