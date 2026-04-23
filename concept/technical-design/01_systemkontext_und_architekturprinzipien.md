---
concept_id: FK-01
title: Systemkontext und Architekturprinzipien
module: system-architecture
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: system-architecture
  - scope: trust-boundaries
  - scope: architecture-principles
defers_to: []
supersedes: []
superseded_by:
tags: [architektur, systemkontext, fail-closed, trust-boundaries, multi-llm]
prose_anchor_policy: strict
formal_refs:
  - formal.architecture-conformance.entities
  - formal.architecture-conformance.invariants
  - formal.state-storage.invariants
  - formal.truth-boundary-checker.invariants
---

# 01 — Systemkontext und Architekturprinzipien

<!-- PROSE-FORMAL: formal.architecture-conformance.entities, formal.architecture-conformance.invariants, formal.state-storage.invariants, formal.truth-boundary-checker.invariants -->

## 1.1 Zielbild

AgentKit ist ein systemweit installiertes Python-Paket (`agentkit`),
das gegen Zielprojekte betrieben wird, ohne seine Laufzeitartefakte in
deren Repository zu deployen. Im Projekt liegen nur die
projektspezifische Konfiguration und die Anbindung an Claude Code; der
kanonische Laufzeit- und Zustandsraum liegt außerhalb des Projekts in
einem zentralen State-Backend.

Das Zielbild: 1-2 Menschen steuern eine Flotte autonomer Agenten, die
98% der Konzeptions-, Implementierungs- und Absicherungsarbeit an
geschäftskritischen Systemen (250k+ LOC) leisten. Der Mensch ist
Stratege und Controller, kein klassischer Entwickler.

## 1.2 Systemgrenzen

### 1.2.1 Systemlandschaft

```mermaid
graph TB
    subgraph DEV["Entwicklermaschine"]

        subgraph CC["Claude Code Session"]
            AGENT["Agent<br/>(Orchestrator / Worker /<br/>QA / Adversarial)"]
            HOOKS["Hook-Schicht<br/>PreToolUse / PostToolUse<br/>(agentkit Python-Hooks)"]
            TOOLS["Tool-Ausführung<br/>Bash, Read, Write, Edit,<br/>Glob, Grep, Agent"]
            SETTINGS[".claude/settings.json"]

            AGENT -->|"Tool-Aufruf"| HOOKS
            HOOKS -->|"exit 0: erlaubt<br/>exit 2: blockiert"| TOOLS
            SETTINGS -.->|"Hook-Registrierung"| HOOKS
        end

        REPO["Zielprojekt-Repo<br/>(Git Worktree)"]
        TOOLS -->|"Dateisystem + Git"| REPO
    end

    subgraph EXTERN_MCP["Externe Systeme (via MCP)"]
        LLM_POOLS["LLM-Session-Pools<br/>(beliebige Implementierung)<br/>MCP: acquire / send / release"]
        VEKTORDB["Story-Knowledge-Base<br/>(Weaviate via MCP)"]
        ARE["ARE (optional)<br/>(MCP)"]
    end

    subgraph EXTERN_OTHER["Externe Systeme (andere Protokolle)"]
        GITHUB["GitHub<br/>REST + GraphQL API<br/>(via gh CLI)"]
        LLM_WEB["LLM-Web-Interfaces<br/>(ChatGPT, Gemini, Grok)"]
    end

    TOOLS -->|"MCP stdio"| LLM_POOLS
    TOOLS -->|"MCP stdio"| VEKTORDB
    TOOLS -->|"MCP"| ARE
    TOOLS -->|"gh CLI"| GITHUB
    LLM_POOLS -->|"impl.-spezifisch"| LLM_WEB
```


### 1.2.2 Komponentenzuordnung

**AgentKit-Kern** (wird entwickelt und ausgeliefert):

| Komponente | Typ | Technologie |
|------------|-----|-------------|
| `agentkit` Python-Paket | Bibliothek + CLI + Hooks | Python 3.14, Pydantic 2.7+, PyYAML 6+ |
| Rollenprompts + Skills | Paketressourcen / systemweite Bundles | Nicht im Projekt deployt |
| JSON Schemas | Artefakt-Validierung | JSON Schema Draft 2020-12 |

