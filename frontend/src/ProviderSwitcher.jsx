// A colour-coded pill shown in every page header so the active AI model is
// always visible (and switchable). Ollama = emerald, Mistral = amber — the
// whole header is themed to match via the `data-provider` attribute on :root
// (set by App). Lives in its own module so every page can import it without a
// circular dependency on App.
export default function ProviderSwitcher({ value, onChange, disabled = false }) {
  const name = value === "mistral" ? "Mistral" : "Ollama";
  const kind = value === "mistral" ? "cloud" : "local";
  return (
    <label
      className="provider-switch"
      data-provider={value}
      title="AI model — applies to chat, dashboard triage and document analysis"
    >
      <span className="provider-switch-dot" aria-hidden="true" />
      <span className="provider-switch-text">
        <span className="provider-switch-kicker">AI model</span>
        <span className="provider-switch-name">
          {name} <em>{kind}</em>
        </span>
      </span>
      <svg className="provider-switch-caret" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label="AI model provider"
      >
        <option value="ollama">Ollama (local)</option>
        <option value="mistral">Mistral (cloud)</option>
      </select>
    </label>
  );
}
