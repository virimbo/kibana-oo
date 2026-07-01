# UX design system

> 🇳🇱 Het uniforme ontwerpsysteem van Open Overheid - Monitoring. Sinds de
> **OO-GX**-restyle (2026-06) volgt elke pagina één visuele taal: een Opera-GX
> *magazine*-look — diep near-black, **één crimson accent**, squared Chakra-Petch
> koppen, glow-CTA's en stat-card hero's. Dit document is de bron van waarheid voor
> kleuren, typografie en componenten.

---

## OO-GX in het kort (huidige stijl)

- **Palet:** near-black surfaces (`--bg-app #0e0a0f`) + **één crimson accent**
  (`--accent #ff1f4c`) voor álle interactie en de primaire getallen. Status blijft
  semantisch groen/amber/rood. Scherpe hoeken (`--radius` 6px).
- **Typografie:** **Chakra Petch** (`--display`, koppen + eyebrows, uppercase),
  **IBM Plex Sans** (`--font`, body), **JetBrains Mono** (`--mono`, getallen/IDs).
- **De `.gx-*` kit** (in `frontend/src/styles.css`, compose deze eerst):

  | Klasse | Doel |
  |--------|------|
  | `.gx-pagehead` | Pagina-kop: eyebrow + display-H1 |
  | `.gx-eyebrow` | `• HOOFDLETTER` crimson kicker |
  | `.gx-h1` / `.gx-h2` | Chakra-Petch uppercase koppen |
  | `.gx-hero` (+ `.gx-sub`) | Hero-blok: eyebrow → kop → sub → CTA |
  | `.gx-cta` | Glow-crimson primaire knop |
  | `.gx-panel` | Scherpe donkere kaart met crimson toplijn |
  | `.gx-pill` | `● LIVE`/status-pill |
  | `.gx-stat-card` (+ `-num/-label/-cap/-row/-rownum`) | "AD BLOCKER · 3.241"-statblok |
  | `.gx-tag` | Klein chip-label |

