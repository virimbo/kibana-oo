import { useState, useEffect } from "react";
import { getJSON } from "./api";

// Infra / Grafana deep-links — one-click cards that open an external dashboard in
// a new tab. Read-only: we only render admin-configured URLs (no credentials).

export default function InfraLinks({ token }) {
  const [links, setLinks] = useState(null); // null = loading

  useEffect(() => {
    let on = true;
    getJSON("/dashboard/infra/links", token)
      .then((d) => on && setLinks(d.links || []))
      .catch(() => on && setLinks([]));
    return () => { on = false; };
  }, [token]);

  if (!links || links.length === 0) return null; // no links / no perms

  return (
    <section className="panel" data-smartcard="card:grafana" data-smartlabel="Grafana / Infrastructuur">
      <h3>🛠 Infrastructuur — Grafana</h3>
      <div className="infra-links">
        {links.map((l, i) => (
          <a
            key={i}
            className="infra-link"
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            title={l.url}
          >
            <span className="infra-link-main">
              <span className="infra-link-name">{l.name}</span>
              <span className="infra-link-host">{l.host} ↗</span>
            </span>
            {l.env && <span className={`infra-env infra-env--${l.env.toLowerCase()}`}>{l.env}</span>}
          </a>
        ))}
      </div>
    </section>
  );
}
