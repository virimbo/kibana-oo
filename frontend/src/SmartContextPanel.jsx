import { useEffect, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import useCardContext from "./useCardContext";

// UI strings. Content (component text, TODOs) comes from the vault in Dutch;
// these are the panel's own chrome labels. Default = nl (beheerder audience).
const STRINGS = {
  nl: {
    title: "Context", info: "Kaartinformatie", purposeB: "Doel (business)",
    purposeT: "Doel (technisch)", deps: "Afhankelijkheden", related: "Gerelateerd",
    health: "Status", risk: "Risico", owner: "Eigenaar", lastInc: "Laatste incident",
    ai: "AI-analyse", todo: "TO DO", doc: "Documentatie", open: "Open in Obsidian",
    none: "Geen", loading: "Laden…", aiThinking: "AI analyseert…",
    aiOff: "AI-analyse niet beschikbaar.", noDoc: "Nog niet gedocumenteerd in de vault.",
    pin: "Vastgezet — Esc om te sluiten", close: "Sluiten",
    actionNow: "WAT TE DOEN NU", actionMissing: "Geen actie vastgelegd — vul de runbook aan.",
    runbookUpdated: "runbook bijgewerkt", runbookStale: "⚠ runbook mogelijk verouderd — controleer",
  },
  en: {
    title: "Context", info: "Card information", purposeB: "Business purpose",
    purposeT: "Technical purpose", deps: "Dependencies", related: "Related",
    health: "Status", risk: "Risk", owner: "Owner", lastInc: "Last incident",
    ai: "AI analysis", todo: "TO DO", doc: "Documentation", open: "Open in Obsidian",
    none: "None", loading: "Loading…", aiThinking: "AI is analysing…",
    aiOff: "AI analysis unavailable.", noDoc: "Not yet documented in the vault.",
    pin: "Pinned — press Esc to close", close: "Close",
    actionNow: "WHAT TO DO NOW", actionMissing: "No action defined — please update the runbook.",
    runbookUpdated: "runbook updated", runbookStale: "⚠ runbook may be outdated — review",
  },
};

const HEALTH_CLASS = { ok: "ok", healthy: "ok", warn: "warn", degraded: "warn", crit: "crit", critical: "crit" };
const RISK_CLASS = { low: "ok", medium: "warn", high: "crit", critical: "crit" };

function Badge({ kind, value }) {
  if (!value) return null;
  const map = kind === "risk" ? RISK_CLASS : HEALTH_CLASS;
  const cls = map[String(value).toLowerCase()] || "muted";
  return <span className={`scp-badge scp-badge--${cls}`}>{value}</span>;
}

export default function SmartContextPanel({ token, aiEnabled = true, lang = "nl" }) {
  const t = STRINGS[lang] || STRINGS.nl;

  // Registry: which cards are smart (also the client-side feature gate — when the
  // backend flag is off it returns {enabled:false} and we stay inert).
  const [registry, setRegistry] = useState(null); // null=loading, {}=disabled
  useEffect(() => {
    let on = true;
    getJSON("/dashboard/context/registry", token)
      .then((d) => on && setRegistry(d.enabled ? d.cards || {} : {}))
      .catch(() => on && setRegistry({}));
    return () => { on = false; };
  }, [token]);

  const isKnown = useCallback((id) => !!(registry && registry[id]), [registry]);
  const { active, pinned, close, holdOpen, releaseOpen } = useCardContext(isKnown);

  const [info, setInfo] = useState(null);
  const [infoState, setInfoState] = useState("idle"); // idle|loading|ready|error
  const [ai, setAi] = useState(null);
  const [aiState, setAiState] = useState("idle"); // idle|loading|ready|off

  const query = useMemo(() => {
    if (!active) return "";
    const p = new URLSearchParams();
    if (active.label) p.set("label", active.label);
    if (active.status) p.set("status", active.status);
    if (active.env) p.set("env", active.env);
    const s = p.toString();
    return s ? `?${s}` : "";
  }, [active]);

  // Fast section. Aborts on leave so sweeping across cards never holds a
  // connection (otherwise slow AI requests would saturate the browser pool).
  useEffect(() => {
    if (!active) { setInfo(null); setInfoState("idle"); return; }
    const ctrl = new AbortController();
    setInfoState("loading");
    getJSON(`/dashboard/context/card/${encodeURIComponent(active.id)}${query}`, token, ctrl.signal)
      .then((d) => { setInfo(d.enabled ? d : null); setInfoState("ready"); })
      .catch((e) => { if (e.name !== "AbortError") setInfoState("error"); });
    return () => ctrl.abort();
  }, [active, query, token]);

  // Lazy AI section — only when the panel is open and AI is on. Also aborts on
  // leave: the previous card's slow Ollama call is cancelled, not left hanging.
  useEffect(() => {
    if (!active || !aiEnabled) { setAi(null); setAiState("off"); return; }
    const ctrl = new AbortController();
    setAi(null); setAiState("loading");
    getJSON(`/dashboard/context/card/${encodeURIComponent(active.id)}/ai${query}`, token, ctrl.signal)
      .then((d) => { if (d.enabled) { setAi(d); setAiState("ready"); } else setAiState("off"); })
      .catch((e) => { if (e.name !== "AbortError") setAiState("off"); });
    return () => ctrl.abort();
  }, [active, query, token, aiEnabled]);

  if (!registry || Object.keys(registry).length === 0) return null; // disabled / no perms
  if (!active) return null;

  const open = info && info.todos ? info.todos.filter((x) => !x.done) : [];
  const doneTodos = info && info.todos ? info.todos.filter((x) => x.done) : [];

  return (
    <aside
      className={`scp${pinned ? " scp--pinned" : ""}`}
      role="complementary"
      aria-label={`${t.title}: ${info?.component || active.label || active.id}`}
      onMouseEnter={holdOpen}
      onMouseLeave={releaseOpen}
    >
      <header className="scp-head">
        <div className="scp-head-main">
          <span className="scp-eyebrow">{t.info}</span>
          <h3 className="scp-title">{info?.component || active.label || active.id}</h3>
        </div>
        <div className="scp-head-badges">
          <Badge kind="health" value={info?.health && info.health !== "unknown" ? info.health : null} />
          <Badge kind="risk" value={info?.risk} />
          <button type="button" className="scp-close" onClick={close} aria-label={t.close}>×</button>
        </div>
      </header>

      <div className="scp-body">
        {infoState === "loading" && <p className="scp-muted">{t.loading}</p>}

        {info && (
          <>
            {info.action && (
              <section className={`scp-action ${info.action.urgent ? "scp-action--urgent" : "scp-action--warn"}`}>
                <div className="scp-action-head">⚠ {t.actionNow}</div>
                {info.action.text && (
                  <div className="scp-action-text">{info.action.text}</div>
                )}
                {info.action.procedure && info.action.procedure.steps?.length > 0 && (
                  <div className="scp-proc">
                    <div className="scp-proc-title">
                      Procedure{info.action.procedure.title ? ` — ${info.action.procedure.title}` : ""}
                    </div>
                    <ol className="scp-proc-steps">
                      {info.action.procedure.steps.slice(0, 14).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                    {info.action.procedure.steps.length > 14 && (
                      <div className="scp-proc-more">
                        + {info.action.procedure.steps.length - 14} meer — open de runbook ↓
                      </div>
                    )}
                  </div>
                )}
                {!info.action.text && !(info.action.procedure && info.action.procedure.steps?.length) && (
                  <div className="scp-action-missing">{t.actionMissing}</div>
                )}
                <div className="scp-action-meta">
                  <span className="scp-action-tag">{[info.action.env, info.action.label].filter(Boolean).join(" · ")}</span>
                  {info.action.runbook_stale ? (
                    <span className="scp-action-stale">{t.runbookStale}</span>
                  ) : info.action.runbook_updated ? (
                    <span className="scp-action-upd">{t.runbookUpdated}: {info.action.runbook_updated}</span>
                  ) : null}
                </div>
              </section>
            )}

            {info.purpose_business && <Field label={t.purposeB} value={info.purpose_business} />}
            {info.purpose_technical && <Field label={t.purposeT} value={info.purpose_technical} />}
            {info.dependencies?.length > 0 && <Chips label={t.deps} items={info.dependencies} />}
            {info.related?.length > 0 && <Chips label={t.related} items={info.related} />}
            {info.owner && <Field label={t.owner} value={info.owner} />}
            {info.last_incident && <Field label={t.lastInc} value={info.last_incident} />}

            {/* AI analysis */}
            {aiEnabled && (
              <section className="scp-section scp-section--ai">
                <h4 className="scp-h4">🧠 {t.ai}</h4>
                {aiState === "loading" && <p className="scp-muted scp-pulse">{t.aiThinking}</p>}
                {aiState === "ready" && ai?.analysis && (
                  <div className="scp-md markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{ai.analysis}</ReactMarkdown></div>
                )}
                {aiState === "off" && <p className="scp-muted">{t.aiOff}</p>}
                {aiState === "ready" && ai?.model && <p className="scp-ai-by">— {ai.provider} · {ai.model}</p>}
              </section>
            )}

            {/* TODO */}
            <section className="scp-section">
              <h4 className="scp-h4">✓ {t.todo}</h4>
              {open.length === 0 && doneTodos.length === 0 ? (
                <p className="scp-muted">{info.documented ? t.none : t.noDoc}</p>
              ) : (
                <ul className="scp-todos">
                  {open.map((x, i) => (
                    <li key={`o${i}`} className="scp-todo"><span className="scp-box" aria-hidden="true">☐</span>{x.text}</li>
                  ))}
                  {doneTodos.map((x, i) => (
                    <li key={`d${i}`} className="scp-todo scp-todo--done"><span className="scp-box" aria-hidden="true">☑</span>{x.text}</li>
                  ))}
                </ul>
              )}
            </section>

            {/* Documentation */}
            <section className="scp-section">
              <h4 className="scp-h4">📄 {t.doc}</h4>
              {info.doc ? (
                <a className="scp-doclink" href={`obsidian://open?vault=KIBANA-OO&file=${encodeURIComponent(info.doc.note)}`}>
                  {info.doc.title} ↗
                </a>
              ) : (
                <p className="scp-muted">{t.noDoc}</p>
              )}
            </section>
          </>
        )}
      </div>

      {pinned && <footer className="scp-foot">{t.pin}</footer>}
    </aside>
  );
}

function Field({ label, value }) {
  return (
    <div className="scp-field">
      <span className="scp-field-label">{label}</span>
      <span className="scp-field-value">{value}</span>
    </div>
  );
}

function Chips({ label, items }) {
  return (
    <div className="scp-field">
      <span className="scp-field-label">{label}</span>
      <span className="scp-chips">{items.map((x, i) => <span key={i} className="scp-chip">{x}</span>)}</span>
    </div>
  );
}
