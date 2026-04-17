# Projektstruktur-Guardrails

Dieses Dokument ist verbindlich fuer alle Agents, die in dieser Codebase arbeiten.
Jeder Agent MUSS diese Regeln einhalten. Verstoesse sind Deliverable-Blocker.

---

## Architekturprinzip: Dreifache Entkopplung

AgentKit existiert in zwei Formen. Diese Dualitaet bestimmt die gesamte Struktur.

| Form | Beschreibung |
|---|---|
| **Development-Codebase** (dieses Repo) | Python-Paket mit src-Layout, Tests, CI — hier wird AgentKit entwickelt |
| **Installiert im Zielprojekt** | AgentKit deployt `.agentkit/`, Prompts, Skills, Hooks, Config in ein fremdes Projekt |

Die Codebase ist in drei Ebenen entkoppelt:

| Ebene | Ort | Zweck |
|---|---|---|
| Package-Code | `src/agentkit/` | Implementierung der Orchestrierungsmaschine |
| Deployte Assets | `src/agentkit/resources/target_project/` | Einzige Source of Truth fuer alles was ins Zielprojekt geht |
| Test-Sandboxes | `tests/integration/target_project_sim/` | Simulierte Zielprojekte in Temp-Verzeichnissen |

---

## Verzeichnisstruktur — Regeln

### Root-Ebene

| Verzeichnis | Zweck | Regeln |
|---|---|---|
| `src/agentkit/` | Package-Code | Einziger Ort fuer Produktionscode. Kein Produktionscode ausserhalb. |
| `tests/` | Alle Tests | Vier Ebenen: `unit/`, `integration/`, `contract/`, `e2e/`. Details unten. |
| `stories/` | Story-Artefakte | Hier landen Story-bezogene Arbeitsergebnisse waehrend der Ausfuehrung. |
| `concept/` | Autoritative Fachkonzepte | Nur Markdown. Aenderungen nur mit explizitem User-Consent. |
| `docs/` | Publizierte Entwicklerdoku | Architecture, API, Guides, ADRs. |
| `examples/` | Demo-Zielprojekte | Lauffaehige Beispiele wie ein installiertes Zielprojekt aussieht. |
| `scripts/` | Dev/CI/Release-Hilfsskripte | Unterteilt in `dev/`, `ci/`, `release/`. |
| `var/` | Lokale ephemere Daten | **Gitignored.** Temp-Files, Logs, Sandboxes. Nie Source of Truth. |

### VERBOTEN auf Root-Ebene

- Keine Zielprojekt-Struktur im Root spiegeln (kein `.agentkit/` im Root)
- Keine losen Python-Dateien im Root
- Keine neuen Top-Level-Verzeichnisse ohne expliziten User-Consent

---

## src/agentkit/ — Package-Module

### Strukturprinzip: Komponenten vor Technik

Die Namespace-Struktur von AK3 folgt dem fachlichen
Komponentenmodell. Package-Namen werden aus der fachlichen
Verantwortung abgeleitet, nicht aus technischen Querschnitten wie
"pipeline", "qa" oder "governance", sofern diese nur
Implementierungs-Sammelcontainer waeren.

**Sollzustand:** komponentenorientierte Namespaces

```text
src/agentkit/
  cli/                         # Entrypoints, Command Routing
  config/                      # Konfiguration und Schema-Bindung
  pipeline_engine/
    setup_phase/
    exploration_phase/
    implementation_phase/
    verify_phase/
    closure_phase/
  guard_system/
  artifact_manager/
  story_context_manager/
  worktree_manager/
  prompt_composer/
  process/
    language/                  # Querschnittliche Prozesssprache fuer Pipeline und Komponenten
  llm_evaluator/
  conformance_service/
  stage_registry/
  telemetry_service/
  phase_state_store/
  governance_observer/
  failure_corpus/
  ccag_permission_runtime/
  kpi_analytics_engine/
  installer/
  integrations/                # Duenne Adapter zu externen Systemen
  resources/                   # Dateien/Templates/Schemas, kein Python
  shared/                      # Kleine, fachneutrale Hilfen und Basistypen
```

