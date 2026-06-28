import { useState, useEffect } from "react";
import TopNav from "./Nav";
import { TIME_RANGES, FALLBACK_DATA_VIEWS } from "./scope";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

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
    defaultDataView, setDefaultDataView = () => {},
    defaultTimeRange, setDefaultTimeRange = () => {},
  } = settings;

  // Available data views for the default-scope picker — same source the chat
  // composer uses (/data-views); falls back to the static list when offline.
  const [scopeViews, setScopeViews] = useState(FALLBACK_DATA_VIEWS);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/data-views`);
        if (!res.ok) return;
        const data = await res.json();
        if (active && Array.isArray(data.data_views) && data.data_views.length) {
          setScopeViews(data.data_views);
        }
      } catch {
        /* keep the fallback list */
      }
    })();
    return () => { active = false; };
  }, []);

  // The active provider's metadata, for the at-a-glance "intelligent" status strip.
  const providerMeta = PROVIDERS.find((p) => p.value === selectedProvider) || PROVIDERS[0];
  const isLocal = providerMeta.kind === "local";

  // Dashboard blocks the admin can show/hide (all default on).
  const DASH_SECTIONS = [
    { key: "uptime", label: "Beschikbaarheid (environment status)", hint: "Het PROD/ACC/TEST up/down-overzicht bovenaan." },
    { key: "service_health", label: "Service health", hint: "De backend-microservices (Harvester, Antivirus, Repository, …) — werken de endpoints?" },
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
          <section className="page-hero gx-pagehead">
            <div className="page-hero-main">
              <span className="page-eyebrow gx-eyebrow">BEHEER · INSTELLINGEN</span>
              <h1 className="page-hero-h1 gx-h1">INSTELLINGEN</h1>
              <p className="page-hero-lead">
                AI-assistent, chatfuncties en dashboard-indeling beheren.
                Wijzigingen worden direct toegepast en onthouden voor deze sessie.
              </p>
            </div>
          </section>

          {/* ── AI model management ─────────────────────────────── */}
          <section className="panel set-panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Model & provider</span>
            <h3 className="gx-h2">🤖 AI-assistent</h3>
            <p className="muted set-intro">
              Zet de AI aan of uit, of kies welk model antwoordt. Als deze uit staat,
              vallen het dashboard, de chat en de documentanalyse terug op
              deterministische, data-only weergaven — er wordt niets naar een model gestuurd.
            </p>

            {/* At-a-glance status: which model answers, the privacy posture, and a
                context-aware advice line. Read-only summary of the choice below. */}
            <div className="set-ai-status" data-provider={aiEnabled ? selectedProvider : "none"}>
              <div className="set-ai-status-grid">
                <div className="set-ai-status-cell">
                  <span className="set-ai-status-key">Actief model</span>
                  <span className="set-ai-status-val">
                    <span className="set-ai-status-dot" aria-hidden="true" />
                    {aiEnabled ? <>{providerMeta.name} <em>{providerMeta.kind}</em></> : "AI uitgeschakeld"}
                  </span>
                </div>
                <div className="set-ai-status-cell">
                  <span className="set-ai-status-key">Privacy</span>
                  <span className="set-ai-status-val">
                    {!aiEnabled
                      ? "n.v.t. — geen model actief"
                      : isLocal
                      ? "Lokaal — geen data verlaat het netwerk"
                      : "Cloud — prompts gaan naar een externe API"}
                  </span>
                </div>
                <div className="set-ai-status-cell">
                  <span className="set-ai-status-key">Bereik</span>
                  <span className="set-ai-status-val">Chat · dashboard-triage · documentanalyse</span>
                </div>
              </div>
              <p className="set-ai-status-advice" data-tone={!aiEnabled ? "off" : isLocal ? "ok" : "warn"}>
                {!aiEnabled
                  ? "AI staat uit — alle monitoring blijft werken; alleen de AI-duiding ontbreekt."
                  : isLocal
                  ? "Privacyvriendelijke keuze: alle analyse blijft lokaal. Voor zwaardere modellen kun je Mistral (cloud) overwegen."
                  : "Let op: bij Mistral (cloud) verlaten loggegevens je netwerk. Voor gevoelige data is Ollama (lokaal) veiliger."}
              </p>
            </div>

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

          {/* ── Default chat scope ──────────────────────────────── */}
          <section className="panel set-panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Standaard zoekbereik</span>
            <h3 className="gx-h2">🔎 Chat-zoekbereik</h3>
            <p className="muted set-intro">
              Het standaard bereik waarmee elke nieuwe chat opent. Gebruikers kunnen
              dit per vraag nog aanpassen via de Dataweergave- en Tijdsbereik-keuzes
              onder het berichtenvak.
            </p>

            <div className="set-scope-grid">
              <label className="set-scope-field">
                <span className="set-row-label">Standaard dataweergave</span>
                <span className="set-row-hint">Welke Elasticsearch data view (index) standaard wordt doorzocht.</span>
                <select
                  className="control-select set-scope-select"
                  value={defaultDataView}
                  onChange={(e) => setDefaultDataView(e.target.value)}
                  aria-label="Standaard dataweergave"
                >
                  {scopeViews.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label && v.label !== v.id ? `${v.id} — ${v.label}` : v.id}
                    </option>
                  ))}
                </select>
              </label>

              <label className="set-scope-field">
                <span className="set-row-label">Standaard tijdsbereik</span>
                <span className="set-row-hint">Het tijdvenster waarover een nieuwe chat begint te zoeken.</span>
                <select
                  className="control-select set-scope-select"
                  value={defaultTimeRange}
                  onChange={(e) => setDefaultTimeRange(Number(e.target.value))}
                  aria-label="Standaard tijdsbereik"
                >
                  {TIME_RANGES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          {/* ── Chat experience ─────────────────────────────────── */}
          <section className="panel set-panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Gespreksinstellingen</span>
            <h3 className="gx-h2">Chatfuncties</h3>
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
          <section className="panel set-panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Dashboard-indeling</span>
            <h3 className="gx-h2">Dashboard-weergave</h3>
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
