# Entscheidung: V2-Ballast-Bewertung — Verbindliche Festlegungen fuer v3

**Datum:** 2026-04-08
**Entscheider:** Stefan Altenhof (Product Owner) + Claude Opus 4.6 (Architektur-Analyst)
**Grundlage:** `analyse-v2-ballast-begruendungen.md` (29 Elemente)
**Kontext:** AgentKit v3 ist Produktivsoftware fuer den Enterprise-Einsatz. Es gibt kein MVP. Alle Entscheidungen gelten fuer den vollen Produktionsumfang.

---

## Leitprinzipien (aus der Entscheidungsrunde)

1. **Kein MVP-Denken.** AgentKit v3 ist Enterprise-Grade. Features werden nicht gestaffelt.
2. **Harte Typisierung.** Keine Strings wo StrEnum/Literal moeglich ist. Typsicherheit ist Pflicht.
3. **Fachkonzepte sind normativ.** Was in FK-20, FK-24, FK-25, FK-26, FK-34, FK-35 steht, wird umgesetzt.
4. **Vertrag und Ausfuehrung trennen.** Vertraege (Specs, Registries) definieren WAS. Enforcement-Layer definiert WIE.
5. **AgentKit-Entwicklung vs. AgentKit-Runtime unterscheiden.** AgentKit selbst ist Single-Repo. Zielprojekte koennen Multi-Repo sein.

---

## Entscheidungsmatrix

### Raus (6 Elemente)

| # | Element | Begruendung |
|---|---|---|
| 1 | Dynamischer Import compose-prompt.py | Fragile Importmechanik. In v3 als regulaeres Python-Modul. |
| 3 | NON_DETERMINISTIC_PHASE Konstanten | In v3 als `requires_llm: bool` pro Phase in der Phase-Config kodieren. |
| 6 | FinalBuildStep Dataclasses | Reines Doku-Artefakt ohne Runtime-Logik. Anforderung bleibt im Prompt. |
| 7 | CrashScenario / CRASH_SCENARIO_CATALOG | Doku-Katalog. Recovery-Logik existiert separat. Info bleibt in Konzeptdokumenten. |
| 8 | Scheduling Policies (3 Klassen) | Doku-Artefakte ohne Verhalten. Info gehoert in Konzeptdokumentation. |
| 10 | ReviewFlowModel / ReviewFlowStep | Beschreibt Worker-Verhalten, keine Runtime-Steuerung. Gehoert in Prompt-Template. |

### Raus (Einzelfeld)

| # | Element | Begruendung |
|---|---|---|
| 13b | `_recovered_from_context` Flag | Konzepte verbieten automatische State-Rekonstruktion. Fehlendes `phase-state.json` → nur `setup` erlaubt. Korrupt → PIPELINE_ERROR. Recovery nur als bewusste Mensch-Aktion (FK-20 §20.7.2). |

### Raus (Meta-Element, durch Einzelentscheidungen abgedeckt)

| # | Element | Begruendung |
|---|---|---|
| 18 | Policy-Doku als frozen Dataclasses | Sammelelement. Einzelentscheidungen zu 6, 7, 8, 10 gelten. |

---

### Verbessern (2 Elemente)

| # | Element | Aenderung |
|---|---|---|
| 19 | Evidence-Fingerprint | SHA256-Hash statt Dateigroessen. Trivial, robust. |
| 20 | Yield/Resume | Funktionalitaet behalten (FK-20 §20.6.2, FK-23 §23.3.1). String-basierte `pause_reason` ersetzen durch `PauseReason` StrEnum + typisierte Resume-Handler. `resume_handler_for(reason: PauseReason) -> ResumeHandler` oder Workflow-Modell mit Yield-Definitionen + `resume_triggers`. |

---

### Restructure (1 Element — Detailkonzept offen)

| # | Element | Stossrichtung |
|---|---|---|
| 16 | PhaseState 40+ Felder | Nicht "zu viele Felder", sondern "zu viele Verantwortlichkeiten in einem Objekt". Ownership-Trennung: |

**Zielstruktur (Stossrichtung, noch nicht final):**

```
StoryContext          — langlebige Story-Semantik (story_type, mode, issue_nr, Repo-Bezug)
PhaseStateCore        — aktueller Laufzeitstatus (phase, status, paused_reason, attempt_id)
PhasePayload          — diskriminierte Union pro Phase (ExplorationState | VerifyState | ClosureState | ...)
RuntimeMetadata       — nicht-fachliche Loader-/Guard-Infos (origin, Persistierbarkeit)
```

**Konsequenzen:**
- `mode`, `story_type` → raus aus PhaseState, rein in StoryContext
- QA-Zyklus-Felder → in VerifyState
- Exploration-Gate-Felder → in ExplorationState
- Closure-Substates → in ClosureState
- Recovery-Flags → RuntimeMetadata
- Phasenfremde Felder verschwinden, ungueltige Kombinationen werden schwerer darstellbar

**Status:** Detailkonzept wird separat ausgearbeitet.

---

### Uebernehmen — typisiert (8 Elemente)

