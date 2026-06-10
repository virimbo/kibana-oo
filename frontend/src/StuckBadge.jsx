// A global alert pill shown in every header (admins only): how many documents
// are stuck or failing in the pipeline right now. Click to jump to the
// Documents tab. Hidden when nothing is stuck.
export default function StuckBadge({ count, onNavigate }) {
  if (!count) return null;
  return (
    <button
      type="button"
      className="stuck-hdr"
      onClick={() => onNavigate("documents")}
      title={`${count} document${count === 1 ? "" : "s"} stuck or failing in the pipeline — click to view`}
    >
      <span className="stuck-hdr-dot" aria-hidden="true">🚦</span>
      {count} stuck
    </button>
  );
}
