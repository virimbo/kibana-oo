import { useState, useEffect } from "react";

// Shared time-range control for Dashboard + Documents: quick presets plus a
// custom absolute from→to window (any dates, including very old). The selection
// is a small object; helpers below turn it into query params and a label, and
// persist it so the window follows the admin across pages.

const PRESETS = [
  { value: 15, label: "Laatste 15 min" },
  { value: 30, label: "Laatste 30 min" },
  { value: 60, label: "Laatste 1 uur" },
  { value: 360, label: "Laatste 6 uur" },
  { value: 1440, label: "Laatste 24 uur" },
  { value: 10080, label: "Laatste 7 dagen" },
  { value: 43200, label: "Laatste 30 dagen" },
  { value: 129600, label: "Laatste 90 dagen" },
  { value: 525600, label: "Laatste 1 jaar" },
];

export const DEFAULT_RANGE = { mode: "preset", period: 60, from: null, to: null };

// Query-string fragment for the active window.
export function timeParams(r) {
  if (r && r.mode === "custom" && r.from && r.to) {
    return `from=${encodeURIComponent(r.from)}&to=${encodeURIComponent(r.to)}`;
  }
  return `period=${(r && r.period) || 60}`;
}

// Human label of the resolved window (absolute dates for a custom range).
export function rangeLabel(r) {
  if (r && r.mode === "custom" && r.from && r.to) {
    const f = new Date(r.from), t = new Date(r.to);
    return `${f.toLocaleString("nl-NL")} → ${t.toLocaleString("nl-NL")}`;
  }
  return PRESETS.find((p) => p.value === (r && r.period))?.label || `${r?.period || 60} min`;
}

const KEY = "kibana_oo_timerange";
export function loadRange() {
  try {
    const v = JSON.parse(sessionStorage.getItem(KEY));
    return v && v.mode ? v : DEFAULT_RANGE;
  } catch {
    return DEFAULT_RANGE;
  }
}
export function saveRange(r) {
  try { sessionStorage.setItem(KEY, JSON.stringify(r)); } catch { /* storage off */ }
}

// ISO ⇄ <input type="datetime-local"> (which works in local time, no tz suffix).
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function fromLocalInput(v) {
  return v ? new Date(v).toISOString() : null;
}

const DAY = 86400000;

export default function TimeRange({ value, onChange, disabled }) {
  const [custom, setCustom] = useState(value.mode === "custom");
  const [from, setFrom] = useState(toLocalInput(value.from));
  const [to, setTo] = useState(toLocalInput(value.to));
  const [err, setErr] = useState("");

  useEffect(() => { setCustom(value.mode === "custom"); }, [value.mode]);

  const onSelect = (v) => {
    if (v === "custom") { setCustom(true); setErr(""); return; }
    setCustom(false);
    onChange({ mode: "preset", period: Number(v), from: null, to: null });
  };

  const apply = () => {
    const f = fromLocalInput(from), t = fromLocalInput(to);
    if (!f || !t) { setErr("Kies zowel een begin als een einde."); return; }
    if (new Date(f) >= new Date(t)) { setErr("Begin moet vóór einde liggen."); return; }
    if (new Date(t) > new Date()) { setErr("Einde kan niet in de toekomst liggen."); return; }
    setErr("");
    onChange({ mode: "custom", period: value.period || 60, from: f, to: t });
  };

  const big = value.mode === "custom" && value.from && value.to &&
    new Date(value.to) - new Date(value.from) > 90 * DAY;

  return (
    <div className="timerange">
      <select
        className="control-select"
        value={custom ? "custom" : value.period}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
        title="Kies een snelle periode of een aangepast bereik"
      >
        {PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        <option value="custom">Aangepast bereik…</option>
      </select>

      {custom && (
        <div className="timerange-custom">
          <label className="timerange-field">
            <span>Van</span>
            <input type="datetime-local" value={from} max={to || undefined}
                   onChange={(e) => setFrom(e.target.value)} disabled={disabled} />
          </label>
          <label className="timerange-field">
            <span>Tot</span>
            <input type="datetime-local" value={to}
                   onChange={(e) => setTo(e.target.value)} disabled={disabled} />
          </label>
          <button type="button" className="btn btn--ghost" onClick={apply} disabled={disabled || !from || !to}>
            Toepassen
          </button>
          {err && <span className="timerange-err">{err}</span>}
        </div>
      )}

      <span className="timerange-label" title="De periode waarop de cijfers betrekking hebben">
        📅 {rangeLabel(value)}{big ? " · groot bereik (kan trager zijn)" : ""}
      </span>
    </div>
  );
}
