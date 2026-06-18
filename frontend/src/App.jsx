import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import DashboardPage from "./Dashboard";
import DocumentsPage from "./Documents";
import SettingsPage from "./Settings";
import AdminPage from "./Admin";
import RegressionPage from "./Regression";
import AuthorizationPage from "./Authorization";
import AlertsPage from "./Alerts";
import DlqIntelPage from "./DlqIntel";
import TopNav from "./Nav";

const SUGGESTIONS = [
  {
    title: "🚨 Kritieke errors nu",
    prompt:
      "Wat zijn de meest kritieke errors van het afgelopen uur? Groepeer ze per service, geef de count per service, en leg de waarschijnlijke oorzaak van de ergste uit.",
  },
  {
    title: "🩺 Falende services",
    prompt:
      "Welke services falen, geven errors of zijn unhealthy op dit moment? Zet de ergste bovenaan met wat er misgaat.",
  },
  {
    title: "📄 Publicatieproblemen",
    prompt:
      "Zijn er errors die het publiceren van documenten zouden blokkeren — connection resets, timeouts, indexing/mapping failures of 5xx? Vat samen wat er risico loopt.",
  },
  {
    title: "🔎 Iets ongewoons?",
    prompt:
      "Vat de laatste 30 minuten aan activiteit samen en markeer alles wat ongewoon of riskant is en waar een admin naar zou moeten kijken.",
  },
];

const TIME_RANGES = [
  { value: 15, label: "Laatste 15 min" },
  { value: 30, label: "Laatste 30 min" },
  { value: 60, label: "Laatste 1 uur" },
  { value: 360, label: "Laatste 6 uur" },
  { value: 1440, label: "Laatste 24 uur" },
];

// Fallback used only if the backend's /data-views endpoint is unreachable.
const DEFAULT_DATA_VIEWS = [
  { id: "logs-*", label: "Alle logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
  { id: "apm-*", label: "APM" },
];

const DATA_VIEW_KEY = "kibana_oo_dataview";
const LLM_PROVIDER_KEY = "kibana_oo_llm_provider";
const AI_ENABLED_KEY = "kibana_oo_ai_enabled";
const AUTOCORRECT_KEY = "kibana_oo_autocorrect";
const SHOW_WELCOME_KEY = "kibana_oo_show_welcome";
const SHOW_HINT_KEY = "kibana_oo_show_hint";
const SHOW_SUGGESTIONS_KEY = "kibana_oo_show_suggestions";
const SHOW_CARD_DETAILS_KEY = "kibana_oo_show_card_details";
const DASH_SECTIONS_KEY = "kibana_oo_dash_sections";
// Dashboard sections that can be shown/hidden from Settings. All default ON, so
// nothing disappears unexpectedly; uptime/certs/dlq are core monitoring.
const DASH_SECTION_DEFAULTS = {
  uptime: true, infra: true, hero: true, certs: true, dlq: true, aanlever: true,
};

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

const fmtTime = (date) =>
  new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);

// ─── Icons ──────────────────────────────────────────────────

