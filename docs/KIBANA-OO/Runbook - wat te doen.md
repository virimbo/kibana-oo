---
title: Runbook — wat te doen
tags: [runbook, beheer, acties, nl]
aliases: [Wat te doen, Runbook acties, What to do]
component: runbook-actions
bijgewerkt: 2026-06-17
eigenaar: KOOP Beheer
---

# Runbook — wat te doen 🚨

Terug naar [[Home]] · zie ook [[Beschikbaarheid (uptime)]] en [[Certificaten en TLS]].

> [!info] Waarvoor is dit?
> Dit is de **actielijst**: *wie moet wat doen* als er iets misgaat. Het Smart
> context paneel leest deze runbook **live** en toont onder **"WAT TE DOEN NU"**
> de juiste actie bij de juiste omgeving zodra een site **DOWN** is of een
> **certificaat bijna verloopt**. Houd deze lijst actueel — pas de regels hieronder
> aan en werk `bijgewerkt:` in de frontmatter bij.

## Hoe het werkt (conventie)

- Eén **kopje per situatie**: `## Bij DOWN`, `## Bij certificaat bijna verlopen`.
- Eronder **één regel per omgeving**: `- PROD: <actie>` / `- ACC: <actie>` /
  `- TEST: <actie>`.
- `TST` wordt automatisch als `TEST` herkend; hoofdletters/spaties maken niet uit.
- Staat er geen regel voor een omgeving? Dan toont het paneel "geen actie
  vastgelegd — vul de runbook aan".

## Bij DOWN
- PROD: Bel direct de 24/7 storingslijn (iedereen) en open een incident.
- ACC: Bel Firas.
- TEST: Bel Anton.

## Bij certificaat bijna verlopen
- PROD: Bel iedereen en vernieuw het certificaat vóór de vervaldatum.
- ACC: Bel Firas om het ACC-certificaat te vernieuwen.
- TEST: Bel Anton om het TEST-certificaat te vernieuwen.

## Onderhoud

- Werk `bijgewerkt:` bij elke wijziging bij. Het paneel toont de datum en
  waarschuwt ("⚠ runbook mogelijk verouderd") als deze ouder is dan ~180 dagen.
- Voeg een nieuwe situatie toe door simpelweg een nieuw `## Bij …`-kopje te maken.
