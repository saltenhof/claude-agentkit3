---
concept_id: META-DEC-2026-07-11-RESUME-CRASH-CONTINUATION
title: Concept-Decision-Record — `/resume` (Session-Continuation) ist der SOLL-Standardmechanismus der Crash-Recovery; `recover-story` ist der Fallback
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, session-ownership, crash-recovery, resume, ownership-transfer, self-rebind, AG3-154, FK-56, FK-20]
formal_scope: prose-only
---

# Concept-Decision-Record — `/resume` als SOLL-Crash-Continuation

Datum: 2026-07-11. Record gemaess META-CONCEPT-CONSISTENCY P3.
Anlass: AG3-154 (CLI/Admin + `recover-story`). Beim Einfrieren des Designs entstand
zunaechst eine Fehl-Eskalation zu SOLL-091 ("co-sign-freier Agent-Self-Rebind"), die
auf der falschen Annahme beruhte, ein Prozess-Neustart erzeuge zwangslaeufig eine neue
Identitaet und es fehle ein attestierbares "stable harness identity"-Primitiv. Ein
Ende-zu-Ende-Durchgang des realen Operator-Workflows hat die Annahme widerlegt.

## 1. Sachverhalt (am Code verifiziert, main@caadbf93)

- AK3 vergibt die Ownership-Session-ID **nicht** selbst: `owner_session_id` ist die
  `session_id` des Harness-Hook-Events. Der Claude-Code-Adapter mappt fuer **jede**
  Operation `session_id=claude_event.session_id`
  (`src/agentkit/harness_client/harness_adapters/claude_code.py:147` u. a.).
- `/resume` setzt dieselbe Harness-Session fort und behaelt deren `session_id`. Damit
  bleibt `owner_session_id` **unveraendert**; der Ownership-Fence
  (`story_execution_mutations_require_current_ownership_epoch`) trifft weiter
  `owner_session_id@ownership_epoch`. Die resumte Session **besitzt die Story weiter**.
- Eine beim Crash unterbrochene In-Flight-Operation rekonsiliert dieselbe Identitaet
  ueber die `op_id`-Idempotenz (FK-91 §91.1a Regeln 14/16) — Status-Read auf
  `.../operations/{op_id}`.
- FK-20 §20.7.3 kannte den Begriff bereits: "Alle anderen Stellen sind `auto-resume`";
  nur die Worker-Loop-Recovery ist menschlich entschieden.

## 2. Entscheidung

1. Der **Standardmechanismus (SOLL)** der Crash-Recovery ist die **Session-Continuation
   via `/resume`**: gleiche `owner_session_id` -> weiter Owner -> einfach weiterarbeiten,
   **ohne Transfer, ohne Recovery-Ereignis, ohne menschliche Mitzeichnung**. Das ist der
   in FK-56 §56.13g gemeinte Fall "dieselbe Harness-Identitaet nimmt ihre eigene
   verwaiste Arbeit wieder auf". Das "Identitaets-Primitiv" ist die resumebare Session
   selbst — es ist **kein zusaetzliches Primitiv zu bauen**.
2. `agentkit recover-story` (`acquired_via=recovery`, neuer Run, `human_cli`, auditiert
   als `admin_transition`) ist der **Fallback** fuer den Fall, dass die Harness-Identitaet
   **nicht** wiederherstellbar ist (Session/Transcript verloren, bewusster Clean-Slate)
   oder waehrend der Ausfallzeit bereits ein Takeover die Story entzogen hat (Ex-Owner
   disowned, §56.13h). Ein `recover-story`-Aufruf ist per Definition **nicht** der
   Resume-Pfad und daher zu Recht eine bewusste menschliche Entscheidung.
3. **SOLL-091** ("co-sign-freier Self-Rebind fuer dieselbe Harness-Identitaet") ist damit
   **erfuellt** — durch den Resume-Pfad, nicht durch neuen Code. Er wird **weder gestrichen
   noch als Folge-Story gebaut**; die Fehl-Eskalation an den Menschen ist zurueckgezogen.
4. Agent-`recover-story` bleibt korrekt **fail-closed** (`recovery_requires_human_cli`):
   nicht weil Identitaet unbeweisbar waere, sondern weil der Same-Identity-Pfad `/resume`
   ist und `recover-story` inhaerent der Fresh-Session-/Menschen-Pfad.

## 3. Konzept-Nachzug (in diesem Record umgesetzt)

- FK-56 §56.13g in "zwei Pfade nach Harness-Verfuegbarkeit" umgeschrieben:
  Standardmechanismus (Session-Continuation via `/resume`) vs. Fallback (`recover-story`).
- FK-20 §20.7.4: `auto-resume` (§20.7.3) explizit an den §56.13g-Standardmechanismus
  gebunden; `recover-story` als Fallback ausgewiesen.

## 4. Nicht-Ziele

- Kein autonomer Worker-Supervisor/Daemon, der abgestuerzte Worker ohne Menschen neu
  startet — waere der einzige Kontext, in dem ein maschinen-attestierter co-sign-freier
  Neustart ueberhaupt einen Ausloeser haette; existiert im Single-Operator-lokalen Modell
  (FK-15 §15.10.1) nicht und widerspricht der Konzept-Linie "keine Liveness-Erkennung".
  Falls jemals gewuenscht, waere Recovery-Autoritaet ueber eine **Supervisor-Attestierung**
  zu modellieren, nicht ueber ein diffuses Harness-Identitaets-Primitiv.