**Regeln:**

1. Ein fachlicher Top-Level-Namespace unter `src/agentkit/`
   repraesentiert genau eine fachliche Komponente.
2. Subkomponenten werden als Unterpakete **nur dann** angelegt, wenn
   sie ausschliesslich der uebergeordneten Komponente dienen.
3. Querschnittsmodule wie `utils/`, `workers/`, `qa/`, `governance/`
   oder `pipeline/` sind als dauerhafte Zielstruktur **nicht**
   zulaessig, wenn sie mehrere fachliche Komponenten vermischen.
4. `integrations/` bleibt als technischer Adapter-Schnitt bestehen,
   weil dies bewusst eine Infrastrukturgrenze und keine Fachkomponente
   ist.
5. `shared/` ist streng minimal zu halten: Basistypen, Exceptions,
   kleine stateless Hilfen. Keine Geschaeftslogik.

### Modulstruktur und Verantwortlichkeiten

| Namespace | Verantwortlichkeit | Abhaengigkeitsrichtung |
|---|---|---|
| `cli/` | CLI-Entrypoints, Command-Routing | Ruft Komponenten und Integrationen auf |
| `config/` | Pydantic-v2-Modelle, Loader, Validierung | Wird von Komponenten importiert |
| `pipeline_engine/` | 5-Phasen-Orchestrierung, Transitionen, Run-Steuerung | Nutzt StoryContext, Worktree, Evaluator, Registry, Telemetrie, State |
| `guard_system/` | Hook-basierte harte Guards und Health-Monitor | Nutzt Telemetrie, ArtifactManager, Config |
| `artifact_manager/` | Envelope-Validierung, Producer-Pruefung, Artefaktvertrag | Wird von Pipeline, Guards, QA genutzt |
| `story_context_manager/` | Autoritativer Story-Kontext nach Setup | Wird von Pipeline und PromptComposer genutzt |
| `worktree_manager/` | Worktree-/Branch-Lifecycle | Wird von Setup/Closure genutzt |
| `prompt_composer/` | Prompt-Assembling und Kontext-Selektion | Nutzt StoryContext, Resources |
| `process/` | Querschnittliche Prozesssprache und Ablaufvertraege | Wird von PipelineEngine und anderen Komponenten genutzt |
| `llm_evaluator/` | Strukturierte LLM-Bewertungen | Nutzt Integrationen und Schemas |
| `conformance_service/` | Dokumententreue-/Conformance-Kette | Nutzt LlmEvaluator |
| `stage_registry/` | Autoritativer Staging-Katalog | Wird von Verify und FailureCorpus genutzt |
| `telemetry_service/` | Events, Nachweise, Telemetrie-Lesezugriffe | Wird von Hooks, Pipeline, Analytics genutzt |
| `phase_state_store/` | Persistenz des laufenden Workflow-Status | Wird von Pipeline und Installer genutzt |
| `governance_observer/` | Governance-Anomalien, Adjudication, Incident-Erzeugung | Nutzt Telemetry, LlmEvaluator, FailureCorpus |
| `failure_corpus/` | Incidents, Patterns, Check-Promotion | Nutzt StageRegistry |
| `ccag_permission_runtime/` | Lernfaehige Tool-Permissions | Eigenstaendiger Hook-Pfad neben GuardSystem |
| `kpi_analytics_engine/` | KPI-Erhebung, Aggregation, Dashboard-Serving | Nutzt TelemetryService |
| `installer/` | Registrierung, Bootstrap, Upgrade-nahe Projektbindung | Nutzt Config, Integrationen, Resources, PhaseStateStore |
| `integrations/` | Adapter: GitHub, ARE, VectorDB, MCP, LLM-Pools | Duenne Adapter, von Komponenten genutzt |
| `resources/` | Deployte Assets + interne Prompts/Schemas | **Nur** Dateien, kein Python-Code |
| `shared/` | Kleine fachneutrale Basistypen/Hilfen | Keine Geschaeftslogik |

