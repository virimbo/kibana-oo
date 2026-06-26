import { useState, useEffect, useCallback, useRef } from "react";
import { getJSON } from "./api";
import TopNav from "./Nav";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const STATUS_ICON = { pass: "✓", warn: "!", fail: "✗" };
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("nl-NL") : "");

function VerdictBadge({ verdict }) {
  const v = verdict || "—";
  const cls = v === "PASS" ? "ok" : v === "WARN" ? "warn" : v === "FAIL" ? "fail" : "running";
  return <span className={`reg-verdict reg-verdict--${cls}`}>{v === "running" ? "RUNNING…" : v}</span>;
}

// A small "48/50 ✓" reliability indicator over the recent runs.
function Reliability({ stat }) {
  if (!stat || !stat.total) return null;
  const bad = stat.failed > 0 ? "fail" : stat.warned > 0 ? "warn" : "ok";
  return (
    <span className={`reg-rel reg-rel--${bad}`} title={`Over the last ${stat.total} runs: ${stat.passed} pass · ${stat.warned} warn · ${stat.failed} fail`}>
      {stat.passed}/{stat.total} ✓
    </span>
  );
}

// ── Check knowledge base (management-level explanations per check) ───────────
// Each entry: wat (what it tests), waarom (why it matters for the org),
// bijFalen (what to do when it fails), categorie (grouping label).
const CHECK_KB = {
  home: {
    cat: "Beschikbaarheid", icon: "🌐",
    wat: "Controleert of de homepage van open.overheid.nl laadt (HTTP 200) en de tekst \"Open overheid\" bevat.",
    waarom: "De homepage is het eerste dat burgers en journalisten zien. Als deze niet laadt, is de hele portal onbereikbaar en ontstaat reputatieschade.",
    bijFalen: "Controleer of de webserver/pod draait, of er een deploy bezig is, en of de DNS/ingress correct is. Meld het direct aan het platform-team.",
  },
  "doc-page": {
    cat: "Beschikbaarheid", icon: "📄",
    wat: "Controleert of een bekende documentpagina (/details/...) bereikbaar is en HTML teruggeeft.",
    waarom: "Individuele documentpagina's zijn de kern van open.overheid.nl — als ze niet laden, kunnen burgers geen Woo-documenten inzien.",
    bijFalen: "Controleer of de detail-route werkt, of de document-database bereikbaar is, en of het test-document nog bestaat.",
  },
  "doc-file": {
    cat: "Beschikbaarheid", icon: "📥",
    wat: "Controleert of het PDF-bestand van een document daadwerkelijk downloadbaar is (status 200, content-type PDF).",
    waarom: "Documenten moeten downloadbaar zijn — een werkende pagina zonder downloadbaar bestand is een onvolledige publicatie.",
    bijFalen: "Controleer de opslag-backend (S3/NFS), of de file-serving route werkt, en of het testbestand nog beschikbaar is in de opslag.",
  },
  "api-meta": {
    cat: "API", icon: "🔌",
    wat: "Controleert of de openbaarmakingen-API metadata teruggeeft (JSON met documenttitel).",
    waarom: "De API wordt gebruikt door derden (journalisten, onderzoekers, andere overheidsportals) om documenten op te vragen. Uitval raakt het hele ecosysteem.",
    bijFalen: "Controleer of de API-service draait, of de database bereikbaar is, en of het antwoord-formaat niet gewijzigd is door een recente release.",
  },
  tls: {
    cat: "Beveiliging", icon: "🔐",
    wat: "Controleert of het TLS-certificaat geldig is, de keten klopt en de grade niet CRITICAL is.",
    waarom: "Een verlopen of ongeldig certificaat toont een browserwaarschuwing aan alle bezoekers, blokkeert API-clients en ondermijnt het vertrouwen in de overheidssite.",
    bijFalen: "Vernieuw het certificaat onmiddellijk. Controleer de volledige keten (intermediate CA's), OCSP-status en vervaldatum. Coördineer met het certificaatbeheer-team.",
  },
  "security-headers": {
    cat: "Beveiliging", icon: "🛡️",
    wat: "Controleert of de essentiële beveiligingsheaders aanwezig zijn: Strict-Transport-Security (HSTS), X-Content-Type-Options (nosniff) en X-Frame-Options.",
    waarom: "Deze headers beschermen tegen veelvoorkomende aanvallen: HSTS voorkomt downgrade-aanvallen, X-Content-Type-Options voorkomt MIME-sniffing, en X-Frame-Options voorkomt clickjacking. Het ontbreken is een beveiligingsrisico dat ook door auditors wordt gesignaleerd.",
    bijFalen: "Controleer de nginx/ingress-configuratie. Meestal is een header verwijderd bij een recente deploy. Voeg de ontbrekende header(s) terug toe aan de reverse-proxy/webserver configuratie.",
  },
  "hsts-maxage": {
    cat: "Beveiliging", icon: "⏱️",
    wat: "Controleert of de HSTS max-age minimaal 1 jaar (31536000 seconden) is.",
    waarom: "Een te korte max-age betekent dat browsers snel stoppen met het afdwingen van HTTPS, waardoor een downgrade-aanval mogelijk wordt. Google en beveiligingsaudits vereisen minimaal 1 jaar.",
    bijFalen: "Pas de Strict-Transport-Security header aan in de webserver-configuratie: stel max-age=31536000 in (inclusief includeSubDomains).",
  },
  "meta-desc": {
    cat: "SEO & Vindbaarheid", icon: "🔍",
    wat: "Controleert of de homepage een <meta name=\"description\"> tag heeft.",
    waarom: "De meta-description is wat Google toont in de zoekresultaten. Zonder beschrijving toont Google willekeurige tekst, waardoor minder mensen doorklikken. Dit is het verschil tussen vindbaar en onzichtbaar.",
    bijFalen: "Voeg een <meta name=\"description\" content=\"...\"> tag toe aan de homepage HTML. De beschrijving moet 120-160 tekens zijn en duidelijk uitleggen wat open.overheid.nl is.",
  },
  "lang-attr": {
    cat: "SEO & Vindbaarheid", icon: "🗣️",
    wat: "Controleert of de HTML-tag een lang=\"nl\" attribuut heeft.",
    waarom: "Het lang-attribuut vertelt zoekmachines en screenreaders in welke taal de pagina is. Zonder dit attribuut kan Google de pagina verkeerd classificeren en tonen screenreaders de tekst met de verkeerde uitspraak — een toegankelijkheidsprobleem (WCAG).",
    bijFalen: "Voeg lang=\"nl\" toe aan de <html> tag in de hoofdtemplate. Dit is een eenmalige wijziging die zowel SEO als toegankelijkheid verbetert.",
  },
  favicon: {
    cat: "Technisch", icon: "🎨",
    wat: "Controleert of /favicon.ico bereikbaar is (HTTP 200).",
    waarom: "De favicon verschijnt in browsertabs, bladwijzers en zoekresultaten. Een ontbrekend favicon genereert 404-errors in de serverlog en oogt onprofessioneel.",
    bijFalen: "Plaats een favicon.ico bestand in de web-root van de applicatie. Controleer of de file-serving route niet geblokkeerd wordt door de ingress.",
  },
  robots: {
    cat: "SEO & Vindbaarheid", icon: "🤖",
    wat: "Controleert of /robots.txt bereikbaar is (HTTP 200).",
    waarom: "Het robots.txt bestand vertelt zoekmachines welke pagina's ze mogen indexeren. Zonder dit bestand kunnen crawlers ongewenste pagina's indexeren of worden juist belangrijke pagina's gemist.",
    bijFalen: "Controleer of het robots.txt bestand aanwezig is in de web-root en of het correct wordt geserveerd door de webserver.",
  },
  "robots-googlebot": {
    cat: "SEO & Vindbaarheid", icon: "🤖",
    wat: "Controleert of robots.txt specifieke regels voor Googlebot bevat.",
    waarom: "Open.overheid.nl staat alleen Googlebot toe op specifieke paden (Allow: /home, /details/*, etc.). Als deze regels verdwijnen na een release, wordt de site niet meer geïndexeerd door Google.",
    bijFalen: "Controleer de inhoud van robots.txt. De Googlebot Allow-regels moeten aanwezig zijn. Als ze ontbreken, herstel het bestand vanuit versiebeheer.",
  },
  "no-5xx": {
    cat: "Beschikbaarheid", icon: "🚫",
    wat: "Controleert of een onbekend pad (dat niet bestaat) geen 5xx server-error geeft.",
    waarom: "Een 404 voor een niet-bestaande pagina is normaal. Een 500-error wijst op een crash in de applicatie — dat is een serieus probleem dat ook andere pagina's kan raken.",
    bijFalen: "Onderzoek de error-handling van de applicatie. Een 5xx op een willekeurig pad duidt op een onafgevangen exception in de fallback/error-route.",
  },
  "csp-header": {
    cat: "Beveiliging", icon: "🔒",
    wat: "Controleert of de Content-Security-Policy (CSP) header aanwezig is.",
    waarom: "CSP beschermt tegen cross-site scripting (XSS) aanvallen door te beperken welke scripts en bronnen de pagina mag laden. Het ontbreken is een beveiligingsrisico.",
    bijFalen: "Controleer de webserver/reverse-proxy configuratie. De CSP-header moet worden ingesteld met een restrictief beleid (default-src 'self', etc.).",
  },
  "referrer-policy": {
    cat: "Beveiliging", icon: "🔗",
    wat: "Controleert of de Referrer-Policy header aanwezig is.",
    waarom: "Zonder Referrer-Policy stuurt de browser de volledige URL (inclusief document-IDs) mee naar externe sites. Dit kan gevoelige informatie lekken.",
    bijFalen: "Voeg een Referrer-Policy header toe aan de webserver-configuratie (aanbevolen: 'no-referrer' of 'strict-origin-when-cross-origin').",
  },
  sitemap: {
    cat: "SEO & Vindbaarheid", icon: "🗺️",
    wat: "Controleert of /sitemap.xml geen server-error (5xx) geeft. (Momenteel geeft de site 401 — er is nog geen sitemap.)",
    waarom: "Een sitemap helpt zoekmachines alle pagina's te ontdekken. Zonder sitemap vindt Google alleen pagina's via links, waardoor nieuwe publicaties later of nooit worden geïndexeerd.",
    bijFalen: "Dit is een bekende beperking. Wanneer een sitemap wordt toegevoegd, zal deze check automatisch beginnen met monitoren of hij beschikbaar blijft.",
  },
  manifest: {
    cat: "Technisch", icon: "📱",
    wat: "Controleert of /manifest.json bereikbaar is (HTTP 200, JSON).",
    waarom: "Het manifest maakt de site installeerbaar als Progressive Web App (PWA) op mobiel en desktop. Het ondersteunt ook de juiste icoon- en themaweergave.",
    bijFalen: "Controleer of manifest.json aanwezig is in de web-root en correct JSON bevat. Meestal verdwijnt het bestand bij een foutieve deploy.",
  },
};

