# AG3-103 — Remediation R2

**Datum:** 2026-06-08
**Review:** `review-r2.md` (CHANGES-REQUESTED — 3x ERROR-Dimension, 3 Remaining Must-Fix)
**Modus:** doc-only / Konzept-Story (`type: concept`). Lieferung = `concept/`-Prosa;
verboten ist nur ein `src/`-/`tests/`-Diff. Diese Runde ist eine reine
Story-Spec-Korrektur (falscher FK-93-Dateiname im Story-Text).
**Geaenderte Dateien:** ausschliesslich `stories/AG3-103-*/story.md` (4 Anker-Korrekturen)
+ diese `remediation-r2.md`. `status.yaml` unveraendert (kein Feld genuin falsch;
Review hat es nicht geflaggt).

## Finding -> Resolution

| # | Finding (review-r2) | Resolution |
|---|---|---|
| 1 | `scope-extension-note.md:6/38/76` traegt noch den Round-1-Widerspruch („keine Code-/Test-/`concept/`-Aenderung", „nicht editieren", „beschreibt … fuehrt … nicht aus"). | **Nicht in diesem Mandat / bereits orchestrator-seitig behoben.** `scope-extension-note.md` ist orchestrator-owned und wurde vom Orchestrator vor dieser Runde korrigiert. Diese Remediation hat die Datei bewusst **nicht** angefasst. |
| 2 | `scope-extension-note.md:72` behauptet noch, das real emittierte `review_divergence`-Schema sei Code/FK-34-foermig / Single Source; Code emittiert real weiter `score`/`routing` (`divergence_hook.py:93`). | **Nicht in diesem Mandat / bereits orchestrator-seitig behoben.** Gleiche orchestrator-owned Datei wie Finding 1. `story.md` traegt die korrekte Aussage bereits (autoritativ = FK-34 §34.8.4 + AG3-066-Zielschema; Hook traegt heute noch `score`/`routing`, §1 / §2.1.4 / AC4a / §5 / §6). Kein Story.md-Eingriff noetig. |
| 3 | **FK-93-Anker falsch:** `story.md:8`, `:24`, `:46`, `:83` zitieren `93_defaults_schwellwerte.md` — diese Datei existiert nicht. Reale Datei: `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`, TTL-Zeile auf `:64`. | **Behoben.** Alle 4 Vorkommen von `93_defaults_schwellwerte.md` in `story.md` auf `93_standardwerte_schwellwerte_timeouts.md` korrigiert (Zeilen 8, 24, 46, 83). Verifikation: Glob bestaetigt genau eine reale Datei `93_standardwerte_schwellwerte_timeouts.md`; Zeile 64 traegt real die Permission-Request-TTL-Zeile `1800s (30 Min) | permissions.request_ttl_s` (Tabelle §93.5a, Heading `:60`). Grep nach altem Namen: 0 Treffer; neuer Name: 4 Treffer. |

## Re-Verifikation aller uebrigen Anker in story.md (real file:line)

Alle weiteren in `story.md` zitierten Anker gegen die realen Dateien geprueft — **alle korrekt**, keine zusaetzliche Korrektur noetig:

- **FK-90** `90_schema_katalog.md`: §90.1 Uebersicht `:33`; Datei-Katalog-Tabelle `:52-70`; §90.2 „Stage-ID = Dateiname" / `{stage_id}.schema.json` `:90-94` — verifiziert.
- **FK-93** `93_standardwerte_schwellwerte_timeouts.md`: §93.5a TTL-Zeile `:64` (1800s, `permissions.request_ttl_s`) — verifiziert (siehe Finding 3).
- **FK-68** `68_telemetrie_eventing_workflow_metriken.md`: §68.2.2 H4 „Review-Divergenz" `:358`, Payload-Field-Row `review_divergence` (`reviewer_a`/`reviewer_b`/`score` (LOW/MEDIUM/HIGH)/`routing`) `:362` — verifiziert.
- **FK-34** `34_llm_bewertungen_adversarial_testing_runtime.md`: §34.8.4 Heading `:570`, „Kap. 68"-Referenz `:573`, Feldtabelle `:575-582` (`story_id`/`reviewer_a`/`reviewer_b`/`divergent`/`quorum_triggered`/`final_verdict`; `580-582` = `divergent`/`quorum_triggered`/`final_verdict`) — verifiziert.
- **Code-Anker (Spiegel-Belege, nicht editiert):** `requests.py:42` (`DEFAULT_TTL_SECONDS: int = 600`) — verifiziert; `divergence_hook.py:93-94` (`score=_SCORE_HIGH`/`routing="third_reviewer"`) — verifiziert.
- **AG3-066-Routing-Belege:** `stories/AG3-066-review-divergence-quorum/story.md:14`, `:65` tragen die FK-68-Prosa-Angleichung-Routing-Aussage an AG3-103 (Owner-Scope getragen); Feldsatz-Anker `:12` — verifiziert.

## Scope-Disziplin

- Nur `story.md` (4 Zeilen) + diese `remediation-r2.md` geschrieben.
- `scope-extension-note.md` (orchestrator-owned, Findings 1+2) **nicht** angefasst.
- Keine Produktionscode-/Test-/`concept/`-Datei und keine fremde Story-Datei
  geaendert (doc-only-Story; `src/`/`tests/`-Diff bleibt leer — bei einer reinen
  Story-Spec-Korrektur ohnehin nicht beruehrt).
- `status.yaml` unveraendert; kein Feld genuin falsch, von review-r2 nicht geflaggt.
- ARCH-55: kein deutscher Identifier/Key eingefuehrt; reine Pfadkorrektur.
