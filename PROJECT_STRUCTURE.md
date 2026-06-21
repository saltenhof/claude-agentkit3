# Projektstruktur-Guardrails

Dieses Dokument ist verbindlich fuer alle Agents, die in dieser Codebase arbeiten.
Jeder Agent MUSS diese Regeln einhalten. Verstoesse sind Deliverable-Blocker.

---

## Architekturprinzip: Dreifache Entkopplung

AgentKit existiert in zwei Formen. Diese Dualitaet bestimmt die gesamte Struktur.

| Form | Beschreibung |
|---|---|
| **Development-Codebase** (dieses Repo) | AgentKit-Produkt mit Deployment Units unter `src/agentkit/`, Tests, CI — hier wird AgentKit entwickelt |
| **Installiert im Zielprojekt** | AgentKit deployt `.agentkit/`, Prompts, Skills, Hooks, Config in ein fremdes Projekt |

Die Codebase ist in drei Ebenen entkoppelt:

| Ebene | Ort | Zweck |
|---|---|---|
| AgentKit-Source | `src/agentkit/` | Einziger Produkt-Source-Root; darunter zuerst Deployment Units, dann fachliche Komponenten |
| Deployte Assets | `src/agentkit/bundles/target_project/` | Einzige Source of Truth fuer alles was ins Zielprojekt geht |
| Test-Sandboxes | `tests/integration/target_project_sim/` | Simulierte Zielprojekte in Temp-Verzeichnissen |

---

## Verzeichnisstruktur — Regeln

### Root-Ebene

| Verzeichnis | Zweck | Regeln |
|---|---|---|
| `src/agentkit/` | AgentKit-Produkt-Source | Einziger Ort fuer Produktionscode und paketierte AgentKit-Artefakte. Darunter nur Deployment Units. |
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

### `concept/` - interne Struktur

Unter `concept/` existieren drei autoritative Bereiche mit
unterschiedlicher Aufgabe:

```text
concept/
  domain-design/              # Fachliche Prosa-Konzepte
  technical-design/           # Technische Feinkonzepte
  formal-spec/                # Deterministisch pruefbare Formalspezifikation
```

**Regeln:**

1. `domain-design/` und `technical-design/` bleiben menschenlesbare
   Prosa-Konzepte.
2. `formal-spec/` enthaelt nur die normative, maschinenpruefbare
   Spezifikationsschicht.
3. `formal-spec/` bleibt ebenfalls **Markdown-only**, aber in
   strukturiertem, linterbarem Format gemaess
   `concept/formal-spec/00_meta/meta-contract.md`.
4. Generierte, abgeleitete oder kompilierte Artefakte aus der
   Formalspezifikation gehoeren **nie** nach `concept/`, sondern nach
   `var/`.

---

## src/agentkit/ — Deployment Units

### Strukturprinzip: Deployment Unit vor Fachkomponente

`src/agentkit/` ist der AgentKit-Namespace. Direkt darunter liegen
keine beliebigen fachlichen oder technischen Sammelordner, sondern nur
auslieferbare Teilanwendungen bzw. paketierte Artefaktfamilien.
Erst innerhalb einer Deployment Unit wird nach fachlichen Komponenten
geschnitten.

Der normative Top-Level-Schnitt ist definiert in
`concept/formal-spec/architecture-conformance/entities.md`.

**Sollzustand:** Deployment-Unit-first:

```text
src/agentkit/
  backend/                     # Python-Service: BFF, Orchestrierung, State, Installer, CLI
    control_plane_http/        # HTTP(S)-Server und Router
    control_plane/             # Control-Plane Runtime/Modelle/Repository
    auth/
    project_management/
    story_context_manager/
    execution_planning/
    pipeline_engine/
    verify_system/
    governance/
    kpi_analytics/
    task_management/
    skills/                    # Skill-Verwaltung, nicht Skill-Inhalte
    ...

  frontend/                    # Produktives Web-Frontend
    app/                       # TypeScript/React-Quellen; kein zweites src/

  harness_client/              # Code, den Harnesses oder Zielprojekt-Tools nutzen
    projectedge/               # Client/Resolver fuer Zielprojekt <-> Backend
    harness_adapters/          # Claude/Codex Hook-/Settings-/CLI-Adapter

  integration_clients/         # Drittsystem-Clients, die AgentKit aufruft
    github/
    jenkins/
    sonar/
    vectordb/
    multi_llm_hub/

  bundles/                     # Paketierte, auslieferbare Nicht-Code-Artefakte
    skill_bundles/
    internal/prompts/
    target_project/
```

### Deployment-Unit-Regeln

1. Direkt unter `src/agentkit/` duerfen nur Deployment Units bzw.
   paketierte Artefaktfamilien liegen: `backend/`, `frontend/`,
   `harness_client/`, `integration_clients/`, `bundles/` plus
   Paketmarker.
2. Fachliche Bounded Contexts liegen unter der Deployment Unit, die sie
   ausliefert. Backend-BCs liegen unter `src/agentkit/backend/`.
