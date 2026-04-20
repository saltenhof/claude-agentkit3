---
concept_id: FK-14
title: Telemetrie, Eventing und Workflow-Metriken
module: telemetry
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: telemetry
  - scope: eventing
  - scope: workflow-metriken
defers_to:
  - target: FK-01
    scope: trust-boundaries
    reason: Trust-Zonen bestimmen Event-Quellen und Vertrauenswürdigkeit
  - target: FK-02
    scope: domain-model
    reason: Project-Key, Story-ID und Run-ID als Korrelationsschlüssel aus FK-02
supersedes: []
superseded_by:
tags: [telemetrie, eventing, metriken, state-backend, review-guard]
prose_anchor_policy: strict
formal_refs:
  - formal.story-workflow.events
  - formal.state-storage.events
  - formal.telemetry-analytics.entities
  - formal.telemetry-analytics.state-machine
  - formal.telemetry-analytics.commands
  - formal.telemetry-analytics.events
  - formal.telemetry-analytics.invariants
  - formal.telemetry-analytics.scenarios
---

# 14 — Telemetrie, Eventing und Workflow-Metriken

## 14.1 Zweck

<!-- PROSE-FORMAL: formal.story-workflow.events, formal.telemetry-analytics.entities, formal.telemetry-analytics.invariants -->

Die Telemetrie erfüllt zwei Aufgaben (FK 8):

1. **Nachvollziehbarkeit:** Was ist während einer gültigen Story-Bearbeitung
   passiert? Welche Agents liefen, welche LLMs wurden aufgerufen,
   welche Tools verwendet?
2. **Prüfbarkeit:** Wurde der definierte Prozess eingehalten? Das
   Integrity-Gate prüft bei Closure die Telemetrie als Nachweis.

**Reset-Grenze:** Telemetrie ist Langzeitaudit für gültige Runs. Wird
eine Story-Umsetzung vollständig zurückgesetzt, gelten die
`execution_events` dieses Runs als fachlich ungültig und werden
entfernt. Ein zurückgesetzter Run zählt weder für Langzeitaudit noch
für Metrikbildung.

Telemetrie-Nachweise sind dort relevant, wo Agents autonom handeln
und der Prozess nicht durch Code erzwungen wird (FK-08-005).
Deterministische Pipeline-Schritte (Structural Checks,
LLM-Evaluator-Aufrufe) brauchen keine Telemetrie-Nachweise, weil
ihr Ablauf durch den Code garantiert ist.

## 14.2 Event-Modell

<!-- PROSE-FORMAL: formal.state-storage.events, formal.telemetry-analytics.commands, formal.telemetry-analytics.events, formal.telemetry-analytics.state-machine, formal.telemetry-analytics.scenarios -->

### 14.2.1 Speicherung: PostgreSQL

Events werden in einer zentralen PostgreSQL-Datenbank des
State-Backends gespeichert. Diese DB ist projektunabhängig,
langlebig und Principal-geschützt.

**Vorteile gegenüber Projektdateien/JSONL:**
- kein frei manipulierbarer Projektzustand für Orchestrator/Worker
- atomare Writes und transaktionale Queries
- saubere Retention und Traceability unabhängig vom Projekt-Temp
- rollenbasierte Zugriffskontrolle bis auf Principal-Ebene

**Logisches Zielmodell:** Die kanonische Telemetrietabelle heißt
`execution_events`. Ihre relationale Abbildung ist in FK-18
autorisiert. FK-14 definiert das Eventmodell und die fachlichen Felder,
nicht die finale SQL-DDL.

**JSONL als Export-/Audit-Format:** Bei Closure kann die Telemetrie
einer Story als JSONL oder Audit-Bundle exportiert werden. Diese
Datei dient der menschlichen Lesbarkeit oder externen Ablage — sie
ist nie Laufzeit-Speicher.

### 14.2.1a Control-Plane-API als normative Schreibgrenze

Die kanonische Telemetrie wird fachlich nicht ueber eine bestimmte
Agent-Plattform, Hook-Implementierung oder CLI normiert, sondern ueber
eine **offizielle Control-Plane-Schreibgrenze**:

- interne Runtime-Komponenten schreiben ueber den `TelemetryService`
- externe Steuerpfade schreiben ueber offizielle AgentKit-API-Operationen
- projekt- oder plattformspezifische Adapter (CLI, Hooks, Skills,
  Wrapper-Skripte) sind nur Aufrufer dieser Grenze

**Normative Regel:** Claude-Code-Hooks, die lokale CLI und kuenftige
REST-Endpunkte sind **keine** konkurrierenden Wahrheiten fuer
Telemetrie, sondern nur Transport- oder Adapterpfade auf denselben
kanonischen Event-Vertrag.

**Zielbild fuer Agents:** Agents sollen offizielle API-Aufrufe nutzen,
nicht frei formulierte Shell- oder HTTP-Sequenzen. Fuer wiederkehrende
Operationen werden feste Request-Templates bereitgestellt, damit der
Agent nur Parameter fuellt und die Plattform nicht improvisiert.