**Plattform** (Voraussetzung, nicht Teil von AgentKit):

| Komponente | Typ | Protokoll |
|------------|-----|-----------|
| Claude Code | Agent-Plattform | CLI + Hook-API (PreToolUse/PostToolUse) |
| Git | Versionskontrolle | CLI (`git`) |
| GitHub | Issue-/Projekt-Backend | REST + GraphQL via CLI (`gh`) |

**Externe Dienste** (via MCP, austauschbar):

| Dienst | Schnittstelle zu AgentKit | Anforderung |
|--------|--------------------------|-------------|
| LLM-Session-Pools | MCP-Tools: `{pool}_acquire`, `{pool}_send`, `{pool}_release`, `{pool}_health`, `{pool}_pool_status` | Mindestens 2 verschiedene LLM-Familien neben Claude. Die konkrete Implementierung (Browser-Automation, API, etc.) ist AgentKit egal — es zählt nur die MCP-Schnittstelle. |
| Story-Knowledge-Base | MCP-Tools: `story_search`, `story_list_sources`, `story_sync` | Aktuell: Weaviate (Docker) + FastMCP-Server. Austauschbar durch jede Implementierung mit gleicher MCP-Schnittstelle. |
| ARE (optional) | MCP-Tools (analog zu Weaviate-Wrapper). **Kein direkter DB-Zugriff.** | Python-Anwendung mit SQL-DB im Backend. Falls ARE nativ nur REST/FastAPI spricht, wird ein MCP-Wrapper als Adapter implementiert (wie bei Weaviate). |
| Zielprojekt | Dateisystem + Git | Beliebiger Tech-Stack |

**Referenz-Implementierung der LLM-Pools** (aktuell im Einsatz, nicht
Teil von AgentKit):

Die folgenden Implementierungen sind die aktuelle Referenz. Sie sind
austauschbar, solange die MCP-Schnittstelle (`acquire`/`send`/`release`)
eingehalten wird.

| Pool | Implementierung | Laufzeit |
|------|----------------|----------|
| `chatgpt-pool` | Python, FastAPI, Playwright | Native Windows, REST `:9100` |
| `gemini-pool` | Python, FastAPI, xdotool + Extension-Bridge | WSL2 Ubuntu, User `gemini`, REST `:9200`, VNC `:5900` |
| `grok-pool` | Python, FastAPI, xdotool + Extension-Bridge | WSL2 Ubuntu, User `grok`, REST `:9400`, VNC `:5901` |

Gemini und Grok laufen auf derselben WSL2-Instanz mit getrennten
Linux-Usern, X11-Displays und Ports.

### 1.2.2a Fachliches Komponentenmodell

Fuer AK3 wird "Komponente" fachlich verstanden: als logisch
abgegrenztes Verantwortungsbuendel mit klarer Schnittstelle. Eine
Komponente ist **nicht** automatisch eine Python-Klasse, ein Modul
oder ein Prozess.

Der normative Komponentenschnitt von AK3 wird in FK-65 festgezogen.
Dieses Kapitel enthaelt nur die uebergeordneten Prinzipien:

| Regel | Bedeutung |
|-------|-----------|
| Verantwortung vor Technik | Komponenten werden nach fachlicher Aufgabe benannt, nicht nach Datei, Klasse oder Pipeline-Schritt |
| Ein Aufrufer, gekapselte Innenlogik | Wird ein Baustein ausschliesslich von genau einer Komponente genutzt und ist Teil ihres inneren Ablaufwissens, ist er Subkomponente |
| Mehrere Aufrufer, eigener Vertrag | Wird ein Baustein von mehreren Komponenten genutzt, ist er Top-Level-Komponente mit eigenem Vertrag |
| Adapter sind keine Fachkomponenten | HTTP, Hook-, MCP- und Projekt-Edge-Bausteine sind R-Code und nicht Teil des fachlichen Kerns |
| Persistenztreiber sind keine Fachkomponenten | `state_backend` ist technische Infrastruktur und keine fachliche Mitte |

