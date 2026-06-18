const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

export async function getJSON(path, token, signal) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (res.status === 403) throw new Error("forbidden");
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Server error: ${res.status}`);
  }
  return res.json();
}

async function sendJSON(path, token, method, body) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (res.status === 403) throw new Error("forbidden");
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Server error: ${res.status}`);
  }
  return res.json();
}

// ─── Unified alerting (Beheer → Alerting) ────────────────────────────────────
export const fetchAlertsStatus = (token) => getJSON("/alerts/status", token);
export const fetchAlertsHistory = (token) => getJSON("/alerts/history", token);
export const putAlertToggle = (token, body) => sendJSON("/alerts/toggle", token, "PUT", body);
export const putAlertConfig = (token, body) => sendJSON("/alerts/config", token, "PUT", body);