**Gültigkeitsregel:** Audit-Bundles dürfen nur aus gültigen,
nicht vollständig zurückgesetzten Runs erzeugt oder aufbewahrt werden.
Ein vollständiger Story-Reset verwirft auch den zugehörigen
Telemetrie-Export.

**Pflichtfelder jedes Events (Spalten):**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `project_key` | String | Registriertes Zielprojekt / Mandanten-Schlüssel |
| `story_id` | String | Story-ID |
| `run_id` | String (UUID) | Run-Identifikator (Kap. 02) |
| `event_id` | String | eindeutige Event-Kennung innerhalb des Runs |
| `event_type` | String | Event-Typ (siehe 14.2.2) |
| `occurred_at` | String (ISO 8601 + Zeitzone) | fachlicher Ereigniszeitpunkt |
| `source_component` | String | emittierende Komponente |
| `severity` | String | debug/info/warning/error/critical |

Darüber hinaus event-spezifische Felder als Detailpayload oder
Payload-Referenz. `pool`, `role`, `reviewer_a`, `score`,
`target_node_id` etc. sind keine festen Top-Level-Spalten des
fachlichen Eventmodells, sondern event-spezifische Felder.

**Mandantenregel:** Alle Runtime-Tabellen im State-Backend tragen
`project_key` als führenden Scope-Schlüssel. `story_id` ist nur
innerhalb eines Projekts eindeutig.

### 14.2.2 Event-Katalog

#### Worker-Lifecycle

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `agent_start` | Worker-Agent wird gestartet | `subagent_type` | Genau 1 pro Run | Hook (PostToolUse für Agent) |
| `agent_end` | Worker-Agent beendet regulär | `subagent_type` | Genau 1, nach agent_start | Hook (PostToolUse für Agent) |
| `increment_commit` | Worker committet ein Inkrement | `sha` | >= 1 pro Story | Hook (PreToolUse für Bash bei `git commit` im Worktree) |
| `drift_check` | Worker prüft Impact/Konzept-Konformität | `result` (ok/drift) | >= 1 pro Story | Worker führt Marker-Befehl aus, Hook erkennt |

#### Ablauf- und Override-Events

Die Einheits-DSL aus FK-20 ist nur dann auditierbar, wenn die Engine
auch ihre eigenen Kontrollflussentscheidungen sichtbar macht. Deshalb
schreibt die `PipelineEngine` sowie jede komponentenseitige
Flow-Runtime normierte Ablauf-Events.

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `flow_start` | Ein `FlowDefinition` beginnt | `flow_id`, `level`, `owner`, `attempt_no` | Genau 1 pro Flow-Attempt | PipelineEngine / Komponenten-Runtime |
| `flow_end` | Ein Flow endet | `flow_id`, `level`, `owner`, `attempt_no`, `status` | Genau 1 pro `flow_start` | PipelineEngine / Komponenten-Runtime |
| `node_result` | Ein Knoten wurde ausgewertet | `flow_id`, `node_id`, `kind`, `outcome`, `attempt_no`, `target_node_id?` | 1..n pro Node | PipelineEngine / Komponenten-Runtime |
| `override_applied` | Ein Override-Record wurde konsumiert | `flow_id`, `node_id`, `override_type`, `actor_type`, `override_id` | 0..n | PipelineEngine / Komponenten-Runtime |

**Outcome-Werte fuer `node_result`:**
- `PASS`
- `FAIL`
- `SKIP`
- `YIELD`
- `BACKTRACK`

`target_node_id` ist nur gesetzt, wenn ein Ruecksprung oder Sprung auf
einen expliziten Zielknoten erfolgt.

#### Worker-Reviews

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `review_request` | Worker fordert Review von Pflicht-LLM an | `pool`, `role` | Mindestens 1 pro Story | Hook (PreToolUse für Pool-Send mit Review-Template) |
| `review_response` | Pflicht-LLM liefert Review-Ergebnis | `pool`, `role` | Gleiche Anzahl wie review_request | Hook (PostToolUse für Pool-Send) |
| `review_compliant` | Review lief über freigegebenes Template | `pool`, `template_name` | Jeder review_request muss ein review_compliant haben | Review-Guard (PostToolUse) |

#### LLM-Aufrufe (generisch)

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `llm_call` | LLM wird über Pool aufgerufen | `pool`, `role`, `retry` (bool), `status` | Pro konfiguriertem Pflicht-Reviewer >= 1 | LLM-Evaluator / Hook |

**Wichtig:** Keine anbieterspezifischen Events (`chatgpt_call`,
`gemini_call`). Das generische `llm_call`-Event mit `pool`-Feld
hält die Pool-Abstraktion intakt (Kap. 01 P8, Kap. 11).