// One check row — click to reveal the drill-down evidence + management info panel.
function CheckRow({ c, stat }) {
  const [open, setOpen] = useState(false);
  const hasEvidence = c.url || c.expected || c.actual || c.evidence;
  const kb = CHECK_KB[c.id];
  const canOpen = hasEvidence || kb;
  return (
    <li className={`reg-check reg-check--${c.status}`}>
      <button
        type="button"
        className="reg-check-head"
        onClick={() => canOpen && setOpen((o) => !o)}
        aria-expanded={open}
        disabled={!canOpen}
      >
        <span className="reg-check-icon">{STATUS_ICON[c.status] || "·"}</span>
        <span className="reg-check-main">
          <span className="reg-check-name">
            {c.name}
            {c.severity === "critical" && <span className="reg-sev">critical</span>}
            <Reliability stat={stat} />
          </span>
          <span className="reg-check-detail">{c.detail}</span>
        </span>
        {c.response_ms != null && <span className="reg-check-ms">{c.response_ms} ms</span>}
        {canOpen && <span className="reg-check-caret">{open ? "▾" : "▸"}</span>}
      </button>
      {open && (
        <div className="reg-detail-panel">
          {kb && (
            <div className="reg-kb">
              <div className="reg-kb-cat">
                <span className="reg-kb-cat-icon">{kb.icon}</span>
                <span className="reg-kb-cat-label">{kb.cat}</span>
              </div>
              <div className="reg-kb-section">
                <span className="reg-kb-label">Wat wordt getest</span>
                <p className="reg-kb-text">{kb.wat}</p>
              </div>
              <div className="reg-kb-section">
                <span className="reg-kb-label">Waarom is dit belangrijk</span>
                <p className="reg-kb-text">{kb.waarom}</p>
              </div>
              {c.status !== "pass" && (
                <div className="reg-kb-section reg-kb-action">
                  <span className="reg-kb-label">Wat te doen bij falen</span>
                  <p className="reg-kb-text">{kb.bijFalen}</p>
                </div>
              )}
            </div>
          )}
          {hasEvidence && (
            <dl className="reg-evidence">
              {c.url && (<><dt>URL</dt><dd>{c.method ? `${c.method} ` : ""}{c.url}</dd></>)}
              {c.expected && (<><dt>Verwacht</dt><dd>{c.expected}</dd></>)}
              {c.actual && (<><dt>Werkelijk</dt><dd>{c.actual}</dd></>)}
              {c.evidence && (<><dt>Bewijs</dt><dd><code className="reg-evidence-snippet">{c.evidence}</code></dd></>)}
            </dl>
          )}
        </div>
      )}
    </li>
  );
}

