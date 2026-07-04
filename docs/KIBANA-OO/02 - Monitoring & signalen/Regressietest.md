---
title: "Regressietest"
category: "Monitoring & signalen"
created: 2026-06-29
updated: 2026-06-29
tags: [kibana-oo, monitoring]
---

# Regressietest

> 🇳🇱 Na een prod-release: controleert automatisch of open.overheid.nl nog
> correct werkt. 17 checks verdeeld over **beschikbaarheid**, **API**,
> **TLS/beveiliging**, **SEO & Google-vindbaarheid** en **technische gezondheid**.
> Te vinden via **Beheer → Regressietest**. Gefaalde kritieke checks activeren
> een alert via het [[Alerting (meldingen)|unified alerting]] systeem.

Gerelateerd: [[Alerting (meldingen)]] · [[Certificaten en TLS]] ·
[[Beschikbaarheid (uptime)]] · [[Monitoring dashboard]] · [[UX design system]]

---

## Wat & waarom

Na een release naar productie wil je **direct** weten of de publieke portal
(open.overheid.nl) nog werkt — niet pas als een burger belt dat het niet laadt.
De regressietest controleert in één druk op de knop:

- Laadt de homepage?
- Zijn documenten bereikbaar en downloadbaar?
- Werkt de openbaarmakingen-API?
- Is het TLS-certificaat geldig?
- Zijn de security-headers intact?
- Is de site vindbaar voor Google (SEO-basis)?

Het resultaat is een **verdikt**: `PASS`, `WARN` of `FAIL`. Bij `FAIL` gaat er
automatisch een alert uit (e-mail + Mattermost) én verschijnt de regressietest
als rode kaart op de [[Alerting (meldingen)|Alerting-pagina]].

---

## Hoe te gebruiken

1. Ga naar **Beheer → Regressietest** (of klik op 🧪 in de navigatie).
2. Klik **▶ Run regression test**.
3. De checks worden één voor één uitgevoerd (duurt ~10-30 seconden).
4. Het resultaat verschijnt in de **hero-sectie** (stat-kaarten: passed / warning / failed).
5. Klik op een individuele check voor de drill-down: URL, verwacht vs. werkelijk, en bewijs.

**Run history** onderaan toont alle eerdere runs — klik er één aan om het detail te zien.

---

## Alle 17 checks

### Beschikbaarheid (critical)

| Check ID | Naam | Wat wordt getest |
|----------|------|-----------------|
| `home` | Homepage loads | `GET /` → status 200, bevat "Open overheid", ≤ 5s |
| `doc-page` | Document page reachable | `GET /details/{uuid}` → status 200, HTML, ≤ 5s |
| `doc-file` | Document file downloadable | `GET /documenten/{uuid}` → status 200, PDF, ≤ 8s |
| `favicon` | Favicon served | `GET /favicon.ico` → status 200, ≤ 4s |

### API (critical)

| Check ID | Naam | Wat wordt getest |
|----------|------|-----------------|
| `api-meta` | Openbaarmakingen API | JSON-response met document-titel, ≤ 6s |

### TLS & beveiliging (critical)

| Check ID | Naam | Wat wordt getest |
|----------|------|-----------------|
| `tls` | TLS certificate & chain | Certificaat-audit: grade mag niet CRITICAL zijn |
| `security-headers` | Security headers present | HSTS + X-Content-Type-Options (nosniff) + X-Frame-Options |
| `hsts-maxage` | HSTS max-age ≥ 1 jaar | `Strict-Transport-Security` bevat `max-age=31536000` |

### SEO & Google-vindbaarheid (critical + warning)

| Check ID | Naam | Ernst | Wat wordt getest |
|----------|------|-------|-----------------|
| `meta-desc` | Homepage has meta description | **critical** | `<meta name="description">` aanwezig |
| `lang-attr` | HTML lang attribute is nl | **critical** | `<html lang="nl">` aanwezig |
| `robots-googlebot` | robots.txt has Googlebot rules | warning | robots.txt bevat "Googlebot" |
| `sitemap` | Sitemap XML status tracked | warning | `/sitemap.xml` geeft geen server error (< 500) |

### Technische gezondheid (warning)

| Check ID | Naam | Wat wordt getest |
|----------|------|-----------------|
| `robots` | robots.txt served | `GET /robots.txt` → status 200 |
| `no-5xx` | Unknown path: no server error | Willekeurig pad → geen 5xx |
| `csp-header` | Content-Security-Policy | CSP-header aanwezig |
| `referrer-policy` | Referrer-Policy | Referrer-Policy header aanwezig |
| `manifest` | PWA manifest served | `GET /manifest.json` → status 200, JSON |