**Leitende Top-Level-Familien von AK3:**

| Familie | Leitende Komponenten |
|---------|----------------------|
| Story-, Planungs- und Ausfuehrungskern | `StoryContextManager`, `ExecutionPlanningService`, `PipelineEngine`, `StoryExecutionLifecycleService`, `WorktreeManager` |
| Governance- und QA-Kern | `GuardSystem`, `CcagPermissionRuntime`, `ConformanceService`, `StageRegistry`, `GovernanceObserver`, `FailureCorpus` |
| Inhalts- und Runtime-Services | `ArtifactManager`, `PromptComposer`, `LlmEvaluator`, `TelemetryService`, `PhaseStateStore` |
| Analytics- und Produktoberflaeche | `KpiAnalyticsEngine`, `DashboardApplication` |
| Bootstrap und Projektbindung | `Installer` |

**Wichtige Abgrenzungen:**

| Abgrenzung | AK3-Regel |
|------------|-----------|
| `PipelineEngine` vs. Phasen | Die Engine ist Top-Level; die Phasen sind ihre Subkomponenten. `PreflightChecker`, `ModeResolver`, `StructuralChecker`, `PolicyEngine` und `IntegrityGate` sind wiederum phasennahe Subkomponenten |
| `ExecutionPlanningService` vs. `PipelineEngine` | Planung bestimmt `READY`, `blocked`, Wellen und Parallelisierungsbudgets; die `PipelineEngine` fuehrt nur bereits zugelassene Story-Runs aus |
| `StageRegistry` | Bleibt Top-Level, weil sie sowohl von `VerifyPhase` als auch vom `FailureCorpus` genutzt wird; sie darf nicht in `VerifyPhase` aufgehen |
| `GuardSystem` vs. `CcagPermissionRuntime` | CCAG ist **nicht** Teil des GuardSystems. Guards erzwingen harte Regeln; CCAG verwaltet lernfaehige, vom Menschen freigegebene Permission-Pfade |
| `PromptComposer` vs. Prompt-Integritaet | Der Composer assembliert Prompts. Sentinel-/Spawn-Integritaet und Governance-Escape-Erkennung gehoeren zum Guard-/Hook-System, nicht zum Composer |
| Externe Integrationen | GitHub, LLM-Pools, ARE und VectorDB bleiben getrennte Adapter; `IntegrationHub` ist kein normativer Top-Level-Baustein |

**Prozessvertrag pro Komponente:**

Alle nichttrivialen Ablaufanteile von AK3 werden ueber eine
einheitliche hierarchische Prozess-DSL modelliert (FK-20). Das gilt
nicht nur fuer die Gesamtpipeline, sondern auch fuer Komponenten und
ihre Subschritte.

| Vertragsbestandteil | Bedeutung |
|---------------------|-----------|
| `FlowDefinition` | Beschreibt Reihenfolge, Branching, Rueckspruenge und Yield-Points |
| `NodeDefinition` | Definiert atomare oder zusammengesetzte Ausfuehrungsschritte |
| `ExecutionPolicy` | Regelt, ob ein Knoten erneut laufen darf oder nach Erfolg uebersprungen wird |
| `OverridePolicy` | Regelt, welche CLI-/Mensch-Overrides zulaessig sind |
| Handler-Implementierung | Enthaelt die Fachlogik, I/O und Seiteneffekte des Knotens |

**Architekturregel:** Eine Komponente besitzt damit zwei klar getrennte
Vertraege:

- einen **Kontrollflussvertrag** in der gemeinsamen DSL
- einen **Ausfuehrungsvertrag** ihrer Schritt-Handler

Diese Trennung ist die Gegenmassnahme gegen neue imperative
God-Files: Kontrollfluss wird deklarativ und auditierbar modelliert,
Fachlogik bleibt lokal in der Komponente.

