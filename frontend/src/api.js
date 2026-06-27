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

// ─── DLQ Intelligence (Beheer/Dashboard → 🔍 Intelligentie) ──────────────────
export const fetchDlqIntel = (token) => getJSON("/dashboard/dlq/intel", token);

// ─── Service health (backend microservices) ──────────────────────────────────
export const fetchServiceHealth = (token) => getJSON("/dashboard/service-health", token);

// ─── Monitoring Targets registry (Beheer → Monitoring) ───────────────────────
export const fetchMonitorTypes = (token) => getJSON("/monitor/types", token);
export const fetchMonitorConnections = (token) => getJSON("/monitor/connections", token);
export const addMonitorConnection = (token, body) => sendJSON("/monitor/connections", token, "POST", body);
export const deleteMonitorConnection = (token, id) => sendJSON(`/monitor/connections/${id}`, token, "DELETE");
export const fetchMonitorTargets = (token) => getJSON("/monitor/targets", token);
export const addMonitorTarget = (token, body) => sendJSON("/monitor/targets", token, "POST", body);
export const patchMonitorTarget = (token, id, patch) => sendJSON(`/monitor/targets/${id}`, token, "PATCH", patch);
export const deleteMonitorTarget = (token, id) => sendJSON(`/monitor/targets/${id}`, token, "DELETE");
export const testMonitorTarget = (token, body) => sendJSON("/monitor/test", token, "POST", body);
export const discoverMonitor = (token, connectionId) => getJSON(`/monitor/discover?connection_id=${connectionId}`, token);
