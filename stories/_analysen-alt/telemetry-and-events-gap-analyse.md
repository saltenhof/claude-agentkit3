# telemetry-and-events — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `telemetry-and-events` |
| Display-Name | `Telemetrie und Events` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-05, FK-68, FK-69, formal.telemetry-analytics.entities, formal.telemetry-analytics.state-machine, formal.telemetry-analytics.commands, formal.telemetry-analytics.events, formal.telemetry-analytics.invariants, formal.telemetry-analytics.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/telemetry/`, `src/agentkit/telemetry_service/` |

## 1. Executive Summary

Der Kern des BC (Event-Modell, Emitter-Protokoll, StateBackendEmitter, PipelineMetrics, SSE-Stream) ist solide implementiert und konzepttreu. Die grundlegende Infrastruktur fuer Event-Emission, -Speicherung und -Abfrage existiert. Es fehlen jedoch drei wesentliche Teilsysteme vollstaendig: die harness-basierten Telemetrie-Hooks (AgentLifecycleHook, CommitHook, ReviewSentinelHook, ReviewGuard, BudgetEventEmitter, DriftCheckHook, DivergenceHook), das Governance-Risk-Window mit NormalizedEvent-Normalisierung sowie die kanonische ProjectionAccessor-Schicht fuer die FK-69-Read-Models. Damit fehlt der entscheidende Beobachtungs- und Pruefbarkeitsanteil, den DK-05 und FK-68 als Kernaufgabe des BC definieren.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 6 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 2 |

## 2. Konzept-Soll (Kurzfassung)

- **Kanonische Event-Speicherung in PostgreSQL ueber TelemetryService/Control-Plane-API** — `FK-68.md §68.2.1, §68.3.4`
- **Vollstaendiger Event-Katalog (>30 Event-Typen, incl. Preflight, Flow, Override, ARE, Planning)** — `FK-68.md §68.2.2`
- **Harness-Hooks als aktuelle Referenz-Implementierung (AgentLifecycleHook, CommitHook, ReviewSentinelHook, ReviewGuard, BudgetEventEmitter, DriftCheckHook, DivergenceHook)** — `FK-68.md §68.3.1`
- **Governance-Risk-Window: NormalizedEvent-Normalisierung durch telemetry-and-events, Scoring durch governance-and-guards** — `FK-68.md §68.8`
- **Telemetrie-Contract (agent_start/agent_end-Paarung, review_compliant-Deckung, preflight_compliant-Deckung) als Integrity-Gate-Grundlage** — `FK-68.md §68.4, §68.9, §68.10`
- **Preflight-Telemetrie-Stream mit eigenem Sentinel und isolierten Zaehlern** — `FK-68.md §68.9`
- **Budget-Tracking fuer Web-Calls (BudgetEventEmitter, nur Research-Stories)** — `FK-68.md §68.6`
- **ProjectionAccessor als DB-Owner aller FK-69-Tabellen (qa_stage_results, qa_findings, story_metrics, fc_*, phase_state_projection)** — `FK-69.md §69.3, §69.4`
- **JSONL-Audit-Bundle-Export bei Closure (nur aus gueltigen, nicht zurueckgesetzten Runs)** — `FK-68.md §68.2.1, §68.3.6`
- **Reset-Purge: alle abgeleiteten Read-Models bei vollstaendigem Story-Reset entfernen** — `FK-69.md §69.10.1, formal.telemetry-analytics.invariants §invariant.reset-invalidates-read-models-and-facts`
- **Workflow-Metriken mit Experiment-Tags in story_metrics und closure.json** — `FK-68.md §68.7`
- **SSE-Stream fuer projektweite Live-Updates (topic-gefilterter Lossy-Stream)** — `FK-68.md §68.2.1a; FK-72 (referenziert in code)`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/telemetry/events.py:EventType` — vollstaendiger Event-Katalog (incl. Preflight, Flow, ARE-Events, governance-spezifische Binding-Events)
- `src/agentkit/telemetry/events.py:Event` — immutables Dataclass-Event-Modell mit allen Pflichtfeldern
- `src/agentkit/telemetry/emitters.py:EventEmitter` — Protocol-Kontrakt fuer Emitter
- `src/agentkit/telemetry/emitters.py:MemoryEmitter` — In-Memory-Emitter fuer Tests
- `src/agentkit/telemetry/emitters.py:NullEmitter` — Null-Emitter
- `src/agentkit/telemetry/storage.py:StateBackendEmitter` — persistenter Emitter via state_backend; emit/query implementiert
- `src/agentkit/telemetry/metrics.py:PipelineMetrics` — aggregierte Run-Metriken (duration, phase_durations, qa_rounds, phases_executed)
- `src/agentkit/telemetry/metrics.py:compute_pipeline_metrics` — reine Berechnungsfunktion aus Events
- `src/agentkit/telemetry/contract/records.py:ExecutionEventRecord` — kanonisches append-only Daten-Record mit allen Pflichtfeldern inkl. phase/flow_id/node_id
- `src/agentkit/telemetry/sse_stream.py:iter_project_sse_stream` — projektweiter SSE-Lossy-Stream mit Topic-Filter
- `src/agentkit/telemetry/http/routes.py:TelemetryRoutes` — HTTP-Handler fuer SSE `/v1/projects/{key}/events`
- `src/agentkit/telemetry_service/` — Facade-Paket (re-exportiert Klassen aus `telemetry/`)
- `src/agentkit/pipeline/phases/closure/metrics.py:build_story_metrics_record` — baut StoryMetricsRecord aus Events + PhaseState
- `src/agentkit/closure/post_merge_finalization/records.py:StoryMetricsRecord` — Closure-Metriken incl. Experiment-Tags (agentkit_version, llm_roles etc.)
- `src/agentkit/verify_system/qa_read_models.py` — FK-69-Projektionshilfen (build_qa_stage_result) — liegt aber im verify_system-Modul, nicht in telemetry

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Harness-Hooks als vollstaendige Referenz-Implementierung (AgentLifecycleHook, CommitHook, ReviewSentinelHook, ReviewGuard, BudgetEventEmitter, DriftCheckHook) | `FK-68.md §68.3.1` | Kein Modul `agentkit.backend.telemetry.hooks.*` vorhanden; Hook-Namen sind nur im governance-runner als String-Referenz vermerkt |
| A2 | DivergenceHook (`agentkit.backend.telemetry.hooks.divergence`) fuer review_divergence-Events | `FK-68.md §68.2.2 (Review-Divergenz-Tabelle)` | Kein Code gefunden; review_divergence-EventType existiert in events.py, wird aber nicht emittiert |
| A3 | Governance-Risk-Window: NormalizedEvent-Normalisierung durch telemetry-and-events (Sensor-Schicht) | `FK-68.md §68.8.0, §68.8.1` | Kein Modul `agentkit.backend.telemetry.hooks.TelemetryHooks` mit NormalizedEvent und ProjectionAccessor-Write ins Rolling Window |
| A4 | JSONL-Audit-Bundle-Export bei Closure (aus gueltigen Runs) | `FK-68.md §68.3.6; FK-68.md §68.2.1 (audit-bundle-Glossar)` | Keine `export_jsonl`-Funktion oder vergleichbare Implementierung gefunden |
| A5 | ProjectionAccessor als eigenstaendiges Modul `agentkit.backend.telemetry.projection_accessor` mit write_projection/read_projection | `FK-69.md §69.3, §69.4` | Projektionszugriff existiert verteilt (verify_system, closure), aber kein zentraler DB-Owner-Zugriffsmodul gemaess FK-69 |
| A6 | Reset-Purge fuer alle FK-69-Tabellen bei vollstaendigem Story-Reset | `FK-69.md §69.10.1; formal.telemetry-analytics.invariants §invariant.reset-invalidates-read-models-and-facts` | Keine Implementierung eines Purge-Jobs oder Reset-Handlers gefunden |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Telemetrie-Contract (Integrity-Gate-Pruefung) | `src/agentkit/telemetry/events.py:EventType` (Event-Typen vorhanden), `src/agentkit/governance/integrity_gate/` (Gate vorhanden) | `FK-68.md §68.4, §68.9, §68.10` | Keine `telemetry_contract.py` mit formalisierten Contract-Rules (agent_start/end-Paarung, review_compliant-Deckung, preflight_compliant-Gleichgewicht, llm_call-Pflicht-Rollen); das Gate kann keine Telemetrie-Pruefung gemaess FK-68 §68.4 durchfuehren |
| B2 | Preflight-Telemetrie-Stream | `src/agentkit/telemetry/events.py:EventType.PREFLIGHT_REQUEST/RESPONSE/COMPLIANT` (Event-Typen vorhanden) | `FK-68.md §68.9` | Kein separater Preflight-Sentinel-Regex, kein Preflight-Guard-Hook, keine isolierten Zaehler-Regeln in einem Contract-Modul; Sentinel-Trennung ist nicht implementiert |
| B3 | Workflow-Metriken und Experiment-Tags | `src/agentkit/pipeline/phases/closure/metrics.py:build_story_metrics_record`, `src/agentkit/closure/post_merge_finalization/records.py:StoryMetricsRecord` | `FK-68.md §68.7` | Experiment-Tags werden im Record-Modell unterstuetzt, aber `adversarial_findings`, `adversarial_tests_created`, `files_changed` und `agentkit_commit` werden in `build_story_metrics_record` nicht befuellt (bleiben None); story_size ist kein Pflichtfeld in PipelineMetrics |
| B4 | FK-69 Read-Models Zugriffsschicht | `src/agentkit/verify_system/qa_read_models.py:build_qa_stage_result`, `src/agentkit/closure/post_merge_finalization/records.py:StoryMetricsRecord` | `FK-69.md §69.3, §69.4, §69.6, §69.7, §69.8` | qa_findings-Projektion fehlt; fc_*-Zugriffsschicht fehlt; phase_state_projection-Zugriffsschicht fehlt; qa_read_models liegt im verify_system-Modul statt in `agentkit.backend.telemetry.read_models` |
| B5 | SSE-Stream-Topic-Routing | `src/agentkit/telemetry/sse_stream.py:_topic_for_record` | `FK-68.md §68.2.1a; FK-72 (SSE-Kontrakt)` | Topic-Mapping ist heuristisch (event_type.startswith("story_") → "stories"; phase is not None → "phases"); alle governance-Events ausser integrity_violation und edge_operation_reconciled landen in "telemetry" statt im korrekten Topic; kpi/planning/failure_corpus/coverage/closure-Topics werden nie gesetzt ausser durch explizites payload.topic-Feld |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | `telemetry_service/` als Facade statt als eigenstaendiges Modul | `src/agentkit/telemetry_service/storage.py`, `src/agentkit/telemetry_service/events.py`, `src/agentkit/telemetry_service/emitters.py`, `src/agentkit/telemetry_service/metrics.py` | `FK-68.md §68.3.4 (TelemetryService als normative Schreibgrenze)` | FK-68 spricht von TelemetryService als kanonischer Control-Plane-Schreibgrenze. Das `telemetry_service`-Paket ist jedoch nur eine Pass-Through-Facade ohne eigene Logik und ohne den Schreibpfad zu kapseln. Die normative Grenze wird nicht durchgesetzt; Aufrufer koennen gleichermassen direkt `agentkit.backend.telemetry.storage.StateBackendEmitter` verwenden. |
| C2 | `PipelineMetrics.qa_rounds` Berechnung weicht von FK-68 ab | `src/agentkit/telemetry/metrics.py:compute_pipeline_metrics` | `FK-68.md §68.7.1 (qa_rounds: Anzahl Remediation-Iterationen im QA-Subflow)` | qa_rounds wird als `count(NODE_RESULT where phase=="implementation")` berechnet. FK-68 §68.7.1 definiert qa_rounds als Anzahl der Remediation-Iterationen (qa_cycle_round) aus `phase_state_projection.attempt_no`. Die korrekte Quelle ist `load_attempts(story_dir, "implementation")` gemaess `closure/metrics.py:build_story_metrics_record`. `compute_pipeline_metrics` liefert also eine falsche, event-basierte Naehreung statt der normativen attempt_no-Zaehlung. |