### Regeln fuer Module

1. **Keine zirkulaeren Imports.** Abhaengigkeitsrichtung ist top-down: `cli` -> fachliche Top-Level-Namespaces -> `integrations|config|resources|shared`.
2. **Neue Namespaces** nur mit fachlicher Begruendung. Keine technischen Sammelcontainer ohne eigene Verantwortung.
3. **Fachliche Top-Level-Namespaces sind der Normalfall fuer Produktionslogik.** Neue Fachlogik gehoert dorthin, nicht in querschnittige Restkategorien.
4. **`resources/` enthaelt keinen Python-Code.** Nur Templates, Prompts, Schemas, Config-Dateien.
5. **`integrations/` sind Adapter.** Geschaeftslogik gehoert in die fachlichen Komponenten, nicht in die Adapter.
6. **`shared/` bleibt klein.** Wenn ein Modul Fachwissen ueber Pipeline, Guards, QA, Storys oder Installer enthaelt, gehoert es nicht nach `shared/`.

### Uebergangsregel fuer den bestehenden AK3-Baum

Der aktuelle Codebaum ist noch teilweise technisch geschnitten. Das
ist als **Migrationszustand** akzeptiert, aber nicht der Sollzustand.

| Heutiger Namespace | Ziel-Komponente / Ziel-Namespace |
|---|---|
| `pipeline/` | `pipeline_engine/` + `phase_state_store/` + `story_context_manager/` + `worktree_manager/` |
| `governance/` | `guard_system/` + `conformance_service/` + `governance_observer/` |
| `qa/` | `pipeline_engine/verify_phase/` + `llm_evaluator/` + `stage_registry/` |
| `telemetry/` | `telemetry_service/` + `kpi_analytics_engine/` |
| `failure_corpus/` | `failure_corpus/` |
| `prompting/` | `prompt_composer/` |
| `project_ops/` | `installer/` |
| `story/` | `story_context_manager/` soweit laufzeitrelevant; reine Story-Domaenentypen koennen als eigenstaendiges Unterpaket dort bleiben |
| `workers/` | Gehoert fachlich zur PipelineEngine; kein dauerhafter Top-Level-Namespace |
| `project/` | Gehoert fachlich zu Installer, StoryContext und WorktreeManager; kein dauerhafter Top-Level-Namespace |
| `utils/` | `shared/` nur fuer wirklich fachneutrale Teile; sonst Rueckbau in fachliche Top-Level-Namespaces |
| `schemas/` | bleibt als Ressourcen-/Vertragsnahes Paket nur wenn es keine Fachlogik enthaelt; ansonsten in `resources/internal/schemas/` oder komponentennah aufteilen |

### Installer-/Projektbindungskomponente

Im Komponentenmodell wird der bisherige technische Sammelcontainer
`project_ops/` fachlich in `installer/` ueberfuehrt.

Substruktur des Sollzustands:
- `register/` — Erstregistrierung und Projektbindung
- `upgrade/` — Upgrade bestehender Installationen/Bindungen
- `checkpoint/` — Idempotente Checkpoint-Schritte
- `preservation/` — Lokale Anpassungen bei Upgrade erhalten
- `binding/` — Skill-/Hook-/Config-Bindung an das Zielprojekt

**Migrationsregel:** Bestehender Code unter `project_ops/` ist
Uebergangsbestand und wird nicht weiter ausgebaut. Neue Logik fuer
Projektregistrierung oder Upgrades gehoert nach
`installer/`.

### pipeline/phases/ — Phasenorientierter Schnitt

Die 5 Phasen sind der fachliche Kern, kein Implementierungsdetail:

| Phase | Verzeichnis | Typ |
|---|---|---|
| 1 — Setup | `phases/setup/` | deterministisch |
| 2 — Exploration | `phases/exploration/` | LLM (optional) |
| 3 — Implementation | `phases/implementation/` | LLM |
| 4 — Verify | `phases/verify/` | deterministisch + LLM |
| 5 — Closure | `phases/closure/` | deterministisch |