// One full run: verdict, per-check results (drill-down), and the change notes.
function RunDetail({ run, rel }) {
  if (!run) return null;
  return (
    <div className="reg-run">
      <div className="reg-run-head">
        <VerdictBadge verdict={run.verdict} />
        <span className="reg-run-counts">
          <b className="reg-ok">{run.passed} passed</b> ·{" "}
          <b className="reg-warn">{run.warned} warning</b> ·{" "}
          <b className="reg-fail">{run.failed} failed</b>
        </span>
        <span className="reg-run-meta">
          {run.trigger === "ci" ? "CI" : "manual"}
          {run.duration_ms != null ? ` · ${(run.duration_ms / 1000).toFixed(1)}s` : ""}
          {run.finished ? ` · ${fmtWhen(run.finished)}` : run.started ? ` · started ${fmtWhen(run.started)}` : ""}
        </span>
      </div>

      <ul className="reg-checks">
        {(run.checks || []).map((c) => <CheckRow key={c.id} c={c} stat={rel[c.id]} />)}
        {run.verdict === "running" && (run.checks || []).length < (run.total || 0) && (
          <li className="reg-check reg-check--running">
            <span className="reg-check-head" style={{ cursor: "default" }}>
              <span className="reg-check-icon">⏳</span>
              <span className="reg-check-main">
                <span className="reg-check-name">Running… {(run.checks || []).length}/{run.total}</span>
              </span>
            </span>
          </li>
        )}
      </ul>

      {run.changes && run.changes.length > 0 && (
        <div className="reg-changes">
          <span className="reg-changes-title">Since last run</span>
          <ul>
            {run.changes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function RegressionPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange, can = () => true, isAdmin = false, stuckCount, aanleverCount, dlqCount,
}) {
  const [run, setRun] = useState(null);       // currently displayed run (latest or a selected history item)
  const [history, setHistory] = useState([]);
  const [rel, setRel] = useState({});         // check_id -> {passed,warned,failed,total}
  const [running, setRunning] = useState(false);
  const [viewingId, setViewingId] = useState(null); // non-null when viewing a past run
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  const loadLatest = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/latest", token);
      const r = d && d.run === null ? null : d;
      if (!viewingId) setRun(r);
      setRunning(!!r && r.verdict === "running");
      return r;
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    }
  }, [token, onLogout, viewingId]);

  const loadHistory = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/runs?limit=15", token);
      setHistory(d.runs || []);
    } catch { /* non-fatal */ }
  }, [token]);

  const loadReliability = useCallback(async () => {
    try {
      const d = await getJSON("/dashboard/regression/reliability?limit=50", token);
      setRel(Object.fromEntries((d.checks || []).map((c) => [c.check_id, c])));
    } catch { /* non-fatal */ }
  }, [token]);

  useEffect(() => {
    loadLatest();
    loadHistory();
    loadReliability();
    return () => clearInterval(pollRef.current);
  }, [loadLatest, loadHistory, loadReliability]);

  // Poll for live progress while a run is in flight.
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!running) return;
    pollRef.current = setInterval(async () => {
      const r = await loadLatest();
      if (r && r.verdict !== "running") {
        clearInterval(pollRef.current);
        setRunning(false);
        loadHistory();
        loadReliability();
      }
    }, 1500);
    return () => clearInterval(pollRef.current);
  }, [running, loadLatest, loadHistory, loadReliability]);

  const runNow = useCallback(async () => {
    setError("");
    setViewingId(null);
    try {
      const r = await fetch(`${BACKEND_URL}/dashboard/regression/run`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.status === 401) return onLogout();
      if (!r.ok) throw new Error("could not start run");
      setRunning(true);
      loadLatest();
    } catch (e) {
      setError(e.message);
    }
  }, [token, onLogout, loadLatest]);

  const viewRun = useCallback(async (id) => {
    try {
      const d = await getJSON(`/dashboard/regression/runs/${id}`, token);
      setViewingId(id);
      setRun(d);
    } catch (e) {
      setError(e.message);
    }
  }, [token]);

  const backToLatest = useCallback(() => {
    setViewingId(null);
    loadLatest();
  }, [loadLatest]);

  return (
    <>
      <TopNav
        active="regression"
        brandMark="🧪"
        brandName="Regressietest"
        brandSub="open.overheid.nl · post-release health gate"
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
          <section className="page-hero gx-pagehead">
            <div className="page-hero-main">
              <span className="page-eyebrow gx-eyebrow">POST-RELEASE · GATE</span>
              <h1 className="page-hero-h1 gx-h1">REGRESSIETEST</h1>
            </div>
          </section>

          <section className="panel gx-panel">
            <div className="reg-bar">
              <div>
                <h3 className="gx-h2" style={{ marginBottom: 4 }}>🧪 Regressietest — open.overheid.nl</h3>
                <p className="muted" style={{ margin: 0 }}>
                  Run this after a prod release to confirm the public portal still works:
                  availability, key journeys, content via the openbaarmakingen API, and TLS.
                </p>
              </div>
              <button className="btn gx-cta" onClick={runNow} disabled={running}>
                {running ? "Running…" : "▶ Run regression test"}
              </button>
            </div>

            {error && <div className="alert alert--error">{error}</div>}

            {viewingId && (
              <button className="btn btn--ghost reg-back" onClick={backToLatest}>← Back to latest</button>
            )}

            {run ? (
              <RunDetail run={run} rel={rel} />
            ) : (
              <p className="muted">No runs yet — click “Run regression test” to start the first one.</p>
            )}
          </section>

          {history.length > 0 && (
            <section className="panel gx-panel">
              <h3 className="gx-h2">Run history</h3>
              <ul className="reg-history">
                {history.map((h) => (
                  <li
                    key={h.run_id}
                    className={`reg-history-row${h.run_id === (viewingId || (run && run.run_id)) ? " is-active" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => viewRun(h.run_id)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && viewRun(h.run_id)}
                  >
                    <VerdictBadge verdict={h.verdict} />
                    <span className="reg-history-when">{fmtWhen(h.finished || h.started)}</span>
                    <span className="reg-history-counts muted">
                      {h.passed}✓ {h.warned}! {h.failed}✗
                      {h.duration_ms != null ? ` · ${(h.duration_ms / 1000).toFixed(1)}s` : ""}
                      {h.trigger === "ci" ? " · CI" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
