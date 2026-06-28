// Shared chat-scope presets — the time-range options used by both the chat
// composer and the admin "default scope" settings, so the two never drift.
export const TIME_RANGES = [
  { value: 15, label: "Laatste 15 min" },
  { value: 30, label: "Laatste 30 min" },
  { value: 60, label: "Laatste 1 uur" },
  { value: 360, label: "Laatste 6 uur" },
  { value: 1440, label: "Laatste 24 uur" },
];

// Fallback data-view list — mirrors the backend's /data-views default and is
// only used when that endpoint is unreachable.
export const FALLBACK_DATA_VIEWS = [
  { id: "logs-*", label: "Alle logs" },
  { id: "ds-prod5-koop-plooi*", label: "KOOP Plooi (prod5)" },
  { id: "ds-prod5-koop-sp", label: "KOOP SP (prod5)" },
  { id: "apm-*", label: "APM" },
];