Neue Phasen-Logik gehoert in das jeweilige Phasen-Verzeichnis. Querschnittslogik (State, Routing, Artifacts) liegt auf `pipeline/`-Ebene.

**Aktualisierung durch Komponentenmodell:** Diese Phasenstruktur bleibt
fachlich gueltig, wird namespace-seitig aber als Substruktur von
`pipeline_engine/` verstanden, nicht als dauerhaftes
eigenstaendiges Top-Level-Modul `pipeline/`.

### resources/ — Single Source of Truth

```
resources/
  target_project/     # Was ins Zielprojekt deployt wird
    .agentkit/        # Prompts, Hooks, Config, Manifests
    .claude/          # Skills, Context
    templates/        # Jinja2-Templates (CLAUDE.md.j2, project.yaml.j2, ...)
  internal/           # Interne Prompts und Schemas (werden NICHT deployt)
```

**Regeln:**
- Jede deployte Datei existiert GENAU EINMAL unter `resources/target_project/`.
- Keine Kopien in `tests/fixtures/` — Tests lesen aus `resources/` oder vergleichen gegen `tests/golden/`.
- Aenderungen an deploybaren Assets erfordern Aktualisierung der Golden Files.

---

## tests/ — Vier Testebenen

### Ueberblick

| Ebene | Verzeichnis | Geschwindigkeit | CI | Zweck |
|---|---|---|---|---|
| Unit | `tests/unit/` | Sekunden | Jeder PR | Reine Logik, keine I/O |
| Integration | `tests/integration/` | Minuten | Jeder PR | Simulierte Zielprojekte, echte Dateisystem-Ops |
| Contract | `tests/contract/` | Sekunden | Jeder PR | Schema-Stabilitaet, Snapshot-Vergleiche |
| E2E | `tests/e2e/` | Minuten-Stunden | Manuell/Nightly | Live-Systeme (GitHub, VectorDB, MCP, ...) |

### Regeln

1. **Unit-Tests spiegeln die src/-Struktur.** `src/agentkit/pipeline/` -> `tests/unit/pipeline/`.
   Im Sollzustand spiegeln sie die Komponentenstruktur:
   `src/agentkit/pipeline_engine/` ->
   `tests/unit/pipeline_engine/`.
2. **Integration-Tests sind szenariobasiert**, nicht modulbasiert. Beispiel: `install_fresh/`, `upgrade_preserve_local_edits/`.
3. **Contract-Tests schuetzen Stabilitaet.** Prompt-Sentinels, Schema-Versionen, Manifest-Formate. Brechen wenn sich ein oeffentliches Format aendert.
4. **E2E-Tests sind IMMER opt-in.** Marker: `@pytest.mark.e2e`. Nie in Standard-CI. Brauchen echte Credentials.
5. **Golden Files** (`tests/golden/`) sind versioniert. Aktualisierung erfordert bewussten Review.
6. **Fixtures** (`tests/fixtures/`) enthalten statische Testdaten. Keine generierten Dateien — die gehoeren in `var/` oder `tmp_path`.
7. **Neue Tests** gehoeren in die richtige Ebene. Im Zweifel: Unit vor Integration, Integration vor E2E.

### Test-Verzeichnisse

```
tests/
  conftest.py                     # Gemeinsame Fixtures, Marker-Registrierung
  unit/                           # Spiegelt src/agentkit/ Struktur
  integration/
    installer/                    # Register/Upgrade-Szenarien
    target_project_sim/           # Verschiedene Projektkonfigurationen
    pipeline_engine/              # Pipeline-Durchlaeufe
    governance_hooks/
    prompts_and_skills/
    artifact_schemas/
  contract/
    scaffold_snapshots/           # Gerenderte Zielprojekt-Dateien
    prompt_templates/             # Prompt-Sentinels
    skill_manifests/
    checkpoint_manifests/
    external_adapter_contracts/
  e2e/
    smoke/                        # Minimaler Durchlauf
    github_live/
    vectordb_live/
    are_live/
    mcp_live/
    llm_pools_live/
  fixtures/                       # Statische Testdaten
  golden/                         # Golden-File-Snapshots
```

