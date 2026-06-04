import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";

const SUGGESTIONS = [
  "Are there any errors in the last hour?",
  "Show me recent log activity",
  "What services are reporting high latency?",
  "Summarize the last 30 minutes of logs",
];

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [timeRange, setTimeRange] = useState(60);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState({ ok: false, checked: false });
  const chatRef = useRef(null);

  // Health check on mount
  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then((r) => r.json())
      .then((data) => setStatus({ ok: data.status === "ok", checked: true }))
      .catch(() => setStatus({ ok: false, checked: true }));
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          time_range_minutes: timeRange,
          stream: true,
        }),
      });

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
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            // Check for event type from previous line
            continue;
          }
          if (line.startsWith("event: ")) {
            continue;
          }

          // Parse SSE format: "event: X\ndata: Y"
          if (line.trim() === "") continue;
        }

        // Simpler SSE parsing: look for event/data pairs in the full buffer
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
              // ignore parse errors
            }
          } else if (eventType === "error") {
            fullContent += `\n\n**Error:** ${eventData}`;
          }
        }
      }

      // Final update with sources
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
        <div className="status">
          <span
            className={`status-dot ${status.checked && !status.ok ? "error" : ""}`}
          />
          <span style={{ color: "var(--text-secondary)" }}>
            {!status.checked
              ? "Connecting..."
              : status.ok
                ? "Connected"
                : "Disconnected"}
          </span>
        </div>
      </header>

      <div className="chat-container" ref={chatRef}>
        {messages.length === 0 ? (
          <div className="welcome">
            <h2>Ask anything about your logs & metrics</h2>
            <p>
              KIBANA-OO searches your Elasticsearch cluster (koop-plooi-prod) and
              uses LLAMA to answer your questions in natural language.
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
          <button onClick={() => sendMessage(input)} disabled={loading || !input.trim()}>
            {loading ? "..." : "Send"}
          </button>
        </div>
      </div>
    </>
  );
}
