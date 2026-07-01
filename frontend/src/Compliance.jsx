import TopNav from "./Nav";

// Beheer → Compliance & Beveiliging (super-admin). An HONEST self-assessment — not
// a legal certification. It surfaces the EU AI Act risk classification + the
// security-review posture so an admin can see where the app stands and what still
// needs an organisational step (DPIA / FG-DPO). Content is curated (not live),
// except the AI-provider privacy flag which reflects the active model.

// EU AI Act classification points.
const AI_ACT = [
  { ok: true, t: "Risicoklasse: beperkt risico (limited risk)",
    d: "Een RAG-chatassistent die tekst genereert over interne logs. Géén hoog-risico­systeem: het neemt geen besluiten over personen (geen biometrie, emotieherkenning, werving, krediet of rechtshandhaving — Annex III niet van toepassing)." },
  { ok: true, t: "Transparantieplicht (Art. 50) — ingevuld",
    d: "Van toepassing vanaf 2 aug 2026. Gebruikers weten dat ze met AI werken (label “AI-GENERATED”, “AI-assistent”-disclosure) en AI kan volledig uit. Aan deze verplichting wordt voldaan." },
  { ok: true, t: "GPAI-verplichtingen liggen bij de modelleverancier",
    d: "Verplichtingen voor het onderliggende model (general-purpose AI) rusten op de leverancier (Mistral / het Ollama-model), niet op deze app als deployer." },
  { ok: false, t: "AVG / persoonsgegevens — aandacht vereist",
    d: "De AI Act ≠ volledige compliance. De app verwerkt persoonsgegevens (o.a. usernames, mogelijk IP’s in logs). Volledige compliance vereist een DPIA + grondslag (AVG Art. 6) en akkoord van de FG/DPO — een organisatorische stap, geen technisch vinkje." },
];

// Security-review dimensions → verdict pill + severity.
const SEC = [
  { v: "ok",   dim: "Authenticatie & autorisatie",
    d: "Keycloak OIDC-login, deny-by-default rechten-matrix + goedkeuringspoort voor nieuwe gebruikers, super-admin root-of-trust; elke mutatie-endpoint is server-side gated (require_super/require_feature)." },
  { v: "ok",   dim: "Secrets-beheer",
    d: "Secrets in .env (gitignored), nooit teruggegeven door een API; monitor-connections tonen alleen de secret_ref-naam. (Aandacht: super-admin-e-mail staat nog als default in config.py — hoort in .env.)" },
  { v: "ok",   dim: "Injectie (ES / SQL / command)",
    d: "ES via gestructureerde DSL (geen string-concatenatie), index- en doc-id-input met regex gevalideerd; geen eval/exec/pickle/subprocess/shell." },
  { v: "gap",  dim: "Datalek naar cloud-LLM (Mistral)", sev: "HOOG",
    d: "Met Mistral als provider gaat tot ~16.000 tekens ruwe logcontext (message/host/error, document-id’s) naar api.mistral.ai — zónder PII-redactie. Belangrijkste privacy-bevinding. Mitigatie: gebruik Ollama (lokaal) voor gevoelige data, of PII-redactie / een DPA met Mistral." },
  { v: "warn", dim: "Rate-limiting op /login", sev: "MIDDEL",
    d: "Geen extra rate-limiting op login (Keycloak heeft mogelijk eigen brute-force-bescherming). Op een VPN lager risico; een per-IP-teller is aan te raden." },
  { v: "warn", dim: "Sessie-levensduur", sev: "MIDDEL",
    d: "Sessies in-memory zonder TTL/idle-timeout; een bearer-token blijft geldig tot herstart. Aanrader: TTL + idle-timeout." },
  { v: "warn", dim: "SSRF-oppervlak (admin-URLs)", sev: "MIDDEL",
    d: "Door super-admins ingevoerde Prometheus/Jaeger-URLs worden as-is aangeroepen (geen https-only / geen block van private IP-ranges). Beperkt tot al-geprivilegieerde gebruikers; defense-in-depth = schema + host-allowlist." },
  { v: "ok",   dim: "Transport / TLS",
    d: "httpx verify=True naar Kibana/RabbitMQ, STARTTLS voor SMTP, actieve certificaat-monitoring met OCSP. (1 gecontroleerde verify=False-fallback voor een publiek, credential-loos portaal.)" },
  { v: "warn", dim: "HTTP-securityheaders & /docs", sev: "LAAG",
    d: "Geen HSTS/CSP/X-Frame-Options-middleware; FastAPI /docs staat open. Aanrader: securityheaders-middleware + /docs in productie afschermen." },
];

const REC = [
  "DPIA uitvoeren + laten tekenen door de FG/DPO; grondslag (AVG Art. 6) en doelbinding vastleggen.",
  "Gevoelige queries op Ollama (lokaal) houden, óf PII-redactie vóór de LLM-context, óf een DPA met Mistral.",
  "Rate-limiting op /login, sessie-TTL/idle-timeout, en super-admin-e-mail uit config.py naar .env.",
  "SSRF-hardening: https-only + host-allowlist voor monitor-connections; securityheaders-middleware toevoegen.",
];

const PILL = {
  ok:   { cls: "alerts-pill--ok",   label: "OK" },
  warn: { cls: "alerts-pill--warn", label: "Aandacht" },
  gap:  { cls: "alerts-pill--crit", label: "Gap" },
};