### 1.2.3 Was AgentKit NICHT ist

- Kein CI/CD-System — es ersetzt keine Build-Pipeline, sondern
  orchestriert Agenten, die in einer solchen arbeiten.
- Kein projektlokaler AgentKit-Server — Zielprojekte enthalten keine
  eigene AgentKit-Runtime. Das State-Backend ist zentral und vom
  Projekt entkoppelt.
- Kein LLM-Anbieter — es nutzt Claude (via Claude Code), ChatGPT,
  Gemini und Grok als externe Dienste.
- Kein Testframework — es orchestriert Tests, schreibt aber selbst
  keine fachlichen Tests.
- Kein Projektmanagement-Tool — es nutzt GitHub Projects als Backend,
  ersetzt es aber nicht.

## 1.3 Architekturprinzipien

### P1: Fail-Closed

Jeder unbekannte Zustand ist ein Fehler. Konkret:

| Situation | Reaktion |
|-----------|----------|
| Fehlende Konfigurationsfelder | Default zugunsten des restriktiveren Pfads (z.B. Exploration Mode statt Execution Mode) |
| Ungültige JSON-Artefakte | Check = FAIL, nicht SKIP |
| LLM liefert kein gültiges JSON | Regex-Fallback → Retry → FAIL |
| Nicht erreichbares externes System | Abbruch mit Fehlercode, nicht stille Fortfahrt |
| Fehlende Telemetrie-Events | Integrity-Gate blockiert Closure |
| Unbekannter Story-Typ | Pipeline-Abbruch |

### P2: Plattform-Enforcement

Guards und Governance werden über die Hook-Schicht von Claude Code
durchgesetzt. Ein Agent kann seine eigenen Hooks nicht deaktivieren,
weil Hooks Teil der Plattforminfrastruktur sind, nicht Teil des
Agent-Codes.

**Technisch:** Hooks werden in `.claude/settings.json` registriert.
Claude Code ruft sie als externe Prozesse auf (`PreToolUse`,
`PostToolUse`). Der Hook-Prozess ist ein Python-Skript aus dem
`agentkit`-Paket, das über `sys.stdin` den Tool-Call empfängt und
über `sys.exit(0)` (erlauben) oder `sys.exit(2)` (blockieren)
antwortet.

```mermaid
sequenceDiagram
    participant A as Agent
    participant CC as Claude Code
    participant H as Hook-Skript (Python)
    participant T as Tool-Ausführung

    A->>CC: Tool-Aufruf (z.B. Bash "git push")
    CC->>H: PreToolUse via stdin: {tool_name, tool_input}
    H->>H: Regeln prüfen (Guard-Logik)
    alt exit(0) — erlaubt
        H-->>CC: exit 0
        CC->>T: Tool ausführen
        T-->>CC: Ergebnis
        CC->>H: PostToolUse via stdin
        H-->>CC: exit 0
        CC-->>A: Tool-Ergebnis
    else exit(2) — blockiert
        H-->>CC: exit 2 + opake Fehlermeldung
        CC-->>A: Fehlermeldung (Tool nicht ausgeführt)
    end
```

### P3: Deterministisch wo möglich, LLM nur wo nötig

| Aufgabe | Mittel |
|---------|--------|
| Pipeline-Steuerung, Phasenwechsel, Mode-Routing | Deterministischer Python-Code |
| Structural Checks, Policy-Evaluation | Deterministischer Python-Code |
| Guard-Enforcement | Deterministischer Python-Code (Hooks) |
| Telemetrie-Erfassung, Metriken | Deterministischer Python-Code |
| Code-Implementierung | LLM als Agent (Dateisystem-Zugriff) |
| Adversarial Testing | LLM als Agent (eingeschränkter Dateisystem-Zugriff) |
| QA-Bewertung, Semantic Review | LLM als Bewertungsfunktion (kein Dateisystem) |
| Dokumententreue-Prüfung | LLM als Bewertungsfunktion (kein Dateisystem) |
| Governance-Adjudication | LLM als Bewertungsfunktion (kein Dateisystem) |