#### Adversarial Testing

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `adversarial_start` | Adversarial Agent wird gestartet | — | Genau 1 (nur implementierende Stories) | Hook (PostToolUse für Agent) |
| `adversarial_sparring` | Adversarial holt Sparring-LLM | `pool` | >= 1 (Pflicht) | Hook (PostToolUse für Pool-Send) |
| `adversarial_test_created` | Adversarial schreibt neuen Test | `file_path` | >= 0 (neue Tests nur wenn bestehende unzureichend, FK-05-198/199) | Hook (PostToolUse für Write in Sandbox-Pfad) |
| `adversarial_test_executed` | Adversarial führt Test aus | `result` (pass/fail), `test_count` | >= 1 (Pflicht) | Hook (PostToolUse für Bash mit Test-Kommando) |
| `adversarial_end` | Adversarial Agent beendet | `findings_count` | Genau 1, nach adversarial_start | Hook (PostToolUse für Agent) |

#### Preflight-Turn

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `preflight_request` | Preflight-Prompt an LLM-Pool gesendet. Hook: PreToolUse für Pool-Send wenn Preflight-Sentinel `[PREFLIGHT:...-v1:{story_id}]` erkannt. | `pool` | >= 1 pro Story (Pflicht) | Hook (PreToolUse Pool-Send, Preflight-Sentinel) |
| `preflight_response` | Preflight-Antwort vom LLM empfangen. Hook: PostToolUse für Pool-Send. | `pool`, `request_count` | == preflight_request count | Hook (PostToolUse Pool-Send, Preflight-Sentinel) |
| `preflight_compliant` | Preflight verwendete genehmigtes Template. Emittiert durch review_guard wenn Preflight-Sentinel gefunden. | `pool`, `template_name` | == preflight_request count | Review-Guard (PostToolUse, Preflight-Sentinel) |

#### Review-Divergenz

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `review_divergence` | Divergenz zwischen zwei Reviewern gemessen. Emittiert nach jedem Review-Paar durch den Divergenz-Score-Rechner (Kap. 28). | `reviewer_a`, `reviewer_b`, `score` (LOW/MEDIUM/HIGH), `routing` | 0..n pro Story | `telemetry/divergence.py` |

#### Governance

| Event | Wann | Zusatzfelder | Erwartungswert | Quelle |
|-------|------|-------------|----------------|--------|
| `integrity_violation` | Ein Guard wurde verletzt | `guard`, `detail`, `stage` (bei prompt_integrity_guard: escape_detection/schema_validation/template_integrity) | Erwartet: 0 (jeder Eintrag ist ein Befund) | Guard-Hooks bei Blockade |
| `web_call` | Agent führt Web-Suche/-Abruf durch | — | <= konfiguriertes Budget (Default: 200) | Budget-Hook (PostToolUse für WebSearch/WebFetch) |
| ~~`guard_invocation`~~ | Guard-Invokationen werden NICHT als Event erfasst (Volumen: 2500-10000/Story). Stattdessen Scratchpad-Counter `runtime.guard_invocation_counters` im State-Backend. Siehe FK-61 §61.4.3. | — | — | — |
| `impact_violation_check` | Impact-Violation wird geprueft | `declared_impact`, `actual_impact`, `result` (pass/violation) | 1 pro implementierender Story | Structural Check in Verify-Phase (FK-33). Ergaenzt FK-61 §61.4.2. |
| `doc_fidelity_check` | Dokumententreue wird geprueft | `level` (goal/design/implementation/feedback_fidelity), `result` (pass/conflict/skipped) | 1-4 pro Story (je nach Typ und Modus) | Dokumententreue-Service (FK-32). Ergaenzt FK-61 §61.5.1. |
| `vectordb_search` | VektorDB-Abgleich bei Story-Erstellung | `total_hits`, `hits_above_threshold`, `hits_classified_conflict`, `threshold_value` | 1 pro Story-Erstellung | Story-Creation-Pipeline (FK-21). Konzeptmandatiert (Kap. 02 §2.1). Ergaenzt FK-61 §61.8.1. |
| `compaction_event` | Context-Compaction im Sub-Agent | `story_id` (aus `.agentkit-story.json`) | 0..n pro Story | PostCompact-Hook (FK-36). Ergaenzt FK-61 §61.2.2. |

**Normative Abstraktion der Quellen:** Der Event-Katalog ist
**producer-neutral**. Ein Event-Typ wird fachlich ueber seine Semantik
definiert, nicht ueber Claude-Code-Hooks, die lokale CLI oder einen
REST-Client. Dieselben Event-Typen muessen spaeter unveraendert ueber
die zentrale AgentKit-Control-Plane ingestierbar bleiben.

### 14.2.3 Beispiel-Events