| # | Element | Spezifikation fuer v3 |
|---|---|---|
| 2 | SpawnReason | StrEnum in `core/types.py`. Werte: `INITIAL`, `PAUSED_RETRY`, `REMEDIATION`. |
| 4 | IncrementStep / INCREMENT_CYCLE | StrEnum + geordnetes Tupel. Exakt wie FK-24 spezifiziert. Beschreibungen als Enum-Property, nicht als separate Dicts. |
| 5 | ReviewTemplate / REVIEW_TEMPLATE_REGISTRY | StrEnum + Registry. Felder: `template`, `filename`, `applies_to`. Felder `description` und `use_case` entfallen (nicht programmatisch genutzt). |
| 9 | WorkerContextItem / WORKER_CONTEXT_SPEC | Runtime-Gate in `prompting/workers`. `WorkerContextItemKey` als StrEnum. Registry mit `key`, `source`, `required_when`, `applies_to`. `description` nur wenn in Fehlermeldungen genutzt. Aufrufkette: `resolve_worker_context()` → `validate_worker_context()` → `compose_worker_prompt()`. Getrennt von Workflow-DSL (Phasenlogik ≠ Spawn-Vertrag). |
| 11 | WorkerArtifactDescriptor / REGISTRY | `WorkerArtifactKind` als StrEnum. Registry mit `kind`, `filename`, `format`, `min_size`. `checked_by` entfaellt. Falls Routing noetig: `required_checks: frozenset[ArtifactCheck]` statt freier String. |
| 12 | Telemetry Contract | Crash-Detection (Start/End-Paarung) essentiell. Event-Count-Vertrag auf Minimum-Schwellen ("mindestens 1 Review", "mindestens 1 Drift-Check"), keine exakten Zaehler pro Story-Groesse. |
| 13 | `_guard_failure` + `_loaded_from_file` | Uebernehmen als RuntimeMetadata (nicht als Felder auf PhaseState). `_loaded_from_file` veredelt zu `origin` (NEW \| LOADED). `_guard_failure` verhindert Persistierung von invalidem State. |
| 17 | 11 Eskalations-Trigger | Alle 11 behalten. FK-20 §20.6.1 und FK-35 §35.4.2 normativ. Kein Trigger redundant. |

---

### Uebernehmen — Produktionsanforderung (4 Elemente)

| # | Element | Spezifikation fuer v3 |
|---|---|---|
| 14 | Exploration-Summary Markdown | Pflichtartefakt. Menschenlesbares Aggregat aus strukturierten Artefakten. Primaerdokument bei Eskalation an Operator. |
| 15 | Multi-Repo Worktree Logic | `worktree_paths` (Dict: repo-id → Pfad) + `primary_repo_id` im Spawn-Vertrag. Runtime-Anforderung fuer Multi-Repo-Zielprojekte. |
| 21 | ARE-Integration | Beide Modi sind Produktionspfade. ARE deaktiviert: Pipeline laeuft ohne ARE-Gate. ARE aktiviert: ARE-Gate ist Pflicht, ohne ARE-Bestaetigung kein Merge. Installer entscheidet Modus. Kein Fallback, kein Graceful-Degradation. |
| 27 | Context Sufficiency Builder | Pflicht-Gate VOR dem Review: stellt sicher dass genuegend Informationen vorhanden sind. Wenn nicht → Informationen zusammentragen, NICHT Review ueberspringen. Reviews finden IMMER statt. |

---

### Pflicht — keine Abstufung (7 Elemente)

| # | Element | Begruendung |
|---|---|---|
| 22 | VektorDB-Abgleich | Immer aktiv. Keine Feature-Flag-Stufung. |
| 23 | LLM-Assessment-Sidecar | Pflicht. Kein Feature-Flag. |
| 24 | Preflight-Turn / Request-DSL | Pflicht. FK-24 §24.5b, 7 Request-Typen. |
| 25 | LLM-Pool-basierte Reviews | Pflicht. Immer ueber LLM-Pools. Kein Claude-Sub-Agent-Fallback. |
| 26 | Quorum / Tiebreaker | Pflicht. Dritter Reviewer bei Divergenz. |
| 28 | Section-aware Bundle-Packing | Pflicht. FK-34-121 normativ. In v2 bereits implementiert. |
| 29 | Scope-Overlap-Check | Pflicht. Parallele Story-Ausfuehrung ist Produktionsszenario. |

---

## Bilanz

| Kategorie | Anzahl |
|---|---|
| Raus | 6 Elemente + 1 Einzelfeld + 1 Meta |
| Verbessern | 2 |
| Restructure (Detailkonzept offen) | 1 |
| Uebernehmen typisiert | 8 |
| Uebernehmen Produktionsanforderung | 4 |
| Pflicht ohne Abstufung | 7 |
| **Gesamt** | **29** |

---

## Offene Detailkonzepte

1. **PhaseState-Restructuring (Element 16):** StoryContext + PhaseStateCore + PhasePayload + RuntimeMetadata. Stossrichtung steht, Detail-Design offen.
2. **Yield/Resume-Typisierung (Element 20):** PauseReason StrEnum + ResumeContract. Zusammen mit Element 16 ausarbeiten.