**LLM als Agent:** Claude-Code-Session mit Dateisystem-Zugriff.
Wird für Worker und Adversarial Agent eingesetzt.

**LLM als Bewertungsfunktion:** Deterministisches Python-Skript ruft
ein LLM über Browser-Pool (MCP) auf. Der Pool-Call (`chatgpt_send`,
`gemini_send`, `grok_send`) sendet einen strukturierten Prompt und
empfängt eine Textantwort, die als JSON geparst wird. Kein
Dateisystem-Zugriff. Kein autonomes Handeln. Das Skript validiert
die Antwort und entscheidet, die Pipeline entscheidet.

### P4: Rollentrennung durch technische Mittel

Rollentrennung ist nicht nur Prompt-Disziplin, sondern wird durch
technische Mechanismen erzwungen:

| Rolle | Technische Einschränkung | Mechanismus |
|-------|------------------------|-------------|
| Orchestrator | Darf nicht auf Codebase zugreifen | `orchestrator_guard.py` (PreToolUse-Hook) |
| Worker | Darf keine QA-Artefakte schreiben | `integrity.py` (PreToolUse-Hook) |
| QA-Agent (Bewertungsfunktion) | Hat keinen Dateisystem-Zugriff | Läuft als Pool-Call, nicht als Agent |
| Adversarial Agent | Darf nur Test-Dateien schreiben | CCAG-Regel oder dedizierter Guard |

### P5: Multi-LLM als Pflicht

Verschiedene Rollen werden von verschiedenen LLM-Familien bedient.
Das ist konfigurierte Pflicht, nicht optionale Ergänzung.

**Konfiguration** in `.story-pipeline.yaml`:

```yaml
multi_llm: true  # Pflicht, Default true

llm_roles:
  worker: "claude"                # Claude Code Session (immer Claude)
  qa_review: "chatgpt"            # Schicht 2: QA-Bewertung (12 Checks)
  semantic_review: "gemini"        # Schicht 2: Semantic Review
  adversarial_sparring: "grok"     # Schicht 3: Edge-Case-Ideen
  doc_fidelity: "gemini"           # Dokumententreue-Prüfung
  governance_adjudication: "gemini"   # Governance-Beobachtung
  story_creation_review: "chatgpt" # VektorDB-Konfliktbewertung
```

Das Integrity-Gate prüft bei Closure, dass alle konfigurierten
Pflicht-Reviewer tatsächlich aufgerufen wurden (Telemetrie-Nachweis).

### P6: Kontext-Selektion

Agenten erhalten nicht den gesamten verfügbaren Kontext, sondern nur
den für ihre aktuelle Aufgabe relevanten. Story-Metadaten (betroffene
Module, Story-Typ, Tech-Stack) selektieren automatisch die passenden
Regel- und Wissensabschnitte aus getaggten Sektionen der
Projektdokumentation. Irrelevante Abschnitte werden nicht in den
Prompt injiziert.

**Technisch:** Ein Manifest-Indexer scannt die Projektdokumentation
(CLAUDE.md, Konzepte, Guardrails) und erzeugt einen validierbaren
Index mit Pfad, Abschnittsanker, Tags und Gültigkeitsbereich. Der
Prompt-Builder arbeitet nur gegen diesen Index — nicht gegen
Inline-Tags in den Dokumenten selbst. Das verhindert Metadaten-Drift
und macht die Selektionsbasis zentral validierbar.

Das Ergebnis ist ein Kontextpaket pro Rolle, das dem Agent-Prompt
vorangestellt wird.

Details zur technischen Umsetzung in Kapitel 08 (Rollen, Prompts,
Kontext-Selektion).

### P7: Minimale Dependencies

Das `agentkit` Python-Paket (Python 3.14) hat drei Kern-Dependencies:

| Dependency | Version | Zweck |
|------------|---------|-------|
| `pyyaml` | ≥ 6.0 | YAML-Konfiguration parsen |
| `pydantic` | ≥ 2.7 | Datenmodelle validieren (frozen, strict) |
| `psutil` | ≥ 5.9 | Prozessmonitoring |