```jsonl
{"project_key":"odin-trading","story_id":"ODIN-042","run_id":"a1b2...","event_id":"evt-001","event_type":"agent_start","occurred_at":"2026-03-17T10:00:01+01:00","source_component":"telemetry_hook","severity":"info","payload":{"subagent_type":"worker"}}
{"project_key":"odin-trading","story_id":"ODIN-042","run_id":"a1b2...","event_id":"evt-002","event_type":"increment_commit","occurred_at":"2026-03-17T10:15:23+01:00","source_component":"telemetry_hook","severity":"info","payload":{"sha":"c3d4e5f"}}
{"project_key":"odin-trading","story_id":"ODIN-042","run_id":"a1b2...","event_id":"evt-003","event_type":"review_request","occurred_at":"2026-03-17T10:30:00+01:00","source_component":"telemetry_hook","severity":"info","payload":{"pool":"chatgpt","role":"qa_review"}}
{"project_key":"odin-trading","story_id":"ODIN-042","run_id":"a1b2...","event_id":"evt-004","event_type":"llm_call","occurred_at":"2026-03-17T11:00:00+01:00","source_component":"llm_evaluator","severity":"info","payload":{"pool":"chatgpt","role":"qa_review","retry":false,"status":"PASS"}}
```

## 14.3 Event-Quellen

### 14.3.1 Hook-basierte Erfassung

Claude-Code-Hooks sind die **aktuelle Referenz-Implementierung** fuer
mehrere beobachtende Telemetriequellen. Sie sind jedoch kein
normativer Sonderstatus, sondern ein Adapterpfad fuer die
Control-Plane-Telemetrie.

Hooks sind dort eine gute Quelle, wo sie Agent-Aktionen ohne
Mitwirkung des Agents beobachten koennen.

| Hook | Typ | Erkennung | Events |
|------|-----|-----------|--------|
| `telemetry/hook.py` | PostToolUse (Agent) | Tool = `Agent`, `subagent_type` aus Prompt | `agent_start`, `agent_end`, `adversarial_start`, `adversarial_end` |
| `telemetry/hook.py` | PostToolUse (Pool-Send) | Tool enthält `_send`, Story aus aktivem Run im State-Backend | `llm_call` |
| `telemetry/hook.py` | PreToolUse (Bash) | `git commit` im Worktree | `increment_commit` |
| `telemetry/hook.py` | PreToolUse (Bash) | Marker-Befehl `DRIFT_CHECK:` | `drift_check` |
| `telemetry/hook.py` | PostToolUse (Pool-Send) | Review-Template-Sentinel erkannt | `review_request`, `review_response` |
| `telemetry/review_guard.py` | PostToolUse (Pool-Send) | Template-Sentinel-Pattern | `review_compliant` |
| `telemetry/budget.py` | PostToolUse (WebSearch/WebFetch) | Tool-Name | `web_call` |
| Guard-Hooks | PreToolUse | Blockade (exit 2) | `integrity_violation` |

### 14.3.2 Skript-basierte Erfassung

Der LLM-Evaluator (Kap. 11) schreibt `llm_call`-Events direkt
in das State-Backend, weil er ein deterministisches Skript ist und
nicht über einen Hook läuft.

### 14.3.2b API-basierte Erfassung

Neben Hook- und Runtime-Erzeugern bleibt die offizielle
Control-Plane-API ein zulaessiger Producer-Pfad fuer Telemetrie:

- Phase- und Closure-Aufrufe koennen kuenftig ueber offizielle
  AgentKit-REST-Operationen statt ueber die lokale CLI erfolgen
- Agenten oder Adapter muessen dabei feste Request-Templates nutzen,
  keine frei formulierten HTTP-Aufrufe
- die API darf nur denselben kanonischen Event-Vertrag produzieren,
  niemals eine zweite Telemetrie-Taxonomie

**Normative Regel:** API-basierte Erfassung ersetzt keine fachlichen
Events. Sie ist nur ein weiterer zulassiger Transportpfad auf den
bereits definierten Event-Katalog.

### 14.3.2a Engine-basierte Erfassung

Die Ablauf-Events `flow_start`, `flow_end`, `node_result` und
`override_applied` werden von der Runtime geschrieben, die die
jeweilige `FlowDefinition` ausfuehrt:

- die `PipelineEngine` fuer Pipeline- und Phasen-Flows
- komponentenseitige Flow-Runtimes fuer Komponentensubflows wie
  `StageRegistry` oder `Installer`

Hooks sind dafuer ungeeignet, weil sie nur Tool-Aufrufe sehen, nicht
aber semantische Entscheidungen wie `SKIP_AFTER_SUCCESS`,
Rueckspruenge oder Override-Konsum.

### 14.3.3 Story-ID-Ermittlung

Hooks müssen die aktive Story-ID kennen, um Events zuzuordnen.
Zwei Mechanismen:

1. **Aktiver Run im State-Backend:** Setup legt für jede Story
   einen aktiven Run-/Lock-Record an. Hooks fragen diesen
   Record read-only ab und ermitteln daraus Story-ID und Run-ID.