export default function CompliancePage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const cloud = llmProvider === "mistral";
  return (
    <>
      <TopNav
        active="compliance"
        brandMark="⚖️"
        brandName="Compliance"
        brandSub="Super admin · EU AI Act & beveiliging"
        can={can} isAdmin={isAdmin} username={username} onLogout={onLogout}
        onNavigate={onNavigate} llmProvider={llmProvider} onProviderChange={onProviderChange}
        stuckCount={stuckCount} aanleverCount={aanleverCount} dlqCount={dlqCount}
      />
      <div className="chat-scroll">
        <div className="dash">
          <section className="page-hero gx-pagehead">
            <div className="page-hero-main">
              <span className="page-eyebrow gx-eyebrow">• BEHEER · COMPLIANCE & BEVEILIGING</span>
              <h1 className="page-hero-h1 gx-h1">COMPLIANCE & BEVEILIGING</h1>
              <p className="page-hero-lead muted">
                Een eerlijke <b>engineering-inschatting</b> van de EU AI Act-positie en de
                beveiliging — <b>geen juridisch oordeel en geen certificering</b>. Een claim
                als “100% compliant” kan alléén ná een <b>DPIA</b> en akkoord van de <b>FG/DPO</b>.
              </p>
            </div>
          </section>

          {/* ── Read-only (RAG) ───────────────────────────────── */}
          <section className="panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Werking</span>
            <h3 className="gx-h2">🔒 Alleen-lezen (RAG)</h3>
            <p className="muted set-intro">
              Dit is een <b>RAG</b>-systeem (Retrieval-Augmented Generation): het{" "}
              <b>leest</b> log- en metricdata uit Elasticsearch via de Kibana-proxy
              (<b>alleen-lezen</b>) en stuurt die als context naar het taalmodel. Het{" "}
              <b>schrijft niet</b> naar de logs, indices of bronsystemen — alle monitors
              zijn read-only. De app houdt uitsluitend een <b>eigen lokale</b> audit- en
              incident-opslag bij voor zijn eigen werking; aan de bewaakte systemen wordt
              niets gewijzigd.
            </p>
          </section>

          {/* ── EU AI Act ─────────────────────────────────────── */}
          <section className="panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Regelgeving</span>
            <h3 className="gx-h2">⚖️ EU AI Act</h3>
            <div className="cmpl-status">
              <span className="alerts-pill alerts-pill--ok"><b>Beperkt risico</b></span>
              <span className="alerts-pill alerts-pill--ok">Transparantie voldaan</span>
              <span className="alerts-pill alerts-pill--warn">DPIA / AVG vereist</span>
            </div>
            <ul className="cmpl-list">
              {AI_ACT.map((p, i) => (
                <li key={i} className={`cmpl-row cmpl-row--${p.ok ? "ok" : "warn"}`}>
                  <span className="cmpl-mark" aria-hidden="true">{p.ok ? "✓" : "!"}</span>
                  <div><span className="cmpl-t">{p.t}</span><span className="cmpl-d muted">{p.d}</span></div>
                </li>
              ))}
            </ul>
            <p className="cmpl-links">
              Controleer bij de officiële bron:{" "}
              <a href="https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai"
                 target="_blank" rel="noreferrer">Europese Commissie — AI Act ↗</a>
              {" · "}
              <a href="https://eur-lex.europa.eu/eli/reg/2024/1689/oj"
                 target="_blank" rel="noreferrer">Verordening (EU) 2024/1689 — EUR-Lex ↗</a>
              {" · "}
              <a href="https://artificialintelligenceact.eu/article/50/"
                 target="_blank" rel="noreferrer">Artikel 50 · transparantie ↗</a>
            </p>
          </section>

          {/* ── Security check ────────────────────────────────── */}
          <section className="panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Beveiligingscheck</span>
            <h3 className="gx-h2">🛡️ Security check</h3>
            <p className="muted set-intro">
              Uitkomst van een code-review. Sterke authenticatie/autorisatie; de belangrijkste
              aandachtspunten staan hieronder met hun ernst.
            </p>
            <div className={`cmpl-liveflag cmpl-liveflag--${cloud ? "warn" : "ok"}`}>
              Actief AI-model: <b>{cloud ? "Mistral (cloud)" : "Ollama (lokaal)"}</b> —
              {cloud
                ? " logcontext verlaat het netwerk richting api.mistral.ai. Gebruik Ollama voor gevoelige data."
                : " draait lokaal; er verlaat geen logdata het netwerk."}
            </div>
            <ul className="cmpl-list">
              {SEC.map((r, i) => (
                <li key={i} className="cmpl-row">
                  <span className={`alerts-pill ${PILL[r.v].cls} cmpl-pill`}>
                    {PILL[r.v].label}{r.sev ? ` · ${r.sev}` : ""}
                  </span>
                  <div><span className="cmpl-t">{r.dim}</span><span className="cmpl-d muted">{r.d}</span></div>
                </li>
              ))}
            </ul>
          </section>

          {/* ── Recommended actions ───────────────────────────── */}
          <section className="panel gx-panel">
            <span className="page-eyebrow gx-eyebrow">Zo wordt compliance aantoonbaar</span>
            <h3 className="gx-h2">✅ Aanbevolen acties</h3>
            <ol className="cmpl-actions">
              {REC.map((r, i) => <li key={i}>{r}</li>)}
            </ol>
            <p className="muted cmpl-foot">
              Volledige toelichting staat in de vault: <code>docs/KIBANA-OO/AI-architectuur.md</code>.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
