import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import DashboardPage from "./Dashboard";
import DocumentsPage from "./Documents";
import SettingsPage from "./Settings";
import ProviderSwitcher from "./ProviderSwitcher";
import StuckBadge from "./StuckBadge";

const SUGGESTIONS = [
  {
    title: "🚨 Critical errors now",
    prompt:
      "What are the most critical errors in the last hour? Group them by service, give the count per service, and explain the likely cause of the worst one.",
  },
  {
    title: "🩺 Failing services",
    prompt:
      "Which services are failing, erroring or unhealthy right now? List the worst first with what's going wrong.",
  },
  {
    title: "📄 Publication problems",
    prompt:
      "Are there errors that would stop documents being published — connection resets, timeouts, indexing/mapping failures, or 5xx? Summarize what's at risk.",
  },
  {
    title: "🔎 Anything unusual?",
    prompt:
      "Summarize the last 30 minutes of activity and flag anything unusual or risky that an admin should look at.",
  },
];

const TIME_RANGES = [
  { value: 15, label: "Last 15 min" },
  { value: 30, label: "Last 30 min" },
  { value: 60, label: "Last 1 hour" },
  { value: 360, label: "Last 6 hours" },
  { value: 1440, label: "Last 24 hours" },
];

// Fallback used only if the backend's /data-views endpoint is unreachable.
const DEFAULT_DATA_VIEWS = [
  { id: "logs-*", label: "All logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
];

const DATA_VIEW_KEY = "kibana_oo_dataview";
const LLM_PROVIDER_KEY = "kibana_oo_llm_provider";
const AUTOCORRECT_KEY = "kibana_oo_autocorrect";
const SHOW_WELCOME_KEY = "kibana_oo_show_welcome";
const SHOW_HINT_KEY = "kibana_oo_show_hint";
const SHOW_SUGGESTIONS_KEY = "kibana_oo_show_suggestions";

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
        throw new Error(data.detail || "Login failed");
      }

      const data = await res.json();
      onLogin(data.token, data.username);
    } catch (err) {
      setError(
        err.message === "Failed to fetch"
          ? "Cannot reach the backend. Make sure it is running."
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
          <span className="brand-name">KIBANA-OO</span>
        </div>
        <p className="login-desc">
          Sign in with your Kibana credentials to ask questions about your
          logs and metrics in plain language.
        </p>
        <p className="ai-disclosure">
          This application uses an AI system (Llama or Mistral) to generate answers based
          on your log data. Responses are AI-generated and should be verified.
        </p>

        <form onSubmit={handleLogin}>
          <label>
            <span>Username</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="your.name@koop.overheid.nl"
              autoFocus
              required
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your Kibana password"
              required
            />
          </label>

          {error && (
            <div className="alert alert--error" role="alert">
              {error}
            </div>
          )}

          <button type="submit" className="btn btn--primary" disabled={loading}>
            {loading ? "Connecting…" : "Sign in"}
          </button>
        </form>

        <p className="login-foot">
          Connected to <code>koop-plooi-prod</code>
        </p>
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
      title={copied ? "Copied" : "Copy answer"}
      aria-label="Copy answer"
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
          <span className="msg-name">KIBANA-OO</span>
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
  token, username, onLogout, isAdmin, onNavigate,
  llmProvider, onProviderChange,
  autocorrect, showWelcome, showHint, showSuggestions, stuckCount,
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
            "_The connection ended before an answer arrived. Please try again — if it persists, check that the backend and Ollama are running._",
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
              ? "Cannot reach the backend. Make sure the backend and Ollama are running."
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
      <header className="header">
        <div className="brand">
          <span className="brand-mark">
            <Icon.Spark />
          </span>
          <div className="brand-text">
            <span className="brand-name">KIBANA-OO</span>
            <span className="brand-sub">AI Log Assistant · koop-plooi-prod</span>
          </div>
        </div>
        <div className="header-right">
          <span className={`status status--${connected === null ? "idle" : connected ? "ok" : "down"}`}>
            <span className="status-dot" />
            {connected === null ? "Checking" : connected ? "Connected" : "Offline"}
          </span>
          {isAdmin && <StuckBadge count={stuckCount} onNavigate={onNavigate} />}
          <ProviderSwitcher value={llmProvider} onChange={onProviderChange} disabled={loading} />
          {isAdmin && (
            <>
              <button className="btn btn--ghost" onClick={() => onNavigate("dashboard")}>
                Dashboard
              </button>
              <button className="btn btn--ghost" onClick={() => onNavigate("documents")}>
                Documents
              </button>
              <button className="btn btn--ghost" onClick={() => onNavigate("settings")} title="Settings">
                <Icon.Gear />
              </button>
            </>
          )}
          <span className="header-user">{username}</span>
          <button className="btn btn--ghost" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-column">
          {messages.length === 0 ? (
            <div className="empty-state">
              {showWelcome && (
                <div className="welcome">
                  <span className="welcome-mark">
                    <Icon.Spark />
                  </span>
                  <h2>Ask anything about your logs &amp; metrics</h2>
                  <p>
                    KIBANA-OO searches your Elasticsearch cluster and uses an AI model
                    to answer in natural language — with the source log entries cited.
                  </p>
                  <p className="ai-disclosure ai-disclosure--chat">
                    You are interacting with an AI system. Responses are generated
                    by a Llama or Mistral language model and may contain inaccuracies. Always
                    verify critical findings in Kibana.
                  </p>
                </div>
              )}
              {showSuggestions && (
                <div className="quick-start">
                  <span className="quick-start-label">Quick questions</span>
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
              <span className="control-label">Data view</span>
              <select
                className="control-select"
                value={dataView}
                onChange={(e) => setDataView(e.target.value)}
                disabled={loading}
                title="Elasticsearch data view to search"
              >
                {dataViews.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label && v.label !== v.id ? `${v.id} — ${v.label}` : v.id}
                  </option>
                ))}
              </select>
            </label>

            <label className="control">
              <span className="control-label">Time range</span>
              <select
                className="control-select"
                value={timeRange}
                onChange={(e) => setTimeRange(Number(e.target.value))}
                disabled={loading}
                title="Time range to search"
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
                title="Remove image"
                aria-label="Remove image"
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
              title="Attach a screenshot (or paste an image)"
              aria-label="Attach image"
            >
              <Icon.Paperclip />
            </button>

            <div className="composer-field">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={
                  image
                    ? "Add a question about the image… (optional)"
                    : "Ask about your logs and metrics…  (Enter to send, Shift+Enter for a new line, paste a screenshot)"
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
            Querying <code>{dataView}</code> · answers are generated from live log
            data. Always verify critical findings in Kibana.
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
  const [isAdmin, setIsAdmin] = useState(false);
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

  useEffect(() => {
    sessionStorage.setItem(LLM_PROVIDER_KEY, llmProvider);
    document.documentElement.dataset.provider = llmProvider; // themes every header
  }, [llmProvider]);

  // Push the provider to the backend session (query param) whenever it changes.
  useEffect(() => {
    if (!token) return;
    fetch(`${BACKEND_URL}/llm-provider?provider=${encodeURIComponent(llmProvider)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
  }, [llmProvider, token]);

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
  useEffect(() => sessionStorage.setItem(AUTOCORRECT_KEY, autocorrect ? "on" : "off"), [autocorrect]);
  useEffect(() => sessionStorage.setItem(SHOW_WELCOME_KEY, showWelcome ? "on" : "off"), [showWelcome]);
  useEffect(() => sessionStorage.setItem(SHOW_HINT_KEY, showHint ? "on" : "off"), [showHint]);
  useEffect(() => sessionStorage.setItem(SHOW_SUGGESTIONS_KEY, showSuggestions ? "on" : "off"), [showSuggestions]);

  const settings = {
    autocorrect, setAutocorrect,
    showWelcome, setShowWelcome,
    showHint, setShowHint,
    showSuggestions, setShowSuggestions,
  };

  // Global proactive alert: how many documents are stuck in the pipeline. Polled
  // for admins so it shows in every header, on every tab (the cached endpoint
  // keeps this cheap).
  const [stuckCount, setStuckCount] = useState(0);
  useEffect(() => {
    if (!token || !isAdmin) {
      setStuckCount(0);
      return;
    }
    let active = true;
    const poll = () =>
      getJSON("/dashboard/pipeline-health", token)
        .then((d) => active && setStuckCount(d.stuck_count || 0))
        .catch(() => {});
    poll();
    const id = setInterval(poll, 60000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [token, isAdmin]);

  // Probe admin access: 403 means non-admin; 200/502 means admin (endpoint reached).
  useEffect(() => {
    if (!token) {
      setIsAdmin(false);
      return;
    }
    let active = true;
    // 200 → admin; 502 → admin but ES is down (gating passed before the query);
    // 403/401 → not an admin / no valid session.
    getJSON("/dashboard/summary", token)
      .then(() => active && setIsAdmin(true))
      .catch(
        (e) =>
          active &&
          setIsAdmin(e.message !== "forbidden" && e.message !== "unauthorized")
      );
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

  if (view === "dashboard" && isAdmin) {
    return (
      <DashboardPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={llmProvider}
        onProviderChange={setLlmProvider}
        stuckCount={stuckCount}
      />
    );
  }

  if (view === "documents" && isAdmin) {
    return (
      <DocumentsPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={llmProvider}
        onProviderChange={setLlmProvider}
        stuckCount={stuckCount}
        initialTraceId={pendingTrace}
      />
    );
  }

  if (view === "settings" && isAdmin) {
    return (
      <SettingsPage
        username={username}
        onLogout={handleLogout}
        onNavigate={navigate}
        llmProvider={llmProvider}
        onProviderChange={setLlmProvider}
        settings={settings}
        stuckCount={stuckCount}
      />
    );
  }

  return (
    <ChatPage
      token={token}
      username={username}
      onLogout={handleLogout}
      isAdmin={isAdmin}
      onNavigate={navigate}
      llmProvider={llmProvider}
      onProviderChange={setLlmProvider}
      autocorrect={autocorrect}
      showWelcome={showWelcome}
      showHint={showHint}
      showSuggestions={showSuggestions}
      stuckCount={stuckCount}
    />
  );
}