2. **Prompt-Analyse:** Bei `agent_start` Events wird die Story-ID
   aus dem Agent-Prompt extrahiert (Regex auf Story-ID-Pattern).

### 14.3.4 Schreib-Mechanismus

```python
def insert_event(project_key: str, client, story_id: str, run_id: str, event_type: str,
                 source_component: str,
                 severity: str = "info",
                 payload: dict | None = None) -> None:
    client.insert_event(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
        source_component=source_component,
        severity=severity,
        payload=payload or {},
    )
```

**Kein projektlokales Locking nötig.** Die Synchronisation übernimmt
PostgreSQL. Agents erhalten keine direkten DB-
Zugangsdaten; nur Hook-/Pipeline-Principals schreiben **über den
telemetry_service bzw. dessen Insert-API**.

**Ausblick Control Plane:** Dieselbe Insert-API bleibt spaeter auch die
normative Rueckseite offizieller REST-Endpunkte. CLI-Skripte und
Hook-Adapter bleiben dann nur noch Frontends derselben
Control-Plane-Schnittstelle.

**Korrelation fuer Prozess-DSL-Events:** Ablauf-Events tragen in ihrem
Payload mindestens `flow_id`, `level`, `owner`, `attempt_no` und bei
Knotenereignissen `node_id`. Nur so kann spaeter nachvollzogen werden,
warum ein Schritt gelaufen, uebersprungen, wiederholt oder per
Override veraendert wurde.

### 14.3.5 Query-Mechanismus

Pipeline-Skripte und das Integrity-Gate fragen Telemetrie über
SQL ab — kein JSONL-Parsing durch Agents:

```python
def count_events(project_key: str, client, story_id: str, event_type: str) -> int:
    return client.count_events(
        project_key=project_key,
        story_id=story_id,
        event_type=event_type,
    )

def has_event(project_key: str, client, story_id: str, event_type: str) -> bool:
    return count_events(project_key, client, story_id, event_type) > 0

def events_for_run(project_key: str, client, run_id: str) -> list[dict]:
    return client.events_for_run(project_key=project_key, run_id=run_id)
```

### 14.3.6 JSONL-Export bei Closure

Bei Closure kann die Telemetrie einer Story als JSONL exportiert werden:

