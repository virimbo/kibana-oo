---
title: open.overheid.nl API
tags: [reference, portal, api]
---

# open.overheid.nl API

Back to [[Home]]. Implemented in `backend/portal.py`.

## Why

The public portal `open.overheid.nl/details/<uuid>` is a **JavaScript SPA** —
fetching it returns ~600 bytes with the title "Open overheid" only. The real
metadata comes from its JSON API.

## Endpoint

```
GET https://open.overheid.nl/overheid/openbaarmakingen/api/v0/zoek/{uuid}
Accept: application/json
```

Only **UUID** publication ids resolve here; internal `ronl-…` ids do not.

## Useful fields

| Field path | Meaning |
|---|---|
| `document.titelcollectie.officieleTitel` | **official title** |
| `document.verantwoordelijke.label` / `publisher.label` | organization |
| `document.classificatiecollectie.documentsoorten[0].label` | type (e.g. "Kamerbrief") |
| `document.classificatiecollectie.informatiecategorieen[0].label` | Woo category |
| `plooiIntern.publicatiestatus` | status (e.g. "gepubliceerd") |
| `versies[0].openbaarmakingsdatum` | publication date |
| `versies[0].bestanden[0]` | file info (pages, size, mime) |
| `document.pid` | canonical link `…/documenten/{uuid}` |

## In code

- `portal.fetch_document_meta(id)` — cached (1h), **non-fatal**, UUID-only,
  negatively caches failures. Used by the [[Document tracer]] and by doc-id
  questions in the [[Chat pipeline]].
- Reachable from the backend container (outbound egress OK).

## Related

- [[Document tracer]] · [[KOOP Plooi log schema]]