3. Externe Drittsystem-Adapter liegen unter
   `src/agentkit/integration_clients/`, nicht als allgemeiner
   Top-Level-Ordner.
4. Harness-spezifische Adapter und ProjectEdge liegen unter
   `src/agentkit/harness_client/`, nicht im Backend-Governance-BC.
5. Auslieferbare Skill-, Prompt- und Zielprojekt-Artefakte liegen unter
   `src/agentkit/bundles/`; Backend-Code, der sie verwaltet, liegt unter
   `src/agentkit/backend/`.
6. `frontend/prototype/` ist kein produktives Frontend. Es ist
   read-only Concept-as-Code/Quarantaene fuer historische UI-Arbeit.
   Produktive Frontend-Quellen liegen ausschliesslich unter
   `src/agentkit/frontend/app/`.

### Backend-Fachkomponenten

Innerhalb von `src/agentkit/backend/` folgt AK3 weiter dem fachlichen
Komponentenmodell. Package-Namen werden aus der fachlichen
Verantwortung abgeleitet, nicht aus technischen Querschnitten wie
`pipeline`, `qa` oder `utils`, sofern diese nur Sammelcontainer waeren.

**Backend-Namespaces:** `artifacts/`, `auth/`, `bootstrap/`,
`boundary/`, `cli/`, `closure/`, `concept_catalog/`, `config/`,
`control_plane/`, `control_plane_http/`, `core_types/`,
`execution_planning/`, `exploration/`, `failure_corpus/`,
`governance/`, `implementation/`, `installer/`,
`integration_stabilization/`, `kpi_analytics/`, `phase_state_store/`,
`pipeline_engine/`, `process/`, `project/`, `project_management/`,
`project_ops/`, `prompt_runtime/`, `requirements_coverage/`,
`schemas/`, `skills/`, `state_backend/`, `story/`,
`story_context_manager/`, `story_creation/`, `story_exit/`,
`story_reset/`, `story_split/`, `task_management/`, `telemetry/`,
`telemetry_service/`, `utils/`, `vectordb/`, `verify_system/`.

**Backend-Regeln:**

1. Ein fachlicher Namespace unter `src/agentkit/backend/`
   repraesentiert genau eine fachliche Komponente oder klar benannte
   Backend-Boundary.
2. Subkomponenten werden als Unterpakete nur dann angelegt, wenn sie
   ausschliesslich der uebergeordneten Komponente dienen.
3. Querschnittsmodule wie `utils/`, `workers/`, `qa/` oder `pipeline/`
   sind als dauerhafte Zielstruktur nicht zulaessig, wenn sie mehrere
   fachliche Komponenten vermischen. Bestehende Altlasten sind
   Migrationskandidaten, keine Vorlage fuer neue Struktur.
4. Backend-Fachlogik importiert Drittsysteme ueber
   `agentkit.integration_clients.*` und Harness-/ProjectEdge-Mechanik
   ueber `agentkit.harness_client.*`.
5. Backend-Code darf paketierte Artefakte aus `agentkit.bundles`
   lesen, aber niemals dorthin Laufzeitdaten schreiben.

### Boundary-Module

Boundary-Module bleiben fachlich relevant, liegen aber innerhalb der
Deployment Unit, die sie ausliefert:

| Boundary | Code-Heimat |
|---|---|
| CLI / Backend-Eingang | `src/agentkit/backend/cli/` |
| Control-Plane HTTP | `src/agentkit/backend/control_plane_http/` |
| Control-Plane Runtime/Records | `src/agentkit/backend/control_plane/` |
| State-Backend Repository/Driver | `src/agentkit/backend/state_backend/` |
| Filesystem Boundary | `src/agentkit/backend/boundary/filesystem/` |
| Drittsystem-Adapter | `src/agentkit/integration_clients/` |
| Harness-/ProjectEdge-Client | `src/agentkit/harness_client/` |

Neue Boundary-Module duerfen nicht als weitere direkte Kinder von
`src/agentkit/` entstehen. Sie gehoeren in die passende Deployment Unit.

### tools/ — Architektur- und Build-Tooling

```text
tools/
  concept_compiler/            # Compiler/Linter/Scenario-Runner fuer formale Konzept-Spezifikationen
```

**Regeln:**

1. Tooling unter `tools/` ist **kein** Produktivcode und darf nicht
   unter `src/agentkit/` liegen.
2. Der `concept_compiler` liest aus `concept/formal-spec/` und
   schreibt nur abgeleitete Artefakte nach `var/`.
3. Tests fuer Tooling liegen unter `tests/`, nicht unter `tools/`.

### Installer-Komponente

`src/agentkit/backend/installer/` (BC 12) ist die fachliche Komponente
fuer Projektregistrierung und Bootstrap. Substruktur gemaess
`entities.md`:

- `checkpoint_engine/` — idempotente Checkpoint-Ausfuehrung
- `bootstrap_checkpoints/` — Erstregistrierungs-Checkpoints
- `integration_checkpoints/` — Integrations-spezifische Checkpoints
- `upgrade/` — Upgrade bestehender Installationen