```python
def export_jsonl(story_id: str, output_path: str) -> None:
    rows = state_backend_client.events_for_story(story_id=story_id)
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

Die JSONL-Datei dient der langfristigen Archivierung und
menschlichen Lesbarkeit, ist aber kein kanonischer Datenspeicher.

## 14.4 Telemetrie-Nachweise im Integrity-Gate

Das Integrity-Gate (Kap. 02, FK 6.5) prüft bei Closure diese
Telemetrie-Nachweise:

| Nachweis | Was geprüft wird | Fail wenn |
|----------|-----------------|-----------|
| `agent_start` mit Story-ID | Worker-Agent wurde gestartet | Kein Worker-Agent lief |
| `agent_end` mit Story-ID | Worker-Agent hat regulär beendet | Agent abgestürzt/abgebrochen |
| `llm_call` pro konfigurierter Pflicht-Rolle | Alle Pflicht-Reviewer aufgerufen | Ein Pflicht-Reviewer fehlt |
| `review_compliant` | Reviews über freigegebene Templates | Agent hat freiformuliert statt Skill |
| Kein `integrity_violation` | Kein Guard verletzt | Agent hat versucht, Governance zu umgehen |
| `web_call` <= Budget | Webzugriffe im Budget | Budget überschritten |

**Prüfung gegen Konfiguration, nicht gegen hardcoded Anbieternamen:**

Das Integrity-Gate liest `llm_roles` aus der Pipeline-Config und
prüft, ob für jede konfigurierte Rolle mindestens ein `llm_call`-Event
mit dem zugeordneten `pool`-Wert in der Telemetrie vorliegt. Es
kennt keine Anbieternamen (kein `chatgpt`, `gemini`, `grok` im
Gate-Code).

### 14.4.1 Größenabhängige Prüfung

Für `review_request`-Events wird die Erwartung basierend auf der
Story-Größe aus `StoryContext` bzw. dessen `context.json`-Export
geprüft:

| Metrik | Minimum-Schwelle |
|--------|-----------------|
| `review_request` | Mindestens 1 pro Story |
| `drift_check` | Mindestens 1 pro Story |

## 14.5 Review-Guard

### 14.5.1 Template-Sentinel-Prüfung

Der Review-Guard (`telemetry/review_guard.py`) prüft, ob LLM-Reviews
über freigegebene Templates ausgeführt wurden. Er sucht nach
einem Sentinel-Pattern in der Pool-Send-Nachricht:

**Pattern:** `[TEMPLATE:{template-name}-v1:{story_id}]`

**Erlaubte Template-Namen:**

| Template | Zweck |
|----------|-------|
| `review-consolidated` | Konsolidiertes Code-Review |
| `review-bugfix` | Bugfix-spezifisches Review |
| `review-spec-compliance` | Spezifikations-Compliance |
| `review-implementation` | Implementierungs-Review |
| `review-test-sparring` | Test-Sparring |
| `review-synthesis` | Review-Synthese |
| `mediation-round` | Mediation zwischen LLMs |

### 14.5.2 Verhalten

Der Review-Guard **blockiert nie** (immer exit 0). Er ist rein
observational:

- **Sentinel gefunden:** Schreibt `review_compliant`-Event mit
  Pool-Name und Template-Name
- **Sentinel nicht gefunden:** Kein Event (Abwesenheit wird vom
  Integrity-Gate als Befund gewertet)

## 14.6 Budget-Tracking

### 14.6.1 Web-Call-Budget

Der Budget-Hook (`telemetry/budget.py`) trackt Web-Aufrufe
(WebSearch, WebFetch) **nur für Research-Stories**.

**Begründung:** Der Research-Prompt animiert den Agent explizit zur
maximalen Suchtiefe ("traversiere rekursiv, geh in die Tiefe, hör
nicht auf"). Ohne Hard-Limit kennt der Agent kein Abbruchkriterium
und sucht endlos weiter. Bei allen anderen Story-Typen gibt es
keinen Grund für ein Web-Call-Limit — Web-Aufrufe sind nicht teurer
als andere Tool-Aufrufe (z.B. Read auf ein umfangreiches Konzept),
und eine Ungleichbehandlung ohne fachliche Begründung wäre
willkürlich.

| Parameter | Wert | Config-Pfad |
|-----------|------|-------------|
| Hard-Limit (nur Research) | 200 | `telemetry.web_call_limit` |
| Warnschwelle (nur Research) | 180 | `telemetry.web_call_warning` |

**Verhalten (nur bei `story_type == "research"`):**
- Count < Warnschwelle: `web_call`-Event schreiben, exit 0
- Count >= Warnschwelle: `web_call`-Event + Warnung, exit 0
- Count >= Hard-Limit: `web_call`-Event + **Blockade (exit 2)**

Bei allen anderen Story-Typen: `web_call`-Event wird geschrieben
(Telemetrie), aber keine Begrenzung. Falls exzessive Web-Nutzung
bei Nicht-Research-Stories auftritt, erkennt das die Governance-
Beobachtung (Kap. 14.8) als Anomalie über den Risikoscore.

**Counter-Persistenz:** zentraler Counter-Record pro Run/Story im
State-Backend. Wird bei jedem WebSearch/WebFetch-Call inkrementiert.

## 14.7 Workflow-Metriken

### 14.7.1 Metriken-Katalog

Am Ende einer gültigen, nicht zurückgesetzten Story (in der
Closure-Phase) werden Metriken aus der
Telemetrie aggregiert:

| Metrik | Berechnung | Quelle |
|--------|-----------|--------|
| `processing_time_min` | Differenz erstes `agent_start` bis Closure | Telemetrie-Timestamps |
| `qa_rounds` | Anzahl verify→implementation-Übergänge | `phase_state_projection.attempt_no` bzw. deren `phase-state.json`-Export |
| `adversarial_findings` | `findings_count` aus `adversarial_end`-Event | Telemetrie |
| `adversarial_tests_created` | Anzahl `adversarial_test_created`-Events | Telemetrie |
| `files_changed` | `git diff --stat` Zeilenzahl | Git |
| `increments` | Anzahl `increment_commit`-Events | Telemetrie |

### 14.7.2 Experiment-Tags

Workflow-Metriken müssen Experiment-Tags unterstützen, die den
quantitativen Vergleich von Stories über verschiedene
Pipeline-Konfigurationen hinweg ermöglichen (FK-14-058). Ohne
diese Tags sind Trendaussagen wie "Hat Prompt-Änderung X die
QA-Runden erhöht?" nicht valide, da der Konfigurationsstand
fehlt. Jeder Metriken-Datensatz wird daher mit Experiment-Tags
versehen, die den quantitativen Vergleich über Stories hinweg
ermöglichen (FK-08-032):

| Tag | Quelle | Zweck |
|-----|--------|-------|
| `agentkit_version` | `agentkit.__version__` | Versionsvergleich |
| `agentkit_commit` | Manifest (`agentkit_commit`) | Exakter Codestand |
| `llm_roles` | Pipeline-Config | Welche LLMs in welchen Rollen |
| `config_version` | Pipeline-Config | Konfigurationsstand |
| `story_type` | `StoryContext` bzw. dessen `context.json`-Export | Typvergleich |
| `story_size` | `StoryContext` bzw. dessen `context.json`-Export | Größenvergleich |
| `mode` | `phase_state_projection` bzw. deren `phase-state.json`-Export | Execution vs. Exploration |

### 14.7.3 Metriken-Persistenz

Metriken werden an zwei Stellen geschrieben:

1. **`closure.json`** (QA-Artefakt): Enthält `metrics`-Objekt mit
   allen Metriken + Experiment-Tags
2. **GitHub Project Fields:** `QA Rounds` und `Completed At` werden
   als Custom Fields gesetzt (Kap. 12)

### 14.7.4 Nutzung der Metriken

| Nutzer | Zweck |
|--------|-------|
| Mensch | Trends erkennen: Steigen QA-Runden nach Prompt-Änderung? |
| Failure Corpus | Metriken als Kontext für Incident-Bewertung |
| Governance-Beobachtung | Anomalie-Erkennung (ungewöhnlich hohe Werte) |
| Postflight | Plausibilitätsprüfung (Metriken gesetzt?) |

## 14.8 Telemetrie für Governance-Beobachtung

Die Governance-Beobachtung (FK 6.6, Kap. 35) nutzt die Telemetrie
als Signalquelle. Die Hooks produzieren nicht nur Events, sondern
normalisieren sie auch zu kompakten Records für das Rolling Window.

### 14.8.1 Normalisiertes Event-Format (für Rolling Window)

```json
{
  "occurred_at": "2026-03-17T10:15:23+01:00",
  "actor": "worker",
  "story_id": "ODIN-042",
  "phase": "implementation",
  "tool_class": "bash",
  "target_path": "/src/main/java/...",
  "risk_flags": ["code_write"]
}
```

| Feld | Werte |
|------|-------|
| `actor` | `orchestrator`, `worker`, `qa`, `adversarial` |
| `phase` | `setup`, `exploration`, `implementation`, `verify`, `closure` |
| `tool_class` | `bash`, `write`, `edit`, `read`, `agent`, `pool_send`, `web` |
| `risk_flags` | `code_write`, `outside_scope`, `governance_file`, `secret_access`, `main_branch`, `force_push` |

### 14.8.2 Akkumulation

Normalisierte Events werden in einem Rolling Window im
State-Backend akkumuliert. Das Window hat
eine konfigurierbare Breite (Default: 50 Events, Kap. 03).

Risikopunkte pro Signal:

| Signal | Risikopunkte |
|--------|-------------|
| Orchestrator liest/schreibt Code | +10 |
| Orchestrator führt Bash ohne aktiven Sub-Agent | +8 |
| Schreiben außerhalb Story-Scope | +8 |
| Governance-Dateien verändert | Sofortiger Stopp (kein Score) |
| Zugriff auf Secrets/Credentials | Sofortiger Stopp |
| >= 3 identische QA-Fails in Folge | +15 |
| Kein Phasenfortschritt >= 4 Stunden | +12 |

**Schwellenüberschreitung** (Default: Score > 30 im Window) →
Incident-Kandidat → LLM-Adjudication (Kap. 35).

## 14.9 Preflight-Telemetrie-Stream

### 14.9.1 Eigenständiger Stream

Preflight ist ein eigenständiger Telemetrie-Stream, der parallel
zum Review-Stream existiert und diesen nicht stört. Die
Grundidee: Preflight-Events dürfen weder die bestehenden
Review-Invarianten verletzen noch ungeprüft bleiben.

**Sentinel-Trennung:**

| Stream | Sentinel-Präfix | Regex |
|--------|----------------|-------|
| Review (bestehend) | `[TEMPLATE:name-v1:{story_id}]` | `\[TEMPLATE:([\w-]+)-v1:([A-Z]+-\d+)\]` |
| Preflight (neu) | `[PREFLIGHT:name-v1:{story_id}]` | `\[PREFLIGHT:([\w-]+)-v1:([A-Z]+-\d+)\]` |

Der bestehende `_REVIEW_SENTINEL`-Regex in `hook.py` und
`review_guard.py` matcht ausschließlich `[TEMPLATE:...]`. Der
Preflight-Sentinel mit `[PREFLIGHT:...]` wird bewusst NICHT
von diesem Regex erfasst, sondern von einem eigenen
`_PREFLIGHT_SENTINEL`-Regex verarbeitet.

### 14.9.2 Invarianten

Preflight-Events stören NICHT die bestehenden Review-Invarianten:

- `review_request`, `review_response`, `review_compliant`
  zählen nur Events aus dem Review-Stream (TEMPLATE-Sentinel)
- `preflight_request`, `preflight_response`, `preflight_compliant`
  bilden einen separaten Zähler-Satz
- Die Review-Mindestfrequenz (`ReviewFrequencyRule`) wird nur
  gegen Review-Events geprüft, nie gegen Preflight-Events

### 14.9.3 Fail-open / Fail-closed

- **Fail-closed:** Fehlender Preflight ist ein Fehler. Preflight ist
  Pflicht — jede Story muss mindestens ein `preflight_request`-Event
  aufweisen. Fehlende Preflight-Events erzeugen den Failure-Code
  `PREFLIGHT_MISSING`.
- **Fail-closed:** Inkonsistenter Preflight ist ein Fehler. Wenn
  `preflight_request > 0`, dann MUSS
  `preflight_response == preflight_request` UND
  `preflight_compliant == preflight_request` gelten. Verletzung
  führt zum Failure-Code `PREFLIGHT_NOT_COMPLIANT` (Kap. 35).

### 14.9.4 Lifecycle-Abgrenzung

```
[agent_start]
    [Implementation — Worker schreibt Code, Reviews, Preflight]
    [Preflight: INNERHALB des Worker-Lifecycles, eigener Telemetrie-Stream]
    [Reviews: INNERHALB des Worker-Lifecycles, Review-Telemetrie-Stream]
