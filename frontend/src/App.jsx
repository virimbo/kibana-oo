import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";
import DashboardPage from "./Dashboard";
import DocumentsPage from "./Documents";

const SUGGESTIONS = [
  {
    title: "Recent errors",
    prompt: "Are there any errors in the last hour? Group them by service.",
  },
  {
    title: "Activity overview",
    prompt: "Summarize recent log activity and highlight anything unusual.",
  },
  {
    title: "Latency check",
    prompt: "What services are reporting high latency or slow responses?",
  },
  {
    title: "30-minute summary",
    prompt: "Summarize the last 30 minutes of logs.",
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

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

// Available LLM providers
const LLM_PROVIDERS = ["ollama", "mistral"];

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
};

// ─── Login Page ─────────────────────────────────────────────

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("anton.partono@koop.overheid.nl");
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
          {msg.time && <span className="msg-time">{fmtTime(msg.time)}</span>}
          <span className="msg-name">You</span>
        </div>
        <div className="bubble bubble--user">{msg.content}</div>
      </div>
    </div>
  );
}

// ─── Chat Page ──────────────────────────────────────────────

function ChatPage({ token, username, onLogout, isAdmin, onNavigate }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [timeRange, setTimeRange] = useState(60);
  const [dataViews, setDataViews] = useState(DEFAULT_DATA_VIEWS);
  const [dataView, setDataView] = useState(
    () => sessionStorage.getItem(DATA_VIEW_KEY) || DEFAULT_DATA_VIEWS[0].id
  );
  const [llmProvider, setLlmProvider] = useState(
    () => sessionStorage.getItem(LLM_PROVIDER_KEY) || "ollama"
  );
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(null); // null = unknown
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const abortRef = useRef(null);
  const stickRef = useRef(true);

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

  // Persist the selected LLM provider across reloads
  useEffect(() => {
    sessionStorage.setItem(LLM_PROVIDER_KEY, llmProvider);
  }, [llmProvider]);

  // When the LLM provider changes (and on load), update the backend session.
  // The endpoint takes `provider` as a query parameter.
  useEffect(() => {
    if (token) {
      fetch(`${BACKEND_URL}/llm-provider?provider=${encodeURIComponent(llmProvider)}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
  }, [llmProvider, token]);

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
      if (!q || loading) return;

      stickRef.current = true;
      setInput("");
      setLoading(true);
      setMessages((prev) => [
        ...prev,
        { role: "user", content: q, time: new Date() },
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
          onError: (detail) => {
            throw new Error(detail);
          },
        });

        updateLast((m) => ({
          ...m,
          status: "done",
          content: m.content || "_No matching data found for this time range._",
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
    [loading, timeRange, dataView, token, onLogout]
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
          <select
            className="control-select provider-select"
            value={llmProvider}
            onChange={(e) => setLlmProvider(e.target.value)}
            title="AI model provider (chat & dashboard triage)"
          >
            <option value="ollama">AI: Ollama (local)</option>
            <option value="mistral">AI: Mistral (cloud)</option>
          </select>
          {isAdmin && (
            <>
              <button className="btn btn--ghost" onClick={() => onNavigate("dashboard")}>
                Dashboard
              </button>
              <button className="btn btn--ghost" onClick={() => onNavigate("documents")}>
                Documents
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
              <span className="control-label">LLM Provider</span>
              <select
                className="control-select"
                value={llmProvider}
                onChange={(e) => setLlmProvider(e.target.value)}
                disabled={loading}
                title="Select LLM provider (Ollama for local Llama, Mistral for cloud)"
              >
                {LLM_PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {p.charAt(0).toUpperCase() + p.slice(1)}
                  </option>
                ))}
              </select>
            </label>

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

          <div className="composer-row">
            <div className="composer-field">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder="Ask about your logs and metrics…  (Enter to send, Shift+Enter for a new line)"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
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
                disabled={!input.trim()}
                title="Send"
              >
                <Icon.Send />
              </button>
            )}
          </div>
        </div>
        <p className="composer-hint">
          Querying <code>{dataView}</code> · answers are generated from live log
          data. Always verify critical findings in Kibana.
        </p>
      </div>
    </>
  );
}

// ─── SSE parsing ────────────────────────────────────────────

async function consumeSSE(body, signal, { onChunk, onSources, onError }) {
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
  const [view, setView] = useState("chat"); // "chat" | "dashboard"
  const [isAdmin, setIsAdmin] = useState(false);

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
        onNavigate={setView}
      />
    );
  }

  if (view === "documents" && isAdmin) {
    return (
      <DocumentsPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onNavigate={setView}
      />
    );
  }

  return (
    <ChatPage
      token={token}
      username={username}
      onLogout={handleLogout}
      isAdmin={isAdmin}
      onNavigate={setView}
    />
  );
}