- **Consistentiebewaking:** de skill `oo-ux-check` (bron van waarheid voor de
  checklist) + de agent `oo-ux-auditor` (read-only, fan-out over alle pagina's).
  Volledige spec: `docs/superpowers/specs/2026-06-19-opera-gx-restyle-design.md`.
- **Regel:** restyle is **markup/CSS-only** — logica, handlers, `data-*` (o.a.
  `data-smartcard`) en in JS gebruikte classNames blijven ongemoeid.

> De rest van dit document beschrijft het onderliggende editorial-patroon (hero's,
> stat-kaarten, shell, responsive). Dat blijft geldig; OO-GX vervangt alleen het
> palet, de typografie en voegt de `.gx-*` kit toe als de nieuwe goudstandaard.

Gerelateerd: [[Alerting (meldingen)]] · [[Monitoring dashboard]] ·
[[Dashboard - statusoverzicht]] · [[Navigatie]] · [[Beschikbaarheid (uptime)]] ·
[[DLQ intelligentie]]

> [!note] Wijzigingen deze ronde (UI-politoer, cosmetisch)
> Een lichte poetsronde over de bestaande OO-GX-taal — geen nieuwe tokens, alleen
> markup/CSS:
> - **Login-achtergrond** is nu **statisch** (animatie weg) met een **kleinere titel**.
> - **Alle paginatitels** zijn kleiner/professioneler geschaald.
> - **Lege ruimtes weggewerkt** — o.a. de `page-hero` en de Alerting *single-env*-grid
>   (geen brede gaten meer bij één omgeving).
> - **Dubbele eyebrow/koppen verwijderd** (geen herhaalde kicker + titel meer).
> - **Nederlandse copy consistenter** op Dashboard, Documenten, Beheer, DLQ en Chat
>   (NL-proza met Engelse tech-termen, zie [[Navigatie]]).

---

## Wat & waarom

KIBANA-OO is een admin-dashboard met meerdere pagina's: Dashboard (monitoring),
Documenten, Regressietest, Alerting, DLQ Intelligentie, Instellingen, Beheercentrum
en Autorisatie. Vóór deze uniformering had elke pagina een eigen lay-out: sommige
begonnen met een kale `<h3>`, andere hadden inline stijlen, en er was geen visuele
hiërarchie. Dat maakte de applicatie **rommelig en onvoorspelbaar** voor beheerders.

De **Alerting-pagina** (Beheer → Meldingen) was het eerst ontworpen met een volledig
redactioneel patroon:

- **Hero-sectie** met eyebrow-label, grote titel, beschrijving en stat-kaarten
- **Eyebrow-labels** (kleine grijze hoofdlettertekst) op elke sectie
- **Categorie-headers** met pictogram, subtitel en rollup-pillen
- **Omgevingskolommen** (PROD/ACC/TST) met kleurgecodeerde tegels
- **Animaties** bij het laden (staggered entrance)
- **Nul inline stijlen** — alles via CSS-klassen

Dit patroon is nu de **goudstandaard**: élke pagina volgt exact dezelfde structuur,
met herbruikbare CSS-klassen (`page-hero`, `page-eyebrow`, `page-stat`, `page-rise`).

---

## De vijf bouwstenen

### 1. Hero-sectie (`page-hero`)

Elke pagina begint met een hero — een groot, visueel blok bovenaan dat de context
onmiddellijk duidelijk maakt:

| Element | CSS-klasse | Doel |
|---------|-----------|------|
| Container | `.page-hero` | Achtergrond met subtiele radiaal-gradient, afgeronde hoeken, border |
| Eyebrow | `.page-eyebrow` | Kleine grijze tekst in hoofdletters, bijv. "BEHEER · MELDINGEN" |
| Titel | `.page-hero-h1` | 30px vet, bijv. "🔔 Alerting" |
| Lead | `.page-hero-lead` | 13.5px secundaire kleur, max 56 tekens breed |
| Acties | `.page-hero-actions` | Knoppen onder de lead-tekst (optioneel) |
| Stat-kaarten | `.page-hero-stats` | Rechts: 1–3 kaarten met getal + label |

**Kleurvarianten** (achtergrondaccent):

| Variant | CSS-klasse | Wanneer gebruiken |
|---------|-----------|------------------|
| Standaard (blauw/groen) | `.page-hero` | Normale toestand, alles gezond |
| Waarschuwing (goud) | `.page-hero--accent-warn` | Er is een probleem, actie nodig |
| Teal (turquoise) | `.page-hero--accent-teal` | Monitoring/data-gerichte pagina's |
| Paars | `.page-hero--accent-purple` | Admin/autorisatie-pagina's |

**Echt voorbeeld — Regressietest:**
De hero toont "Beheer · Regressietest" als eyebrow, de titel "🧪 Regressietest",
een korte uitleg, en rechts drie stat-kaarten (passed / warning / failed) met
de tellingen van de laatste run. Als er een test draait wisselt de achtergrond
naar goud (`.page-hero--accent-warn`).

---

### 2. Eyebrow-label (`page-eyebrow`)

Een klein, grijs label in hoofdletters dat boven elke sectie staat. Het geeft
context vóórdat je de titel leest — precies zoals een krantenkop een rubrieksnaam
boven het artikel zet.

**Specificaties:**
- Lettergrootte: 10.5px
- Gewicht: 700 (vet)
- Letterafstand: 0.16em
- Kleur: `--text-faint` (gedempte grijstint)
- Hoofdlettertransformatie: uppercase

**Voorbeelden per pagina:**

| Pagina | Eyebrow |
|--------|---------|
| Alerting | "BEHEER · MELDINGEN" |
| DLQ Intelligentie | "BEHEER · DEAD-LETTER QUEUES" |
| Regressietest | "BEHEER · REGRESSIETEST" |
| Instellingen | "BEHEER · INSTELLINGEN" + per sectie: "MODEL & PROVIDER", "GESPREKSINSTELLINGEN", "DASHBOARD-INDELING" |
| Beheercentrum | "BEHEER" + "NAVIGATIE" |
| Autorisatie | "SUPER ADMIN · AUTORISATIE" + "TOEGANGSMATRIX", "SPOOR" |
| Dashboard | Per zone: "BEREIK & DATABRON", "ACTIE VEREIST", "DOCUMENTVERWERKING", "LOGS & FOUTEN", "KUNSTMATIGE INTELLIGENTIE" |

---

### 3. Stat-kaarten (`page-stat`)

Rechthoekige kaarten met één groot getal en een klein label eronder. Staan rechts
in de hero of in een grid. De kleur van het getal communiceert de ernst.

**Specificaties:**
- Getal: 30px, gewicht 800, tabular-nums
- Label: 10.5px, hoofdletters, gedempte kleur
- Achtergrond: `--bg-input` met border
- Minimumbreedte: 92px, padding 14px 16px

**Kleuren (tone):**

| Klasse | Kleur getal | Wanneer |
|--------|------------|---------|
| `.page-stat--ok` | Groen (`--success`, #46c97a) | Alles gezond |
| `.page-stat--warn` | Goud (`--warn`, #e3b341) | Waarschuwing, actie aanbevolen |
| `.page-stat--crit` | Rood (`--error`, #ff6b66) | Kritiek, directe actie nodig |
| `.page-stat--muted` | Grijs (`--text-faint`) | Geen data / neutraal |

**Live-indicatie:** Als `.is-live` wordt toegevoegd krijgt de kaart een gekleurde
border. Bij kritiek (`.page-stat--crit.is-live`) pulseert de kaart met een rode
gloed-animatie (1.8s cyclus).

---

### 4. Sectie-header (`page-section-head`)

Een horizontale balk met pictogram, eyebrow, titel en optionele rollup-pillen.
Gebruikt voor de inhoudelijke secties onder de hero.

| Element | CSS-klasse | Doel |
|---------|-----------|------|
| Container | `.page-section-head` | Flex-row met border-bottom |
| Pictogram | `.page-section-icon` | 22px emoji, links |
| Titels | `.page-section-titles` | Kolom: eyebrow + h2 |
| Titel | `.page-section-title` | 18px vet |
| Rollup | `.page-section-roll` | Pillen/badges rechts |

**Echt voorbeeld — Autorisatie:**
De sectie "Wie mag wat" heeft een 👥 pictogram, de eyebrow "TOEGANGSMATRIX" en
rechts de verdictbadge. De "Wijzigingslog" sectie toont een 📜 pictogram met
eyebrow "SPOOR".

---

### 5. Entrance-animatie (`page-rise`)

Elke tegel, kaart of rij die in beeld komt schuift subtiel omhoog (10px) en
fadet in (0 → 1 opacity) over 0.42 seconde. Met `animation-delay` per index
ontstaat een **staggered** (getrapt) effect:

```css
animation: page-rise .42s cubic-bezier(.2,.7,.2,1) both;
```

**Waar toegepast:**
- Admin-kaarten (50ms interval)
- DLQ Intelligentie queue-tegels (35ms interval)
- Alerting magazine-tegels (35ms interval)

---

## Kleurensysteem

### Achtergrondlagen (donker thema)

| Token | Hex | Gebruik |
|-------|-----|---------|
| `--bg-app` | `#0e0a0f` | Pagina-achtergrond (near-black, lichte paarse zweem) |
| `--bg-panel` | `#1a1216` | Panelen, kaarten |
| `--bg-elevated` | `#221820` | Verhoogde elementen (hover, tegels) |
| `--bg-input` | `#251a22` | Invoervelden, stat-kaarten |

### Tekst

| Token | Hex | Gebruik |
|-------|-----|---------|
| `--text-primary` | `#f5eef0` | Hoofdtekst, titels (warm off-white) |
| `--text-secondary` | `#b9a9b0` | Beschrijvingen, subtitels |
| `--text-faint` | `#7d6b73` | Eyebrows, hints, meta |

### Accent (de OO-GX crimson — interactief)

| Token | Hex | Gebruik |
|-------|-----|---------|
| `--accent` | `#ff1f4c` | **Alle** interactieve elementen, focus, links, primaire stat-getallen |
| `--accent-hover` | `#ff4d6d` | Hover |
| `--accent-soft` | `rgba(255,31,76,.12)` | Zachte tint (pill-achtergrond) |
| `--accent-glow` | `rgba(255,31,76,.35)` | Glow op CTA's en de eyebrow-dot |

> De provider-tokens (`--provider-accent` …) zijn **geremapt** op deze crimson —
> het AI-model kleurt de UI niet meer (zie [[#Provider-theming (vervallen)]]).

### Ernst (severity — semantisch, nooit gethematiseerd)

| Ernst | Token | Hex | Achtergrond (soft) |
|-------|-------|-----|--------------------|
| Gezond (OK) | `--success` | `#3ad07a` | `rgba(58,208,122,.16)` |
| Waarschuwing | `--warn` | `#ffb020` | `rgba(255,176,32,.12)` |
| Kritiek / Fout | `--error` | `#ff3b4e` | `rgba(255,59,78,.10)` |

### Omgevingen

| Omgeving | Token | Hex | Gebruik |
|----------|-------|-----|---------|
| PROD | `--env-prod` | `#7682e0` (indigo) | Badges, kolom-accenten, borders — bewust NIET rood (rood = alleen echte problemen) |
| ACC | `--env-acc` | `#ffb020` (goud) | Badges, kolom-accenten |
| TST | `--env-test` | `#2db6a6` (teal) | Badges, kolom-accenten |

Elke omgeving heeft ook een zachte variant (`--env-prod-soft` etc.) voor
achtergrondtinten.

---

## Typografie

| Doel | Grootte | Gewicht | Extra |
|------|---------|---------|-------|
| Hero-titel (H1) | clamp(34–64px) | 700 | `var(--display)`, **uppercase**, `letter-spacing: -.01em` (`.gx-h1`) |
| Sectietitel (H2) | clamp(20–28px) | 700 | `var(--display)`, uppercase (`.gx-h2`) |
| Eyebrow | 11px | 700 | `var(--display)`, `letter-spacing: .16em`, uppercase, crimson, `•`-dot (`.gx-eyebrow`) |
| Stat-getal | clamp(30–52px) | 700 | `var(--mono)`, crimson (`.gx-stat-num`) |
| Stat-label | 13px | 700 | `var(--display)`, uppercase, gedempte kleur |
| Lead/sub | 15px | normaal | `var(--font)`, `--text-secondary` (`.gx-sub`) |
| Body | 14–15px | normaal | `var(--font)` |
| Badge/pill | 10px | 700 | `var(--display)`, uppercase (`.gx-pill`) |
| Mono (code/IDs) | 11.5–12px | 500/700 | `var(--mono)` |

Lettertypefamilies (self-hosted via `@fontsource`, offline/VPN-proof):
- `--display`: **Chakra Petch** — squared/tech display, voor koppen + eyebrows.
- `--font`: **IBM Plex Sans** — body.
- `--mono`: **JetBrains Mono** — getallen, IDs, code.

Vorm: `--radius` 6px / `--radius-sm` 4px (scherper, mechanischer dan voorheen).

---

## Pagina-overzicht (vóór en na)

| Pagina | Vóór uniformering | Na uniformering |
|--------|------------------|-----------------|
| **Alerting** | ✅ Al goudstandaard | Ongewijzigd (referentie) |
| **Dashboard** | Kale controls-balk, geen eyebrows op zones | Paneel-achtige controls met eyebrow "BEREIK & DATABRON"; elke zone heeft een eyebrow |
| **Regressietest** | Kale `<h3>` met inline stijlen, knop zonder primary-klasse | Hero met stat-kaarten (passed/warning/failed), `btn--primary`, sectie-headers met eyebrows |
| **DLQ Intelligentie** | Kale `<h3>`, 5× inline stijlen, hardcoded kleuren | Hero met stat-kaarten (kritiek/waarschuwing/gezond), CSS-klassen, entrance-animaties |
| **Instellingen** | Kale panelen zonder introductie | Hero met uitleg, eyebrow per sectieblok |
| **Beheercentrum** | Kale paneel met `<h3>` | Hero (paars accent) met uitleg, sectie-header "Kies een onderdeel", entrance-animaties op kaarten |
| **Autorisatie** | Kale paneel zonder context | Hero (paars accent) met stat-kaarten (gebruikers/functies), sectie-headers met eyebrows |

---

## Gedeelde CSS-klassen

Alle nieuwe klassen staan in `frontend/src/styles.css` onder het commentaar
`/* ══ Shared page-level design tokens ═══════════════════════ */` (onderaan het bestand).

| Klasse | Gebaseerd op | Doel |
|--------|-------------|------|
| `.page-hero` | `.alerts-hero-wrap` | Paginabrede hero-container |
| `.page-hero--accent-warn` | `.alerts-hero-wrap.is-paused` | Goud-accent bij waarschuwingen |
| `.page-hero--accent-teal` | nieuw | Teal-accent voor data-pagina's |
| `.page-hero--accent-purple` | nieuw | Paars-accent voor admin-pagina's |
| `.page-hero-main` | `.alerts-hero-main` | Linker kolom hero (titel + tekst) |
| `.page-hero-h1` | `.alerts-hero-h1` | Grote paginatitel |
| `.page-hero-lead` | `.alerts-hero-lead` | Beschrijvende lead-tekst |
| `.page-hero-actions` | `.alerts-master` | Actieknoppen in de hero |
| `.page-hero-stats` | `.alerts-hero-stats` | Stat-kaarten rechts |
| `.page-stat` | `.alerts-stat` | Individuele stat-kaart |
| `.page-stat-num` | `.alerts-stat-num` | Groot getal in stat-kaart |
| `.page-stat-lbl` | `.alerts-stat-lbl` | Label onder het getal |
| `.page-eyebrow` | `.alerts-eyebrow` | Sectie-eyebrow (herbruikbaar) |
| `.page-section-head` | `.alerts-cat-head` | Sectie-header met border |
| `.page-section-icon` | `.alerts-cat-icon` | Pictogram in sectie-header |
| `.page-section-titles` | `.alerts-cat-titles` | Eyebrow + titel kolom |
| `.page-section-title` | `.alerts-cat-title` | H2 in sectie-header |
| `.page-rise` | `alerts-rise` | Entrance-animatie |
| `.dash-section-eyebrow` | nieuw | Eyebrow in dashboard-zones |

---

## Responsive gedrag

| Scherm | Aanpassingen |
|--------|-------------|
| **< 600px** (mobiel) | Hero: kleinere padding, titel 22px, stat-kaarten vullen de breedte |
| **< 720px** | SmartContextPanel wordt een full-height slide-over |
| **< 1180px** | Navigatie: alleen pictogrammen, geen labels; gebruikersnaam verborgen |

---

## Configuratie

Er is geen `.env`-instelling nodig — het design system is puur CSS en JSX. De
visuele taal wordt automatisch toegepast via de gedeelde klassen.

### Provider-theming (vervallen)

In OO-GX kleurt het AI-model de UI **niet meer**. De provider-tokens
(`--provider-accent` …) zijn geremapt op de ene crimson `--accent`, zodat de
bestaande `var(--provider-accent)`-gebruiken automatisch crimson tonen. Het actieve
model (Ollama / Mistral / AI uit) wordt nog wél als **tekstlabel** getoond door
`ProviderSwitcher` — maar zonder eigen accentkleur.

---

## Checklist voor nieuwe pagina's

Bij het toevoegen van een nieuwe pagina:

1. ☐ Begin met een `.page-hero` (kies de juiste accentvariant)
2. ☐ Voeg een `.page-eyebrow` toe met "BEHEER · [paginanaam]"
3. ☐ Gebruik `.page-hero-h1` voor de titel (met emoji)
4. ☐ Voeg `.page-hero-lead` toe met een korte uitleg
5. ☐ Voeg stat-kaarten toe (`.page-hero-stats` + `.page-stat`) als er tellingen zijn
6. ☐ Gebruik `.page-section-head` voor inhoudelijke secties
7. ☐ Voeg `.page-eyebrow` toe aan elke sectie
8. ☐ Voeg `.page-rise` toe aan tegels/kaarten voor entrance-animatie
9. ☐ Gebruik **geen** inline stijlen — maak CSS-klassen aan
10. ☐ Test op mobiel (< 600px) en smal (< 1180px)

---

## Echt voorbeeld: een pagina bouwen

Stel: je voegt een "Gezondheidscontrole" pagina toe.

```jsx
<section className="page-hero page-hero--accent-teal">
  <div className="page-hero-main">
    <span className="page-eyebrow">Beheer · Gezondheidscontrole</span>
    <h1 className="page-hero-h1">💚 Gezondheidscontrole</h1>
    <p className="page-hero-lead">
      Overzicht van alle actieve monitoren en hun huidige status.
    </p>
  </div>
  <div className="page-hero-stats">
    <div className="page-stat page-stat--ok is-live">
      <span className="page-stat-num">12</span>
      <span className="page-stat-lbl">gezond</span>
    </div>
    <div className="page-stat page-stat--crit">
      <span className="page-stat-num">0</span>
      <span className="page-stat-lbl">kritiek</span>
    </div>
  </div>
</section>

<section className="panel">
  <header className="page-section-head">
    <span className="page-section-icon">📋</span>
    <div className="page-section-titles">
      <span className="page-eyebrow">Overzicht</span>
      <h2 className="page-section-title">Actieve monitoren</h2>
    </div>
  </header>
  {/* inhoud hier */}
</section>
```

Dit geeft exact dezelfde visuele structuur als de Alerting-pagina: hero bovenaan
met statistieken, en daaronder nette secties met eyebrows en titels.