## 5. Ableitungen / Empfehlungen

1. **Hook-Implementierungen priorisieren (A1, A2):** Die harness-basierten Hooks sind die normative Hauptquelle fuer den Grossteil der Pflicht-Events (agent_start/end, increment_commit, drift_check, review_request/response/compliant, adversarial_*). Ohne sie kann kein Integrity-Gate gemaess FK-68 §68.4 greifen und keine Telemetrie-Pruefbarkeit entstehen. Betrifft direkt die Pruefbarkeits-Kernaufgabe des BC (DK-05).
2. **TelemetryContract als Modul implementieren (B1):** Das Integrity-Gate kann ohne `telemetry_contract.py` mit formalisierten Rules keine Telemetrie-Nachweise pruefen. Dieser Baustein ist der Verbindungspunkt zwischen Telemetrie-Erhebung und Closure-Gate und blockiert den gesamten Pruefbarkeitspfad.
3. **ProjectionAccessor zentralisieren (A5, B4):** Die FK-69-Zugriffsschicht ist derzeit ueber `verify_system` und `closure` verteilt und verletzt Single-Source-of-Truth. Ein zentrales `agentkit.backend.telemetry.projection_accessor`-Modul mit write_projection/read_projection wuerde den DB-Owner-Vertrag gemaess FK-69 §69.4 erfullen und gleichzeitig den Reset-Purge-Pfad (A6) ermoeglichen.
4. **PipelineMetrics.qa_rounds korrigieren (C2):** Die abweichende Berechnung in `compute_pipeline_metrics` produziert nicht-normative Werte. Da `build_story_metrics_record` bereits korrekt `load_attempts` verwendet, sollte entweder `compute_pipeline_metrics` auf dieselbe Quelle umgestellt oder klar dokumentiert werden, dass `PipelineMetrics` keine FK-68-konforme Metrik liefert und nur fuer interne Zwecke gilt.
5. **Governance-Risk-Window (A3) und Audit-Bundle-Export (A4) anschliessen:** Beide fehlen vollstaendig. Der NormalizedEvent-Normalisierungspfad ist Voraussetzung fuer die GovernanceObserver-Komponente in governance-and-guards. Der JSONL-Export ist Voraussetzung fuer die Archivierungspflicht bei Closure.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/05-telemetrie-und-metriken.md` (DK-05)
  - `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` (FK-68)
  - `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md` (FK-69)
  - `concept/formal-spec/telemetry-analytics/entities.md`
  - `concept/formal-spec/telemetry-analytics/invariants.md`
  - `concept/formal-spec/telemetry-analytics/state-machine.md`
  - `concept/formal-spec/telemetry-analytics/commands.md`
  - `concept/formal-spec/telemetry-analytics/scenarios.md`
  - `concept/technical-design/_meta/domain-registry.yaml` (BC-Schnitt)
  - `src/agentkit/telemetry/events.py`
  - `src/agentkit/telemetry/emitters.py`
  - `src/agentkit/telemetry/storage.py`
  - `src/agentkit/telemetry/metrics.py`
  - `src/agentkit/telemetry/contract/records.py`
  - `src/agentkit/telemetry/sse_stream.py`
  - `src/agentkit/telemetry/http/routes.py`
  - `src/agentkit/telemetry_service/storage.py`, `events.py`, `emitters.py`, `metrics.py`
  - `src/agentkit/pipeline/phases/closure/metrics.py`
  - `src/agentkit/closure/post_merge_finalization/records.py`
- **Punktuell gelesen:**
  - `src/agentkit/verify_system/qa_read_models.py` (FK-69-Projektionshelfer)
  - `src/agentkit/governance/runner.py` (Hook-Namen-Registrierung)
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/telemetry/**` und `src/agentkit/telemetry_service/**`: Modulstruktur ermitteln
  - Glob `src/agentkit/telemetry/hooks/**` und `src/agentkit/telemetry/read_models/**`: Fehlen der Hook- und Read-Model-Untermodule bestaetigt
  - Grep `review_guard|ReviewGuard|BudgetEventEmitter|NormalizedEvent|ProjectionAccessor|review_sentinel|divergence`: Pruefen ob Hook-Implementierungen irgendwo im src-Baum existieren
  - Grep `telemetry_contract|TelemetryContract`: Pruefen ob Contract-Modul existiert
  - Grep `story_reset|reset.*purge|purge.*run_id`: Reset-Purge-Implementierung gesucht, nicht gefunden
  - Grep `export_jsonl|audit_bundle|AuditBundle`: Audit-Bundle-Export gesucht, nicht gefunden
  - Grep `projection_accessor|ProjectionAccessor|qa_stage_results|qa_findings|story_metrics|phase_state_projection`: Verteilung der Read-Model-Zugriffsschicht ermittelt