---

## stories/ — Story-Artefakte

Das `stories/`-Verzeichnis ist der Ablageort fuer Story-bezogene Arbeitsergebnisse. Hier landen Artefakte die waehrend der Story-Ausfuehrung durch die Pipeline erzeugt werden.

---

## Tool-Caches und generierte Verzeichnisse

### Im Root belassen (Tool-Defaults, gitignored)

Diese Verzeichnisse werden von Python-Tools automatisch erzeugt und bleiben dort wo sie standardmaessig landen:

- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `__pycache__/`
- `.coverage`, `htmlcov/`
- `*.egg-info/`, `dist/`, `build/`
- `.venv/`

**Nicht umleiten.** Gegen Tool-Defaults zu arbeiten erzeugt Friction bei Entwicklern, IDEs und CI.

### var/ — Projekt-eigene ephemere Daten

`var/` ist gitignored und reserviert fuer AgentKit-eigene Laufzeitdaten:
- `var/tmp/` — Temporaere Dateien (Merge-Files, Zwischenergebnisse)
- `var/logs/` — Lokale Laufzeit-Logs
- `var/sandboxes/` — Test-Sandboxes, simulierte Zielprojekte

**Regel:** Alles in `var/` ist wegwerfbar. Kein Agent darf `var/` als Source of Truth verwenden.

---

## Verbotene Muster

| Muster | Warum verboten |
|---|---|
| Zielprojekt-Struktur im Repo-Root | Development-Codebase ist nicht das Zielprojekt |
| Deployte Dateien mehrfach vorhalten | Genau eine Source of Truth: `resources/target_project/` |
| Phase-Logik nach technischer Schicht schneiden | Phasen sind fachlich, aber als Subkomponenten der `PipelineEngine` zu organisieren statt als technischer Restcontainer |
| E2E-Tests in Standard-CI | Brauchen Credentials, sind langsam, nicht deterministic |
| Tool-Caches umleiten | Erzeugt nur Friction, `.gitignore` reicht |
| Geschaeftslogik in `integrations/` | Adapter sind duenn, Logik gehoert in fachliche Komponenten |
| Python-Code in `resources/` | Nur Templates, Prompts, Schemas, Config-Dateien |
| Neue Top-Level-Verzeichnisse ohne Consent | Struktur ist bewusst designed, nicht ad-hoc erweiterbar |
| Lose Python-Dateien im Root | Alles unter `src/agentkit/` |
| Zirkulaere Imports zwischen Modulen | Abhaengigkeitsrichtung ist top-down |

---

## Kurzreferenz fuer Agents

**Ich will neuen Produktionscode schreiben** -> `src/agentkit/<passendes-modul>/`

**Ich will ein neues Modul anlegen** -> Fachliche Begruendung noetig. Kein Modul fuer eine Klasse.

**Ich will einen Test schreiben** -> Richtige Ebene waehlen: `unit/` (Logik), `integration/` (Dateisystem/Szenarien), `contract/` (Stabilitaet), `e2e/` (Live-Systeme).

**Ich will ein Deploy-Asset aendern** -> `src/agentkit/resources/target_project/` aendern, dann Golden Files in `tests/golden/` aktualisieren.

**Ich will temporaere Dateien erzeugen** -> `var/` oder `tmp_path` (in Tests). Nie in `src/` oder `tests/fixtures/`.

**Ich will eine Integration hinzufuegen** -> `src/agentkit/integrations/<name>/` als duenner Adapter. Geschaeftslogik im fachlichen Modul.

**Ich will die Struktur erweitern** -> Dieses Dokument konsultieren. Neue Top-Level-Verzeichnisse nur mit User-Consent.
