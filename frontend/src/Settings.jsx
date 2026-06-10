import ProviderSwitcher from "./ProviderSwitcher";
import StuckBadge from "./StuckBadge";

// A reusable on/off switch.
function Toggle({ checked, onChange, label, hint }) {
  return (
    <div className="set-row">
      <div className="set-row-text">
        <span className="set-row-label">{label}</span>
        {hint && <span className="set-row-hint">{hint}</span>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={`switch${checked ? " is-on" : ""}`}
        onClick={() => onChange(!checked)}
        aria-label={label}
      >
        <span className="switch-knob" />
      </button>
    </div>
  );
}

// Admin Settings tab — feature toggles for the chat experience.
export default function SettingsPage({ username, onLogout, onNavigate, llmProvider, onProviderChange, settings, stuckCount }) {
  const {
    autocorrect, setAutocorrect,
    showWelcome, setShowWelcome,
    showHint, setShowHint,
    showSuggestions, setShowSuggestions,
  } = settings;

  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">⚙</span>
          <div className="brand-text">
            <span className="brand-name">Settings</span>
            <span className="brand-sub">Feature toggles · admin</span>
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
          <section className="panel set-panel">
            <h3>Chat experience</h3>
            <p className="muted set-intro">
              Toggle features on or off. Changes apply immediately and are remembered for this session.
            </p>

            <Toggle
              checked={autocorrect}
              onChange={setAutocorrect}
              label="Auto-correct questions"
              hint="Fix spelling & grammar before sending. IDs, codes and numbers are preserved."
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
        </div>
      </div>
    </>
  );
}
