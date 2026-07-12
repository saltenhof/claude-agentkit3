---
concept_id: META-DEC-2026-07-12-CLOSURE-PAYLOAD-DEFERS-TO-CYCLE
title: Concept-Decision-Record — Aufloesung des per-scope `defers_to`-Zyklus fuer `closure-payload` (FK-29 ↔ FK-39)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, defers-to, ownership, closure-payload, phase-payload, FK-29, FK-39, AG3-157]
formal_scope: prose-only
---

# Concept-Decision-Record — `closure-payload` defers_to-Zyklus (FK-29 ↔ FK-39)

Datum: 2026-07-12. Record gemaess META-CONCEPT-CONSISTENCY P3.
Anlass: Das neue Konzept-Referenz-Integritaets-Gate (AG3-157, W1) hat beim ersten
Lauf auf `main` einen **same-scope `defers_to`-Zyklus** fuer den Scope
`closure-payload` gemeldet und (vertragsgemaess) gestoppt, weil ein per-scope-Zyklus
ein un-baselinebarer ERROR ist. Dies ist ein echter, vorbestehender Konzept-Defekt,
den das Gate korrekt aufgedeckt hat.

## 1. Befund (am Code/Konzept verifiziert, main@f323f738)

Zwei Dokumente delegierten denselben Scope `closure-payload` **wechselseitig**:
- FK-29 (`29_closure_sequence.md:119-121`) → FK-39, Grund „ClosurePayload als
  diskriminierte Union in FK-39 §39.2.3".
- FK-39 (`39_phase_state_persistenz.md:29-31`) → FK-29, Grund „ClosurePayload und
  ClosureProgress liegen in FK-29".

Ein wechselseitiges `defers_to` fuer **denselben** Scope ist inkohaerente Delegation
(beide behaupten, das jeweils andere Dokument besitze `closure-payload`).

## 2. Faktenlage (Ownership eindeutig, kein Judgment-Call)

- **FK-29 §29.1.0** DEFINIERT `ClosurePayload` und `ClosureProgress` normativ
  (`class ClosurePayload` :178, `class ClosureProgress` :170; „Eigentuemerschaft
  liegt [in FK-29]" :24). → **FK-29 besitzt den Scope `closure-payload`.**
- **FK-39 §39.2.3** definiert die **generische** `PhasePayload`-Discriminated-Union
  (das Framework), in das `ClosurePayload` als *eine* phasenspezifische Variante
  einsteckt. FK-39 `authority_over` fuehrt `phase-payload` (nicht `closure-payload`).

Der `FK-29 → FK-39 / closure-payload`-Edge war also **falsch**: er verwechselte den
generischen PhasePayload-Union-Rahmen (FK-39) mit der Closure-Variante (FK-29).

## 3. Entscheidung

1. **Owner von `closure-payload` ist FK-29.** Der korrekte Delegations-Edge
   `FK-39 → FK-29 (closure-payload)` bleibt unveraendert.
2. Der falsche `FK-29 → FK-39 (closure-payload)`-Edge wird **re-skopiert** auf den
   tatsaechlich delegierten Gegenstand: `FK-29 → FK-39 (phase-payload)` —
   FK-29 nutzt den generischen PhasePayload-Union-Rahmen, den FK-39 via
   `authority_over: phase-payload` besitzt. Damit ist der `closure-payload`-Scope
   azyklisch (nur noch FK-39 → FK-29).
3. Keine inhaltliche Aenderung an ClosurePayload/ClosureProgress selbst; rein die
   Delegations-Semantik wird korrigiert (FK-29 §29.1.0 bleibt die normative Quelle).

## 4. Nachzug

- `29_closure_sequence.md` Frontmatter: `defers_to`-Eintrag scope `closure-payload`
  → `phase-payload` re-skopiert (Grund praezisiert).
- 4 Konzept-Gates bleiben gruen. AG3-157 kann nach dieser Aufloesung gruen auf `main`
  laufen (der per-scope-Zyklus ist entfernt).
- Dies ist eine **normative** Korrektur ausserhalb der AG3-157-Implementierung: das
  Gate deckt Defekte auf, es behebt sie nicht (AG3-157 darf keine normativen
  Aenderungen erzwingen). Weitere per-scope-Zyklen, falls das Gate welche findet,
  werden je einzeln so entschieden (oder eskaliert).
