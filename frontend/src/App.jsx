import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";

const SUGGESTIONS = [
  "Are there any errors in the last hour?",
  "Show me recent log activity",
  "What services are reporting high latency?",
  "Summarize the last 30 minutes of logs",
];

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

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
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>KIBANA-OO</h1>
        <p className="login-subtitle">AI Log Assistant</p>
        <p className="login-desc">
          Sign in with your Kibana credentials to start asking questions about
          your logs and metrics.
        </p>

        <form onSubmit={handleLogin}>
          <label>
            Username
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Your Kibana username"
              autoFocus
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your Kibana password"
              required
            />
          </label>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" disabled={loading}>
            {loading ? "Connecting..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ─── Chat Page ──────────────────────────────────────────────

function ChatPage({ token, username, onLogout }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [timeRange, setTimeRange] = useState(60);
  const [loading, setLoading] = useState(false);
  const chatRef = useRef(null);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  async function handleLogout() {
    await fetch(`${BACKEND_URL}/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
    onLogout();
  }

  async function sendMessage(question) {
    if (!question.trim() || loading) return;

    const userMsg = { role: "user", content: question };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const assistantMsg = { role: "assistant", content: "", sources: [] };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const response = await fetch(`${BACKEND_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question,
          time_range_minutes: timeRange,
          stream: true,
        }),
      });

      if (response.status === 401) {
        onLogout();
        return;
      }

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";
      let sources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const event of events) {
          const eventMatch = event.match(/event:\s*(\w+)/);
          const dataMatch = event.match(/data:\s*(.*)/s);

          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1];
          const eventData = dataMatch[1].trim();

          if (eventType === "chunk") {
            fullContent += eventData;
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: fullContent,
                sources,
              };
              return updated;
            });
          } else if (eventType === "sources") {
            try {
              sources = JSON.parse(eventData);
            } catch {
              // ignore
            }
          } else if (eventType === "error") {
            fullContent += `\n\n**Error:** ${eventData}`;
          }
        }
      }

      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: fullContent || "No response received.",
          sources,
        };
        return updated;
      });
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: `**Connection error:** ${err.message}. Make sure the backend and Ollama are running.`,
          sources: [],
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
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
        <h1>KIBANA-OO</h1>
        <div className="header-right">
          <span className="header-user">{username}</span>
          <button className="logout-btn" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="chat-container" ref={chatRef}>
        {messages.length === 0 ? (
          <div className="welcome">
            <h2>Ask anything about your logs & metrics</h2>
            <p>
              KIBANA-OO searches your Elasticsearch cluster (koop-plooi-prod)
              and uses LLAMA to answer your questions in natural language.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="suggestion"
                  onClick={() => sendMessage(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              {msg.role === "assistant" ? (
                <>
                  {msg.content ? (
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  ) : (
                    <span className="loading-dots">Thinking</span>
                  )}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="sources">
                      Sources: {msg.sources.length} log entries from{" "}
                      {[...new Set(msg.sources.map((s) => s.index))].join(", ")}
                    </div>
                  )}
                </>
              ) : (
                msg.content
              )}
            </div>
          ))
        )}
      </div>

      <div className="input-area">
        <div className="input-row">
          <select
            className="time-select"
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
          >
            <option value={15}>Last 15m</option>
            <option value={30}>Last 30m</option>
            <option value={60}>Last 1h</option>
            <option value={360}>Last 6h</option>
            <option value={1440}>Last 24h</option>
          </select>
          <input
            type="text"
            placeholder="Ask about your logs and metrics..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
          >
            {loading ? "..." : "Send"}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── App (router) ───────────────────────────────────────────

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("kibana_oo_token") || null
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("kibana_oo_user") || ""
  );

  function handleLogin(newToken, user) {
    setToken(newToken);
    setUsername(user);
    sessionStorage.setItem("kibana_oo_token", newToken);
    sessionStorage.setItem("kibana_oo_user", user);
  }

  function handleLogout() {
    setToken(null);
    setUsername("");
    sessionStorage.removeItem("kibana_oo_token");
    sessionStorage.removeItem("kibana_oo_user");
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <ChatPage token={token} username={username} onLogout={handleLogout} />
  );
}
