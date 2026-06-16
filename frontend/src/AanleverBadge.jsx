// A global alert pill (admins only): how many documents are currently rejected
// at delivery (aanleverfouten) and not yet fixed. Click to jump to the dashboard
// card. Hidden when there are none.
export default function AanleverBadge({ count, onNavigate }) {
  if (!count) return null;
  return (
    <button
      type="button"
      className="aanlever-hdr"
      onClick={() => onNavigate("dashboard")}
      title={`${count} aanleverfout${count === 1 ? "" : "en"} — documenten geweigerd bij aanlevering, nog te herstellen. Klik om te bekijken.`}
    >
      <span className="aanlever-hdr-dot" aria-hidden="true">⚠</span>
      {count} aanleverfout{count === 1 ? "" : "en"}
    </button>
  );
}
