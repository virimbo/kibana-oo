---
title: Testing and CI
tags: [testing, docker]
category: "Referentie & ontwikkeling"
created: 2026-06-09
updated: 2026-06-09
---

# Testing and CI

Back to [[Home]].

## Run the backend tests (Docker python:3.13)

The host (Python 3.14) cannot build `pydantic-core` wheels, so tests run in a
`python:3.13` container with a cached pip volume.

```bash
cd backend
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd):/app" -v kibanaoo-pipcache:/root/.cache/pip -w /app \
  python:3.13-slim sh -c 'pip install -q -r requirements.txt && python -m pytest -q'
```

- `MSYS_NO_PATHCONV=1` stops Git Bash mangling the container paths on Windows.
- The image installs `tesseract-ocr` for the [[Chat pipeline|OCR]] feature at
  build time; the test image installs only Python deps (OCR tests exercise the
  non-Tesseract guard paths).

## Test files (`backend/tests/`)

- `test_monitoring.py` — snapshot fact layer ([[Monitoring dashboard]]).
- `test_portal.py` — [[open.overheid.nl API]] metadata extraction.
- `test_chat_doc_ids.py` — doc-id detection, all-views collection, generic
  fallback, instant + never-empty stream ([[Chat pipeline]]).
- `test_chat_image_polish.py` — OCR guards + grammar polish.

## Rebuild & verify the running stack

```bash
docker compose build backend frontend
docker compose up -d --force-recreate backend frontend
curl -s http://localhost:3000/health
```

## Related

- [[Architecture]] · [[Chat pipeline]]
