# Analyse: Worker-Phasen und Koordination -- Konzeptbestand

**Datum:** 2026-04-07
**Quellen:** Ausschliesslich Konzeptdokumente aus `_concept/domain-design/` und `_concept/technical-design/`
**Zweck:** Bestandsaufnahme der Spezifikation fuer AgentKit v3 -- keine Designvorschlaege

---

## Inhaltsverzeichnis

1. [Implementation-Phase](#1-implementation-phase)
2. [Exploration-Phase](#2-exploration-phase)
3. [Worker-Koordination](#3-worker-koordination)
4. [Remediation-Loop](#4-remediation-loop)

---

## 1. Implementation-Phase

### 1.1 Ueberblick

Die Implementation-Phase ist der einzige nicht-deterministische Schritt in der Pipeline (FK-05-093). AgentKit steuert nicht **was** der Worker implementiert, sondern den **Rahmen**: Worktree-Isolation, Guards, Review-Pflicht, Inkrement-Disziplin, Handover-Paket.

**Primaerdokumente:**
- FK-24: `_concept/technical-design/24_implementation_runtime_worker_loop.md` (authority ueber: implementation, worker-loop, handover-paket, worker-manifest)
- DK-02: `_concept/domain-design/02-pipeline-orchestrierung.md`, Abschnitt "Implementierung"
- DK-00: `_concept/domain-design/00-uebersicht.md`, Phase 3

### 1.2 Worker-Start und Prompt-Uebergabe

| Anforderung | Quelle | Beschreibung | Essentiell? |
|---|---|---|---|
| Orchestrator spawnt Worker als Claude-Code-Sub-Agent | FK-24 SS24.2.1 | Agent-Tool: spawn worker, prompt_file=worker-implementation.md | Ja |
| Hook: `agent_start` Event bei Spawn | FK-24 SS24.2.1 | Telemetrie-Event fuer Traceability | Ja |
| Worker erhaelt Story-Beschreibung aus `context.json` im Prompt | FK-24 SS24.2.2 | Eingebettet in Prompt | Ja |
| Worker erhaelt Akzeptanzkriterien aus Issue-Body (via `context.json`) | FK-24 SS24.2.2 | Eingebettet in Prompt | Ja |
| Worker erhaelt Konzept/Entwurf als Datei-Referenz (`entwurfsartefakt.json` oder `concept_paths`) | FK-24 SS24.2.2 | Datei-Referenz im Prompt | Ja |
| Worker erhaelt Guardrails (`_guardrails/`-Dateien aus `context.json`) | FK-24 SS24.2.2 | Datei-Referenzen im Prompt | Ja |
| Worker erhaelt Maengelliste bei Remediation (`feedback.json`) | FK-24 SS24.2.2 | Datei-Referenz im Prompt | Ja (bei Remediation) |
| Worker erhaelt Story-Typ und Groesse (bestimmt Review-Haeufigkeit) | FK-24 SS24.2.2 | Im Prompt aus `context.json` | Ja |
| Worker erhaelt ARE `must_cover` ueber MCP (wenn aktiviert) | FK-24 SS24.2.2 | Im Prompt eingebettet | Optional (ARE) |

**Worker hat Zugriff auf:** Worktree (`story/{id}`), Prompts, Skills, LLM-Pools (fuer Reviews). **NICHT:** QA-Artefakte (gesperrt durch Hook).

### 1.3 Worker-Varianten (Prompt-Templates)

| Story-Typ | Prompt-Datei | Besonderheiten | Quelle |
|---|---|---|---|
| Implementation | `worker-implementation.md` | Volle Inkrement-Disziplin, TDD/Test-After | FK-24 SS24.2.3 |
| Bugfix | `worker-bugfix.md` | Red-Green-Suite TDD-Workflow, Reproducer-Pflicht | FK-24 SS24.2.3, SS24.9 |
| Remediation | `worker-remediation.md` | Arbeitet Maengelliste ab (Feedback-Loop) | FK-24 SS24.2.3 |

### 1.4 Inkrementelles Vorgehen (FK-05-094 bis FK-05-104)

**AgentKit muss erzwingen/unterstuetzen:**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Vertikale Inkremente (fachlich lauffaehige Teilstaende), nicht technische Schichten | FK-24 SS24.3.1 | Ja (Prompt-Vorgabe) |
| Vier-Schritt-Zyklus pro Inkrement: Implementieren, Lokal verifizieren, Drift pruefen, Committen | FK-24 SS24.3.2 | Ja |
| Lokale Verifikation: Compile/Lint + betroffene Tests (nicht Full-Build) | FK-24 SS24.3.4 | Ja (Prompt-Vorgabe) |
| Zweistufige Drift-Erkennung: Hook-basiert (deterministisch) + Worker-Selbsteinschaetzung | FK-24 SS24.3.5 | Ja |
| `increment_commit`-Hook bei jedem Commit im Worktree (PreToolUse fuer `git commit`) | FK-24 SS24.3.5 Stufe 1 | Ja |
| Drift-Evaluator-Skript: Diff berechnen, Module extrahieren, gegen Entwurfsartefakt vergleichen | FK-24 SS24.3.5 Stufe 1 | Ja |
| `drift_check`-Telemetrie-Event pro Inkrement | FK-23 SS23.7.2 | Ja |
| Bei signifikantem Drift: `drift_detected: true` im Phase-State, Orchestrator stoppt Worker | FK-24 SS24.3.5 | Ja |
| Committen erst wenn Slice konsistent und lokal gruen | FK-24 SS24.3.6 | Ja (Prompt-Vorgabe) |

### 1.5 Teststrategie (FK-05-106 bis FK-05-115)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| TDD fuer deterministische Logik | FK-24 SS24.4.1 | Ja (Prompt-Vorgabe) |
| TDD fuer Bugfix-Reproduktionen (Red-Green-Suite) | FK-24 SS24.4.1, SS24.9 | Ja |
| Test-After fuer Integrations-Verdrahtung | FK-24 SS24.4.1 | Ja (Prompt-Vorgabe) |
| Mindestens 1 Integrationstest pro Story | FK-24 SS24.4.3 | Ja (Prompt-Vorgabe) |
| Kein Inkrement bleibt ungetestet (FK-05-115) | FK-24 SS24.4.3 | Ja |
| Bugfix: Reproducer-Test ist Pflicht | FK-24 SS24.9 | Ja |

### 1.6 Reviews durch konfigurierte LLMs (FK-05-116 bis FK-05-122)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Pflicht-Reviews durch konfigurierte LLMs (nicht frei waehlbar) | FK-24 SS24.5.1 | Ja |
| Review-Haeufigkeit nach Story-Groesse: XS/S=1, M=2, L/XL=3+ | FK-24 SS24.5.2 | Ja |
| Reviews ueber freigegebene Templates (Template-Sentinel) | FK-24 SS24.5.3 | Ja |
| Review-Guard erkennt Sentinel, erzeugt `review_compliant`-Event | FK-24 SS24.5.3 | Ja |
| Review-Templates in `prompts/sparring/` (6 definierte Templates) | FK-24 SS24.5.4 | Ja |
| Evidence Assembly ersetzt manuelle merge_paths-Kuration (ab v3.0) | FK-24 SS24.5a | Ja |
| Evidence Assembler ueber CLI: `agentkit evidence assemble` | FK-24 SS24.5a.1 | Ja |
| 3-Stufen-Assembly: Git-Diff + Nachbardateien, Import-Extraktion, Worker-Hints | FK-24 SS24.5a.1 | Ja |
| Optionaler Preflight-Turn vor Review (bis zu 8 strukturierte Requests) | FK-24 SS24.5b | Optional (aber spezifiziert) |
| Request-DSL mit 7 Request-Typen (NEED_FILE, NEED_SCHEMA, etc.) | DK-04 SS4.5.3.3 | Optional (aber spezifiziert) |
| RequestResolver loest Requests deterministisch auf | FK-24 SS24.5b.1 | Optional (aber spezifiziert) |

### 1.7 Finaler Build und Gesamttest

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Vollstaendiger Build (gesamtes Projekt) nach allen Inkrementen | FK-24 SS24.6 | Ja |
| Gesamte Test-Suite ausfuehren (Regression erkennen) | FK-24 SS24.6 | Ja |
| Push: `git push -u origin story/{story_id}` | FK-24 SS24.6 | Ja |

### 1.8 Handover-Paket (FK-05-123 bis FK-05-126)

**Schema: `handover.json`** -- FK-24 SS24.7.2

| Pflichtfeld | Typ | Beschreibung | Essentiell? |
|---|---|---|---|
| `schema_version` | String | `"3.0"` | Ja |
| `story_id` | String | Story-ID | Ja |
| `run_id` | String | Run-UUID | Ja |
| `changes_summary` | String | Was wurde geaendert und warum | Ja |
| `increments` | Array | Vertikale Inkremente mit Commit-SHA und Tests | Ja |
| `assumptions` | Array | Welche Annahmen gelten (duerfen leer sein) | Ja |
| `existing_tests` | Array | Welche Tests existieren (Test-Locator) | Ja |
| `risks_for_qa` | Array | Welche Risiken sollte QA-Agent gezielt pruefen | Ja |
| `drift_log` | Array | Dokumentierte Abweichungen vom Entwurf (duerfen leer sein) | Ja |
| `acceptance_criteria_status` | Object | Status pro AC: ADDRESSED, NOT_APPLICABLE, BLOCKED | Ja |

**Nutzung in Verify:** Schicht 1 nutzt `increments`, `existing_tests`. Schicht 2 nutzt `changes_summary`, `assumptions`, `drift_log`, `acceptance_criteria_status`. Schicht 3 nutzt `risks_for_qa`, `existing_tests`.

### 1.9 Worker-Manifest (`worker-manifest.json`)

**Drei moegliche Status:** FK-24 SS24.8.2

| Status | Bedeutung | Pflichtfelder |
|---|---|---|
| `COMPLETED` | Alle ACs adressiert, Build/Tests gruen | `story_id`, `files_changed`, `tests_added`, `commit_sha`, `acceptance_criteria_status` |
| `COMPLETED_WITH_ISSUES` | ACs adressiert, bekannte Einschraenkungen | wie COMPLETED + dokumentierte Findings |
| `BLOCKED` | Unloesbare Constraint-Kollision (REF-042) | `story_id`, `blocking_issue`, `blocking_category`, `attempted_remediations`, `recommended_next_action`, `partial_work_summary`, `safe_to_snapshot_commit` |

**Blocking-Kategorien (4):** `POLICY_CONFLICT`, `ENVIRONMENTAL`, `FIXABLE_LOCAL`, `FIXABLE_CODE`

### 1.10 Worker-Artefakte (Gesamtbild)

| Artefakt | Zweck | Format | Geprueft von | Quelle |
|---|---|---|---|---|
| `protocol.md` | Menschenlesbares Protokoll | Markdown | Structural Check (> 50 Bytes) | FK-24 SS24.8.1 |
| `handover.json` | Fachliche Uebergabe an QA | JSON | Schicht 2+3 | FK-24 SS24.8.1 |
| `worker-manifest.json` | Technische Deklaration | JSON | Schicht 1 (Structural Checks) | FK-24 SS24.8.1 |

### 1.11 Worker-Health-Monitor (REF-042)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Hook-basiertes Scoring-Modell (0-100 Punkte) | FK-24 SS24.12, DK-02 | Ja |
| Gewichtete Heuristiken: Laufzeit, Repetitions-Muster, Hook/Commit-Konflikte, Fortschritts-Stagnation, Tool-Call-Anzahl | FK-24 SS24.12 | Ja |
| Eskalationsleiter: <50 Normal, 50-69 Warnung, 70-84 Soft-Intervention, >=85 Hard Stop | FK-24 SS24.12 | Ja |
| Soft-Intervention: Strukturierte Selbstdiagnose (PROGRESSING / BLOCKED / SPARRING_NEEDED) | FK-24 SS24.12 | Ja |
| LLM-Assessment als optionaler Sidecar-Prozess (Korrekturfaktor -10 bis +10) | FK-24 SS24.12 | Optional |
| Persistenz: `_temp/qa/<STORY-ID>/agent-health.json` | FK-24 SS24.12 | Ja |

### 1.12 Telemetrie der Implementation-Phase

| Event | Erwartungswert | Quelle |
|---|---|---|
| `agent_start` (subagent_type: worker) | Genau 1 | FK-24 SS24.10 |
| `increment_commit` | >= 1 | FK-24 SS24.10 |
| `drift_check` | >= 1 | FK-24 SS24.10 |
| `review_request` | Abhaengig von Groesse | FK-24 SS24.10 |
| `review_response` | = review_request | FK-24 SS24.10 |
| `review_compliant` | = review_request | FK-24 SS24.10 |
| `llm_call` (role: Worker-Review) | = review_request | FK-24 SS24.10 |
| `worker_health_score` | >= 0 (bei aktivem Monitor) | FK-24 SS24.10 |
| `worker_health_intervention` | 0 oder 1 | FK-24 SS24.10 |
| `agent_end` (subagent_type: worker) | Genau 1 | FK-24 SS24.10 |

### 1.13 Bugfix-Workflow (FK-05-107, FK-05-108)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Red-Green-Suite TDD-Workflow | FK-24 SS24.9.1 | Ja |
| 5 Schritte: Reproducer schreiben, Red Phase (FAIL), Bug fixen, Green Phase (PASS), Suite Phase (Regression) | FK-24 SS24.9.1 | Ja |
| Structural Checks validieren: Red (exit!=0), Green (exit==0), Suite (exit==0), Red/Green-Konsistenz | FK-24 SS24.9.2 | Ja |

---

## 2. Exploration-Phase

### 2.1 Ueberblick

Die Exploration-Phase ist optional und gilt nur fuer implementierende Story-Typen (Implementation, Bugfix). Sie erzeugt ein Entwurfsartefakt (Change-Frame), das vor der Implementierung geprueft und eingefroren wird.

**Primaerdokumente:**
- FK-23: `_concept/technical-design/23_modusermittlung_exploration_change_frame.md` (authority ueber: mode-routing, exploration-phase, change-frame, drift-detection)
- DK-02: `_concept/domain-design/02-pipeline-orchestrierung.md`, Abschnitte "Exploration-Phase" und "Modus-Ermittlung"
- DK-00: `_concept/domain-design/00-uebersicht.md`, Phase 2

### 2.2 Modus-Ermittlung

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Deterministische 6-Kriterien-Entscheidung (technische Umsetzung in FK-22 SS22.8) | FK-23 SS23.2 | Ja |
| Default: Exploration Mode (fail-closed) | FK-23 SS23.2.1 | Ja |
| Execution Mode nur wenn ALLE 6 Kriterien auf Execution UND kein VektorDB-Konflikt | FK-23 SS23.2.1 | Ja |
| Execution Mode: naechste Phase = `implementation` mit `worker-implementation.md` | FK-23 SS23.2.2 | Ja |
| Exploration Mode: naechste Phase = `exploration` mit `worker-exploration.md` | FK-23 SS23.2.2 | Ja |

### 2.3 Feste Schrittfolge des Exploration-Workers (FK-05-083)

| Schritt | Was der Worker tut | Output | Quelle |
|---|---|---|---|
| 1. Verdichten | Story auf praezise Veraenderungsabsicht komprimieren | 1-2 Saetze (Ziel und Scope) | FK-23 SS23.3.2 |
| 2. Referenzdokumente | Passende Architektur-/Strategie-/Konzeptdokumente identifizieren | Liste der Dokumente | FK-23 SS23.3.2 |
| 3. Aenderungsflaeche | Im bestehenden System lokalisieren: Module, Services, APIs, Tabellen | Betroffene Bausteine | FK-23 SS23.3.2 |
| 4. Loesungsrichtung | Architekturmuster waehlen, Verankerungsort bestimmen, begruenden | Loesungsrichtung | FK-23 SS23.3.2 |
| 5. Selbst-Konformitaet | Eigenen Entwurf gegen Referenzdokumente abgleichen | Konformitaetsaussage | FK-23 SS23.3.2 |
| 6. Schreiben | Entwurfsartefakt mit allen 7 Bestandteilen erzeugen | `entwurfsartefakt.json` | FK-23 SS23.3.2 |

**Wichtig (FK-05-087):** Die nachfolgende Dokumententreue-Pruefung ist die **zweite, unabhaengige** Konformitaetspruefung, nicht die erste.

### 2.4 Entwurfsartefakt (Change-Frame) -- 7 Bestandteile (FK-05-075 bis FK-05-082)

| Bestandteil | Pflicht | Validierung | Quelle |
|---|---|---|---|
| `ziel_und_scope` | Ja | `aendert_sich` + `aendert_sich_nicht` nicht leer | FK-23 SS23.4.1, SS23.4.2 |
| `betroffene_bausteine` | Ja | `betroffen` mind. 1 Eintrag | FK-23 SS23.4.2 |
| `loesungsrichtung` | Ja | Alle 3 Felder nicht leer | FK-23 SS23.4.2 |
| `vertragsaenderungen` | Ja | Mind. 1 der 4 Arrays nicht leer (oder explizit "keine") | FK-23 SS23.4.2 |
| `konformitaetsaussage` | Ja | `referenzdokumente` mind. 1 | FK-23 SS23.4.2 |
| `verifikationsskizze` | Ja | Mind. 1 Testebene beschrieben | FK-23 SS23.4.2 |
| `offene_punkte` | Ja | Alle 3 Arrays vorhanden (duerfen leer sein) | FK-23 SS23.4.2 |

**Schema:** `entwurfsartefakt.schema.json`, Schema-Version `"3.0"`. Weitere Pflichtfelder: `schema_version`, `story_id`, `run_id`, `created_at`, `frozen`.

### 2.5 Freeze-Mechanismus

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `frozen: true` im JSON setzen | FK-23 SS23.4.3 | Ja |
| Datei nach `_temp/qa/{story_id}/entwurfsartefakt.json` schreiben | FK-23 SS23.4.3 | Ja |
| Schreibschutz ueber Hook-Mechanismus (kein Dateisystem-Schutz) | FK-23 SS23.4.3 | Ja |

### 2.6 Exploration Exit-Gate: Drei-Stufen-Modell (REF-034)

Phase ist erst `COMPLETED` wenn `exploration_gate_status == "approved_for_implementation"`.

**Stufe 1: Dokumententreue Ebene 2 (Entwurfstreue)**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| StructuredEvaluator prueft Entwurfstreue (synchron, deterministisch gesteuert) | FK-23 SS23.5.1, SS23.5.2 | Ja |
| Referenzdokumente aus zwei Quellen: Worker-deklariert + System-ergaenzt | FK-23 SS23.5.2 | Ja |
| Bei FAIL: Eskalation an Mensch. Pipeline pausiert. | FK-23 SS23.5.3 | Ja |
| Gate fuer `offene_punkte.freigabe_noetig`: Pipeline pausiert bei nicht-leerer Liste | FK-23 SS23.5.3 | Ja |
| Phase-State: `exploration_gate_status = "doc_compliance_passed"` bei PASS | FK-23 SS23.5 | Ja |

**Stufe 2: Design-Review Gate**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| PAUSED: `awaiting_design_review`, `agents_to_spawn: [design-reviewer]` | FK-23 SS23.3.1 | Ja |
| Design-Review als LLM-Review-Agent (unabhaengig vom Worker) | FK-23 SS23.5 | Ja |
| Nach Design-Review: Trigger-Evaluation (deterministisch) | FK-23 SS23.3.1 | Ja |
| Bei Risikotrigger: Design-Challenge (zweiter LLM-Review) | FK-23 SS23.3.1 | Ja |
| Stufe 2c: Finale Aggregation mit Verdict | FK-23 SS23.3.1 | Ja |
| Verdict PASS -> `exploration_gate_status = "design_review_passed"` | FK-23 SS23.3.1 | Ja |
| Verdict PASS_WITH_CONCERNS (required_before_impl): PAUSED human_approval_required | FK-23 SS23.3.1 | Ja |
| Verdict PASS_WITH_CONCERNS (advisory/required_in_impl): weiter | FK-23 SS23.3.1 | Ja |
| Verdict FAIL remediable (round <= 2): PAUSED awaiting_exploration_remediation | FK-23 SS23.3.1 | Ja |
| Verdict FAIL non-remediable (oder round > 2): ESCALATED | FK-23 SS23.3.1 | Ja |
| `exploration_review_round` Zaehler (max 2 Runden, dann Eskalation) | FK-23 SS23.5 | Ja |

**Stufe 3: Approved for Implementation**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `exploration_gate_status = "approved_for_implementation"` | FK-23 SS23.5 | Ja |
| Phase: exploration COMPLETED | FK-23 SS23.3.1 | Ja |

### 2.7 Uebergang zur Implementation

**Bei Exploration Mode (REF-034):**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Phase Runner setzt `agents_to_spawn` auf Worker-Implementation | FK-23 SS23.6.1 | Ja |
| `required_acceptance_criteria` aus `required_in_impl`-Concerns | FK-23 SS23.6.1 | Ja |
| `advisory_context` aus `advisory`-Concerns | FK-23 SS23.6.1 | Ja |
| Orchestrator spawnt Worker mit `worker-implementation.md` | FK-23 SS23.6.1 | Ja |
| Worker hat Zugriff auf eingefrorenes Entwurfsartefakt als verbindliche Vorgabe | FK-23 SS23.6.1 | Ja |
| Worker hat Zugriff auf `design-review.json` mit Review-/Challenge-Befunden | FK-23 SS23.6.1 | Ja |
| Worker darf vom Entwurf abweichen, nur mit Markierung und Begruendung (FK-05-101) | FK-23 SS23.6.1 | Ja |
| Bei signifikanter Abweichung: erneute Dokumententreue-Pruefung (FK-05-102) | FK-23 SS23.6.1 | Ja |

**Bei Execution Mode:**

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Keine Exploration-Phase. Worker startet direkt mit `worker-implementation.md` | FK-23 SS23.6.2 | Ja |
| Dokumententreue als Umsetzungstreue (Ebene 3) nach Implementierung in Verify | FK-23 SS23.6.2 | Ja |

### 2.8 Phase-State-Felder fuer Exploration (REF-034)

| Feld | Typ | Werte | Quelle |
|---|---|---|---|
| `exploration_gate_status` | String | `""`, `"doc_compliance_passed"`, `"design_review_passed"`, `"design_review_failed"`, `"approved_for_implementation"` | FK-23 SS23.5, FK-20 SS20.3.2 |
| `exploration_review_round` | Integer | 0-2, dann Eskalation | FK-23 SS23.5, FK-20 SS20.3.2 |

---

## 3. Worker-Koordination

### 3.1 Ueberblick

Die Worker-Koordination beschreibt das Zusammenspiel zwischen dem **Orchestrator-Agent**, dem **Phase Runner** (deterministisches Skript) und den **Worker-Agents**.

**Primaerdokumente:**
- FK-20: `_concept/technical-design/20_workflow_engine_state_machine.md` (authority ueber: workflow-engine, phase-runner, feedback-loop)
- DK-01: `_concept/domain-design/01-rollen-und-llm-einsatz.md` (Rollentrennung, Orchestrator-Prinzipien)
- DK-02: `_concept/domain-design/02-pipeline-orchestrierung.md` (Phase-Transition-Enforcement)

### 3.2 Rollentrennung: AgentKit vs. Orchestrator

| Verantwortung | Traeger | Beschreibung | Quelle |
|---|---|---|---|
| Pipeline-Steuerung (Phasenwechsel, Feedback-Loops, Eskalation) | Phase Runner (AgentKit, deterministisch) | Python-Skript, entscheidet ueber Phasenwechsel | FK-20 SS20.1 |
| Agent-Spawn (Worker starten, Ergebnisse lesen, naechsten Schritt bestimmen) | Orchestrator-Agent (LLM) | Liest Phase-State, spawnt Agents | FK-20 SS20.4.3 |
| Inhaltliche Arbeit (Code, Tests, Reviews) | Worker-Agent (LLM) | Arbeitet im Worktree | FK-24 SS24.1 |
| Phasenlogik, Feedback-Loop-Entscheidung | Phase Runner | Orchestrator hat keinen Einfluss auf Phasenlogik | FK-20 SS20.1 |

**Kernprinzip (FK-05-002):** "Kein Agent entscheidet ueber den Ablauf; der Ablauf entscheidet, wann welcher Agent arbeiten darf."

### 3.3 Phase Runner: CLI-Schnittstelle

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| CLI: `agentkit run-phase {phase} --story {story_id} [--config {path}]` | FK-20 SS20.4.1 | Ja |
| Orchestrator ruft Phase Runner fuer jede Phase einzeln auf | FK-20 SS20.4.1 | Ja |
| Phase Runner fuehrt Phase aus, aktualisiert Phase-State, beendet sich | FK-20 SS20.4.1 | Ja |
| Orchestrator liest Phase-State und entscheidet naechsten Schritt | FK-20 SS20.4.1 | Ja |
| Phasen-Dispatch: match phase -> case "setup"/"exploration"/"implementation"/"verify"/"closure" | FK-20 SS20.4.2 | Ja |

### 3.4 Phase-Transition-Enforcement

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `run_phase()` prueft Phasenuebergang gegen `PHASE_TRANSITION_GRAPH` | FK-20 SS20.4.2a | Ja |
| Fail-closed: ungueltiger Uebergang -> ESCALATED, Phase wird nicht betreten | FK-20 SS20.4.2a | Ja |
| Resume derselben Phase (z.B. Exploration nach PAUSED) ist kein Uebergang | FK-20 SS20.4.2a | Ja |
| Status-Pruefung: Vorphase muss COMPLETED sein (Ausnahme: Remediation-Pfad) | FK-20 SS20.4.2a | Ja |
| Erstaufruf ohne State-Datei: nur `setup` erlaubt | FK-20 SS20.4.2a | Ja |
| Semantische Preconditions: Exploration-Gate muss bestanden sein vor Implementation | FK-20 SS20.4.2a | Ja |
| Diagnostische Fehlermeldungen: from_phase, to_phase, from_status, erlaubte Uebergaenge | FK-20 SS20.4.2a | Ja |

**Erlaubter Phasenuebergangsgraph:**

| Von | Erlaubte Ziele | Quelle |
|---|---|---|
| setup | exploration, implementation | DK-02 |
| exploration | implementation | DK-02 |
| implementation | verify | DK-02 |
| verify | implementation, closure, exploration | DK-02 |
| closure | (Terminal) | DK-02 |

### 3.5 Spawn-Spezifikation (`agents_to_spawn`)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `agents_to_spawn` Array im Phase-State | FK-20 SS20.3.1 | Ja |
| Jeder Eintrag hat: `type`, `prompt_file`, `model` | FK-20 SS20.3.1 | Ja |
| Orchestrator liest `agents_to_spawn` und spawnt Agents | FK-20 SS20.4.3 | Ja |
| Bei Exploration Mode: zusaetzlich `required_acceptance_criteria` und `advisory_context` | FK-23 SS23.6.1 | Ja |

**Spawn-Contract (Architektonische Grenzregel, DK-01 SS1.1):**

| Rollentyp | Realisierung | Beispiele | Quelle |
|---|---|---|---|
| Rollen OHNE Dateisystem-Zugriff | LlmEvaluator.evaluate() ueber MCP-Pool (deterministisch gesteuert) | QA-Bewertung, Semantic Review, Dokumententreue, Design-Review, Design-Challenge | DK-01 SS1.1 |
| Rollen MIT Dateisystem-Zugriff | Claude-Agent-Spawn | Worker, Adversarial Agent | DK-01 SS1.1 |

### 3.6 Phasen-Ergebnisse und Orchestrator-Reaktion

| Phase-Ergebnis | Orchestrator reagiert | Quelle |
|---|---|---|
| `setup` COMPLETED, `mode: execution` | Spawnt Worker (Implementation) | FK-20 SS20.4.3 |
| `setup` COMPLETED, `mode: exploration` | Spawnt Exploration-Worker | FK-20 SS20.4.3 |
| `setup` FAILED | Eskalation an Mensch | FK-20 SS20.4.3 |
| `exploration` COMPLETED | Spawnt Implementation-Worker | FK-20 SS20.4.3 |
| `exploration` ESCALATED | Eskalation an Mensch | FK-20 SS20.4.3 |
| `exploration` PAUSED (awaiting_design_review) | Spawnt Design-Reviewer | FK-23 SS23.3.1 |
| `exploration` PAUSED (awaiting_design_challenge) | Spawnt Design-Challenger | FK-23 SS23.3.1 |
| `exploration` PAUSED (awaiting_exploration_remediation) | Spawnt Exploration-Worker erneut | FK-23 SS23.3.1 |
| `implementation` COMPLETED | Ruft `run-phase verify` auf | FK-20 SS20.4.3 |
| `implementation` ESCALATED (worker_blocked) | Eskalation an Mensch | FK-20 SS20.4.3 |
| `verify` COMPLETED | Ruft `run-phase closure` auf | FK-20 SS20.4.3 |
| `verify` FAILED | Spawnt Remediation-Worker, dann erneut `run-phase verify` | FK-20 SS20.4.3 |
| `verify` ESCALATED (max Runden) | Eskalation an Mensch | FK-20 SS20.4.3 |
| `closure` COMPLETED | Story ist Done | FK-20 SS20.4.3 |
| `closure` ESCALATED | Eskalation an Mensch | FK-20 SS20.4.3 |

### 3.7 Schlanker Orchestrator (DK-01 SS1.5)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Orchestrator erhaelt minimalen Kontext (nur Steuerungsinformationen) | DK-01 SS1.5 | Ja |
| Steuerungsinfo: Phasenergebnis (PASS/FAIL/ESCALATE/BLOCKED), Fehlerklasse, Retry-Faehigkeit, Phasenuebergang | DK-01 SS1.5 | Ja |
| Steuerungsinfo NICHT: Story-Kontext, Anforderungsdetails, Code-Diffs, Analyseinhalte | DK-01 SS1.5 | Ja |
| Orchestrator liest nur Phasen-Steuerungsartefakt (reduzierte Steuerungsprojektion) | DK-01 SS1.5 | Ja |
| Orchestrator-Guard erzwingt: kein Lesezugriff auf Inhaltsartefakte der Content-Plane | DK-01 SS1.5 | Ja |

### 3.8 Phase-State-Persistenz

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `_temp/qa/{story_id}/phase-state.json` als zentrale State-Datei | FK-20 SS20.3.1 | Ja |
| Nur Phase Runner schreibt, Orchestrator liest nur | FK-20 SS20.3.3 | Ja |
| Schluesselfeder: phase, status, mode, story_type, attempt, feedback_rounds, max_feedback_rounds, verify_layer, verify_context, agents_to_spawn, closure_substates, errors, warnings, producer | FK-20 SS20.3.2 | Ja |
| `verify_context` bestimmt QA-Tiefe (`post_exploration` / `post_implementation`) | FK-25 SS25.3a | Ja |
| `escalation_reason` bei ESCALATED (REF-042) | FK-20 SS20.3.2 | Ja |

### 3.9 Yield/Resume-Zyklen (PAUSED-Mechanismus)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Phase-State `status: PAUSED` mit `pause_reason` | FK-20 SS20.6.2 | Ja |
| Resume derselben Phase ist kein Phasenuebergang | FK-20 SS20.4.2a | Ja |
| `agentkit resume --story {id}` nach menschlicher Pruefung | FK-23 SS23.5.3 | Ja |
| PAUSED vs ESCALATED: PAUSED = voruebergehend, ESCALATED = permanent gestoppt | FK-20 SS20.6.2 | Ja |

### 3.10 Recovery

| Szenario | Recovery | Quelle |
|---|---|---|
| Agent-Session crashed in Implementation | Neuer Run mit neuer `run_id`, Worktree existiert noch | FK-20 SS20.7.1 |
| Phase Runner crashed in Verify | `run-phase verify` erneut, Schicht 1 idempotent | FK-20 SS20.7.1 |
| Closure crashed nach Merge vor Issue-Close | `run-phase closure` erneut, Substates bestimmen Einstieg | FK-20 SS20.7.1 |
| Mensch will eskalierten Run fortsetzen | `agentkit reset-escalation --story {id}`, neuer Run | FK-20 SS20.7.1 |

---

## 4. Remediation-Loop

### 4.1 Ueberblick

Der Remediation-Loop ist der Feedback-Zyklus Verify -> Remediation -> Implementation -> Verify. Er wird vom Phase Runner deterministisch gesteuert.

**Primaerdokumente:**
- FK-20: `_concept/technical-design/20_workflow_engine_state_machine.md`, SS20.5 (Feedback-Loop)
- FK-25: `_concept/technical-design/25_verify_pipeline_closure_orchestration.md`, SS25.2 (Atomarer QA-Zyklus), SS25.8 (Feedback-Mechanismus)
- DK-04: `_concept/domain-design/04-qualitaetssicherung.md`, SS4.6 (Finding-Resolution und Remediation-Haertung)

### 4.2 Ablauf

```
Verify FAIL
  -> Phase Runner: feedback_rounds++, qa_cycle_status = "awaiting_remediation"
  -> Phase Runner: Maengelliste aus Verify-Ergebnissen assemblieren -> feedback.json
  -> Phase Runner: agents_to_spawn = [remediation_worker]
  -> Orchestrator: Spawnt Remediation-Worker mit Maengelliste
  -> Remediation-Worker: Fixes commiten
  -> Orchestrator: Ruft run-phase verify erneut auf
  -> Phase Runner: advance_qa_cycle() -> alle zyklusgebundenen Artefakte invalidiert
  -> Verify laeuft von vorne (alle 4 Schichten)
  -> Bei erneutem FAIL und feedback_rounds < max: Loop wiederholen
  -> Bei feedback_rounds >= max: ESCALATED
```

### 4.3 Steuerung

| Wer steuert was | Traeger | Quelle |
|---|---|---|
| Feedback-Runden-Zaehler (feedback_rounds++) | Phase Runner | FK-20 SS20.5.1 |
| Max-Runden-Pruefung (feedback_rounds < max_feedback_rounds) | Orchestrator (liest Phase-State) | FK-20 SS20.5.1 |
| Maengelliste assemblieren | Phase Runner (build_feedback()) | FK-25 SS25.8.1 |
| Remediation-Worker spawnen | Orchestrator | FK-20 SS20.5.1 |
| Artefakt-Invalidierung (advance_qa_cycle()) | Phase Runner | FK-25 SS25.2 |
| Eskalation bei max Runden | Phase Runner setzt ESCALATED | FK-25 SS25.8.3 |

### 4.4 Atomarer QA-Zyklus (FK-25 SS25.2)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Drei Identitaetsfelder pro Zyklus: `qa_cycle_id` (12-Zeichen UUID), `qa_cycle_round` (monotoner Zaehler), `evidence_epoch` (ISO-8601 Timestamp) | FK-25 SS25.2.1 | Ja |
| QA-Zyklus-Felder im Story-State persistiert und in alle QA-Artefakte geschrieben | FK-25 SS25.2.1 | Ja |
| State Machine: idle -> awaiting_qa -> awaiting_policy -> awaiting_remediation -> pass / escalated | FK-25 SS25.2.2 | Ja |
| Bei neuem Zyklus: 11 zyklusgebundene Artefaktdateien geloescht oder nach `stale/` verschoben | FK-25 SS25.2.3 | Ja |
| Runtime-Staleness-Check: `artifact_matches_current_cycle()` prueft `qa_cycle_id` | FK-25 SS25.2.4 | Ja |
| Fail-closed bei Mismatch: Artefakt wird abgelehnt | FK-25 SS25.2.4 | Ja |

**Invalidierte Artefakte (11):**
`semantic.json`, `guardrail.json`, `decision.json`, `llm-review.json`, `qa_review.json`, `feedback.json`, `adversarial.json`, `e2e_verify.json`, `structural.json`, `context.json`, `context_sufficiency.json`

### 4.5 Maengelliste (feedback.json)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Schema: `story_id`, `run_id`, `feedback_round`, `findings[]` | FK-25 SS25.8.2, FK-20 SS20.5.2 | Ja |
| Findings aus allen 4 Schichten gesammelt | FK-25 SS25.8.1 | Ja |
| Pro Finding: `source` (structural/llm-review/semantic-review/adversarial), `check_id`, `status`, `detail`/`reason`/`description` | FK-25 SS25.8.2 | Ja |
| Remediation-Worker erhaelt `feedback.json` als Input | FK-25 SS25.8.2 | Ja |

### 4.6 Konfiguration

| Parameter | Default | Config-Pfad | Quelle |
|---|---|---|---|
| Max Feedback-Runden | 3 | `policy.max_feedback_rounds` | FK-20 SS20.5.3 |
| Max Exploration-Review-Runden | 2 | (implizit in FK-23) | FK-23 SS23.5 |

### 4.7 Finding-Resolution im Remediation-Modus (DK-04 SS4.6)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Layer-2-StructuredEvaluator im Remediation-Modus (Runde 2+): Findings der Vorrunde als zusaetzlicher Prompt-Kontext | DK-04 SS4.6.2 | Ja |
| Findings direkt aus Review-Artefakten der Vorrunde laden, NICHT aus Worker-Zusammenfassungen | DK-04 SS4.6.2 | Ja |
| Findings aus `stale/{previous_cycle_id}/` laden | FK-25 SS25.10a.3 | Ja |
| Evaluator bewertet pro Finding: `fully_resolved`, `partially_resolved`, `not_resolved` | DK-04 SS4.6.2 | Ja |
| Bewertung als zusaetzliche Check-IDs im bestehenden QA-Review-Output (kein neues Artefakt) | DK-04 SS4.6.2 | Ja |
| Closure blockiert wenn mindestens ein Finding `partially_resolved` oder `not_resolved` | DK-04 SS4.6.2, FK-25 SS25.10a | Ja |
| Worker-Artefakte (protocol.md, handover.json) duerfen Finding-Status NICHT autoritativ setzen (Trust C) | DK-04 SS4.2 | Ja |

### 4.8 Mandatory Adversarial Targets (DK-04 SS4.6.3)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Layer-2-Finding vom Typ `assertion_weakness` mit testbarem Negativfall wird mandatory adversarial target | DK-04 SS4.6.3 | Ja |
| Strukturiertes Target mit: Finding-ID, Normative Referenz, bereits adressierter Teil, offener Teil | DK-04 SS4.6.3 | Ja |
| Adversarial Agent muss pro mandatory target: Test schreiben ODER `UNRESOLVABLE: Grund` melden | DK-04 SS4.6.3 | Ja |
| Nicht erfuelltes mandatory target: deterministisch zurueck in Remediation-Loop | FK-25 SS25.8.4 | Ja |
| Nicht erfuelltes Target wird als zusaetzlicher Maengelpunkt in `feedback.json` uebergeben | FK-25 SS25.8.4 | Ja |
| Rueckkopplung nutzt bestehenden Loop (max 3 Runden) | FK-25 SS25.8.4 | Ja |

### 4.9 Fehlschlagende Adversarial-Tests (Quarantaene)

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| Valide fehlschlagende Tests nicht verworfen, sondern in `tests/adversarial_quarantine/` | FK-25 SS25.6.4 | Ja |
| Remediation-Worker erhaelt expliziten Auftrag, Test gruen zu machen | FK-25 SS25.6.4 | Ja |
| Analog zum Red-Green-Workflow bei Bugfixes | FK-25 SS25.6.4 | Ja |

### 4.10 Eskalation bei Max-Runden

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `feedback_rounds >= max_feedback_rounds`: Status ESCALATED | FK-25 SS25.8.3 | Ja |
| `qa_cycle_status = "escalated"` | FK-25 SS25.8.3 | Ja |
| Story permanent blockiert bis menschliche Intervention | FK-25 SS25.8.3 | Ja |
| `agentkit reset-escalation` CLI-Kommando setzt `feedback_rounds` zurueck | FK-25 SS25.8.3 | Ja |
| Menschliche Optionen: Story anpassen, Anforderungen lockern, manuell fixen | FK-20 SS20.5.3 | Ja |

### 4.11 Verify-Kontext im Remediation-Loop

| Anforderung | Quelle | Essentiell? |
|---|---|---|
| `verify_context = "post_implementation"` fuer alle Remediation-Runden | FK-25 SS25.3a | Ja |
| Volle 4-Schichten-QA bei jedem Remediation-Verify (nicht nur Structural) | FK-25 SS25.3a | Ja |
| `STRUCTURAL_ONLY_PASS` nach Implementation verboten | FK-25 SS25.3a.4 | Ja |
| Fehlende LLM-Reviews sind HARD BLOCKER (nicht WARNING) | FK-25 SS25.3a.5 | Ja |

---

## Zusammenfassung: Was muss fuer AgentKit v3 umgesetzt werden

### Essentiell (Kernfunktionalitaet)

**Implementation-Phase:**
1. Worker-Spawn-Protokoll mit Prompt-Komposition aus context.json + Templates
2. Worker-Varianten (3 Prompt-Templates: Implementation, Bugfix, Remediation)
3. Handover-Paket-Schema (`handover.json` mit 7 Pflichtfeldern)
4. Worker-Manifest-Schema (`worker-manifest.json` mit 3 Status: COMPLETED, COMPLETED_WITH_ISSUES, BLOCKED)
5. protocol.md als menschenlesbares Protokoll
6. Drift-Erkennung: Hook-basiert (deterministisch) + Worker-Selbsteinschaetzung
7. Telemetrie-Events (10 definierte Events)
8. Review-Pflicht durch konfigurierte LLMs mit Template-Sentinels
9. Evidence Assembly (deterministischer Assembler mit 3-Stufen-Pipeline)
10. Worker-Health-Monitor (Scoring-Modell, Eskalationsleiter)
11. Bugfix Red-Green-Suite-Workflow

**Exploration-Phase:**
1. Modus-Ermittlung (6-Kriterien, deterministisch, fail-closed)
2. Feste Schrittfolge des Exploration-Workers (6 Schritte)
3. Entwurfsartefakt-Schema (7 Bestandteile, JSON mit Validierung)
4. Freeze-Mechanismus (Hook-basiert)
5. Drei-Stufen-Exit-Gate (Dokumententreue, Design-Review, Approved)
6. Design-Review und Design-Challenge via LLM-Evaluator
7. exploration_gate_status und exploration_review_round Tracking
8. Uebergang zur Implementation mit required_acceptance_criteria

**Worker-Koordination:**
1. Phase Runner als CLI (`agentkit run-phase`)
2. Phase-Transition-Enforcement mit Graphen-Validierung
3. Phase-State-Persistenz (`phase-state.json`) -- nur Phase Runner schreibt
4. agents_to_spawn Spawn-Spezifikation
5. Schlanker Orchestrator (nur Steuerungsinfo, Orchestrator-Guard)
6. PAUSED/Resume-Mechanismus
7. Eskalationsverhalten (PAUSED vs ESCALATED)
8. Recovery (Crash-Handling via Substates und run_id)
9. verify_context (post_exploration / post_implementation)

**Remediation-Loop:**
1. Atomarer QA-Zyklus (3 Identitaetsfelder, Artefakt-Invalidierung, Staleness-Check)
2. Maengelliste (feedback.json) aus allen 4 Schichten
3. Feedback-Runden-Zaehler mit konfigurierbarem Maximum
4. Finding-Resolution im Remediation-Modus (Layer-2-Evaluator bewertet Vorrunden-Findings)
5. Mandatory Adversarial Targets mit Rueckkopplung
6. Adversarial-Test-Quarantaene fuer Remediation-Worker
7. Closure-Blocker bei nicht aufgeloesten Findings
8. reset-escalation CLI-Kommando

### Optional / Nice-to-have (aber spezifiziert)

1. ARE-Integration (must_cover, Evidence, ARE-Gate) -- via Feature-Flag
2. VektorDB-Abgleich -- via Feature-Flag
3. LLM-Assessment-Sidecar im Worker-Health-Monitor
4. Preflight-Turn im Review-Flow (Request-DSL, RequestResolver)
5. LLM-Pool-basierte Reviews (ChatGPT, Gemini, Grok) -- via Feature-Flag
6. Quorum bei Reviewer-Divergenz (Tiebreaker durch dritten Reviewer)
7. Context Sufficiency Builder (Pre-Step fuer Layer 2)
8. Section-aware / Symbol-aware Bundle-Packing
9. Scope-Overlap-Check im Preflight (parallele Stories)