[agent_end]
    ↓
[Verify: prüft BEIDE Streams unabhängig]
```

Preflight-Events liegen zeitlich INNERHALB der
`agent_start`…`agent_end`-Klammer, weil der **Worker** den
Preflight als Teil seines Review-Ablaufs auslöst (Kap. 26,
§26.5b). Der Worker assembliert das Evidence-Bundle (Kap. 28),
sendet den Preflight-Prompt an das Review-LLM, löst die
Requests deterministisch auf und sendet dann den eigentlichen
Review.

Die Trennung der Streams ist **logisch**, nicht **zeitlich**:
- Preflight-Events (`preflight_request`/`response`/`compliant`)
  und Review-Events (`review_request`/`response`/`compliant`)
  können im selben Zeitfenster entstehen
- Die Integrity-Gate-Prüfung (Kap. 35) wertet beide Streams
  unabhängig aus: Review-Compliance und Preflight-Compliance
  sind getrennte Prüfungen

### 14.9.5 Beispiel-Events (Preflight-Stream)

```jsonl
{"occurred_at":"2026-03-17T09:55:00+01:00","story_id":"ODIN-042","run_id":"a1b2...","event_type":"preflight_request","pool":"chatgpt"}
{"occurred_at":"2026-03-17T09:56:30+01:00","story_id":"ODIN-042","run_id":"a1b2...","event_type":"preflight_response","pool":"chatgpt","request_count":1}
{"occurred_at":"2026-03-17T09:56:30+01:00","story_id":"ODIN-042","run_id":"a1b2...","event_type":"preflight_compliant","pool":"chatgpt","template_name":"review-preflight"}
```

## 14.10 Telemetrie-Contract-Erweiterung

### 14.10.1 Abgrenzung zum Worker-Contract

Preflight-Events werden NICHT in die Worker-Contract-Rules
(`review_min_count`, `ReviewFrequencyRule`) aufgenommen.
Preflight ist Pflicht, wird vom Worker selbst ausgelöst
(Kap. 26, §26.5b), zählt aber nicht als Review.
Die bestehenden Contract-Rules bleiben unverändert:

| Contract-Rule | Zählt | Zählt NICHT |
|---------------|-------|-------------|
| `review_min_count` (Story-Größe) | `review_request` | `preflight_request` |
| `review_compliant == review_request` | Review-Stream | Preflight-Stream |

### 14.10.2 Eigene Preflight-Validierungsregel

Statt Preflight in die Worker-Contract-Rules einzubauen, gilt
eine eigene Validierungsregel:

```
count_events(project_key, story_id, "preflight_request") >= 1
UND count_events(project_key, story_id, "preflight_response")
     == count_events(project_key, story_id, "preflight_request")