const Icon = {
  Spark: (p) => (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" {...p}>
      <path d="M12 2l2.09 5.91L20 10l-5.91 2.09L12 18l-2.09-5.91L4 10l5.91-2.09L12 2z" />
    </svg>
  ),
  Send: (p) => (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
    </svg>
  ),
  Stop: (p) => (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" {...p}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  ),
  Copy: (p) => (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  ),
  Check: (p) => (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M20 6L9 17l-5-5" />
    </svg>
  ),
  Paperclip: (p) => (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  ),
  Gear: (p) => (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
};

// ─── Login Page ─────────────────────────────────────────────

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${BACKEND_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Aanmelden mislukt");
      }

      const data = await res.json();
      onLogin(data.token, data.username);
    } catch (err) {
      setError(
        err.message === "Failed to fetch"
          ? "Kan de backend niet bereiken. Controleer of die draait."
          : err.message
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="brand brand--lg">
          <span className="brand-mark">
            <Icon.Spark />
          </span>
          <span className="brand-name">Open Overheid - Monitoring</span>
        </div>
        <p className="login-desc">
          Meld u aan met uw <strong>SP-inloggegevens</strong> (Standaard Platform) om
          toegang te krijgen tot de monitoringomgeving.
        </p>

        <form onSubmit={handleLogin}>
          <label>
            <span>Gebruikersnaam</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="uw.naam@koop.overheid.nl"
              autoFocus
              required
            />
          </label>
          <label>
            <span>Wachtwoord</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Uw SP-wachtwoord"
              required
            />
          </label>

          {error && (
            <div className="alert alert--error" role="alert">
              {error}
            </div>
          )}

          <button type="submit" className="btn btn--primary" disabled={loading}>
            {loading ? "Bezig met aanmelden…" : "Aanmelden"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ─── Message bits ───────────────────────────────────────────

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <button
      className="icon-btn"
      onClick={copy}
      title={copied ? "Gekopieerd" : "Antwoord kopiëren"}
      aria-label="Antwoord kopiëren"
    >
      {copied ? <Icon.Check /> : <Icon.Copy />}
    </button>
  );
}

function Sources({ sources }) {
  if (!sources || sources.length === 0) return null;
  const indices = [...new Set(sources.map((s) => s.index).filter(Boolean))];

  return (
    <div className="sources">
      <span className="sources-label">
        {sources.length} source{sources.length === 1 ? "" : "s"}
      </span>
      {indices.map((idx) => (
        <span key={idx} className="source-chip" title={idx}>
          {idx}
        </span>
      ))}
    </div>
  );
}

function AssistantMessage({ msg }) {
  const isError = msg.status === "error";
  const isStreaming = msg.status === "streaming";
  const isEmpty = !msg.content;

  return (
    <div className="msg msg--assistant">
      <span className={`avatar avatar--ai${isError ? " avatar--error" : ""}`}>
        <Icon.Spark />
      </span>
      <div className="msg-body">
        <div className="msg-head">
          <span className="msg-name">Open Overheid - Monitoring</span>
          <span className="ai-badge">AI-generated</span>
          {msg.time && <span className="msg-time">{fmtTime(msg.time)}</span>}
          {!isEmpty && !isStreaming && !isError && (
            <CopyButton text={msg.content} />
          )}
        </div>

        <div className={`bubble bubble--ai${isError ? " bubble--error" : ""}`}>
          {isEmpty && isStreaming ? (
            <div className="thinking">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
              <span className="thinking-text">Analyzing logs…</span>
            </div>
          ) : (
            <div className="markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {msg.content}
              </ReactMarkdown>
              {isStreaming && <span className="caret" />}
            </div>
          )}
        </div>

        {!isStreaming && <Sources sources={msg.sources} />}
      </div>
    </div>
  );
}

function UserMessage({ msg }) {
  return (
    <div className="msg msg--user">
      <div className="msg-body">
        <div className="msg-head">
          {msg.corrected && (
            <span className="corrected-badge" title="Spelling/grammar auto-corrected">
              ✓ corrected
            </span>
          )}
          {msg.time && <span className="msg-time">{fmtTime(msg.time)}</span>}
          <span className="msg-name">You</span>
        </div>
        <div className="bubble bubble--user">
          {msg.image && <img src={msg.image} alt="attached" className="bubble-image" />}
          {msg.content && <div className="bubble-text">{msg.content}</div>}
        </div>
      </div>
    </div>
  );
}

// ─── Chat Page ──────────────────────────────────────────────

function ChatPage({
  token, username, onLogout, isAdmin, can = () => false, onNavigate,
  llmProvider, onProviderChange, aiEnabled = true,
  autocorrect, showWelcome, showHint, showSuggestions, stuckCount, aanleverCount, dlqCount,
}) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [timeRange, setTimeRange] = useState(60);
  const [dataViews, setDataViews] = useState(DEFAULT_DATA_VIEWS);
  const [dataView, setDataView] = useState(
    () => sessionStorage.getItem(DATA_VIEW_KEY) || DEFAULT_DATA_VIEWS[0].id
  );
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(null); // null = unknown
  const [image, setImage] = useState(null); // { dataUrl, name } of an attached screenshot
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const abortRef = useRef(null);
  const stickRef = useRef(true);
  const fileInputRef = useRef(null);

  // Read an image File into a data URL (capped so we don't ship huge payloads).
  function attachImageFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    if (file.size > 10 * 1024 * 1024) {
      alert("Image is larger than 10 MB — please attach a smaller screenshot.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setImage({ dataUrl: reader.result, name: file.name || "screenshot" });
    reader.readAsDataURL(file);
  }

  function onPickImage(e) {
    attachImageFile(e.target.files?.[0]);
    e.target.value = ""; // allow re-selecting the same file
  }

  function onPasteComposer(e) {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) {
      e.preventDefault();
      attachImageFile(item.getAsFile());
    }
  }

  // Auto-scroll while the user is near the bottom
  useEffect(() => {
    if (stickRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickRef.current = distance < 120;
  }

  // Load the available data views from the backend (single source of truth)
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/data-views`);
        if (!res.ok) return;
        const data = await res.json();
        if (!active || !Array.isArray(data.data_views) || data.data_views.length === 0) return;
        setDataViews(data.data_views);
        // Keep the saved choice if still valid, otherwise fall back to the default.
        setDataView((current) => {
          const ids = data.data_views.map((v) => v.id);
          return ids.includes(current) ? current : data.default || ids[0];
        });
      } catch {
        /* keep the fallback list */
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Persist the selected data view across reloads
  useEffect(() => {
    sessionStorage.setItem(DATA_VIEW_KEY, dataView);
  }, [dataView]);

  // Health poll for the connection indicator
  useEffect(() => {
    let active = true;
    async function ping() {
      try {
        const res = await fetch(`${BACKEND_URL}/health`);
        if (active) setConnected(res.ok);
      } catch {
        if (active) setConnected(false);
      }
    }
    ping();
    const id = setInterval(ping, 20000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  // Auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  async function handleLogout() {
    abortRef.current?.abort();
    await fetch(`${BACKEND_URL}/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
    onLogout();
  }

  function updateLast(patch) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      next[next.length - 1] =
        typeof patch === "function" ? patch(last) : { ...last, ...patch };
      return next;
    });
  }

  const sendMessage = useCallback(
    async function sendMessage(question) {
      const q = question.trim();
      const img = image; // capture; cleared below
      if ((!q && !img) || loading) return;

      stickRef.current = true;
      setInput("");
      setImage(null);
      setLoading(true);
      setMessages((prev) => [
        ...prev,
        { role: "user", content: q, image: img?.dataUrl, time: new Date() },
        { role: "assistant", content: "", sources: [], status: "streaming", time: new Date() },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await fetch(`${BACKEND_URL}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            question: q,
            time_range_minutes: timeRange,
            data_view: dataView,
            stream: true,
            image: img?.dataUrl || null,
            autocorrect,
          }),
          signal: controller.signal,
        });

        if (response.status === 401) {
          onLogout();
          return;
        }
        if (!response.ok || !response.body) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || `Server error: ${response.status}`);
        }

        await consumeSSE(response.body, controller.signal, {
          onChunk: (text) =>
            updateLast((m) => ({ ...m, content: m.content + text })),
          onSources: (sources) => updateLast({ sources }),
          onQuestion: (corrected) =>
            // Update the *user* bubble (second from the end) to the cleaned text.
            setMessages((prev) => {
              const next = [...prev];
              const ui = next.length - 2;
              if (ui >= 0 && next[ui].role === "user" && corrected.trim()) {
                next[ui] = { ...next[ui], content: corrected, corrected: corrected !== q };
              }
              return next;
            }),
          onError: (detail) => {
            throw new Error(detail);
          },
        });

        updateLast((m) => ({
          ...m,
          status: "done",
          content:
            m.content ||
            // Last-resort safety net: the backend now always streams a real
            // answer (or a summary built from the logs), so this only shows if
            // the connection dropped before any content arrived.
            "_De verbinding eindigde voordat er een antwoord kwam. Probeer het opnieuw — als het aanhoudt, controleer of de backend en Ollama draaien._",
        }));
      } catch (err) {
        if (err.name === "AbortError") {
          updateLast((m) => ({
            ...m,
            status: "done",
            content: m.content
              ? m.content + "\n\n_— stopped —_"
              : "_Stopped._",
          }));
        } else {
          const detail =
            err.message === "Failed to fetch"
              ? "Kan de backend niet bereiken. Controleer of de backend en Ollama draaien."
              : err.message;
          updateLast({
            status: "error",
            content: `**Connection error**\n\n${detail}`,
            sources: [],
          });
        }
      } finally {
        abortRef.current = null;
        setLoading(false);
      }
    },
    [loading, timeRange, dataView, token, onLogout, image, autocorrect]
  );

  function stop() {
    abortRef.current?.abort();
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  return (
    <>
      <TopNav
        active="chat"
        brandMark={<Icon.Spark />}
        brandName="Open Overheid - Monitoring"
        brandSub="AI-logassistent · koop-plooi-prod"
        can={can}
        isAdmin={isAdmin}
        username={username}
        onLogout={handleLogout}
        onNavigate={onNavigate}
        llmProvider={llmProvider}
        onProviderChange={onProviderChange}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        status={{
          tone: connected === null ? "idle" : connected ? "ok" : "down",
          label: connected === null ? "Controleren" : connected ? "Verbonden" : "Offline",
        }}
      />

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-column">
          {!aiEnabled && (
            <div className="ai-off-banner">
              <span className="ai-off-dot" aria-hidden="true" />
              <span>
                <b>AI is switched off.</b> Answers are deterministic, data-only
                summaries — no model is queried. Turn it back on in{" "}
                <button type="button" className="link-btn" onClick={() => onNavigate("settings")}>
                  Settings
                </button>
                .
              </span>
            </div>
          )}
          {messages.length === 0 ? (
            <div className="empty-state">
              {showWelcome && (
                <div className="welcome">
                  <span className="welcome-mark">
                    <Icon.Spark />
                  </span>
                  <h2>Stel gerust een vraag over je logs &amp; metrics</h2>
                  <p>
                    Open Overheid - Monitoring doorzoekt je Elasticsearch-cluster en gebruikt een
                    AI-model om in natuurlijke taal te antwoorden — met de bron-log-entries erbij.
                  </p>
                  <p className="ai-disclosure ai-disclosure--chat">
                    Je communiceert met een AI-systeem. Antwoorden worden gegenereerd
                    door een Llama- of Mistral-taalmodel en kunnen onnauwkeurigheden bevatten.
                    Verifieer kritieke bevindingen altijd in Kibana.
                  </p>
                </div>
              )}
              {showSuggestions && (
                <div className="quick-start">
                  <span className="quick-start-label">Snelle vragen</span>
                  <div className="suggestions">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s.title}
                        className="suggestion"
                        onClick={() => sendMessage(s.prompt)}
                      >
                        <span className="suggestion-title">{s.title}</span>
                        <span className="suggestion-prompt">{s.prompt}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            messages.map((msg, i) =>
              msg.role === "assistant" ? (
                <AssistantMessage key={i} msg={msg} />
              ) : (
                <UserMessage key={i} msg={msg} />
              )
            )
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer-inner">
          <div className="composer-controls">
            <label className="control">
              <span className="control-label">Dataweergave</span>
              <select
                className="control-select"
                value={dataView}
                onChange={(e) => setDataView(e.target.value)}
                disabled={loading}
                title="Elasticsearch data view om te doorzoeken"
              >
                {dataViews.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label && v.label !== v.id ? `${v.id} — ${v.label}` : v.id}
                  </option>
                ))}
              </select>
            </label>

            <label className="control">
              <span className="control-label">Tijdsbereik</span>
              <select
                className="control-select"
                value={timeRange}
                onChange={(e) => setTimeRange(Number(e.target.value))}
                disabled={loading}
                title="Tijdsbereik om te doorzoeken"
              >
                {TIME_RANGES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {image && (
            <div className="attach-preview">
              <img src={image.dataUrl} alt={image.name} className="attach-thumb" />
              <span className="attach-name">{image.name}</span>
              <span className="attach-hint">— I'll read the text from this image</span>
              <button
                type="button"
                className="attach-remove"
                onClick={() => setImage(null)}
                title="Afbeelding verwijderen"
                aria-label="Afbeelding verwijderen"
              >
                ×
              </button>
            </div>
          )}

          <div className="composer-row">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={onPickImage}
            />
            <button
              type="button"
              className="btn btn--ghost btn--attach"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              title="Screenshot toevoegen (of plak een afbeelding)"
              aria-label="Afbeelding toevoegen"
            >
              <Icon.Paperclip />
            </button>

            <div className="composer-field">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={
                  image
                    ? "Stel een vraag over de afbeelding… (optioneel)"
                    : "Stel een vraag over je logs en metrics…  (Enter om te versturen, Shift+Enter voor een nieuwe regel, plak een screenshot)"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={onPasteComposer}
                disabled={loading}
              />
            </div>

            {loading ? (
              <button className="btn btn--stop" onClick={stop} title="Stop generating">
                <Icon.Stop />
                Stop
              </button>
            ) : (
              <button
                className="btn btn--primary btn--send"
                onClick={() => sendMessage(input)}
                disabled={!input.trim() && !image}
                title="Send"
              >
                <Icon.Send />
              </button>
            )}
          </div>
        </div>
        {showHint && (
          <p className="composer-hint">
            Bevraagt <code>{dataView}</code> · antwoorden worden gegenereerd uit live log-
            data. Verifieer kritieke bevindingen altijd in Kibana.
          </p>
        )}
      </div>
    </>
  );
}

// ─── SSE parsing ────────────────────────────────────────────

async function consumeSSE(body, signal, { onChunk, onSources, onError, onQuestion }) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // sse-starlette frames events with CRLF ("\r\n"), so events are separated
      // by "\r\n\r\n". Normalise to "\n" so the boundary split below matches and
      // tokens render live — without this the whole stream is parsed once at the
      // end as a single "done" event and nothing is ever shown.
      buffer = buffer.replace(/\r\n/g, "\n");

      let sep;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        dispatchEvent(rawEvent);
      }
    }
    if (buffer.trim()) dispatchEvent(buffer);
  } finally {
    reader.cancel().catch(() => {});
  }

  function dispatchEvent(raw) {
    let event = "message";
    const dataLines = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        let d = line.slice(5);
        if (d.startsWith(" ")) d = d.slice(1);
        dataLines.push(d);
      }
    }
    const data = dataLines.join("\n");

    if (event === "chunk") {
      onChunk(data);
    } else if (event === "question") {
      onQuestion?.(data);
    } else if (event === "sources") {
      try {
        onSources(JSON.parse(data));
      } catch {
        /* ignore malformed sources */
      }
    } else if (event === "error") {
      onError(data || "Generation failed");
    }
    // "done" needs no handling — the stream simply ends
  }
}

// ─── App (router) ───────────────────────────────────────────

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("kibana_oo_token") || null
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("kibana_oo_user") || ""
  );
  const [view, setView] = useState("chat"); // "chat" | "dashboard" | "documents" | "settings"
  const [perms, setPerms] = useState(null); // { is_super, features[], catalog[] } | null
  const can = useCallback(
    (f) => !!perms && (perms.is_super || (perms.features || []).includes(f)),
    [perms]
  );
  const isSuper = !!perms && perms.is_super;
  const isAdmin = !!perms && (perms.is_super || (perms.features || []).length > 0);
  // Navigate between views, optionally deep-linking a document to trace (used by
  // the dashboard "documents at risk" list and the header badge).
  const [pendingTrace, setPendingTrace] = useState(null);
  const navigate = useCallback((nextView, traceId = null) => {
    setPendingTrace(traceId);
    setView(nextView);
  }, []);
  // LLM provider is global: visible + switchable from every page, persisted,
  // and synced to the backend session here so it applies no matter which page
  // you switch it on.
  const [llmProvider, setLlmProvider] = useState(
    () => sessionStorage.getItem(LLM_PROVIDER_KEY) || "ollama"
  );
  // Master AI on/off (admin Settings). When off, the effective provider sent to
  // the backend is "none" — every AI surface is hidden and the backend short-
  // circuits all generation to its deterministic fallbacks. The selected
  // provider (ollama/mistral) is remembered so flipping back restores it.
  const [aiEnabled, setAiEnabled] = useState(
    () => sessionStorage.getItem(AI_ENABLED_KEY) !== "off"
  );
  const effectiveProvider = aiEnabled ? llmProvider : "none";

  useEffect(() => {
    sessionStorage.setItem(LLM_PROVIDER_KEY, llmProvider);
  }, [llmProvider]);
  useEffect(() => {
    sessionStorage.setItem(AI_ENABLED_KEY, aiEnabled ? "on" : "off");
    document.documentElement.dataset.provider = effectiveProvider; // themes every header
  }, [aiEnabled, effectiveProvider]);

  // Push the effective provider to the backend session whenever it changes.
  useEffect(() => {
    if (!token) return;
    fetch(`${BACKEND_URL}/llm-provider?provider=${encodeURIComponent(effectiveProvider)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
  }, [effectiveProvider, token]);

  // One handler for every provider control (the header pill and the admin
  // radios). "none" switches AI off; a real provider switches it on and is
  // remembered, so toggling back restores the last choice.
  const handleProviderChange = useCallback((next) => {
    if (next === "none") {
      setAiEnabled(false);
    } else {
      setLlmProvider(next);
      setAiEnabled(true);
    }
  }, []);

  // Feature toggles (managed from the admin Settings tab; persisted per session).
  // Defaults: a clean, minimal chat — the welcome screen and composer hint are
  // hidden, auto-correct is on.
  const [autocorrect, setAutocorrect] = useState(
    () => sessionStorage.getItem(AUTOCORRECT_KEY) !== "off"
  );
  const [showWelcome, setShowWelcome] = useState(
    () => sessionStorage.getItem(SHOW_WELCOME_KEY) === "on"
  );
  const [showHint, setShowHint] = useState(
    () => sessionStorage.getItem(SHOW_HINT_KEY) === "on"
  );
  // Quick-question chips are ON by default — the fast path for common questions.
  const [showSuggestions, setShowSuggestions] = useState(
    () => sessionStorage.getItem(SHOW_SUGGESTIONS_KEY) !== "off"
  );
  // Dashboard: the hover "card detail" panel (SmartContextPanel) — ON by default.
  const [showCardDetails, setShowCardDetails] = useState(
    () => sessionStorage.getItem(SHOW_CARD_DETAILS_KEY) !== "off"
  );
  useEffect(() => sessionStorage.setItem(AUTOCORRECT_KEY, autocorrect ? "on" : "off"), [autocorrect]);
  useEffect(() => sessionStorage.setItem(SHOW_WELCOME_KEY, showWelcome ? "on" : "off"), [showWelcome]);
  useEffect(() => sessionStorage.setItem(SHOW_HINT_KEY, showHint ? "on" : "off"), [showHint]);
  useEffect(() => sessionStorage.setItem(SHOW_SUGGESTIONS_KEY, showSuggestions ? "on" : "off"), [showSuggestions]);
  useEffect(() => sessionStorage.setItem(SHOW_CARD_DETAILS_KEY, showCardDetails ? "on" : "off"), [showCardDetails]);

  // Dashboard section visibility (show/hide whole blocks) — one object, default all on.
  const [dashSections, setDashSections] = useState(() => {
    try {
      return { ...DASH_SECTION_DEFAULTS, ...JSON.parse(sessionStorage.getItem(DASH_SECTIONS_KEY) || "{}") };
    } catch {
      return { ...DASH_SECTION_DEFAULTS };
    }
  });
  useEffect(() => sessionStorage.setItem(DASH_SECTIONS_KEY, JSON.stringify(dashSections)), [dashSections]);
  const setDashSection = useCallback((key, val) => setDashSections((s) => ({ ...s, [key]: val })), []);

  const settings = {
    aiEnabled, setAiEnabled,
    autocorrect, setAutocorrect,
    showWelcome, setShowWelcome,
    showHint, setShowHint,
    showSuggestions, setShowSuggestions,
    showCardDetails, setShowCardDetails,
    dashSections, setDashSection,
  };

  // Global proactive alert: how many documents are stuck in the pipeline. Polled
  // for admins so it shows in every header, on every tab (the cached endpoint
  // keeps this cheap).
  const [stuckCount, setStuckCount] = useState(0);
  const [aanleverCount, setAanleverCount] = useState(0);
  const [dlqCount, setDlqCount] = useState(0);
  useEffect(() => {
    if (!token || !isAdmin) {
      setStuckCount(0);
      setAanleverCount(0);
      setDlqCount(0);
      return;
    }
    let active = true;
    const poll = () => {
      if (can("pipeline_health")) {
        getJSON("/dashboard/pipeline-health", token)
          .then((d) => active && setStuckCount(d.stuck_count || 0))
          .catch(() => {});
      }
      if (can("aanleverfouten")) {
        getJSON("/dashboard/aanleverfouten", token)
          .then((d) => active && setAanleverCount(d.count || 0))
          .catch(() => {});
      }
      if (can("rabbitmq")) {
        getJSON("/dashboard/dlq", token)
          .then((d) => active && setDlqCount(d.count || 0))
          .catch(() => {});
      }
    };
    poll();
    const id = setInterval(poll, 60000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [token, isAdmin, can]);

  // What this user may see/do — drives page/card gating (deny-by-default).
  useEffect(() => {
    if (!token) {
      setPerms(null);
      return;
    }
    let active = true;
    getJSON("/me/permissions", token)
      .then((p) => active && setPerms(p))
      .catch(() => active && setPerms({ is_super: false, features: [], catalog: [] }));
    return () => {
      active = false;
    };
  }, [token]);

  function handleLogin(newToken, user) {
    setToken(newToken);
    setUsername(user);
    sessionStorage.setItem("kibana_oo_token", newToken);
    sessionStorage.setItem("kibana_oo_user", user);
  }

  function handleLogout() {
    setToken(null);
    setUsername("");
    setView("chat");
    sessionStorage.removeItem("kibana_oo_token");
    sessionStorage.removeItem("kibana_oo_user");
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />;
  }

  if (view === "dashboard" && can("dashboard")) {
    return (
      <DashboardPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        aiEnabled={aiEnabled}
        showCardDetails={showCardDetails}
        dashSections={dashSections}
        can={can}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        isAdmin={isAdmin}
      />
    );
  }

  if (view === "documents" && can("documents")) {
    return (
      <DocumentsPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        aiEnabled={aiEnabled}
        can={can}
        isAdmin={isAdmin}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        initialTraceId={pendingTrace}
      />
    );
  }

  if (view === "admin" && isAdmin) {
    return (
      <AdminPage
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        can={can}
        isSuper={isSuper}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        isAdmin={isAdmin}
      />
    );
  }

  if (view === "authorization" && isSuper) {
    return (
      <AuthorizationPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        can={can}
        isSuper={isSuper}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        isAdmin={isAdmin}
      />
    );
  }

  if (view === "regression" && can("regression")) {
    return (
      <RegressionPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        can={can}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        isAdmin={isAdmin}
      />
    );
  }

  if (view === "dlq-intel" && can("rabbitmq")) {
    return (
      <DlqIntelPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        can={can}
        isAdmin={isAdmin}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
      />
    );
  }

  if (view === "alerts" && can("alerts")) {
    return (
      <AlertsPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        onProviderChange={handleProviderChange}
        can={can}
        isAdmin={isAdmin}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
      />
    );
  }

  if (view === "settings" && can("settings")) {
    return (
      <SettingsPage
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={effectiveProvider}
        selectedProvider={llmProvider}
        onProviderChange={handleProviderChange}
        settings={settings}
        can={can}
        stuckCount={stuckCount}
        aanleverCount={aanleverCount}
        dlqCount={dlqCount}
        isAdmin={isAdmin}
      />
    );
  }

  return (
    <ChatPage
      token={token}
      username={username}
      onLogout={handleLogout}
      isAdmin={isAdmin}
      can={can}
      onNavigate={navigate}
      llmProvider={effectiveProvider}
      onProviderChange={handleProviderChange}
      aiEnabled={aiEnabled}
      autocorrect={autocorrect}
      showWelcome={showWelcome}
      showHint={showHint}
      showSuggestions={showSuggestions}
      stuckCount={stuckCount}
      aanleverCount={aanleverCount}
      dlqCount={dlqCount}
    />
  );
}