Optionale Dependencies:

| Dependency | Zweck | Feature-Flag |
|------------|-------|-------------|
| `weaviate-client` 4.9-5.0 | VektorDB-Anbindung | `features.vectordb: true` |
| `mcp[cli]` ≥ 1.2.0 | MCP-Server für Story-Knowledge-Base | `features.vectordb: true` |

**Infrastruktur-Dependency:** Die systemweite AgentKit-Installation
setzt eine zentrale PostgreSQL-Instanz als State- und Analytics-Store
voraus. Der passende Treiber ist deshalb Teil der Runtime-
Implementierung, auch wenn er nicht zum minimalen Agenten-Kern gehört.
Externe Systeme werden über CLI-Tools (`gh`, `git`), MCP-Protokoll
oder die zentrale Postgres-Infrastruktur angesprochen.

### P8: Datenformate

| Artefakttyp | Format | Begründung |
|-------------|--------|------------|
| Telemetrie-Events (Laufzeit) | PostgreSQL | Kanonischer, projektunabhängiger Audit-Trail mit Berechtigungsgrenzen |
| Telemetrie-Events (Archiv) | Export/Bundle aus dem State-Backend | Menschenlesbar, langfristige Archivierung |
| QA-Ergebnisse | Strukturierte Records in PostgreSQL + optionale JSON-Exporte | Validierbar gegen JSON Schema, aber nicht dateibasiert kanonisch |
| Pipeline-State | Strukturierte Records in PostgreSQL | Zustandspersistenz zwischen Phasen mit Zugriffskontrolle |
| Konfiguration | YAML | Menschenlesbar, editierbar |
| Prompts | Markdown | Paketressourcen, versioniert mit AgentKit |
| Manifest/Installationsmetadaten | Service-Record + lokale Config-Version | Maschinell prüfbar ohne Projekt-Manifest |

**Telemetrie-Prinzip:** Events werden zur Laufzeit in das zentrale
PostgreSQL-Backend geschrieben und über deterministische Abfragen
ausgewertet. Exportformate wie JSONL sind Audit- oder
Untersuchungsformate, aber nie kanonischer Laufzeit-Speicher.

**LLM-Call-Events:** Telemetrie-Events für externe LLM-Aufrufe
verwenden den generischen Event-Typ `llm_call` mit dem Feld `pool`
(Name des MCP-Servers, z.B. `chatgpt`, `gemini`, `grok`) und `role`
(konfigurierte Rolle aus `llm_roles`, z.B. `qa_review`,
`semantic_review`). Das Integrity-Gate prüft gegen die konfigurierten
Pflicht-Rollen, nicht gegen hardcoded Anbieternamen. Damit bleibt
die Pool-Abstraktion intakt — ein Wechsel des LLM-Providers erfordert
nur eine Konfigurationsänderung, keine Code-Änderung.

## 1.4 Trust Boundaries

### 1.4.1 Boundary-Modell

```
    ┌─── Zone 1: Plattform (Claude Code + Hooks) ──────────────────────────┐
    │   Nicht vom Agent kontrollierbar. Hook-Enforcement.                   │
    │                                                                      │
    │   ┌─── Zone 2: Pipeline-Orchestrierung ──────────────────────────┐   │
    │   │   Deterministischer Python-Code. Entscheidet.                │   │
    │   │                                                              │   │
    │   │   ┌─── Zone 3: Agent-Ausführung ────────────────────────┐    │   │
    │   │   │   LLM-gesteuert, nicht-deterministisch.             │    │   │
    │   │   │   Kann lügen, abkürzen, fabrizieren.                │    │   │
    │   │   │   Jede Behauptung wird durch Zone 1/2 verifiziert.  │    │   │
    │   │   └─────────────────────────────────────────────────────┘    │   │
    │   └──────────────────────────────────────────────────────────────┘   │
    │                                                                      │
    │   ┌─── Zone 4: Externe LLMs (Pools) ────────────────────────────┐   │
    │   │   Antworten nicht vertrauenswürdig.                         │   │
    │   │   Nur als Bewertungsfunktion. Pipeline entscheidet.         │   │
    │   └─────────────────────────────────────────────────────────────┘   │
    └──────────────────────────────────────────────────────────────────────┘
```