UND count_events(project_key, story_id, "preflight_compliant")
     == count_events(project_key, story_id, "preflight_request")
```

> **[Entscheidung 2026-04-08]** Element 12 — Telemetry Contract: Crash-Detection (Start/End-Paarung) ist essentiell. Event-Count-Vertrag auf Minimum-Schwellen ("mindestens 1 Review", "mindestens 1 Drift-Check"), keine exakten Zaehler pro Story-Groesse.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 12.

Diese Regel wird in `telemetry_contract.py` als eigener
Constraint implementiert, der `EventType.PREFLIGHT_REQUEST`,
`EventType.PREFLIGHT_RESPONSE` und
`EventType.PREFLIGHT_COMPLIANT` referenziert.

Bei Verletzung: der Recurring Guard
`check_guard_preflight_compliance()` (Kap. 35) meldet einen
Warning-Level-Befund. Das Integrity-Gate erzeugt den
Failure-Code `PREFLIGHT_NOT_COMPLIANT`.

---

*FK-Referenzen: FK-08-001 bis FK-08-034 (Telemetrie-Events,
Erwartungswerte, Workflow-Metriken, Experiment-Tags),
FK-06-082 bis FK-06-091 (Integrity-Gate Telemetrie-Nachweise),
FK-06-097 bis FK-06-111 (Governance-Beobachtung Sensorik),
FK-05-119 bis FK-05-121 (Review-Häufigkeit nach Story-Größe),
FK-14-100 bis FK-14-109 (Preflight-Telemetrie-Stream,
Sentinel-Isolation, Fail-open/Fail-closed, Contract-Erweiterung)*
