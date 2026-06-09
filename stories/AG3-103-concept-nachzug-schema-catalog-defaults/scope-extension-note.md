# AG3-103 — Scope-Extension-Note

**Datum:** 2026-06-08
**Modus:** Orchestrator-gerichtete Scope-Erweiterung (Product-Owner-Trigger)
**Story:** AG3-103 (Konzept-Nachzug — Schema-Katalog-Realitaet + Defaults/Schwellwerte + interne FK-Widersprueche)
**Typ bleibt:** `concept` (doc-only) — bei `type: concept` IST die `concept/`-Prosa-Aenderung das Deliverable; verboten ist nur ein `src/`-/`tests/`-Diff.

## Was erweitert wurde

In Scope von AG3-103 wurde explizit aufgenommen: die **FK-68 §68.2.2
Payload-Field-Row fuer `review_divergence`** an den **FK-34 §34.8.4**
Feldsatz anzugleichen (FK-Prosa-Nachzug):

- **Vorher (abgeloest, stale):** Zusatzfelder `reviewer_a`, `reviewer_b`,
  `score` (LOW/MEDIUM/HIGH), `routing` — Tabelle „Review-Divergenz" in
  `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md`,
  ~Z. 358-362.
- **Nachher (autoritativ, FK-34 §34.8.4 ~Z. 570-582):** `story_id`,
  `reviewer_a`, `reviewer_b`, `divergent`, `quorum_triggered`,
  `final_verdict`; `score`/`routing` entfallen vollstaendig (kein
  paralleles Format).
- **Owner-Markierung:** FK-34 §34.8.4 ist der **autoritative Ziel-Feldsatz**;
  FK-68-§68.2.2-Prosa zieht darauf nach. Achtung Ist-Zustand: der Code emittiert
  in `divergence_hook.py:93` **derzeit noch** das stale `score`/`routing`-Format;
  die Code-Migration auf den FK-34-Feldsatz ist **AG3-066** (noch nicht erfolgt).
  AG3-103 gleicht nur die FK-68-Prosa an das FK-34-Ziel an — kein paralleles Format.

## Geaenderte Story-Stellen (alle in `story.md`)

1. Header „Quell-Konzepte": FK-68 §68.2.2 + FK-34 §34.8.4 als
   autoritative Quellen ergaenzt.
2. §1 Ist-Zustand: neuer Beleg-Bullet zur Cross-Story-Luecke
   (`review_divergence` §68.2.2 stale vs. FK-34, AG3-066-Routing).
3. §2.1 In Scope (Item 4): neuer Bullet — §68.2.2-Payload-Field-Row auf
   den FK-34-Feldsatz umschreiben (doc-only, Owner Code/FK-34).
4. §3 Akzeptanzkriterien: neues AC 4a (exakter Feldsatz, kein
   `score`/`routing`, AG3-066-Routing erfuellt).
5. §5 Guardrail-Referenzen: neuer „FK-PROSA FOLGT CODE"-Eintrag.
6. §6 Hinweise: §68.2.2-Hinweis (die FK-68-`concept/`-Prosa IST hier das
   Deliverable und wird editiert; Code-Migration des Hooks ist AG3-066) +
   `divergence_hook.py`/`normalizer.py` zur Nicht-anfassen-Liste (kein
   `src/`-/`tests/`-Diff) ergaenzt.

`status.yaml`: unveraendert. `type` ist bereits `concept` (korrekt).
Es wurde **bewusst keine** harte `depends_on`/`unblocks`-Kante zu AG3-066
gesetzt — AG3-066s Code-Migration ist self-contained und unabhaengig
(AG3-066 deklariert kein `depends_on: AG3-103`); die FK-Prosa-Angleichung
ist ein paralleler Konzept-Nachzug, kein Build-Prerequisite. Eine harte
Kante wuerde die Kopplung ueberzeichnen.

## Warum — die AG3-066-Cross-Story-Luecke

AG3-066 (review-divergence/quorum) migriert die **eine kanonische**
`review_divergence`-Code-Payload end-to-end auf den FK-34-§34.8.4-Feldsatz
(Hook, `MANDATORY_PAYLOAD_FIELDS`, Contract-Pin, Risk-Window-Excerpt) und
**routet die FK-68-PROSE-Angleichung explizit an AG3-103** (siehe
`stories/AG3-066-review-divergence-quorum/story.md`, Guardrail-/Hinweis-
Verweise „FK-Prosa-Ergaenzung an AG3-103 geroutet").

AG3-103s **urspruenglicher** Scope (Item 4, letzter Bullet) deckte aber
nur die FK-68 **§68.2 Glossar**-`event-type-id`-value-Liste ab — **nicht**
die **§68.2.2 Payload-Field-Row** fuer `review_divergence`, die weiterhin
die stale `score`/`routing`-Form zeigte. Damit zeigte das AG3-066-Routing
auf etwas, das AG3-103 noch nicht besass — ein verwaistes Cross-Story-
Routing, das AG3-066 bouncen liess.

Diese Erweiterung schliesst die Luecke: AG3-103 besitzt jetzt explizit den
FK-68-§68.2.2-Prosa-Nachzug, sodass das AG3-066-Routing ein klares Ziel
mit klarem Owner hat (ZERO DEBT: kein still liegengelassenes Cross-Story-
Routing).

## Bounded-Context-Autoritaet (Begruendung doc-only)

Per `concept/_meta/bc-cut-decisions.md` ist die v3-Linie (typisierte
Modelle/Code) die normative Autoritaet fuer das **Soll**-Schema; FK-Prosa
spiegelt das. Autoritativer Ziel-Feldsatz fuer `review_divergence` ist
FK-34 §34.8.4. Ist-Zustand: der Code emittiert noch das stale
`score`/`routing`-Format (`divergence_hook.py:93`); die Code-Migration auf
das Ziel ist AG3-066. AG3-103 ist eine doc-only-Konzeptstory: die
FK-68-§68.2.2-`concept/`-Prosa-Angleichung **ist** das Deliverable und wird
hier ausgefuehrt (concept/-Edit) — verboten ist nur ein `src/`-/`tests/`-Diff.

## ARCH-55

Alle eingefuehrten Feld-/Wire-Keys sind englisch (`story_id`, `divergent`,
`quorum_triggered`, `final_verdict`, ...). Kein deutscher Identifier/Key in
der FK-Prosa.
