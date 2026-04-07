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

### Modulstruktur und Verantwortlichkeiten

| Modul | Verantwortlichkeit | Abhaengigkeitsrichtung |
|---|---|---|
| `cli/` | CLI-Entrypoints, Command-Routing | Ruft alle anderen Module auf |
| `config/` | Pydantic v2 Config-Modelle, Loader, Validierung | Wird von allen importiert |
| `project/` | Modell des Zielprojekts (Manifest, Pfade, Repos, Features) | Wird von pipeline/ und project_ops/ importiert |
| `project_ops/` | Install, Upgrade, Checkpoint, Merge-Preservation | Nutzt config/, project/, resources/ |
| `pipeline/` | 5-Phasen-Orchestrierung (Engine, State, Routing, Phases) | Nutzt story/, workers/, qa/, governance/ |
| `story/` | Story-Domaene (Typen, Sizing, Routing-Rules) | Reine Domaenenlogik, keine externen Deps |
| `workers/` | Worker-Steuerlogik (Spawn, Koordination) | Nutzt prompting/, integrations/ |
| `prompting/` | Prompt-Komposition, Sentinels, Integrity | Liest aus resources/ |
| `governance/` | Guards, Integrity Gates, Policies | Wird von pipeline/ aufgerufen |
| `qa/` | 4-Layer QA (Structural, Evaluators, Adversarial, Policy Engine) | Wird von pipeline/phases/verify/ aufgerufen |
| `telemetry/` | Events, Emitter, Metriken, KPIs | Wird von pipeline/ gefuettert |
| `failure_corpus/` | Incident-Patterns, Taxonomy, Checks | Wird von qa/ und governance/ genutzt |
| `integrations/` | Adapter: GitHub, ARE, VectorDB, MCP, LLM-Pools | Duenne Adapter, von anderen Modulen genutzt |
| `schemas/` | JSON/YAML Schemas fuer Artefakte und Config | Wird von config/ und qa/ genutzt |
| `utils/` | Reine Hilfsfunktionen (stateless) | Keine Geschaeftslogik |
| `resources/` | Deployte Assets + interne Prompts/Schemas | **Nur** Dateien, kein Python-Code |

### Regeln fuer Module

1. **Keine zirkulaeren Imports.** Abhaengigkeitsrichtung ist top-down: `cli` -> `pipeline` -> `story`/`qa`/`governance` -> `config`/`utils`.
2. **Neue Module** nur mit fachlicher Begruendung. Kein Modul fuer eine einzelne Klasse.
3. **`resources/` enthaelt keinen Python-Code.** Nur Templates, Prompts, Schemas, Config-Dateien.
4. **`integrations/` sind Adapter.** Geschaeftslogik gehoert in die fachlichen Module, nicht in die Adapter.

### project_ops/ — Warum dieser Name

`project_ops/` deckt den gesamten Lifecycle ab: AgentKit in ein Zielprojekt hineinbringen, veraendern, migrieren und synchron halten.

| Alternativer Name | Warum abgelehnt |
|---|---|
| `bootstrap/` | Klingt nach einmaligem Setup — aber Install + Upgrade + Checkpoints + Merge-Preservation ist Dauerbetrieb |
| `installer/` | Zu eng sobald Upgrader und Merge-Preservation daneben stehen |

Substruktur:
- `install/` — Erstinstallation ins Zielprojekt
- `upgrade/` — Upgrade bestehender Installationen
- `checkpoint/` — Idempotente Checkpoint-Schritte
- `merge_preservation/` — Lokale Anpassungen bei Upgrade erhalten
- `shared/` — Gemeinsame Infrastruktur (Pfade, File-Ops, Diffing, Templating)

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
    project_ops/                  # Install/Upgrade-Szenarien
    target_project_sim/           # Verschiedene Projektkonfigurationen
    pipeline/                     # Pipeline-Durchlaeufe
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
| Phase-Logik nach technischer Schicht schneiden | Phasen sind fachlich, nicht technisch |
| E2E-Tests in Standard-CI | Brauchen Credentials, sind langsam, nicht deterministic |
| Tool-Caches umleiten | Erzeugt nur Friction, `.gitignore` reicht |
| Geschaeftslogik in `integrations/` | Adapter sind duenn, Logik gehoert in fachliche Module |
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