### 1.4.2 Trust-Regeln

| Regel | Bedeutung |
|-------|-----------|
| Zone 3 darf Zone 1 nicht umgehen | Agent kann Hooks nicht deaktivieren |
| Zone 3 darf Zone 2 nicht manipulieren | Agent kann Pipeline-State nicht direkt schreiben; State-Mutationen laufen nur über deterministische Services mit Rollenrechten |
| Zone 4 entscheidet nicht | LLM-Antworten werden geparst und validiert; die Pipeline entscheidet basierend auf dem Ergebnis |
| Trust-Klasse C ist nie blocking | Vom Agent selbst erzeugte Evidence (Screenshots, API-Logs) kann QA nicht bestehen/nicht blockieren |
| Opake Fehlermeldungen an Zone 3 | Guards geben dem Agent keine Details, warum er blockiert wurde |

## 1.5 Hauptlaufzeitpfade

### 1.5.1 Story-Bearbeitung (Hauptpfad)

```mermaid
flowchart TD
    classDef exploration fill:#fff3cd,stroke:#d4a017,color:#333
    classDef lightweight fill:#d4edda,stroke:#28a745,color:#333
    classDef fail fill:#f8d7da,stroke:#dc3545,color:#333

    START(["Mensch setzt Issue<br/>auf 'Freigegeben'"]) --> ORCH
    ORCH["Orchestrator-Agent<br/>startet Pipeline"] --> SETUP

    subgraph SETUP_PHASE ["agentkit run-phase setup"]
        SETUP["Preflight (8 Gates)"] --> WT["Worktree erstellen"]
        WT --> CTX["Story-Context<br/>berechnen"]
        CTX --> GUARDS["Guards aktivieren<br/>(Marker-Datei)"]
        GUARDS --> MODE{"Mode-Routing<br/>(6 Kriterien)"}
    end

    MODE -->|Exploration| EXPLORE
    MODE -->|Execution| IMPL

    subgraph EXPLORE_PHASE ["Exploration-Phase"]
        EXPLORE["Worker erzeugt<br/>Entwurfsartefakt<br/>(7 Bestandteile)"]:::exploration
        EXPLORE --> DOCTREUE["Dokumententreue<br/>Ebene 2<br/>(LLM via Pool)"]:::exploration
        DOCTREUE -->|FAIL| ESC_E(["Eskalation<br/>Pipeline pausiert"]):::fail
        DOCTREUE -->|PASS| IMPL
    end

    subgraph IMPL_PHASE ["Implementation (Worker-Agent)"]
        IMPL["Vertikale Inkremente:<br/>Code → Check → Drift → Commit"]
        IMPL --> REVIEW["Reviews durch<br/>konfigurierte LLMs"]
        REVIEW --> HANDOVER["Handover-Paket<br/>erzeugen"]
    end

    HANDOVER --> VERIFY

    subgraph VERIFY_PHASE ["agentkit run-phase verify"]
        VERIFY["Schicht 1:<br/>Deterministische Checks"]
        VERIFY -->|PASS| LLM_EVAL["Schicht 2:<br/>LLM-Bewertungen<br/>(QA 12 Checks + Semantic)"]
        LLM_EVAL -->|PASS| ADV["Schicht 3:<br/>Adversarial Testing"]
        ADV -->|keine Befunde| POLICY["Schicht 4:<br/>Policy-Evaluation"]
        VERIFY -->|FAIL| FEEDBACK
        LLM_EVAL -->|FAIL| FEEDBACK
        ADV -->|Befunde| FEEDBACK
        POLICY -->|FAIL| FEEDBACK
        FEEDBACK["Mängelliste<br/>an Worker"]:::fail --> IMPL
    end

    POLICY -->|PASS| CLOSURE

    subgraph CLOSURE_PHASE ["agentkit run-phase closure"]
        CLOSURE["Integrity-Gate<br/>(7 Dim. + Telemetrie)"]
        CLOSURE -->|FAIL| ESC_C(["Eskalation<br/>an Mensch"]):::fail
        CLOSURE -->|PASS| MERGE["Branch mergen"]
        MERGE --> CLOSE["Issue schließen<br/>Status: Done"]
        CLOSE --> METRICS["Metriken erfassen"]
        METRICS --> POSTFLIGHT["Postflight-Gates"]
    end

    POSTFLIGHT --> DONE(["Story abgeschlossen"])
```