---

## Betekenis van de kleuren

| Kleur | Verdict | Betekenis |
|-------|---------|-----------|
| 🟢 Groen | PASS | Alle checks geslaagd |
| 🟡 Goud | WARN | Eén of meer waarschuwingen, maar geen kritieke fouten |
| 🔴 Rood | FAIL | Eén of meer kritieke checks gefaald — **actie nodig** |

**Per check:**
- **pass** = voldoet aan alle verwachtingen
- **warn** = waarschuwing (bijv. traag, of een niet-kritieke check faalt)
- **fail** = kritieke verwachting niet gehaald (bijv. homepage laadt niet)

**Prestatie-budgetten** (max_ms) zijn altijd "soft": overschrijding geeft een
waarschuwing, nooit een harde fout.

---

## Alerting bij FAIL

Wanneer een regressietest het verdict **FAIL** krijgt:

1. **Direct na de run**: het bestaande mechanisme stuurt een e-mail en webhook
   (dezelfde kanalen als de certificaatmonitor).
2. **Via unified alerting**: gefaalde checks verschijnen als rode kaarten in de
   categorie **🧪 Regressietest** op de [[Alerting (meldingen)|Alerting-pagina]].
   Hier gelden dezelfde regels: globale schakelaar, categorie-schakelaar,
   omgevingsschakelaar, en per-kaart aan/uit.

Dit betekent dat een beheerder die de Alerting-pagina bewaakt, automatisch ziet
wanneer de regressietest faalt — zonder apart naar de Regressietest-pagina te
hoeven gaan.

---

## Echt voorbeeld

Na een release draai je de regressietest. Het resultaat:

| Check | Status | Detail |
|-------|--------|--------|
| Homepage loads | ✓ pass | 200 · 145 ms |
| Document page reachable | ✓ pass | 200 · 312 ms |
| Document file downloadable | ✓ pass | 200 · application/pdf · 89 ms |
| API returns metadata | ✓ pass | title: Besluit op Wob/Woo-verzoek... |
| **Security headers present** | **✗ fail** | **missing X-Frame-Options** |
| HSTS max-age ≥ 1 jaar | ✓ pass | all 1 headers present · 52 ms |
| HTML lang=nl | ✓ pass | lang="nl" |
| Meta description | ✓ pass | meta description="Open overheid" |
| robots.txt has Googlebot | ✓ pass | 200 · 48 ms |

**Verdict: FAIL** — de `X-Frame-Options` header is verdwenen na de release.
Er gaat automatisch een alert uit. De beheerder opent de Alerting-pagina en ziet
een rode kaart "Security headers present" onder 🧪 Regressietest → PROD.

---

## Configuratie

| `.env`-variabele | Standaard | Uitleg |
|-----------------|-----------|--------|
| `REGRESSION_TARGET_URL` | `https://open.overheid.nl` | De te testen URL |
| `REGRESSION_KNOWN_DOC_ID` | `1a7e9fc7-...` | UUID van een document dat zeker bestaat |
| `REGRESSION_TRIGGER_TOKEN` | _(leeg)_ | Token voor CI/CD-trigger (leeg = uitgeschakeld) |
| `REGRESSION_ALERT_ENABLED` | `true` | Alerts bij FAIL aan/uit |
| `REGRESSION_HISTORY_CAP` | `1000` | Max aantal opgeslagen runs |

---

## Nieuwe checks toevoegen

Checks zijn data-gedreven: voeg een dict toe aan `default_checks()` in
`backend/regression.py`. Er zijn vijf soorten (`kind`):

| Kind | Doel | Voorbeeld |
|------|------|-----------|
| `http` | HTTP GET + status/content/text check | Homepage, robots.txt |
| `file` | Streamed GET (alleen headers, geen body) | PDF-download |
| `api_meta` | JSON API + titel-extractie | Openbaarmakingen |
| `tls` | Certificaat-audit | TLS chain & grade |
| `headers` | Response-headers controleren | HSTS, CSP, X-Frame-Options |
| `html_meta` | HTML-attributen en meta-tags | lang, description, favicon-link |

Geen code-wijziging nodig voor een nieuwe check van een bestaand type — alleen
een nieuw dict in de lijst. Zie `backend/regression.py:default_checks()`.