### Phasen als eigenstaendige Bounded Contexts

Die 5 Phasen der Pipeline sind in v3 **eigenstaendige fachliche BCs**,
keine Subverzeichnisse unter `pipeline_engine/`:

| Phase | BC | Namespace |
|---|---|---|
| 1 — Setup | BC 4 governance | `backend/governance/setup_preflight_gate/` |
| 2 — Exploration | BC 5 exploration | `backend/exploration/` |
| 3 — Implementation | BC 6 implementation | `backend/implementation/` |
| 4 — Verify | BC 2 verify_system | `backend/verify_system/` |
| 5 — Closure | BC 7 closure | `backend/closure/` |

`backend/pipeline_engine/` (BC 1) ist die Orchestrierungsmaschine, die
diese BCs aufruft — nicht ihr Container. Neue Phasen-Logik gehoert in
den jeweiligen BC, nicht in `pipeline_engine/`.

### bundles/ — Single Source of Truth

```
bundles/
  skill_bundles/      # Paketierte Skill-Bundles
  internal/prompts/   # Interne Prompt-Bundles
  target_project/     # Was ins Zielprojekt deployt wird
    .agentkit/        # Prompts, Hooks, Config, Manifests
    .claude/          # Skills, Context
    .codex/           # Codex-Konfiguration
    templates/        # Jinja2-Templates (CLAUDE.md.j2, project.yaml.j2, ...)
    tools/
      agentkit/
        projectedge.py  # Zielprojekt-Code (kein AgentKit3-Produktionscode)
```

**Regeln:**
- Jede deployte Datei existiert GENAU EINMAL unter `src/agentkit/bundles/target_project/`.
- Keine Kopien in `tests/fixtures/` — Tests lesen aus `bundles/` oder vergleichen gegen `tests/golden/`.
- Aenderungen an deploybaren Assets erfordern Aktualisierung der Golden Files.
- `bundles/target_project/tools/agentkit/projectedge.py` ist Zielprojekt-Code, kein
  AgentKit3-Produktionscode. Es wird ins Zielprojekt deployt und laeuft dort als lokaler
  Projekt-Adapter.

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

1. **Unit-Tests spiegeln die Code-Heimat innerhalb der Deployment Unit.**
   `src/agentkit/backend/pipeline_engine/` -> `tests/unit/pipeline_engine/`.
   Analog fuer alle BCs.
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
| Deployte Dateien mehrfach vorhalten | Genau eine Source of Truth: `src/agentkit/bundles/target_project/` |
| Phasen-Logik als Subdirectory von `backend/pipeline_engine/` | Exploration, Implementation, Verify, Closure sind eigenstaendige BCs |
| E2E-Tests in Standard-CI | Brauchen Credentials, sind langsam, nicht deterministic |
| Tool-Caches umleiten | Erzeugt nur Friction, `.gitignore` reicht |
| Geschaeftslogik in `integration_clients/` | Adapter sind duenn, Logik gehoert in fachliche Komponenten |
| Laufzeitdaten oder Backend-Code in `bundles/` | Nur paketierte Skills, Prompts und Zielprojekt-Assets |
| Neue Top-Level-Verzeichnisse ohne Consent | Struktur ist bewusst designed, nicht ad-hoc erweiterbar |
| Lose Python-Dateien im Root | Alles unter `src/agentkit/` |
| Zirkulaere Imports zwischen Modulen | Abhaengigkeitsrichtung ist top-down |

---

## Kurzreferenz fuer Agents

**Ich will Backend-Produktionscode schreiben** -> `src/agentkit/backend/<passendes-modul>/`

**Ich will produktiven Frontend-Code schreiben** -> `src/agentkit/frontend/app/`

**Ich will Harness-/ProjectEdge-Code schreiben** -> `src/agentkit/harness_client/`

**Ich will einen Drittsystem-Client schreiben** -> `src/agentkit/integration_clients/<system>/`

**Ich will ein neues Modul anlegen** -> Fachliche Begruendung noetig. Kein Modul fuer eine Klasse.

**Ich will einen Test schreiben** -> Richtige Ebene waehlen: `unit/` (Logik), `integration/` (Dateisystem/Szenarien), `contract/` (Stabilitaet), `e2e/` (Live-Systeme).

**Ich will ein Deploy-Asset aendern** -> `src/agentkit/bundles/target_project/` aendern, dann Golden Files in `tests/golden/` aktualisieren.

**Ich will temporaere Dateien erzeugen** -> `var/` oder `tmp_path` (in Tests). Nie in `src/` oder `tests/fixtures/`.

**Ich will eine Integration hinzufuegen** -> `src/agentkit/integration_clients/<name>/` als duenner Adapter. Geschaeftslogik im fachlichen Backend-Modul.

**Ich will die Struktur erweitern** -> Dieses Dokument konsultieren. Neue Top-Level-Verzeichnisse nur mit User-Consent.