### 1.5.2 Story-Erstellung (Nebenpfad)

```mermaid
flowchart TD
    classDef optional fill:#e0e0e0,stroke:#999,stroke-dasharray: 5 5,color:#555

    TRIGGER(["Mensch oder Agent<br/>löst Erstellung aus"]) --> SKILL
    SKILL["Skill create-userstory<br/>wird geladen"] --> KONZEPT
    KONZEPT["Konzeption<br/>Problem, Lösung,<br/>Akzeptanzkriterien"] --> VEKTORDB
    VEKTORDB["VektorDB-Abgleich<br/>Similarity + LLM-Bewertung"] --> ZIELTREUE
    ZIELTREUE["Dokumententreue Ebene 1:<br/>Zieltreue (LLM via Pool)"] --> ARE
    ARE["ARE: Anforderungen<br/>verlinken"]:::optional --> GITHUB
    GITHUB["GitHub Issue erstellen<br/>mit Custom Fields"] --> BACKLOG
    BACKLOG["Status: Backlog"] --> FREIGABE
    FREIGABE{"Mensch gibt frei?"}
    FREIGABE -->|ja| FREI["Status: Freigegeben"]
    FREIGABE -->|nein| REWORK["Nacharbeit"] --> KONZEPT
```

## 1.6 Tech-Stack-Zusammenfassung

| Schicht | Technologie | Version | Protokoll |
|---------|-------------|---------|-----------|
| Agent-Plattform | Claude Code | aktuell | CLI + Hook-API |
| Hook-Sprache | Python | 3.14 | stdin/stdout, exit codes |
| Konfiguration | YAML | — | Dateisystem |
| Datenmodelle | Pydantic | 2.7+ | Python-Klassen |
| Telemetrie | JSONL | — | Dateisystem (append) |
| QA-Artefakte | JSON | — | Dateisystem + JSON Schema |
| VCS | Git | 2.30+ | CLI (`git`) |
| GitHub | GitHub API | REST v3 + GraphQL v4 | CLI (`gh`) |
| VektorDB | Weaviate | 1.25+ | gRPC + HTTP REST |
| Embedding | text2vec-transformers | — | Docker Sidecar |
| VektorDB-MCP | FastMCP | 1.2+ | stdio-Transport |
| LLM-Session-Pools | Beliebig (externe Infrastruktur) | — | MCP-Tools: `{pool}_acquire`, `{pool}_send`, `{pool}_release`. Implementierung ist AgentKit-agnostisch. |
| ARE (optional) | Python-Anwendung + SQL-DB | — | MCP-Tools oder FastAPI-Endpunkte. Kein direkter DB-Zugriff durch AgentKit. |
| Build/Test | projektspezifisch | — | via `mvn`, `pytest`, `jest` etc. |
| Linting/Typing | ruff, mypy | — | CLI |
| Tests | pytest | 8+ | pytest-Konventionen |
| Coverage | pytest-cov | — | 85% Minimum |

---

*FK-Referenzen: FK-04-005 bis FK-04-023 (Rollen, Multi-LLM),
FK-06-001 bis FK-06-006 (Fail-Closed-Prinzipien),
FK-07-004 bis FK-07-008 (Trust-Klassen),
FK-11-001 bis FK-11-009 (Installer/Tech-Stack)*
