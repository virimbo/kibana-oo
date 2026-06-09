---
title: Chat pipeline
tags: [chat, backend]
---

# Chat pipeline

Back to [[Home]]. Endpoint: `POST /chat` in `backend/main.py`.

## What happens to a question

```
question (+ optional image, autocorrect flag)
   │
   ├─ OCR the image (ocr.image_to_text, off-thread)  ──> fold text into the question
   │
   ├─ extract_doc_ids(text)  (UUID or ronl-…)
   │
   ├─ CONCURRENTLY:
   │     • polish_text(question)         (spelling/grammar, id-safe)   [[LLM providers]]
   │     • _do_search()                  (the search below)
   │
   └─ stream the answer (SSE: question → chunk… → sources → done)
```

## Two search paths (`_do_search`)

### 1. Document-scoped (the question names a doc id)
- Trace each id across a **wide window (30 days)** and **every data view**
  (`_collect_doc_events`), tolerating per-view failures.
- Enrich with the official title/metadata from the [[open.overheid.nl API]].
- This is what powers audits like *"why was this published twice?"*. See [[Document tracer]].

### 2. Generic question
- Search the **selected** view + window first.
- If empty → **escalate**: broaden to **all data views over 24h**
  (`chat_widen_minutes`). Widening only the index was not enough — the time
  window matters too. See [[Runbook - No answer in chat]].
- Still empty → return an **instant, actionable message** (no slow LLM call).

## Robustness guarantees

- **The stream never ends empty.** If the model yields zero tokens, the backend
  sends a clear message ("try again, or switch the AI model") instead of a blank
  bubble. (This was the real cause of the misleading "No matching data".)
- Per-query failures are tolerated (`_fetch_generic`) so one bad index can't
  blank the context.
- OCR, portal lookups and polish are all **best-effort / non-fatal**.

## Image upload (OCR)

- `ocr.py` uses **Tesseract** (English + Dutch), with grayscale + upscale
  preprocessing so UI text and IDs read cleanly. Offline, provider-agnostic.
- Extracted text flows through the normal pipeline → a screenshot containing a
  doc id is **auto-traced**.

## Auto-correct

- `llm.polish_text` — fixes spelling/grammar, **preserves IDs/codes/numbers**,
  runs concurrently with the search (≈no added latency), streams the cleaned
  text back first (SSE `question` event) so the UI updates the bubble.

## Related

- [[LLM providers]] · [[Document tracer]] · [[Runbook - No answer in chat]] · [[KOOP Plooi log schema]]
