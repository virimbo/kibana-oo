// Global alert pill (admins with the rabbitmq feature): how many RabbitMQ
// dead-letter queues currently hold messages. Click → dashboard. Hidden at zero.
export default function DlqBadge({ count, onNavigate }) {
  if (!count) return null;
  return (
    <button
      type="button"
      className="dlq-hdr"
      onClick={() => onNavigate("dashboard")}
      title={`${count} dead-letter queue${count === 1 ? "" : "s"} met stuck messages — klik om te bekijken`}
    >
      <span className="dlq-hdr-dot" aria-hidden="true">🐰</span>
      {count} DLQ
    </button>
  );
}
