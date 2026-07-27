# AG3-175 — Implementierungsplan (Phase 0, vor Codereview)

- **Rolle:** Coding-Worker (Worker-Modus).
- **Stand der Messungen:** Branch `feat/ag3-175-dual-harness-registration`,
  Basis `1e713f3a` (main). Alle Zeilenangaben sind an diesem Stand geprueft.
- **Review-Budget:** EINE Codex-Runde (`status.yaml` Zeile 15). Deshalb enthaelt
  dieser Plan bewusst auch die unangenehmen Befunde vor dem Code.
- **Sprache:** Prosa deutsch, alle Bezeichner/Fehlernamen/TOML-/JSON-Keys
  englisch (ARCH-55, `guardrails/architecture-guardrails.md:130`).

**In diesem Plan wird kein Produktionscode und kein Test geschrieben.** Es gibt
**keinen Blocker**. Offen sind die Dependency-Entscheidung (§5 D-1, liegt beim
PO) und die Konzept-Nachzuege (§9 Q-1), plus vier kleinere Fragen (§9 Q-1b..Q-5).

> **Revision 2 (Korrektur nach Orchestrator-Rueckmeldung).** Zwei Befunde der
> Revision 1 waren falsch, beide aus demselben Fehler: Ich habe eine **Absenz
> aus einer einzelnen Datei** geschlossen, statt das Paket zu durchsuchen.
>
> 1. **Q-0 „kein Einstiegspunkt" ist widerlegt.** Der Einstiegspunkt existiert
>    in `engine.py`, nicht in `mcp_server.py`. Der echte Defekt ist kleiner und
>    liegt vollstaendig in meinem Scope: **CP 10 registriert das falsche Modul.**
>    Neu §1.5.
> 2. **„Der Bundle-Doppelgaenger wird nie deployt" ist widerlegt.** Er wird
>    kopiert und ist damit ein **dritter Writer** derselben Datei. Neu §1.2 und
>    §4.2; aus der Aufraeumfrage Q-2 wird eine Korrektheitspflicht.
>
> Ausserdem neu: eine **vierte** verpflichtende `env`-Variable
> (`AGENTKIT_CONCEPTS_DIR`), und der Befund, dass die Conformance-Probe eine
> **erreichbare Weaviate** braucht (§1.6). §9.0 enthaelt das vollstaendige
> Re-Audit aller uebrigen Absenz-Behauptungen dieses Plans.

---

## 0. Wie geprueft wurde

Gemessen wurde mit Lesezugriffen auf den Code, mit `tomllib`-Probes ueber
`.venv\Scripts\python`, mit `pip index versions` / `pip download --no-deps`
(kein Install; die Wheels liegen im Scratchpad und wurden per `sys.path`-
Zipimport nur zur Faktenmessung geladen) und mit einem Lauf des heute
registrierten Serverkommandos. Wo etwas **nicht** verifiziert werden konnte,
steht das ausdruecklich als „nicht verifiziert" dabei.

Die Sweep-Frage aus dem Briefing („ist meine Liste der `.codex/config.toml`-
Stellen vollstaendig?") wurde mit einer eigenen, breiten Suche ueber `src/`,
`tests/` und `bundles/` beantwortet (Literale `config.toml`, `.codex`,
`CODEX_HOME`, `mcp_servers`, `hooks.pre_tool_use`, `agentkit-hook-codex`,
Symbolnamen, plus alle `toml*`-Imports im Repo).

---

## 1. Verifikation der Briefing-Befunde

### 1.1 Befund A — bestaetigt, in beiden Teilen

**Teil 1 (Eintrag ohne `env`): bestaetigt.**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:148-153`

```python
if context.vectordb_enabled:
    servers[_STORY_KNOWLEDGE_BASE_SERVER] = {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "agentkit.backend.vectordb.mcp_server"],
    }
```

Kein `env`, kein `cwd`. Dagegen fordert
`src/agentkit/backend/vectordb/runtime_binding.py:33-37` alle drei Schluessel
`PROJECT_ID`, `WEAVIATE_HTTP_ENDPOINT`, `WEAVIATE_GRPC_ENDPOINT` vorhanden und
nicht-leer (`_required`, Zeile 40-52), und `_reject_localhost` (Zeile 55-67)
lehnt vier synthetisierte Defaults ab. Der heute geschriebene Eintrag erzeugt
also einen Server, der `RuntimeBinding.from_env` nicht bestehen kann.
(Kleine Korrektur zum Briefing: der Literal-Block beginnt bei Zeile **149**,
nicht 148; 148 ist das `if`.)

**Teil 2 (Probe wird neu abgeleitet und mit anderem `cwd` gebaut): bestaetigt.**
`cp10.py:353` `cmd: McpServerCommand = server_command_from_mcp_entry(entry)` und
`cp10.py:360-365`:

```python
bound = McpServerCommand(command=cmd.command, args=cmd.args, env=cmd.env, cwd=cwd)
```

**Zusatzbefund zur Bruecke** (im Briefing als Frage offen): der `cwd`-Verlust
ist keine Nachlaessigkeit des Aufrufers, sondern liegt in
`src/agentkit/backend/installer/mcp_conformance/check.py:202-227` selbst —
`server_command_from_mcp_entry` liest `command`, `args`, `env` und gibt
`McpServerCommand(command=command, args=args, env=env)` **ohne `cwd`** zurueck
(Zeile 227). Die Funktion kann `cwd` also strukturell nicht durchleiten. Ein
verlustfreier Weg muss deshalb **nicht** ueber diese Funktion laufen (siehe §2).

### 1.2 Befund B — bestaetigt, und die Kollision ist groesser als beschrieben

Bestaetigt:

- `src/agentkit/backend/installer/codex_settings.py:22-29` baut die Datei als
  festen Ganzdatei-String (Kommentar + `[hooks.pre_tool_use]` + `command`).
- `codex_settings.py:32-44` entscheidet die Neuschreibung per Textvergleich
  `config_path.read_text(...) == content` (Zeile 41).
- `src/agentkit/backend/installer/lifecycle/detach.py:340-362`
  (`_remove_ak3_codex_config`) entfernt die Datei **nur** bei Gleichheit mit
  `build_codex_config_toml()` (Zeile 359 `if current != build_codex_config_toml():`)
  und meldet sonst `preserved_foreign_files`.
- Belegt durch `tests/integration/installer/test_detach.py:630-641`
  (byte-gleich → entfernt) und `:643-658` (fremde Tabelle → erhalten), plus
  `tests/unit/cli/test_lifecycle_cli.py:240-265` (CLI-Payload).

**Die Reihenfolge, die das Briefing behauptet, ist ebenfalls belegt** — und sie
ist der eigentliche Beweis fuer „der zweite Lauf zerstoert die Registrierung":

- `write_codex_settings` wird in `runner.py:1186` innerhalb von
  `deploy_post_registration_artifacts` (`runner.py:1117`) aufgerufen; diese
  Funktion ist der **CP-8-Rumpf** (`bootstrap_checkpoints/cp07_to_09.py:219`).
- Der Flow ist CP 8 → CP 9 → CP 10
  (`checkpoint_engine/flow.py:117-118`, `node_ids.py:29/33`).
- Also: CP 8 schreibt die Datei, CP 10 wuerde die MCP-Tabelle hineinmergen, und
  der **naechste** Installationslauf setzt in CP 8 wieder den Fixstring — die in
  CP 10 gemergte Tabelle ist weg. AC 1 („idempotent") waere im Mehrlauf falsch.

**Zusaetzliche Kollisionen, die im Briefing fehlen** (alle geprueft):

| Stelle | Was sie tut | Konsequenz fuer das Design |
|---|---|---|
| `src/agentkit/bundles/target_project/.codex/config.toml` (3 Zeilen, byte-identisch zu `build_codex_config_toml()` — gemessen) | **DRITTER WRITER derselben Datei.** `runner.py:543-558` `_deploy_static_resource_files` kopiert **jede** Nicht-`templates`-**Datei** aus dem Bundle ins Zielprojekt (`if rel.parts[0] == "templates" or item.is_dir(): continue`) via `_copy_file_if_changed` (`runner.py:693-697` → `copy_file`, bedingungsloses Ueberschreiben). Aufgerufen in `runner.py:1148`, also **CP 8**, und **vor** `write_codex_settings` in `runner.py:1186`. Der Filter in `runner.py:1149-1151` betrifft nur die `created`-**Meldung**, nicht die Kopie; `_default_governance_hook_settings_paths` (`runner.py:1380-1386`) listet ohnehin nur `.claude/settings.json` und `.codex/hooks.json`. | **Korrektheitspflicht, nicht Kosmetik** (§4.2). Heute fallen Bundle-Inhalt und Builder-Ausgabe zufaellig zusammen, deshalb faellt es nicht auf. Nach AG3-175 wuerde diese Kopie die MCP-Tabelle bei **jedem** Folgelauf ueberschreiben — dieselbe Zerstoerung wie Befund B(1), aber ueber einen **anderen** Codepfad, den die Scope-Entscheidung nicht benennt. |
| `src/agentkit/backend/core_types/plane_artifact_names.py:96-99` | `SELF_PROTECTION_HOOK_SETTINGS_PARTS` enthaelt `(".codex", "config.toml")` — **zweites** Pfadliteral neben `installer/paths.py:13,39`. | Nur Namenskonstante, kein I/O. Kein Designzwang, aber: die Datei ist **guard-geschuetzt**. |
| `src/agentkit/backend/governance/guard_system/protected_paths.py:131-138` | `.codex/config.toml` liegt in `SELF_PROTECTION_HARNESS_FILE_PARTS` → Worker-Mutationen werden verweigert (`tests/unit/governance/guards/test_self_protection_guard.py:70-74`). | Der **Installer** ist der einzige legitime Schreiber. Bestaetigt den Schnitt „ein Writer, im Install-Pfad". Keine Aenderung noetig. |
| `src/agentkit/backend/governance/principal_capabilities/paths.py:89-92` | klassifiziert die Datei als `PathClass.GOVERNANCE_PLANE` (`tests/unit/governance/principal_capabilities/test_paths.py:55`). | Nur Klassifikation, kein Inhaltswissen. Keine Aenderung noetig. |
| `installer/paths.py:13,39,63-64` | `CODEX_DIR`, `CODEX_CONFIG_FILE`, `codex_config_path()` — Pfadbau, **kein** Containment-Helfer. | Der Symlink-/Junction-Schutz aus AC 7 existiert hier **nicht** und muss neu hinzu (§6). |
| `codex_settings.py:47-61` `remove_codex_settings` | Loescht die Datei **ungeschuetzt** (`unlink`) und hat **keinen** Produktionsaufrufer; Uninstall laeuft ueber `detach`. Nur `tests/unit/installer/test_codex_settings.py:35-42` ruft sie. | Toter, gefaehrlicher Pfad neben dem geschuetzten. **§9 Q-3**. |
| `harness_adapters/settings_writer.py:461-528` `CodexSettingsWriter` | schreibt `.codex/hooks.json`, **nie** `config.toml`. | Kein Konflikt; aber das Muster (Adapter-Writer mit `settings_path`, Fremd-Erhalt, fail-closed) ist die Vorlage fuer den neuen Writer. |
| Keine `toml*`-Bibliothek irgendwo unter `src/` | einziger `tomllib`-Import im Repo: `tests/contract/packaging/test_packaging_pins.py:5`. | Bestaetigt Befund D. |

Die **Scope-Entscheidung des Orchestrators** (ein semantischer Writer; die zwei
gekoppelten Aufrufstellen ziehen mit; `preserved_foreign_files` wird nicht
geschwaecht) wird uebernommen. §4 formuliert das Praedikat so, dass die
Preservation-Zusicherung **nicht** schwaecher wird — das ist bei einem naiven
„semantischen" Praedikat naemlich der Default-Fehler (siehe §4.3).

### 1.3 Befund C — bestaetigt, mit einer entscheidenden Verschaerfung

Bestaetigt:

- `src/agentkit/backend/config/models.py:531-549` (`VectorDbConfig`) traegt
  `similarity_threshold`, `max_llm_candidates`, `host: str | None`,
  `port: int | None` — **kein** gRPC-Port, **keine** Endpunkte.
- `vectordb/project_binding.py:104-152` `resolve_authoritative_project_id` ist
  der SSOT-Resolver (project.yaml-`project_prefix` autoritativ, `PROJECT_ID`-Env
  Fallback, Divergenz harter Fehler).
- `vectordb/wait_for_weaviate.py:36-39` `DEFAULT_HOST="localhost"`,
  `DEFAULT_PORT=8080` — und `runtime_binding._reject_localhost:55-67` verbietet
  genau `http://localhost:8080`, `http://127.0.0.1:8080`, `localhost:50051`,
  `127.0.0.1:50051`. Diese Defaults sind hier also unbenutzbar. Die
  D2-Beobachtung des Briefings (lokaler gRPC muss anders geschrieben werden)
  wird **nicht** angefasst.

**Verschaerfung (neu, und sie entscheidet die Designfrage):** Die Endpunkte
koennen **nicht** einfach „vom Operator in `project.yaml` gepflegt" werden.
`runner._build_project_yaml` (`runner.py:342-420`) baut die **gesamte** Mapping
aus `InstallConfig` neu und enthaelt heute **keinen** `vectordb`-Block; CP 5
schreibt sie mit `_write_yaml_if_changed` (`cp01_to_06.py:246`) bei jeder
Abweichung zurueck. Eine handgepflegte `pipeline.vectordb`-Stanza wird vom
naechsten Installationslauf also **geloescht**. Der einzige stabile Weg ist
`InstallConfig` → CP 5 → `project.yaml` → CP 10 (§3).

Gemessen (`_build_project_yaml` mit `features_vectordb=True`): Top-Level-Keys
`codebase_dir, concepts_dir, guardrails_dir, guardrails_pattern, input_dir,
meetings_dir, pipeline, project_key, project_name, repositories, story_types,
temp_dir, wiki_stories_dir`; `pipeline`-Keys `ci, config_version,
exploration_mode, features, llm_roles, max_feedback_rounds,
max_remediation_rounds, sonarqube, verify_layers`. **Kein `vectordb`.**

Zwei nuetzliche Nebenmessungen an derselben Mapping:

- `ProjectConfig.model_validate(_build_project_yaml(cfg))` gelingt → die
  CP-5-Mapping ist ein **vollstaendig typisierbares** `ProjectConfig`.
- dabei ist `pc.project_prefix == "DEMO"` bei `project_key="demo"` → das Modell
  leitet den Prefix selbst ab. Die Projekt-ID-Autoritaet ist damit ohne
  Regelduplikat verfuegbar.

### 1.4 Befund D — bestaetigt, mit harten Zahlen

- `.venv\Scripts\python`: Python **3.14.4**; `tomllib` hat **kein** `dump`/`dumps`
  (gemessen: `hasattr(tomllib,'dump') → False`, `dumps → False`).
- `pip list | grep -i toml` → leer (Exit 1). `pyproject.toml` fuehrt keinen
  TOML-Writer.
- `tomllib`-Striktheit gemessen (relevant fuer §6):

| Eingabe | Ergebnis |
|---|---|
| `[a]\nx=1\nx=2` | `TOMLDecodeError: Cannot overwrite a value (at line 3, column 4)` |
| `[a]\nx=1\n[a]\ny=2` | `TOMLDecodeError: Cannot declare ('a',) twice (at line 3, column 3)` |
| Bytes `x = "\xff\xfe"` | `UnicodeDecodeError` beim Dekodieren |
| `mcp_servers = 5` | **akzeptiert** → `{'mcp_servers': 5}` |
| `[mcp_servers]\nfoo = 5` | **akzeptiert** → `{'mcp_servers': {'foo': 5}}` |

Also: doppelte Keys/Tabellen und ungueltiges UTF-8 erledigt die Stdlib;
**Shape-Pruefungen muessen wir selbst machen**. TOML hat ausserdem **keinen**
Nicht-Tabellen-Root — die „falsche Root-Shape" aus AC 7 existiert in TOML nicht
und wird in §6 ehrlich als solche benannt statt erfunden.

### 1.5 NEUER BEFUND — CP 10 registriert das falsche Modul (kein Blocker)

In Revision 1 stand hier ein „harter Blocker: es gibt keinen Einstiegspunkt".
**Das war falsch.** Ich hatte in `mcp_server.py` nachgesehen — also in dem Modul,
das die Konfiguration zufaellig nennt — und aus dessen Absenz auf das Paket
geschlossen. Eine Paketsuche (`grep -rn "if __name__|^def main|run_stdio_server"
src/agentkit/backend/vectordb/`) findet den Einstiegspunkt sofort.

**Der Einstiegspunkt existiert, in `engine.py`:**

- `engine.py:1258` `def main() -> int:` — „Executable stdio entry point. Reads
  the env, composes the production engine, and serves. Fails closed (exit 1) on
  any binding/connection fault."
- `engine.py:1250-1255` `run_stdio_server(service)` — importiert
  `build_mcp_server` aus `mcp_server` und ruft `server.run()`.
- `engine.py:1311-1312` `if __name__ == "__main__": raise SystemExit(main())`.
- `engine.py:1315-1326` `__all__` exportiert `main` und `run_stdio_server`.

Selbst nachgemessen:

```
$ .venv/Scripts/python -m agentkit.backend.vectordb.engine < /dev/null
{"error": "composition_failed", "detail": "AGENTKIT_CONCEPTS_DIR is missing/empty;
 the concept corpus root has no default (fail-closed, D2/N20)."}
EXITCODE=1
```

Ein lebender, korrekt fail-closed arbeitender Einstiegspunkt. Der Kontrast zu
meiner eigenen Messung von `-m …mcp_server` (Exit 0, keine Ausgabe) ist genau
der Unterschied zwischen Bibliotheksmodul und Programm.

**Der wirkliche Defekt ist kleiner und liegt vollstaendig in meinem Scope:**
`cp10.py:152` schreibt

```python
"args": ["-m", "agentkit.backend.vectordb.mcp_server"],   # Bibliotheksmodul
```

wo das ausfuehrbare Modul `agentkit.backend.vectordb.engine` ist. `command` und
`args` sind Felder des `McpServerSpec`, den **AG3-175 selbst rendert** — Scope 1
und AC 5 machen sie zu meinem Deliverable. Die Korrektur ist keine
Scope-Ausweitung, sie **ist** der Scope. Nichts geht an den PO zurueck, es
braucht keine neue Story, und AC 1 ist produktiv erreichbar.

Der Kommandowert nach der Korrektur (eine Konstantenstelle in
`installer/mcp_registration.py`):

```python
STORY_KNOWLEDGE_BASE_COMMAND = "python"
STORY_KNOWLEDGE_BASE_ARGS = ("-m", "agentkit.backend.vectordb.engine")
```

`"python"` bleibt (statt `sys.executable`), weil FK-50 §50.3 CP 10 diesen Wert
dokumentiert und `resolve_command` (`mcp_conformance/process.py:80-97`) bare
Namen ueber `PATH` aufloest. Der Zielprojekt-`python` muss `agentkit` sehen —
das ist eine Installationsvoraussetzung, keine Rendering-Entscheidung.

### 1.6 NEUER BEFUND — eine VIERTE Pflicht-`env`-Variable, und die Probe braucht Weaviate

Beides von Orchestrator und mir zunaechst uebersehen.

**(a) `AGENTKIT_CONCEPTS_DIR` ist Pflicht und hat keinen Default.**
`engine.py:1272-1285` prueft vor allem anderen:

```python
concepts_dir_value = env.get("AGENTKIT_CONCEPTS_DIR", "").strip()
if not concepts_dir_value:  ->  {"error": "composition_failed", ...}; return 1
```

Der Kommentar haelt den Grund fest (N20/D2): ein Default auf das Literal
`concept` hat den Server einmal auf AK3s **eigenen** Entwicklungskorpus gezeigt.
`AGENTKIT_STORIES_DIR` (`engine.py:1290`) hat dagegen einen Default (`"stories"`).

**Vollstaendige, gemessene Anforderungsmatrix des gestarteten Prozesses**
(jeweils genau ein Key weggelassen, Rest vollstaendig, Endpunkt auf einen toten
Port; Ausgabe gekuerzt):

| `env`-Key | Pflicht? | validiert durch | gemessene Ausgabe bei Absenz |
|---|---|---|---|
| `PROJECT_ID` | ja | `RuntimeBinding` | `required env key 'PROJECT_ID' is missing from the runtime binding …` |
| `WEAVIATE_HTTP_ENDPOINT` | ja | `RuntimeBinding` | `required env key 'WEAVIATE_HTTP_ENDPOINT' is missing …` |
| `WEAVIATE_GRPC_ENDPOINT` | ja | `RuntimeBinding` | `required env key 'WEAVIATE_GRPC_ENDPOINT' is missing …` |
| `AGENTKIT_CONCEPTS_DIR` | **ja** | `main()` selbst, **nicht** `RuntimeBinding` | `AGENTKIT_CONCEPTS_DIR is missing/empty; the concept corpus root has no default (fail-closed, D2/N20).` |
| `AGENTKIT_STORIES_DIR` | nein | Default `"stories"`, aufgeloest gegen die **Prozess-`cwd`** | kommt an der `env`-Validierung vorbei, scheitert erst an der Konnektivitaet |

Damit ist die Kernaussage klar: **`runtime_binding.REQUIRED_ENV_KEYS` (3 Keys)
ist NICHT die Anforderungsmenge des Prozesses (4 Pflicht-Keys).** Ein Spec, der
`RuntimeBinding` besteht und trotzdem einen Prozess erzeugt, der mit Exit 1
endet, ist genau der Fehlermodus, gegen den AC 5 existiert. Konsequenz in §3.1
und §8.

**(b) Die Conformance-Probe braucht eine erreichbare Weaviate.**
`compose_runtime` (`engine.py:1188-1221`) ruft in dieser Reihenfolge:
`RuntimeBinding.from_env` (1204) → `connect_real_client(binding)` (1205) →
`ensure_corpus_collections(client)` (1211) → erst danach kommt
`run_stdio_server` (1301). Gemessen mit vollstaendigem `env` und totem Endpunkt:

```
{"error": "composition_failed", "detail": "Could not connect to Weaviate at
 127.0.0.1:9999 (grpc 127.0.0.1:59999): … Is Weaviate running and reachable at
 http://127.0.0.1:9999? (fail-closed, FK-13 §13.2)."}
EXITCODE=1
```

Der Prozess erreicht `initialize`/`tools/list` also **nur** mit laufender
Weaviate. Folgen, ehrlich benannt:

- AC 1 („nach einem Installationslauf ist der Server registriert") setzt in einem
  echten Lauf eine **laufende Weaviate** voraus. Das ist konsistent mit AG3-176
  Scope 1 („Der Installer installiert oder startet keine Datenbank — er setzt sie
  voraus") und mit der Story-Abgrenzung „E2E gegen echte Infrastruktur
  (nachgelagert mit dem PO)".
- In der CI ist AC 1/AC 4 damit **nicht** mit dem produktiven Kommando
  beweisbar. Der Testplan trennt das deshalb in drei Stufen (§8.2a) und
  behauptet an keiner Stelle mehr, als die jeweilige Stufe traegt.
- **Nuetzlicher Nebeneffekt:** die beiden Fehlerbilder („`env`-Key fehlt" vs.
  „Weaviate nicht erreichbar") sind an der `detail`-Zeile unterscheidbar. Genau
  das macht einen **offline** lauffaehigen Beweis der `env`-Vollstaendigkeit
  moeglich (§8.2a T1).

---

## 2. Ein einmal gerenderter, digest-gebundener Spec (Scope 1, AC 5)

### 2.1 Datenfluss (eine Ableitung, eine Probe, zwei Projektionen)

```
ProjectConfig (typisiert, aus der CP-5-Mapping)
        │
        ├── project_id  ──> resolve_authoritative_project_id(...)      [SSOT AG3-174]
        ├── pipeline.vectordb.weaviate_{http,grpc}_endpoint
        ├── concepts_dir       ──> AGENTKIT_CONCEPTS_DIR   (absolut)
        └── wiki_stories_dir   ──> AGENTKIT_STORIES_DIR    (absolut)
        │
        ▼
   env-Mapping (genau REGISTERED_ENV_KEYS = 5 Keys, nichts sonst)
        │
        ▼
RuntimeBinding.from_env(env, command=…, args=…, cwd=str(project_root))   [einmal]
        │  validiert: alle Keys da/nicht-leer, kein localhost-Default, cwd nicht leer
        ▼
   McpServerSpec                                    [frozen, AG3-174-SSOT]
        │  desired_server_from_spec()  (Wertgleichheits-Assertion, §2.3)
        ▼
   DesiredMcpServer (+ are-mcp analog)              [frozen, BC-neutral]
        │
        ├──> render .mcp.json-Text            ┐
        └──> render .codex/config.toml-Text    │  BEIDE vor jedem Write
        │                                      ┘
        ▼
   RenderedRegistration(servers, mcp_json_text, codex_toml_text,
                        before_image, digest)        [frozen]
        │
        ▼  check_mcp_conformance(server.to_server_command())  je Server
   ProbedRegistration(rendered, digest_at_probe, tool_names)  [frozen]
        │
        ▼  verify_binding()  → Digest neu berechnen und vergleichen
   write .mcp.json   →   write .codex/config.toml
```

### 2.2 Neue/geaenderte Module

| Modul | Rolle |
|---|---|
| **neu** `src/agentkit/backend/core_types/mcp_server_registration.py` | BC-neutraler Vertrag: `DesiredMcpServer`, `AK3_MCP_SERVER_NAMES`, `canonical_registration_payload()`, `registration_digest()`, `McpServerRegistrationError`. Importiert **nichts** aus `installer/` oder `harness_client/`. |
| **neu** `src/agentkit/backend/installer/mcp_registration.py` | Installer-Seite: `desired_server_from_spec()`, `RegistrationBeforeImage`, `RenderedRegistration`, `ProbedRegistration`, `probe_registration()`. Darf `vectordb.runtime_binding` und `installer.mcp_conformance` importieren. |
| **neu** `src/agentkit/harness_client/harness_adapters/codex/config_toml.py` | FK-76-Format: strikter Loader, `classify_ownership()`, `render_codex_config()`, `CodexConfigError`/`CodexConfigRejection`. Importiert nur `core_types.mcp_server_registration` + `tomllib`/`tomlkit`. Kein Dateisystem. |
| **geaendert** `installer/codex_settings.py` | wird duenner Installer-Rand: Pfad + Containment + atomarer Write + Idempotenz-Entscheidung + `created_files`; delegiert Rendering/Klassifikation an den Adapter. |
| **geaendert** `installer/bootstrap_checkpoints/cp10.py` | typisierte Desired-Menge, eine Probe, Zwei-Dateien-Koordination. |
| **geaendert** `installer/lifecycle/detach.py` | `_remove_ak3_codex_config` nutzt `classify_ownership` statt Byte-Vergleich. Sonst **nichts**. |
| **geaendert** `config/models.py`, `installer/runner.py`, `checkpoint_engine/reasons.py` | Endpunkt-Felder, Scaffold-Stanza, `registration_incomplete`/`configuration_invalid`. |

Warum der Vertrag in `core_types/` liegt und nicht im Installer: FK-76 §76.9 ist
normativ zur Importrichtung — `installation-and-bootstrap` ruft
`harness_integration` auf, nicht umgekehrt. Ein `harness_adapters`-Modul, das
`backend.installer` importiert, waere ein Richtungsverstoss.
`backend/core_types/` ist im Repo genau dafuer etabliert („BC-neutral SINGLE
SOURCE OF TRUTH", so bezeichnet in `installer/paths.py:32-37` fuer
`plane_artifact_names`). ARCH-23 („austauschbare Libraries hinter Abstraktion
wrappen") verlangt zusaetzlich, dass `tomlkit` **nur** in `config_toml.py`
auftaucht — genau ein Importpunkt.

### 2.3 `McpServerSpec` → `DesiredMcpServer`: die Bruecke, die heute verliert

```python
@dataclass(frozen=True, slots=True)
class DesiredMcpServer:
    name: str
    command: str
    args: tuple[str, ...]
    cwd: str
    env: tuple[tuple[str, str], ...]
    required: bool = True
```

`__post_init__` validiert strikt (nicht-leerer Name aus `[A-Za-z0-9._-]+`,
nicht-leeres `command`, `args` nur `str`, nicht-leeres `cwd`, `env`-Keys
eindeutig und nicht leer, alle `env`-Werte `str`, `required` echtes `bool`).
`to_mcp_json_entry()` liefert `{"type": "stdio", "command", "args", "cwd",
"env"}`; `to_server_command()` liefert
`McpServerCommand(command=…, args=…, env=…, cwd=…)` — **alle vier Felder**, das
ist die verlustfreie Bruecke, die `server_command_from_mcp_entry` (check.py:227)
strukturell nicht liefern kann.

`desired_server_from_spec(name, spec)` ist die einzige Stelle, an der aus dem
AG3-174-SSOT ein Registrierungsobjekt entsteht, und sie enthaelt die
**Wertgleichheits-Assertion**:

```
spec.env_dict()["PROJECT_ID"]             == spec.project_id
spec.env_dict()["WEAVIATE_HTTP_ENDPOINT"] == spec.weaviate_http_endpoint
spec.env_dict()["WEAVIATE_GRPC_ENDPOINT"] == spec.weaviate_grpc_endpoint
set(spec.env_dict()) == set(REGISTERED_ENV_KEYS)          # 5 Keys, §3.1
```

Abweichung → `McpServerRegistrationError`. Damit ist ausgeschlossen, dass die
Projektion andere Werte traegt als der Spec behauptet — das ist die
„Wertgleichheit" aus AC 5, mechanisch und nicht per Kommentar.

**Korrektur gegenueber Revision 1:** dort stand
`set(env) == set(REQUIRED_ENV_KEYS)`. Das war falsch und haette den Defekt aus
§1.6(a) einbetoniert: `REQUIRED_ENV_KEYS` sind die drei Keys, die
`RuntimeBinding` **validiert**, nicht die vier, die der Prozess **braucht**. Die
Registrierung schuldet dem Prozess, nicht dem Validator.

`cwd` fuer den Codex-Eintrag und den `.mcp.json`-Eintrag ist **derselbe**
`str(context.project_root)` — genau der Wert, mit dem auch geprobt wird. Der
heutige Divergenzpfad (cp10.py:360-365) entfaellt vollstaendig.

Dass `.mcp.json` ein `cwd` toleriert, ist nicht Theorie: die AK3-eigene
`.mcp.json` im Repo-Root nutzt es produktiv (`"cwd": "T:/codebase/claude-agentkit3"`).

### 2.4 Was „digest-/wertgleich gebunden" mechanisch heisst

Beides, in dieser Kombination:

1. **Identitaet eines gefrorenen Objekts.** `DesiredMcpServer`,
   `RenderedRegistration`, `ProbedRegistration` sind
   `@dataclass(frozen=True, slots=True)`; alle Sequenzen sind `tuple`. Eine
   **in-place**-Mutation ist unmoeglich (`FrozenInstanceError`), nicht nur
   verboten.
2. **Hash ueber eine kanonische Serialisierung.**

```python
def canonical_registration_payload(
    servers: Sequence[DesiredMcpServer],
    *, mcp_json_text: str, codex_toml_text: str,
) -> str:
    payload = {
        "servers": [
            {"name": s.name, "command": s.command, "args": list(s.args),
             "cwd": s.cwd, "env": sorted(s.env), "required": s.required}
            for s in sorted(servers, key=lambda s: s.name)
        ],
        "mcp_json_text": mcp_json_text,
        "codex_toml_text": codex_toml_text,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)

def registration_digest(...) -> str:      # sha256 hex ueber utf-8 des Payloads
```

Der Digest umfasst **sowohl die Spec-Werte als auch die beiden gerenderten
Texte**. Das schliesst die Luecke „geprobt wurde Objekt X, gerendert wurde
Objekt Y": der Digest kann nur stimmen, wenn Texte und Specs zueinander passen.

3. **Der Write akzeptiert nur ein `ProbedRegistration`.** Es gibt keinen
   Codepfad von einem rohen `McpServerSpec` oder `DesiredMcpServer` zu einem
   `write`. `ProbedRegistration.verify_binding()` berechnet den Digest neu und
   wirft `McpServerRegistrationError` bei Abweichung — **vor** dem ersten Write.

Damit ist AC 5 erfuellbar: ein Test, der nach der Probe ein Feld aendert, muss
`dataclasses.replace(...)` benutzen (in-place geht nicht) und ein neues
`ProbedRegistration` mit dem alten Digest zusammensetzen → `verify_binding()`
schlaegt an → CP 10 `FAILED`, null Writes.

**Ehrlicher Restbefund:** Python kennt keine Capability-Grenze. Ein Test, der
nicht nur das Feld aendert, sondern **auch** den Digest neu berechnet, faelscht
kein Feld mehr, sondern eine Probe-Quittung — dagegen schuetzt kein
Sprachmittel, und der richtige Umgang damit ist, dann eben neu zu proben. Was
der Mechanismus garantiert: (a) in-place-Mutation unmoeglich, (b) jede
Substitution erkannt, (c) kein Write-Pfad ohne Quittung. Was er **nicht**
garantiert: Schutz gegen bewusste Nachbildung der Quittung. Das wird im Bericht
so stehen und nicht als Atomizitaet der Bindung verkauft.

---

## 3. Konfigurationsquelle fuer `env` (Befund C)

### 3.1 Woher die Werte kommen — fuenf Keys, nicht drei

| `env`-Key | Quelle (typisiert) | Begruendung |
|---|---|---|
| `PROJECT_ID` | `resolve_authoritative_project_id()` (`project_binding.py:104-152`) | SSOT-Resolver aus AG3-174, wiederverwendet. Kein zweiter Resolver. |
| `WEAVIATE_HTTP_ENDPOINT` | `ProjectConfig.pipeline.vectordb.weaviate_http_endpoint` | Erweiterung des bestehenden Fachmodells, wie im Briefing zugelassen (§3.2). |
| `WEAVIATE_GRPC_ENDPOINT` | `ProjectConfig.pipeline.vectordb.weaviate_grpc_endpoint` | dito. |
| `AGENTKIT_CONCEPTS_DIR` | `ProjectConfig.concepts_dir`, absolut gemacht gegen `project_root` | **Pflicht** (§1.6a). Existiert bereits auf dem CP-5-Pfad — **kein neues Config-Feld noetig**. |
| `AGENTKIT_STORIES_DIR` | `ProjectConfig.wiki_stories_dir`, absolut gemacht gegen `project_root` | technisch optional, **wird trotzdem explizit gerendert** (Begruendung unten). |

```python
REGISTERED_ENV_KEYS: tuple[str, ...] = (
    "PROJECT_ID", "WEAVIATE_HTTP_ENDPOINT", "WEAVIATE_GRPC_ENDPOINT",
    "AGENTKIT_CONCEPTS_DIR", "AGENTKIT_STORIES_DIR",
)
```

Kein `GH_REPO` (gemessen: der String kommt in `src/agentkit/` **nirgends** vor),
kein `WEAVIATE_HOST`/`_PORT` (siehe §9 Q-4 zum vollstaendigen Konzept-Delta).

**Die beiden Verzeichniswerte sind schon da.** Gemessen an der
CP-5-Mapping (§1.3): die Top-Level-Keys enthalten `concepts_dir` und
`wiki_stories_dir`; `_build_project_yaml` schreibt sie aus `paths.CONCEPTS_DIR`
bzw. `paths.STORIES_DIR`. `ProjectConfig` traegt sie typisiert
(`models.py:871-872`, Defaults `"concepts"` / `"stories"`) und validiert sie mit
`_validate_project_relative_dir` (`models.py:50-70`: nicht leer, nicht absolut,
nicht laufwerksverankert, kein `..`-Segment). FK-13 §13.9 („das konfigurierte
`concepts_dir` ist massgeblich") ist damit erfuellt, ohne eine zweite
Konfigurationsquelle — im Unterschied zu den Endpunkten braucht es hier
**keine** Modell- oder Scaffold-Erweiterung.

**Warum `AGENTKIT_STORIES_DIR` explizit gerendert wird, obwohl es einen Default
hat** (die Frage war mir zur eigenen Entscheidung gestellt; ich komme auf
dasselbe Ergebnis wie die Neigung des Orchestrators, aber der tragende Grund ist
ein anderer):

1. **`cwd` darf keine Konfigurationsquelle sein.** Der Default ist
   `Path("stories").resolve()` (`engine.py:1290`) und loest gegen die
   **Prozess-`cwd`** auf. `runtime_binding`s eigener Docstring (Zeile 6-7) und D2
   legen fest: „`cwd` is the working / containment boundary, **NOT** a second
   configuration source". Sich auf den Default zu verlassen wuerde genau diese
   Regel brechen — ein Konfigurationswert entstuende aus der Arbeitsverzeichnis-
   Bindung.
2. **`wiki_stories_dir` ist konfigurierbar.** Ein Projekt, das es abweichend
   setzt, bekaeme mit dem Default still den falschen Korpus-Root. Das ist
   dieselbe Fehlerklasse wie N20 (der `concept`-Default zeigte auf AK3s eigenen
   Korpus) — nur leiser, weil es nicht fail-closed abbricht, sondern **falsche
   Daten** indiziert. Ein stiller falscher Korpus ist schlimmer als ein Abbruch.
3. AC 2 verlangt feldweise Wertgleichheit beider Formate „env mit `PROJECT_ID`
   und Endpunktwerten". Eine implizite, nirgends geschriebene Variable ist nicht
   vergleichbar.

**Absolut statt relativ**, aus demselben Grund 1: absolute Pfade haengen nicht
davon ab, dass der Harness die `cwd` des Eintrags tatsaechlich setzt.
Containment ist doppelt gesichert — `_validate_project_relative_dir` verbietet
schon Absolutheit und `..` in der Config, und der Renderer prueft zusaetzlich,
dass der aufgeloeste Pfad unter `project_root` liegt (dieselbe Idee wie
`assert_project_local_codex_config`, §6.3).

**Grenze, bewusst gezogen:** CP 10 prueft Shape und Containment der beiden
Verzeichnisse, **nicht ihre Existenz oder ihren Inhalt**. Korpus-Preflight und
Erstindizierung gehoeren AG3-176 (dessen Scope 1/3).

### 3.2 Vollstaendige Endpunkte, nicht Host+Ports

`VectorDbConfig` bekommt zwei Felder:

```python
weaviate_http_endpoint: str | None = None    # z.B. "http://weaviate.internal:9903"
weaviate_grpc_endpoint: str | None = None    # z.B. "weaviate.internal:50051"
```

Validierung im Modell (Pydantic v2 `field_validator`, `extra="forbid"`,
`frozen=True` bleiben):

- `None` erlaubt (das Feld ist optional fuer Projekte ohne VektorDB).
- Nicht-`None`: nach `strip()` nicht leer; HTTP muss mit `http://` oder
  `https://` beginnen und einen Host haben; gRPC muss der Form `host:port` mit
  Port in `1..65535` entsprechen. Verstoss → `ValueError` →
  `ConfigError` durch `load_project_config`.
- **Bewusst nicht im Modell:** die localhost-Default-Ablehnung. Die einzige
  Autoritaet dafuer bleibt `runtime_binding._reject_localhost` (Zeile 55-67),
  aufgerufen ueber `RuntimeBinding.from_env`. Eine zweite Sperrliste waere eine
  zweite Wahrheit.

`host` / `port` bleiben **unveraendert** — sie haben echte Konsumenten
(`story_creation/runtime_factory.py:267-274`,
`wait_for_weaviate.py:124-125`). Additive Aenderung, kein Bruch.

Warum vollstaendige Endpunkte und nicht `host`+`http_port`+`grpc_port`:
`RuntimeBinding` (AG3-174) und `ProjectBinding` (`project_binding.py:43-44`,
`51-52`) modellieren beide vollstaendige Endpunkt-**Strings**; `_reject_localhost`
prueft den ganzen String. Aus Host+Port zu komponieren wuerde das Schema
(`http://` vs `https://`) erfinden — genau das, was D2 verbietet. Und es wuerde
eine dritte Repraesentation derselben Sache einfuehren.

### 3.3 Wie die Werte in `project.yaml` kommen

`InstallConfig` (`runner.py:128-234`) bekommt zwei Felder analog zu den
ARE-Feldern (`are_mcp_server` usw., `runner.py:224-227`):

```python
vectordb_http_endpoint: str | None = None
vectordb_grpc_endpoint: str | None = None
```

`_build_project_yaml` schreibt `pipeline["vectordb"]` **nur** wenn
`config.features_vectordb` **und** beide Werte gesetzt sind — kein Teil-Stanza,
kein Default. Fehlt einer, gibt es keine Stanza, und CP 10 scheitert benannt
(§3.4). Das ist die Konsequenz aus §1.3: eine handgepflegte Stanza wuerde von
CP 5 geloescht, also ist `InstallConfig` → CP 5 der einzige stabile Weg.

### 3.4 Wie die Konfiguration CP 10 erreicht (`CheckpointContext`)

CP 10 bekommt nur `CheckpointContext`
(`checkpoint_engine/context.py:82-108`). Der etablierte Weg fuer
CP-5-produzierte Daten ist `context.run_state.project_yaml` — genau so liest
CP 10 heute die ARE-Stanza (`cp10.py:166-170`). CP 5 setzt das Feld in **allen**
Modi (`cp01_to_06.py:211-212`, vor der Modus-Verzweigung).

Aber: statt roh im Dict zu graben, wird die Mapping **einmal typisiert**:

```python
raw = context.run_state.project_yaml
if raw is None: -> FAILED / configuration_invalid  (CP 5 nicht gelaufen)
project_config = ProjectConfig.model_validate(raw)        # strikt, extra=forbid
vectordb = project_config.pipeline.vectordb
if vectordb is None or not vectordb.weaviate_http_endpoint \
        or not vectordb.weaviate_grpc_endpoint:
    -> FAILED / configuration_invalid, NULL Writes
project_id = resolve_authoritative_project_id(
    project_root=str(context.project_root), supplied=None, env=os.environ,
    config_project_id=project_config.project_prefix,      # siehe unten
)
```

Gemessen: `ProjectConfig.model_validate(_build_project_yaml(cfg))` gelingt, und
`project_prefix` ist vom Modell abgeleitet („DEMO" bei `project_key="demo"`).
Ein typisierter Zugriff ist damit belegt moeglich — keine zweite Ladepfad-Wahrheit,
keine Env-Direktzugriffe auf Endpunkte im Checkpoint.

**Eine minimale, additive Erweiterung des SSOT-Resolvers** ist dafuer noetig und
wird als solche ausgewiesen: `resolve_authoritative_project_id` liest die
Autoritaet heute **von der Platte** (`_project_id_from_config`,
`project_binding.py:155-197`). In DRY_RUN/VERIFY hat CP 5 die `project.yaml`
aber noch nicht geschrieben → die Autoritaet waere leer und der Resolver wuerde
werfen, obwohl der Installer die Konfiguration in der Hand haelt, die er gerade
schreiben wird. Deshalb: neues Keyword `config_project_id: str | None = None`
mit der Semantik „wenn gesetzt, ersetzt dieser Wert den Plattenblick als
Konfigurations-Autoritaet; die Divergenzpruefung gegen `PROJECT_ID` aus der Env
bleibt unveraendert". Bestehende Aufrufer bleiben unberuehrt (Default `None`).
Das ist **Wiederverwendung mit einer Naht**, nicht ein zweiter Resolver — es
gibt weiterhin genau eine Implementierung der Regel
„project_prefix > PROJECT_ID-Env, Divergenz = Fehler". Ausgewiesen als **§9 Q-5**.

### 3.5 Der benannte Fehlerfall

Neue Konstante in `checkpoint_engine/reasons.py`:

```python
#: CP 10: the consumed project configuration is absent/invalid (PO decision D4
#: vocabulary). Distinct from mcp_configuration_invalid, which is about an
#: existing harness config FILE.
REASON_CONFIGURATION_INVALID: Final = "configuration_invalid"
```

Der Token ist **nicht erfunden**: PO-Entscheidung D4
(`AG3-174/po-decisions.md:88-90`) ratifiziert genau `configuration_invalid`
fuer „Strings, Zahlen, Null und doppelte `features`-/`vectordb`-/Endpoint-Keys",
und AG3-176 AC 2 baut darauf auf. AG3-175 fuehrt die Konstante ein und benutzt
sie fuer die fehlende/ungueltige Endpunkt-Konfiguration; AG3-176 verschaerft
darauf aufbauend die YAML-Ladegrenze (dessen Story nennt `models.py:531-549`
ausdruecklich als eigene Baustelle — die beiden Schnitte kollidieren nicht: 175
fuehrt die Felder ein, 176 verschaerft die Ladegrenze).

Konsequenz: **kein synthetisierter Default, keine Wirkung, kein Write.** Der
Checkpoint gibt `FAILED` + `reason=configuration_invalid` in **allen** Modi
zurueck, wenn die Endpunkte fehlen — auch in DRY_RUN, weil ein Plan, der die zu
schreibenden Werte nicht kennt, kein Plan ist, sondern eine Behauptung.

---

## 4. Der eine Codex-TOML-Writer (Befund B)

### 4.1 Heimat und Schnittstelle

`src/agentkit/harness_client/harness_adapters/codex/config_toml.py` — reine
Text-zu-Text-Fachlichkeit, kein Dateisystem (das bleibt Installer-Rand). FK-76
ist normativer Owner des Formats (§76.5), FK-50 CP 10 des Ob/Wann.

```python
AK3_CONFIG_HEADER_COMMENT = "# AgentKit-managed Codex hook configuration."
AK3_OWNED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"hooks", "mcp_servers"})
AK3_OWNED_HOOK_KEYS: frozenset[str] = frozenset({"pre_tool_use"})
AK3_OWNED_SERVER_FIELDS: frozenset[str] = frozenset(
    {"command", "args", "cwd", "env", "required"})

class CodexConfigRejection(StrEnum): ...        # §6, maschinenlesbar
class CodexConfigError(ValueError):
    code: CodexConfigRejection                  # benannter Fehler
class CodexConfigOwnership(StrEnum):
    AK3_ONLY = "ak3_only"; MIXED = "mixed"
    FOREIGN = "foreign";   UNREADABLE = "unreadable"

def load_codex_config(raw: bytes) -> dict[str, object]
def classify_ownership(raw: bytes | None, *, hook_command: str) -> CodexConfigOwnership
def render_codex_config(raw: bytes | None, *, hook_command: str,
                        servers: Sequence[DesiredMcpServer]) -> str
```

`hook_command` wird durchgereicht statt im Adapter hart verdrahtet, damit es
weiterhin **genau eine** Definition des Wrapper-Namens gibt.
`CODEX_HOOK_COMMAND` bleibt dort, wo es heute ist (`codex_settings.py:19`) und
wird hineingegeben — kein viertes Literal (heute existieren drei:
`codex_settings.py:19`, `detach.py:44-45`, `settings_writer.py:457`; die
Konsolidierung **dieser** Duplikate ist nicht Scope, siehe §9 Q-3).

### 4.2 Wie der Hook-Eintrag durch denselben Writer entsteht

`build_codex_config_toml()` behaelt seinen Namen (Importeure:
`detach.py:29`, `tests/integration/installer/test_detach.py:21`,
`tests/unit/installer/test_codex_settings.py:5-9`) und wird intern zu

```python
def build_codex_config_toml() -> str:
    return render_codex_config(None, hook_command=CODEX_HOOK_COMMAND, servers=())
```

`write_codex_settings(project_root)` wird zu:

1. `config_path = assert_project_local_codex_config(project_root)` (§6.3).
2. `raw = config_path.read_bytes() if config_path.is_file() else None`.
3. `text = render_codex_config(raw, hook_command=CODEX_HOOK_COMMAND, servers=())`
   — servers leer, weil CP 8 nichts ueber MCP weiss.
4. `if raw is not None and raw == text.encode("utf-8"): return None` (Idempotenz).
5. sonst atomar schreiben, Relativpfad zurueckgeben.

Damit ueberlebt eine in CP 10 gemergte MCP-Tabelle den naechsten
Installationslauf: `render_codex_config` mit `servers=()` mergt den
Hook-Eintrag ein und **entfernt nichts** (UPSERT-Semantik, §4.4). Genau das ist
der Nachweis, den das Briefing verlangt (zwei aufeinanderfolgende Laeufe).

**Der dritte Writer muss dafuer ebenfalls weg** (§1.2, korrigierter Befund).
`_deploy_static_resource_files` (`runner.py:543-558`) kopiert
`bundles/target_project/.codex/config.toml` in CP 8 ins Zielprojekt — und zwar
in `runner.py:1148`, also **vor** `write_codex_settings` in Zeile 1186. Solange
die Bundle-Datei existiert, wuerde sie bei jedem Folgelauf die MCP-Tabelle
ueberschreiben (`_copy_file_if_changed` → `copy_file`, bedingungslos), und der
danach laufende semantische Writer wuerde die Tabelle brav wieder anlegen: die
Datei flatterte bei jedem Lauf. Das ist derselbe Zerstoerungsmechanismus wie
Befund B(1) auf einem zweiten Pfad.

**Massnahme:** `src/agentkit/bundles/target_project/.codex/config.toml` wird
**geloescht**. Damit gibt es genau einen Writer, statt einen Sonderfall in
`_deploy_static_resource_files` einzubauen (FIX-THE-MODEL statt Workaround, und
SSOT: der Inhalt existiert dann nur noch einmal, im Adapter).

Belege, dass das gefahrlos ist:

- Das Verzeichnis `.codex/` entsteht unabhaengig davon: `_deploy_directory_structure`
  (`project_structure.py:95-111`) spiegelt Verzeichnisse (`if item.is_dir()`),
  und `.codex/skills/` bleibt im Bundle.
- `tests/contract/scaffold_snapshots/test_install_scaffold.py:127` verlangt
  `(tmp_path/".codex"/"config.toml").is_file()` nach dem Install — bleibt gruen,
  weil `write_codex_settings` (CP 8, Zeile 1186) die Datei erzeugt. Der Erzeuger
  wechselt von der Kopie zum Writer, das Ergebnis bleibt.
- Kein Test pinnt die Bundle-Datei (gemessen: kein Treffer fuer
  `target_project.*codex` in `tests/`).
- Gemessen: Bundle-Bytes und `build_codex_config_toml()` sind heute
  **byte-identisch** — die Loeschung aendert das Installationsergebnis also nicht,
  sie entfernt nur die zweite Quelle.

Damit ist die Schreiberliste danach vollstaendig: **ein** Writer (CP 8 Hook,
CP 10 MCP-Tabelle, dieselbe Renderfunktion), **ein** Leser fuer die
Detach-Klassifikation, **keine** Kopie.

#### 4.2.1 Ein vorbestehender Defekt, der dabei mitgeschlossen wird

Die Bundle-Kopie ist **nicht nur** ein zukuenftiges Risiko fuer die MCP-Tabelle.
Sie ist **heute schon** ein Datenverlustpfad, unabhaengig von AG3-175. Gemessen
am echten Produktionspfad (`_deploy_static_resource_files` auf ein Zielprojekt
mit nutzererweiterter Datei):

```
BEFORE (user-extended):        AFTER the static resource deploy:
# AgentKit-managed …           # AgentKit-managed …
[hooks.pre_tool_use]           [hooks.pre_tool_use]
command = "agentkit-hook-codex"command = "agentkit-hook-codex"

# user note: my own Codex
# settings, please keep
[user.custom]
alpha = 1

USER CONTENT SURVIVED: False
```

Ein Zielprojekt, dessen Nutzer `.codex/config.toml` um eigene
Codex-Konfiguration erweitert hat, **verliert sie beim naechsten
Installationslauf** — geloescht in CP 8, bevor `write_codex_settings` die Datei
ueberhaupt ansieht. Gleichzeitig geht `detach.py:340-362` ausdruecklich den
Umweg, genau diesen Fremdinhalt zu **erhalten** und als
`preserved_foreign_files` zu melden (FK-10 §10.2.9, „preserve project code").

**Die Installation zerstoert also, was das Detach sorgfaeltig schuetzt.** Das ist
ein vorbestehender Widerspruch im Ist-Zustand, kein Nebeneffekt dieser Story. Er
wird hier **mitgeschlossen**, weil die Loeschung der Bundle-Datei ohnehin
notwendig ist — aber er ist ausdruecklich als **vorbestehender Defekt** zu
berichten, nicht als Aufraeumarbeit.

**Zweiter Loeschpfad, wichtig fuer die Testbarkeit:** Die Bundle-Loeschung allein
behebt den Nutzerdatenverlust **nicht**. `write_codex_settings` vergleicht heute
byteweise gegen einen Fixstring (`codex_settings.py:41-43`) und schreibt bei
Abweichung die Datei neu — eine nutzererweiterte Datei weicht ab und wird
ebenfalls ueberschrieben. Der Verlust hat also **zwei** Ursachen, und der
vollstaendige Fix braucht **beides**: Bundle-Loeschung **und** semantischen
Writer.

Konsequenz fuer den Testplan: der ehrliche Beweis
`test_user_extended_codex_config_survives_two_install_runs` kann erst mit
**Schritt 3 + 5** gruen werden, nicht mit der Bundle-Loeschung allein. Er wird
dort geschrieben (§8.2 B-Nachweis-Zeilen) und ist die Revert-Probe fuer beide
Ursachen gleichzeitig: dreht man die Bundle-Loeschung **oder** den semantischen
Writer zurueck, wird er rot. Ein frueherer Test, der den heutigen kaputten Stand
festschreibt, waere wertlos und muesste spaeter invertiert werden.

Determinismus des Writes: der Adapter liefert Text mit `\n`; geschrieben wird
mit `atomic_write_text(path, text, newline="")` (`backend/utils/io.py:20-54`),
damit die Bytes auf der Platte exakt `text.encode("utf-8")` sind. Ohne
`newline=""` uebersetzt Windows zu `\r\n`, und dann ist der Byte-Vergleich in
Schritt 4 und die Idempotenzaussage von der Plattform abhaengig. Nebeneffekt:
auf einem Windows-Bestandsprojekt wird die Datei **einmal** neu geschrieben
(CRLF → LF). Das ist ein sichtbarer, gewollter Einmaleffekt und wird im Bericht
genannt.

### 4.3 Das semantische AK3-Ownership-Praedikat

Ersetzt den Byte-Vergleich in `write_codex_settings` (Idempotenz) und
`_remove_ak3_codex_config` (Detach-Klassifikation). Praezise, in dieser
Reihenfolge:

Sei `raw` der Dateiinhalt als Bytes und
`canonical(parsed) := render_codex_config(None, hook_command=…, servers=<die in
`parsed` gefundenen AK3-Servertabellen>)`.

`classify_ownership(raw)`:

1. `raw is None` → **FOREIGN** (nichts da).
2. `raw` nicht als UTF-8 dekodierbar **oder** `tomllib` wirft
   `TOMLDecodeError` → **UNREADABLE**.
3. `parsed = tomllib.loads(...)`. Berechne
   - `foreign_top   = set(parsed) - AK3_OWNED_TOP_LEVEL_KEYS`
   - `foreign_hooks = set(parsed.get("hooks", {})) - AK3_OWNED_HOOK_KEYS`
     (falls `hooks` keine Tabelle: → **MIXED**)
   - `foreign_servers = set(parsed.get("mcp_servers", {})) - AK3_MCP_SERVER_NAMES`
     (falls keine Tabelle: → **MIXED**)
   - `hook_is_ak3 = parsed.get("hooks", {}).get("pre_tool_use") == {"command": hook_command}`
4. Wenn `foreign_top or foreign_hooks or foreign_servers or not hook_is_ak3`:
   → **MIXED** (bzw. **FOREIGN**, wenn ueberhaupt kein AK3-Inhalt vorhanden ist).
5. Sonst: `raw == canonical(parsed).encode("utf-8")` ?
   - **ja** → **AK3_ONLY**
   - **nein** → **MIXED**

**Schritt 5 ist der Punkt, der die Preservation-Zusicherung nicht schwaecht.**
Ohne ihn haette ein rein wertbasiertes Praedikat eine Regression: eine Datei,
in die ein Nutzer nur einen **Kommentar** geschrieben hat, enthaelt
wertmaessig ausschliesslich AK3-Keys — Detach wuerde sie loeschen, obwohl der
heutige Byte-Vergleich sie erhaelt. Schritt 5 vergleicht Bytes, aber gegen eine
**abgeleitete** kanonische Rendition statt gegen einen Fixstring. Damit gilt:

| Dateiinhalt | heute | mit dem neuen Praedikat |
|---|---|---|
| AK3-Hook allein | entfernt | **AK3_ONLY → entfernt** (unveraendert) |
| AK3-Hook + AK3-MCP-Tabelle | *erhalten* (Bug) | **AK3_ONLY → entfernt** (Fix) |
| AK3-Hook + fremde Tabelle | erhalten | **MIXED → erhalten** (unveraendert) |
| AK3-Hook + fremder MCP-Server | erhalten | **MIXED → erhalten** (unveraendert) |
| AK3-Hook + zusaetzlicher Nutzerkommentar | erhalten | **MIXED → erhalten** (unveraendert) |
| unparsebar | erhalten | **UNREADABLE → erhalten** (unveraendert) |

`_remove_ak3_codex_config` aendert damit **nur** sein Praedikat:
`classify_ownership(raw) is AK3_ONLY` statt `current == build_codex_config_toml()`.
Kein neues Verhalten, keine neue Faehigkeit; `preserved_foreign_files` wird in
allen Nicht-AK3_ONLY-Faellen weiterhin gefuellt und ueber
`cli/lifecycle.py:269` gemeldet.

`AK3_MCP_SERVER_NAMES = frozenset({"story-knowledge-base", "are-mcp"})` lebt in
`core_types/mcp_server_registration.py` und ersetzt die heute privaten Literale
`cp10.py:62` / `cp10.py:64` (die dann von dort importiert werden) — ein Literal,
nicht drei. Bewusst **feature-flag-unabhaengig**: „welche Namen gehoeren AK3"
ist eine Ownership-Aussage, keine Laufzeitfrage. Sonst wuerde Detach eine
frueher von AK3 geschriebene `are-mcp`-Tabelle als fremd einstufen und liegen
lassen.

### 4.4 Merge-Semantik von `render_codex_config`

```
ownership = classify_ownership(raw)
if ownership is UNREADABLE:  raise CodexConfigError(...)     # kein Write
if raw is None or ownership is AK3_ONLY:
    return render_canonical(hook_command, union(found_ak3_servers, servers))
validate_shape_and_name_collisions(parsed, servers)          # §6
return merge_with_tomlkit(raw, hook_command, servers)        # Fremdinhalt bleibt
```

Zwei Eigenschaften, die daraus folgen und getestet werden:

- **UPSERT, nie entfernen.** Die kanonische Rendition rendert die *Vereinigung*
  der bereits vorhandenen AK3-Servertabellen und der gewuenschten (gewuenschte
  gewinnen feldweise). Spiegelt `_merge_mcp_servers` (`cp10.py:173-202`), das
  ebenfalls nie entfernt.
- **Kanonisierungs-Invariante.** Eine Datei, die AK3 selbst erzeugt hat
  (CP 8 Hook, danach CP 10 MCP), ist byte-identisch zur kanonischen Rendition
  aus dem Nichts. Das ist per Konstruktion so, weil AK3_ONLY-Dateien
  **neu gerendert** und nicht inkrementell gepatcht werden — sonst haenge die
  Detach-Klassifikation an tomlkit-Layoutdetails (Leerzeilen), und eine von AK3
  geschriebene Datei koennte als MIXED liegenbleiben. Eigener Test (§8).

---

## 5. Werkzeugentscheidung TOML (Befund D) — entscheidungsreifer Antrag

Es gibt heute keinen TOML-Writer im Projekt, `tomllib` liest nur (gemessen,
§1.4). Ein Writer ist unvermeidbar.

### 5.1 Gemessene Fakten zu den Kandidaten

Beide Wheels wurden mit `pip download --no-deps` geholt (kein Install) und ihre
`METADATA` gelesen:

| | `tomli-w` 1.2.0 | `tomlkit` 0.15.1 |
|---|---|---|
| Lizenz | MIT (`Classifier: License :: OSI Approved :: MIT License`) | MIT (`License: MIT`, `License-File: LICENSE`) |
| `Requires-Python` | `>=3.9` | `>=3.9` |
| `Requires-Dist` | **keine** (null transitive Runtime-Deps) | **keine** (null transitive Runtime-Deps) |
| Groesse / Module | 14.5 KB, 2 Module | 208 KB, 12 Module |
| Python-3.14-Classifier | nicht gelistet | gelistet |
| reiner Python-Code | ja | ja |

Verhalten gemessen (Zipimport der Wheels, Round-Trip an einer realistischen
Codex-Datei mit AK3-Kommentar, AK3-Hook-Tabelle und fremder `[user.custom]`):

- **`tomli-w`**: Ausgabe enthaelt Werte und Tabellen korrekt — und **keinen
  einzigen Kommentar**. Sowohl der AK3-Kommentar als auch `# user note: do not
  remove` sind verschwunden.
- **`tomlkit`**: `# foreign top comment`, `# trailing comment` und
  `# user note: do not remove` bleiben erhalten; fremde Top-Level-Tabelle und
  fremder `[mcp_servers.other-server]` bleiben unveraendert; die AK3-Tabelle
  wird angefuegt; `dumps(parse(x)) == x`; **zweiter identischer Merge liefert
  byte-identische Ausgabe** (`one == two → True`).

### 5.2 Die Kommentarfrage, ehrlich

AC 7 fordert Erhalt „semantisch wertgleich". Streng gelesen ist ein Kommentar
kein Wert, und `tomli-w` wuerde AC 7 buchstabengetreu erfuellen. Praktisch ist
das aber falsch:

1. `.codex/config.toml` ist **Fremdeigentum** im Zielprojekt. Ein Zielprojekt
   darf dort kommentierte Codex-Konfiguration pflegen. Ein
   kommentarvernichtender Writer ist aus Nutzersicht Datenverlust — dieselbe
   Klasse, die FK-10 §10.2.9 („preserve project code") und der ganze
   `preserved_foreign_files`-Mechanismus adressieren.
2. Es wuerde die eigene Zusicherung untergraben: mit `tomli-w` wuerde der
   naechste Installationslauf einen Nutzerkommentar loeschen, und **danach**
   wuerde das Ownership-Praedikat (§4.3 Schritt 5) die Datei als AK3_ONLY
   einstufen und Detach sie **entfernen**. Aus einem „nur ein Kommentar
   verloren" wird so ein „Datei geloescht". Diese Kette ist der eigentliche
   Grund gegen `tomli-w`, nicht Aesthetik.
3. Ein eigener Emitter ist die schlechteste Option: TOML-Escaping,
   Multiline-Strings, Datumstypen, Array-of-Tables — eigener Code auf einem
   fail-closed-Pfad mit hoher Testlast und ohne Kommentarerhalt.

### 5.3 Antrag D-1 (Entscheidung des PO erbeten)

1. **Was:** Runtime-Dependency `tomlkit==0.15.1` in `pyproject.toml`
   `[project].dependencies`. Lizenz MIT (im Wheel als `License-File: LICENSE`
   mitgeliefert). Keine transitiven Runtime-Dependencies (gemessen: kein
   `Requires-Dist`). Exakter Pin nach dem D5-Muster
   (`tokenizers==0.21.0`), plus ein Contract-Test im bestehenden Stil von
   `tests/contract/packaging/test_packaging_pins.py`.
2. **Warum das die richtige Wahl ist:** Es ist der einzige der drei Wege, der
   fremde Kommentare/Formatierung im Zielprojekt erhaelt, und damit der
   einzige, der die Loeschkette aus §5.2 Punkt 2 verhindert. Round-Trip-Stabilitaet
   und Merge-Idempotenz sind gemessen, nicht angenommen. Ohne es: entweder
   dokumentierter Datenverlust an Fremdeigentum (`tomli-w`) oder handgeschriebener
   TOML-Emitter auf einem fail-closed-Pfad (hoehere Fehler- und Testlast, gleiche
   Kommentarluecke).
3. **Nachteile, ehrlich:** 208 KB und 12 Module statt 14 KB und 2 Module; eine
   reichere API, die man disziplinieren muss (deshalb ARCH-23: genau ein
   Importpunkt, `codex/config_toml.py`); `tomlkit` ist ein Ein-Maintainer-Projekt
   im Poetry-Umfeld — bei Aufgabe muesste man auf `tomli-w` plus einen
   Kommentar-Kompromiss zurueckfallen (der Wechsel betraefe dann genau ein
   Modul). Kein Native-Code, kein Plattformrisiko, keine transitiven Deps.
   Weitere nennenswerte Nachteile sehe ich nicht.
4. **Frage:** Soll `tomlkit==0.15.1` als Runtime-Dependency aufgenommen und
   integriert werden?

`tomllib` (Stdlib) bleibt fuer alles **Lesen**/Validieren zustaendig — dessen
Striktheit (doppelte Keys/Tabellen) ist gemessen und wird nicht durch
`tomlkit`s toleranteren Parser ersetzt. Konkret: `load_codex_config` parst mit
`tomllib` (Gate), und nur der Merge-Pfad benutzt `tomlkit`. Damit gilt die
strengere der beiden Semantiken.

---

## 6. Striktheits-/Erhaltungs-Matrix (Scope 6, AC 7)

### 6.1 Ablehnungsfaelle

Alle Faelle werfen `CodexConfigError` mit einem `code` aus
`CodexConfigRejection` **bevor** irgendetwas geschrieben wird; CP 10 mappt das
auf `FAILED` + `reason=mcp_configuration_invalid`. Byte-Identitaet beider
Dateien folgt strukturell aus der Phasenordnung in §7 (lesen → pruefen →
rendern → proben → schreiben): jeder dieser Fehler entsteht in Phase 2/3, also
vor Write 1.

| # | Story-Scope-6-Fall | `code` | Erkennung | Beweis Byte-Identitaet |
|---|---|---|---|---|
| 1 | ungueltiges UTF-8 | `not_utf8` | `raw.decode("utf-8")` wirft `UnicodeDecodeError` (gemessen) | Fehler in Phase 2 |
| 2 | unparsebares TOML | `unparsable_toml` | `tomllib.TOMLDecodeError` | Phase 2 |
| 3 | doppelte Tabelle / doppelte Keys | `unparsable_toml` | `tomllib` nativ: `Cannot declare ('a',) twice` / `Cannot overwrite a value` (gemessen) | Phase 2 |
| 4 | `mcp_servers` nicht tabellenfoermig | `mcp_servers_not_table` | eigene Shape-Pruefung (tomllib akzeptiert `mcp_servers = 5`, gemessen) | Phase 2 |
| 5 | Servereintrag nicht tabellenfoermig | `server_entry_not_table` | eigene Pruefung (tomllib akzeptiert `foo = 5`, gemessen) | Phase 2 |
| 6 | `hooks` / `hooks.pre_tool_use` nicht tabellenfoermig | `hooks_not_table` | eigene Pruefung | Phase 2 |
| 7 | falscher Typ `command`/`args`/`cwd`/`env`/`required` | `server_field_type_invalid` | `command`: nicht-leerer `str`; `args`: `list[str]`; `cwd`: nicht-leerer `str`; `env`: Tabelle `str→str`; `required`: echtes `bool` (kein `1`) | Phase 2 |
| 8 | eigener Servername fremd belegt | `server_name_foreign_occupied` | §6.2 | Phase 2 |
| 9 | Symlink-/Junction-Ausbruch aus dem Project-Root | `path_escapes_project_root` | §6.3 | Phase 1 (vor jedem Lesen) |

**Ausdruecklich nicht erfunden:** „falsche **Root**-Shape" aus AC 7 hat in TOML
kein Gegenstueck — der Root eines TOML-Dokuments ist immer eine Tabelle
(gemessen: `tomllib.loads` liefert stets ein `dict`). Der aequivalente Fall ist
„ein AK3-eigener Top-Level-Key traegt keinen Tabellenwert" und wird von den
Faellen 4 und 6 abgedeckt. Das wird im Bericht so benannt statt einen
Pseudo-Testfall zu bauen.

### 6.2 „Fremd belegter eigener Servername" — die Definition

Die Story verlangt gleichzeitig „fremd belegter eigener Servername → ablehnen"
und „unbekannte harness-spezifische Felder → erhalten". Fuer die **eigene**
Tabelle widerspricht sich das, wenn man „unbekanntes Feld" als
Fremdbelegungsindikator nimmt. Aufloesung ueber die Identitaet einer
Registrierung:

> `[mcp_servers.<eigener Name>]` gilt als **fremd belegt**, wenn `command` oder
> `args` von dem abweichen, was AK3 schreiben wuerde.

Begruendung: Identitaet einer Hook-/Server-Registrierung ist im Repo bereits
ueber das Kommando definiert (FK-76 §76.5.1 „Identitaet eines AK3-Handlers ist
`(hook_event_name, matcher, command)`"; `settings_writer.py` Merge-Identitaet
„event + matcher + command"). Hat jemand ein **anderes Programm** unter unserem
Namen registriert, ist das eine echte Namenskollision, die nicht still
ueberschrieben werden darf. Stimmen `command` und `args`, ist es unsere eigene
(oder eine aequivalente) Registrierung: dann UPSERT von `cwd`/`env`/`required`
und **Erhalt aller weiteren, unbekannten Felder** in dieser Tabelle. Damit sind
beide Story-Klauseln gleichzeitig erfuellt und das Praedikat ist fuer einen
Reviewer nachpruefbar. Typfehler in einem AK3-eigenen Feld (Fall 7) fuehren
unabhaengig davon zur Ablehnung.

### 6.3 Benutzerpfade, Symlinks, Junctions (AC 3)

Auf Windows ist die realistische Variante die **Junction**, nicht der Symlink.
Es gibt eine bereits getestete Primitive dafuer:
`src/agentkit/backend/skills/links.py:84-90` `is_directory_link(path)`
(`path.is_symlink() or os.path.isjunction(path)`) — genau die, die `detach.py`
fuer seine Junction-Guards benutzt (`detach.py:510-519`). `paths.py` enthaelt
**keinen** Containment-Helfer (geprueft, §1.2); `ProjectBinding.resolve_within_root`
(`project_binding.py:75-92`) ist der getestete Containment-Beweis, haengt aber
an einem `ProjectBinding` mit `project_id` und Weaviate-Endpunkt — fuer einen
Pfadcheck im Installer ein unpassender Konstruktionsaufwand. Deshalb: **eine
kleine Funktion im Installer-Rand**, die beide vorhandenen Primitiven benutzt
statt eine dritte Idee einzufuehren:

```python
def assert_project_local_codex_config(project_root: Path) -> Path:
    """Return .codex/config.toml, proving it cannot leave the project root."""
    root = project_root.resolve(strict=False)
    codex_dir = project_root / CODEX_DIR
    if is_directory_link(codex_dir):                  # skills.links, getestet
        raise CodexConfigError(code=path_escapes_project_root, ...)
    path = codex_config_path(project_root)            # paths.py:63-64
    if path.is_symlink():
        raise CodexConfigError(code=path_escapes_project_root, ...)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise CodexConfigError(code=path_escapes_project_root, ...)
    return path
```

Diese Funktion laeuft in **Phase 1**, vor jedem Lesen und Schreiben, sowohl in
`write_codex_settings` (CP 8) als auch in CP 10. Damit ist ausgeschlossen, dass
ein umgehaengtes `.codex` oder eine verlinkte `config.toml` einen Write nach
`~/.codex/` traegt.

`CODEX_HOME` wird von AK3 **nirgends** gelesen — die repoweite Suche findet den
Namen ausschliesslich in Story-Dokumenten, in keiner Zeile Produktionscode. Die
Nicht-Benutzung von Userspace ist damit strukturell, nicht durch eine Pruefung
hergestellt. Konsequenz fuer den Testplan: siehe §8, AC 3 (dieser Teil ist
**nicht** revert-rot, und das wird gesagt statt behauptet).

### 6.4 Erhaltungsfaelle (positiv)

| Fall | Zusicherung | Mechanismus |
|---|---|---|
| fremde Top-Level-Tabellen (`[user.custom]`, `[profiles.x]`) | unveraendert erhalten, inkl. Kommentaren | tomlkit-Round-Trip (gemessen) |
| fremde MCP-Server (`[mcp_servers.other-server]`) | unveraendert erhalten | gemessen |
| unbekannte Felder in **fremden** Servertabellen | unveraendert erhalten | tomlkit beruehrt sie nicht |
| unbekannte Felder in der **eigenen** Servertabelle | erhalten, AK3-Felder werden geupsertet | §6.2 |
| Kommentare, Leerzeilen, Key-Reihenfolge in Fremdinhalt | erhalten | gemessen |
| wiederholter Merge | byte-identisch | gemessen (`one == two`) |

---

## 7. Zwei-Dateien-Fehlersemantik (Scope 5, AC 6, D6)

### 7.1 Operationsreihenfolge (register-Modus)

| Phase | Schritt | Fehler → |
|---|---|---|
| 0 | Feature-Gate (unveraendert, `cp10.py:263-271`) | `SKIPPED`/`vectordb_disabled` |
| 1 | Containment/Junction-Assertion fuer **beide** Pfade (§6.3) | `FAILED`/`mcp_configuration_invalid`, 0 Writes |
| 1 | typisierte Config, `project_id`, Endpunkte (§3.4) | `FAILED`/`configuration_invalid`, 0 Writes |
| 1 | `RuntimeBinding.from_env(...)` → **ein** `McpServerSpec` | `FAILED`/`configuration_invalid`, 0 Writes |
| 1 | `desired_server_from_spec(...)` → `DesiredMcpServer`-Menge | `FAILED`/`configuration_invalid`, 0 Writes |
| 2 | **beide Bestandsdateien strikt lesen** → `RegistrationBeforeImage(mcp_json: bytes\|None, codex_config: bytes\|None)` | `FAILED`/`mcp_configuration_invalid`, 0 Writes |
| 2 | **beide konfliktpruefen** (`.mcp.json`-Shape via `_load_target_mcp_json`; Codex via §6) | `FAILED`/`mcp_configuration_invalid`, 0 Writes |
| 3 | **beide vollstaendig rendern** → `mcp_json_text`, `codex_toml_text`; `RenderedRegistration` mit Digest | `FAILED`, 0 Writes |
| 4 | Idempotenz: beide Rendertexte == Before-Image → `PASS`/`already_satisfied` | — (0 Writes) |
| 5 | **Conformance-Probe** je Server aus `to_server_command()` (FK-50: „unmittelbar vor dem Schreiben") | `FAILED`/`mcp_*`-Reason, 0 Writes |
| 6 | `verify_binding()` (Digest neu berechnen) | `FAILED`/`configuration_invalid`, 0 Writes |
| 7 | Re-Read beider Dateien und Vergleich mit dem Before-Image (TOCTOU) | `FAILED`/`mcp_configuration_invalid`, 0 Writes |
| 8 | **Write 1**: `.mcp.json` atomar | §7.3 |
| 9 | **Write 2**: `.codex/config.toml` atomar | §7.3 |
| 10 | `CREATED`/`UPDATED`, `created_files` fuer beide Dateien | — |

Die Probe liegt **nach** dem Rendern und **unmittelbar vor** dem ersten Write —
damit sind gleichzeitig Story-Scope 5 („vor dem ersten Write gelesen,
konfliktgeprueft, vollstaendig gerendert") und FK-50 CP 10 („prueft unmittelbar
vor dem Schreiben") erfuellt. Beide Modi ohne Mutation (DRY_RUN/VERIFY) enden
nach Phase 3/4 und starten keinen Prozess (`context.mode.mutations_allowed`,
`cp10.py:294`).

Phase 7 ist eine **Zusatzhaertung ohne AC-Pflicht** (erkennt eine Fremdaenderung
zwischen Lesen und Schreiben). Sie kostet zwei `read_bytes` und schuetzt die
Byte-Identitaets-Zusicherung. Falls der Orchestrator sie als Scope-Ausweitung
sieht: streichbar, ohne dass ein AC faellt.

### 7.2 Was das „gebundene Before-Image" konkret ist

```python
@dataclass(frozen=True, slots=True)
class RegistrationBeforeImage:
    mcp_json: bytes | None          # None == Datei existierte nicht
    codex_config: bytes | None
```

Es ist ein **Feld von `RenderedRegistration`** und geht damit in denselben
Digest ein, den `verify_binding()` prueft. „Gebunden" heisst genau das: das
Rollback kann nicht den Inhalt einer anderen Datei oder eines anderen Laufs
zurueckschreiben, weil Before-Image, Rendertexte und Specs eine
digestgesicherte Einheit sind. `None` ist ein echter Zustand (nicht `b""`), weil
der Rollback dann **loeschen** und nicht eine leere Datei hinterlassen muss.

### 7.3 Fehler in der Write-Phase

Neue Konstante:

```python
#: CP 10: a write-phase I/O failure left the two-file registration incomplete
#: (D6). The detail states exactly which files were written and whether the
#: best-effort rollback from the bound before-image succeeded.
REASON_REGISTRATION_INCOMPLETE: Final = "registration_incomplete"
```

Der Name ist von Story-Scope 5 / AC 6 / D6 vorgegeben; die Konstante folgt der
bestehenden Konvention in `checkpoint_engine/reasons.py:38-48`
(`REASON_MCP_CONFIGURATION_INVALID` usw.) und liegt in derselben Datei.

- **`OSError` in Write 1:** null Writes. `FAILED` + `registration_incomplete`,
  Detail „no file was written".
- **`OSError` in Write 2:** best-effort-Rollback von `.mcp.json` aus dem
  gebundenen Before-Image (`bytes` zurueckschreiben, bei `None` die Datei
  loeschen). `FAILED` + `registration_incomplete`, Detail nennt „`.mcp.json`
  written, rollback OK" **oder** „rollback FAILED: <Ursache>". Es wird niemals
  ein sauberes Rollback behauptet, wenn auch das Zurueckschreiben scheitert —
  dieselbe Ehrlichkeitslinie wie `_rollback_bindings`
  (`tests/unit/installer/test_rollback_honest_partial.py:1-13`).

### 7.4 Idempotente Konvergenz eines Wiederholungslaufs

Ein Retry laeuft die volle Phasenordnung erneut. Weil (a) beide Renderings
deterministisch sind, (b) der Merge UPSERT ist und nie entfernt, und (c) die
Idempotenzpruefung in Phase 4 gegen die Bytes prueft, gilt:

- Beide Dateien schon korrekt → `PASS`/`already_satisfied`, null Writes.
- Genau eine Datei aktuell (der Crash-Fall) → nur die fehlende wird geschrieben,
  Ergebnis `UPDATED`.
- Fremdinhalt seit dem Abbruch dazugekommen → bleibt erhalten (§6.4).

### 7.5 Das Crashfenster — benannt, nicht verkauft

> Zwischen Write 1 (`.mcp.json`) und Write 2 (`.codex/config.toml`) liegt ein
> Fenster. Wird der Prozess dort hart beendet (Kill, Stromausfall), ist
> `.mcp.json` aktualisiert und `.codex/config.toml` nicht. Es gibt **keine**
> gemeinsame Dateisystemtransaktion ueber zwei Dateien; jeder Einzelwrite ist
> atomar (`atomic_write_text`: temp + `fsync` + `os.replace`,
> `utils/io.py:42-54`). Der Zustand ist erkennbar (die Codex-Datei traegt keine
> `[mcp_servers.story-knowledge-base]`-Tabelle) und konvergiert beim naechsten
> Installationslauf. Kein Rollback laeuft in diesem Fall, weil kein Code mehr
> laeuft.

Dokumentationsort: **FK-76 §76.5.4** (Owner beider Formate) als kurzer Absatz
„Zwei-Dateien-Fehlersemantik", plus die Wiederholung im Story-Bericht. Das ist
eine Konzeptaenderung und deshalb **nicht** vorab autorisiert → **§9 Q-1**.
Falls der PO keine Konzeptaenderung will, landet der Absatz ausschliesslich im
Bericht; dann bleibt eine Norm-/Code-Luecke, die ich benennen wuerde.

---

## 8. Testplan

### 8.1 Ebenen und Begruendung

| Datei | Ebene | Begruendung gegen CLAUDE.md |
|---|---|---|
| `tests/unit/core_types/test_mcp_server_registration.py` | unit | reine Logik: Validierung, kanonischer Payload, Digest-Stabilitaet. Kein I/O. Passt in das bestehende `tests/unit/core_types/`. |
| `tests/unit/harness_client/test_codex_config_toml.py` | unit | reine Text-zu-Text-Fachlichkeit (Striktheitsmatrix, Erhaltungsmatrix, Ownership, Kanonisierung). Kein Dateisystem. `tests/unit/harness_client/` existiert (die Story schreibt „tests/unit/harness/"; das ist im Repo dieses Verzeichnis). |
| `tests/unit/installer/test_codex_settings.py` (erweitern) | unit | Containment-/Junction-Ablehnung und Idempotenz von `write_codex_settings`; kleine, isolierte FS-Operationen in `tmp_path`, wie heute schon in dieser Datei. |
| `tests/unit/installer/checkpoint_engine/test_cp10_dual_registration.py` | unit | folgt der bestehenden Platzierung von `test_cp10_mcp_conformance.py`. Die Story nennt `tests/unit/installer/`. Ehrliche Einordnung: diese Tests starten echte Prozesse und schreiben Dateien — nach der Buchstabendefinition „reine Logik" waeren sie Integration. Konsistenz mit der vorhandenen CP-10-Suite wiegt hier schwerer als die Etikette; die szenariobasierten Mehrlauf-Faelle liegen bewusst darunter in `tests/integration/`. |
| `tests/unit/installer/test_registered_entry_starts.py` | unit | Startbarkeit und `env`-Vollstaendigkeit des gerenderten Eintrags (§8.2a T1/T2). Startet einen kurzlebigen Subprozess gegen einen toten Endpunkt; kein Netz, keine Infrastruktur, deterministisch. |
| `tests/integration/installer/test_codex_mcp_registration.py` | integration | szenariobasierte Zielprojekt-/Dateisystemablaeufe: zwei vollstaendige Installationslaeufe, `CODEX_HOME`-Isolation, zweiter Projektordner, keine Bundle-Ruecklaufkopie. |
| `tests/e2e/installer/test_dual_registration_live.py` | e2e (opt-in) | Nur Stufe T3: Register-Lauf gegen eine laufende Weaviate. Niemals Standard-CI (CLAUDE.md). |
| `tests/integration/installer/test_detach.py` (erweitern) | integration | die Detach-Klassifikation lebt dort schon (`:630-658`). |
| `tests/contract/installer/test_mcp_registration_binding.py` | contract | Stabilitaet des Vertrags: feldweise Wertgleichheit der beiden Formate, Digest-Bindung, adversariale Matrix als Tabelle. Genau die „Stabilitaet von Schemas/Snapshots/Manifests"-Rolle. |
| `tests/contract/packaging/test_packaging_pins.py` (erweitern) | contract | der Pin, im bestehenden D5-Muster (`:36-39`). |

Guardrail „kein manuelles State-Setup" (`guardrails/testing-guardrails.md`
Punkt 2) wird eingehalten: CP-10-Tests fahren zuvor **CP 5** (bzw. den ganzen
Install) und nehmen `run_state.project_yaml` nicht von Hand — das ist derselbe
Weg, den `test_cp10_mcp_conformance.py:105-110` heute schon geht
(`cp05_pipeline_config(ctx)` vor `cp10_mcp_registration(ctx)`).

### 8.2 Tests je AC, mit Revert-Rot-Analyse

| AC | Test (Datei :: Name) | Beweist | Wird rot, wenn man zurueckdreht |
|---|---|---|---|
| 1 | `integration/.../test_codex_mcp_registration.py::test_both_configs_registered_after_install` | Server steht in `.mcp.json` **und** `[mcp_servers.story-knowledge-base]` | die Codex-Projektion in CP 10 |
| 1 | `…::test_mcp_table_survives_second_install_run` | zwei vollstaendige Laeufe; die MCP-Tabelle ist nach Lauf 2 noch da | den semantischen Writer (Fixstring + Byte-Vergleich in `write_codex_settings`) — genau Befund B(1) |
| 1 | `…::test_both_merges_preserve_foreign_entries` | fremder `.mcp.json`-Server und fremde TOML-Tabelle ueberleben | den semantischen Merge (Ganzdatei-Rewrite) |
| 2 | `contract/.../test_mcp_registration_binding.py::test_codex_entry_field_equal_to_mcp_json_entry` | feldweise Gleichheit von `command`, `args`, `cwd` und **jedem** `env`-Paar; `required is True` nur im TOML, `type: "stdio"` nur im JSON (formatspezifisch, explizit im Test benannt) | die gemeinsame `DesiredMcpServer`-Quelle (getrennt konstruierte Eintraege) |
| 2 | `…::test_env_carries_exactly_the_registered_keys` | `set(env) == set(REGISTERED_ENV_KEYS)` (5 Keys) in **beiden** Formaten | das `env` am Spec (heutiger Zustand, Befund A) |
| 2 | `…::test_registered_env_keys_cover_runtime_binding_requirements` | `set(REGISTERED_ENV_KEYS) >= set(runtime_binding.REQUIRED_ENV_KEYS)` | **Drift-Sperre**: kommt kuenftig ein Key zu `REQUIRED_ENV_KEYS` hinzu, wird dieser Test rot, statt dass eine unvollstaendige `env` still ausgeliefert wird (§1.6a) |
| 1/4 | `unit/…/test_cp10_dual_registration.py::test_registered_args_name_the_executable_module` | die gerenderten `args` nennen `agentkit.backend.vectordb.engine` | die Modulkorrektur (§1.5) — mit `mcp_server` rot |
| 3 | `integration/.../test_codex_mcp_registration.py::test_isolated_codex_home_is_never_written` | mit gesetztem `CODEX_HOME=tmp/codex_home` bleibt dieses Verzeichnis nach dem Install **leer** | **nicht revert-rot.** Es gibt keine Produktionszeile, deren Entfernen den Test rot macht — AK3 liest `CODEX_HOME` nirgends (§6.3). Der Test ist eine Regressionssperre gegen eine kuenftige Aenderung, kein Fix-Beweis. Das wird im Bericht so gesagt. |
| 3 | `…::test_second_project_does_not_see_registration` | zweiter Projektordner ohne `.codex/config.toml` und ohne `.mcp.json`-Eintrag | ebenfalls nur teilweise: `codex_config_path(project_root)` ist projektrelativ, also strukturell. Revert-rot **nur** gegen eine hypothetische Umstellung auf einen Home-Pfad. Ehrlich als „strukturelle Zusicherung" markiert. |
| 3 | `unit/installer/test_codex_settings.py::test_junctioned_codex_dir_is_rejected` / `::test_symlinked_config_file_is_rejected` | `path_escapes_project_root`, kein Write, Zieldatei ausserhalb unveraendert | **revert-rot** gegen `assert_project_local_codex_config` (§6.3). Auf Windows via `os.path.isjunction`; auf POSIX via Symlink. Vorbild fuer die Plattformabfrage: `test_installer_namespace.py:55-60` (`_directory_links_supported`). |
| 4 | `unit/…/test_cp10_dual_registration.py::test_failed_conformance_writes_neither_file` | fehlgeschlagene Probe → `FAILED`, `.mcp.json` und `.codex/config.toml` byte-identisch (bzw. weiterhin abwesend) | die Phasenordnung (Probe vor Write) |
| 4 | `…::test_conformance_probes_exactly_the_written_command` | die geprobte `McpServerCommand` traegt **`cwd`** und dasselbe `env` wie der geschriebene Eintrag | den verlustfreien Bridge-Pfad — heute divergiert `cwd` (cp10.py:360-365) |
| 5 | `contract/.../test_mcp_registration_binding.py::test_field_mutation_after_probe_blocks_the_write` | `dataclasses.replace(server, cwd=…)` + altes `ProbedRegistration` → `McpServerRegistrationError`, null Writes | `verify_binding()` |
| 5 | `…::test_in_place_mutation_is_impossible` | direkte Zuweisung wirft (`FrozenInstanceError`) | `frozen=True` |
| 5 | `…::test_negative_matrix_non_default_endpoints` | frei gewaehlte, nicht-Default-Endpunkte landen **wortgleich** in beiden Formaten (kein Default eingesetzt) | jede Default-Synthese |
| 5 | `…::test_negative_matrix_empty_and_wrong_cwd` | leeres `cwd` → `RuntimeBindingError`; `cwd` ausserhalb des Project-Roots → Ablehnung | die `cwd`-Validierung |
| 5 | `…::test_negative_matrix_missing_env_field` | zwei getrennte Klassen, weil die Validatoren verschieden sind: je fehlender `REQUIRED_ENV_KEYS`-Eintrag (3) → `RuntimeBindingError` beim Rendern, null Writes; fehlendes `AGENTKIT_CONCEPTS_DIR` → **kein** `RuntimeBindingError` (es wird von `main()` geprueft, nicht von `RuntimeBinding`), sondern `McpServerRegistrationError` aus der `REGISTERED_ENV_KEYS`-Vollstaendigkeitspruefung, null Writes | die `from_env`-Bindung bzw. die Vollstaendigkeitspruefung. Der Verhaltensbeweis, dass die Aufteilung stimmt, ist §8.2a T2 gegen den echten Prozess. |
| 5 | `…::test_negative_matrix_divergent_project_id` | `PROJECT_ID`-Env ≠ `project_prefix` → `ProjectBindingError`, null Writes | den Resolver-Aufruf |
| 6 | `unit/…/test_cp10_dual_registration.py::test_codex_parse_error_writes_nothing` | vorab korrupte `.codex/config.toml` → `FAILED`, **`.mcp.json` byte-identisch** | die Reihenfolge „beide lesen/pruefen/rendern vor Write 1" — bei umgedrehter Reihenfolge waere `.mcp.json` schon geschrieben |
| 6 | `…::test_io_error_after_first_write_rolls_back_and_names_the_error` | simulierter `OSError` beim zweiten Write → `.mcp.json` byte-identisch zum Before-Image, `reason == "registration_incomplete"` | das Rollback aus dem Before-Image |
| 6 | `…::test_retry_after_incomplete_registration_converges` | nach dem simulierten Abbruch ein normaler Lauf → beide Dateien korrekt, danach `PASS` | Determinismus des Renderings / UPSERT |
| 7 | `unit/harness_client/test_codex_config_toml.py::test_rejection_matrix[<9 Faelle>]` | je Fall: `CodexConfigError.code`, kein Rueckgabetext | die jeweilige Einzelpruefung; jede Pruefung ist einzeln entfernbar → einzeln rot |
| 7 | `unit/…/test_cp10_dual_registration.py::test_rejection_matrix_leaves_both_files_byte_identical[…]` | dieselben Faelle am Checkpoint: **beide** Dateien byte-identisch | Phasenordnung + Einzelpruefung |
| 7 | `unit/harness_client/…::test_preservation_matrix` | fremde Top-Level-Tabelle, fremder MCP-Server, unbekannte Felder, Kommentare — alle erhalten; Werte semantisch gleich (per `tomllib`-Reparse verglichen) | `tomlkit` → `tomli-w`/Ganzdatei-Rewrite macht die Kommentar-Assertions rot |
| 7 | `unit/harness_client/…::test_canonical_rendering_is_merge_stable` | `render(None, servers)` == `render(render(None, servers), servers)` und `classify(...) is AK3_ONLY` | die Kanonisierung von AK3_ONLY-Dateien (§4.4) |
| B-Nachweis | `integration/installer/test_detach.py::test_detach_removes_ak3_hook_plus_mcp_config` | AK3-Hook + AK3-MCP-Tabelle → entfernt, in `removed_bindings` | das neue Praedikat (mit Byte-Vergleich gegen den Fixstring bleibt die Datei liegen) |
| B-Nachweis | `…::test_detach_preserves_config_with_foreign_table_alongside_mcp` | AK3-Hook + AK3-MCP + `[user.custom]` → `preserved_foreign_files`, Datei bleibt | Schritt 3 des Praedikats |
| B-Nachweis | `…::test_detach_preserves_ak3_only_config_with_user_comment` | AK3-Inhalt + zusaetzlicher Kommentar → erhalten | **Schritt 5** des Praedikats. Ohne ihn wird dieser Test rot — das ist der Test, der die Nicht-Schwaechung von `preserved_foreign_files` beweist. |
| B-Nachweis | `integration/installer/test_codex_mcp_registration.py::test_static_resource_deploy_does_not_reintroduce_a_bundle_config` | nach zwei Laeufen gibt es keine Bundle-Kopie, die die MCP-Tabelle ueberschreibt; `bundles/target_project/.codex/` enthaelt keine `config.toml` | die Bundle-Loeschung (§4.2) — mit der Datei flattert die Registrierung zwischen den Laeufen |
| **vorbestehender Defekt** (§4.2.1) | `integration/installer/test_codex_mcp_registration.py::test_user_extended_codex_config_survives_two_install_runs` | nutzererweiterte `.codex/config.toml` (fremde Tabelle **und** Kommentar) ueberlebt zwei vollstaendige Installationslaeufe wertgleich | **beide** Ursachen: die Bundle-Kopie (CP 8 `_deploy_static_resource_files`) **und** den Fixstring-Byte-Vergleich in `write_codex_settings`. Dreht man eine davon zurueck, wird der Test rot. Landet mit Schritt 3+5, weil die Bundle-Loeschung allein nicht genuegt. |
| Pin | `contract/packaging/test_packaging_pins.py::test_tomlkit_pinned_exactly` | `"tomlkit==0.15.1" in dependencies` | den Pin |

**Mocks/Stubs:** genau einer — der simulierte `OSError` fuer den zweiten Write
(AC 6). Er ist der einzige Weg, den Pfad „I/O-Fehler nach dem ersten Write" zu
erreichen; das Briefing erlaubt ihn ausdruecklich. Umsetzung minimal: der zweite
Write geht ueber **eine** benannte Funktion, die im Test per `monkeypatch` beim
ersten Aufruf `OSError` wirft. Kein Fake fuer MCP, keinen fuer das Dateisystem
sonst, keinen fuer die Config.

### 8.2a Der Beweis, dass der registrierte Eintrag wirklich startet

Das ist die Luecke, die der Beinahe-Fehler aus §1.5/§1.6 sichtbar gemacht hat:
„der Eintrag ist wohlgeformt" und „der Eintrag startet einen Server" sind zwei
verschiedene Aussagen, und AC 1/AC 4 behaupten die zweite. Drei Stufen, jede mit
klar begrenzter Aussagekraft:

**T1 — `tests/unit/installer/test_registered_entry_starts.py::test_rendered_entry_reaches_the_transport_layer`
(offline, revert-rot, der wichtigste Test).**
Der Test rendert den echten Spec fuer ein `tmp_path`-Projekt, startet
`[<command>, *<args>]` als Subprozess mit **genau** der gerenderten `env`, gegen
einen absichtlich toten Weaviate-Endpunkt, und behauptet:

- Exit-Code 1,
- die JSON-`detail` ist die **Konnektivitaets**-Meldung
  (`Could not connect to Weaviate at …`), **nicht** eine `env`-Meldung.

Das beweist zwei Dinge auf einmal, ohne eine Key-Liste nachzuerzaehlen:
(a) das registrierte Modul ist ausfuehrbar — mit `…mcp_server` endet der Prozess
mit Exit **0** und leerer Ausgabe (gemessen), der Test wird also rot; und (b) die
`env` ist **vollstaendig** — fehlte ein Pflicht-Key, waere die `detail` die
jeweilige `env`-Meldung (alle vier gemessen, §1.6a), der Test wird rot.
Damit bezieht der Test seine Wahrheit aus dem Prozess selbst und kann nicht
gegen dessen echte Anforderungen driften — anders als jede gepflegte Konstanten-
liste. Er ist revert-rot gegen die Modulkorrektur **und** gegen jeden
weggelassenen `env`-Key.

**T2 — `…::test_missing_env_key_matrix` (offline).** Fuenf Faelle, je ein Key
weggelassen; erwartet werden die gemessenen `detail`-Strings aus der Tabelle in
§1.6a. Der `AGENTKIT_STORIES_DIR`-Fall ist der Gegenprobe-Fall: er kommt an der
`env`-Validierung vorbei (Default) und scheitert an der Konnektivitaet — das
belegt, dass die vier anderen echte Pflicht-Keys sind und nicht nur mitgeschrieben
werden.

**T3 — `tests/e2e/installer/test_dual_registration_live.py` (opt-in, `-m e2e`).**
Vollstaendiger CP-10-Register-Lauf gegen eine **laufende** Weaviate: die
Conformance-Probe besteht mit dem produktiven Kommando, danach tragen beide
Dateien den Eintrag. Das ist die einzige Stufe, die AC 1 mit dem produktiven
Kommando end-to-end zeigt. Sie laeuft nie in der Standard-CI (CLAUDE.md:
„`tests/e2e/` nur opt-in") und deckt sich mit der Story-Abgrenzung „E2E gegen
echte Infrastruktur — nachgelagert mit dem PO".

**Was in der CI daraus folgt, ehrlich formuliert.** Weil `compose_runtime` vor
dem stdio-Serve verbindet und Collections anlegt (§1.6b), kann die
Conformance-Probe **ohne** laufende Weaviate nicht bestehen. Die CI beweist
deshalb:

- die CP-10-Mechanik (Probe vor Write, null Writes bei Fehlschlag, Zwei-Dateien-
  Semantik) mit dem echten `tests/fixtures/minimal_mcp_server.py` als
  Kommando-Substitut (das etablierte Muster, `test_cp10_mcp_conformance.py:44-45,
  74-78`),
- die Startbarkeit und `env`-Vollstaendigkeit des **produktiven** Eintrags ueber
  T1/T2 offline,
- das Zusammenspiel beider erst in T3.

Im Bericht steht das getrennt. Ich werde nicht behaupten, die CI beweise AC 1
mit dem produktiven Kommando.

### 8.3 Wie gemessen wird

`addopts = "-n 4 --dist loadfile"` (`pyproject.toml:70`) traegt **kein**
`--cov`. Ein blankes `pytest` misst keine Coverage. Gemessen wird deshalb wie
die CI (`Jenkinsfile:133-139` und `:213-220`):

```
.venv\Scripts\python -m pytest tests/unit -q --cov=src --cov-fail-under=0 --cov-report=term-missing
.venv\Scripts\python -m pytest tests/contract tests/integration -m "not requires_gh" -q --cov=src --cov-append --cov-report=term-missing
```

`pytest-randomly` ist aktiv; bei einem Reihenfolgeverdacht wird der Seed
festgenagelt und die Reproduktion belegt. Alle Aufrufe ausschliesslich ueber
`.venv\Scripts\python -m …`.

### 8.4 Bestehende Tests, die sich zwangslaeufig aendern

Ehrlich vorab benannt, damit im Review keine „stille Testanpassung" auffaellt:

| Test | Warum | Art der Aenderung |
|---|---|---|
| `unit/…/test_more_checkpoints.py:87-103` `test_cp10_dry_run_plan_contract_with_vectordb` | ruft CP 10 ohne CP 5; ohne Endpunkt-Config gibt CP 10 kuenftig `FAILED`/`configuration_invalid` | CP 5 mit gesetzten Endpunkten vorschalten — was Guardrail „kein manuelles State-Setup" ohnehin verlangt |
| `unit/…/test_checkpoints.py:275-289` `test_cp10_does_not_write_mcp_json_in_dry_run_or_verify` | `make_config(features_vectordb=True)` ohne Endpunkte | Endpunkte in `make_config` ergaenzen; die Aussage („kein Write in dry_run/verify") bleibt und muss gruen bleiben |
| `unit/…/test_checkpoints.py:317-345`, `test_remediation_fixes.py:227` | bauen `are-mcp`-Eintraege als rohe Dicts fuer `_desired_mcp_servers` | auf `DesiredMcpServer` umstellen |
| `unit/installer/test_codex_settings.py:23-32` | `write_codex_settings` ist weiter idempotent (zweiter Aufruf `None`) | bleibt gruen; ergaenzt um die neuen Containment-Faelle |
| `integration/installer/test_detach.py:630-641` | byte-gleiche AK3-Datei wird weiter entfernt | bleibt gruen (AK3_ONLY) |
| `integration/installer/test_detach.py:643-658` | fremde Tabelle wird weiter erhalten | bleibt gruen (MIXED) |
| `contract/scaffold_snapshots/test_install_scaffold.py:127`, `integration/project_ops/install_fresh/test_install_fresh.py:72`, `unit/installer/test_multi_harness_installer.py:94-162`, `unit/cli/test_main.py:793`, `integration/installer/test_register_project.py:205/260/279` | pruefen Existenz/Abwesenheit von `.codex/config.toml` und `"agentkit-hook-codex"` im Inhalt | bleiben gruen; der Hook-Eintrag bleibt inhaltlich derselbe, nur der Erzeuger wechselt von der Bundle-Kopie zum Writer (§4.2) |
| **Datei entfaellt:** `src/agentkit/bundles/target_project/.codex/config.toml` | dritter Writer (§1.2/§4.2) | Loeschung. Kein Test pinnt sie (gemessen); die Existenzzusicherung nach dem Install bleibt durch `write_codex_settings` erfuellt |

Der ARE-`.mcp.json`-Eintrag bekommt durch die Typisierung erstmals ein `cwd`
(heute fehlt es, `cp10.py:157-162`). Das ist eine sichtbare Inhaltsaenderung an
einem fremden Eintragstyp und wird als solche im Bericht genannt. Ob der
ARE-Server **auch** in `.codex/config.toml` gespiegelt wird, ist offen: **§9 Q-1b**.

---

## 9. Risiken und offene Fragen

### Q-0 — erledigt, widerlegt, keine Frage mehr offen

Die Blocker-Frage der Revision 1 ist **gegenstandslos**: der Einstiegspunkt
existiert in `engine.py` (§1.5). Der reale Defekt — CP 10 registriert das
Bibliotheksmodul statt `engine` — liegt in `command`/`args` des Specs, den
AG3-175 selbst rendert, und ist damit Scope, nicht Scope-Ausweitung. Keine
PO-Entscheidung, keine neue Story. AC 1 ist erreichbar (produktiv mit laufender
Weaviate, §1.6b).

### 9.0 Re-Audit aller uebrigen Absenz-Behauptungen dieses Plans

Der Fehler in Q-0 war methodisch: aus der Absenz **in einer Datei** auf die
Absenz **im Paket** geschlossen. Ich habe daraufhin jede weitere
Absenz-Behauptung des Plans mit einer Paket-/Repo-weiten Suche nachgeprueft.

| Behauptung | Nachpruefung | Ergebnis |
|---|---|---|
| „Der Bundle-Doppelgaenger wird nie deployt" | `grep -rn "target_project" src/agentkit/backend/` → **zweiter** Pfad `runner.py:1138/1148` gefunden, `_deploy_static_resource_files` (`runner.py:543-558`) kopiert **Dateien** | **WIDERLEGT.** Ich hatte nur `_deploy_directory_structure` gelesen und aus seinem `if item.is_dir()` auf „keine Dateien" geschlossen — obwohl ein Kommentar in `models.py:194` von einem deployten Sonar-Profil sprach, also von genau so einer Dateikopie. Korrigiert in §1.2/§4.2. |
| „AK3 liest `CODEX_HOME` nirgends" | `grep -rn "CODEX_HOME" src/ tools/` → 0 Treffer | bestaetigt |
| „`remove_codex_settings` hat keinen Produktionsaufrufer" | `grep -rn "remove_codex_settings" src/ tests/` → nur Definition, `__all__`, ein Unit-Test | bestaetigt |
| „`server_command_from_mcp_entry` hat danach keinen Produktionsaufrufer" | `grep -rn … src/ tests/` → produktiv nur `cp10.py:44/353`, sonst `__all__` + ein Test | bestaetigt |
| „`paths.py` hat keinen Containment-Helfer" | repo-weite Suche nach `resolve_within_root\|within_root\|is_relative_to\|containment` | bestaetigt; die Alternativen (`ProjectBinding.resolve_within_root`, `skills/links.is_directory_link`, `decommission.py:256`) sind in §6.3 benannt und werden wiederverwendet |
| „Kein Test fahrt CP 10 im Register-Modus mit dem echten vectordb-Eintrag" | `grep -rn "features_vectordb"` in `tests/` (6 Treffer, alle geprueft) **plus** Suche nach `vectordb` in Test-YAML-Fixtures (0 Treffer) **plus** `conftest.py:85/111` als einziger Setzweg | bestaetigt |
| „Kein TOML-Writer im Projekt" | `pip list`, plus repo-weite Suche nach `toml`-Importen (einziger Treffer: `test_packaging_pins.py:5`) | bestaetigt |
| „Kein Test pinnt die Bundle-`config.toml`" | `grep -rn "target_project.*codex\|codex.*target_project" tests/` → 0 Treffer | bestaetigt |
| „`GH_REPO` wird vom Server nicht gelesen" | `grep -rn "GH_REPO" src/agentkit/` → 0 Treffer | bestaetigt |

Ein Rest, der ausdruecklich **nicht** durch Absenz belegt ist: dass `tomlkit`
die einzige tragfaehige Writer-Wahl ist (§5) stuetzt sich auf positive
Messungen an beiden Wheels, nicht auf die Absenz von Alternativen.

### Q-1 — Konzeptaenderungen, die dieser Plan braucht (nicht vorab autorisiert)

`AG3-174/po-decisions.md:315-320` haelt fest, dass D7/D8 die **einzigen**
Konzeptaenderungen jener Story waren. Fuer AG3-175 ist keine autorisiert.
Der Plan braucht drei kleine, klar begrenzte Nachzuege:

- **(a) FK-76 §76.5.4** — ein Absatz „Zwei-Dateien-Fehlersemantik": kein
  gemeinsamer Transaktionsraum, Einzelwrites atomar, Crashfenster benannt,
  Retry konvergiert (§7.5). Das ist die vom PO geforderte Dokumentation des
  unvermeidbaren Restes.
- **(b) FK-50 §50.3 CP 10 Reason-Tabelle** — eine Zeile
  `registration_incomplete` und eine Zeile `configuration_invalid`; ausserdem
  die Praezisierung, dass `mcp_configuration_invalid` auch fuer die
  **Spiegeldatei** `.codex/config.toml` gilt (FK-76 §76.5.4 erklaert dieselben
  Regeln fuer beide Formate, die FK-50-Tabelle nennt nur `.mcp.json`).
- **(c) FK-50 §50.3 CP 10 Beispiel-JSON** — der `story-knowledge-base`-Block im
  Konzept zeigt heute **kein** `env`, **kein** `cwd` und nennt
  `"args": ["-m", "agentkit.backend.vectordb.mcp_server"]`, also das **falsche,
  nicht ausfuehrbare** Modul (§1.5). Das Beispiel muesste `env` (5 Keys), `cwd`
  und `…vectordb.engine` zeigen, sonst schreibt das Konzept den heutigen
  Defektzustand fest.

**Frage:** Sind (a), (b), (c) als begleitender Nachzug freigegeben? Falls nein,
liefere ich Code, der von der Konzeptprosa abweicht — das waere ein
Konzepttreue-Verstoss, den ich nicht eigenmaechtig eingehe. Ich implementiere
erst nach der Antwort. **(c) haengt inhaltlich mit Q-4 zusammen** und sollte
gemeinsam entschieden werden: es ist derselbe Sachverhalt in zwei Konzepten.

### Q-1b — Wird auch der ARE-Server nach Codex gespiegelt?

Story Scope 3 und AC 1/AC 2 sprechen von **einem** Server
(`[mcp_servers.story-knowledge-base]`). FK-76 §76.5.4 formuliert den Vertrag
dagegen generisch („Je Server eine Tabelle `[mcp_servers.<id>]`") und
ausdruecklich als **Spiegelung** des `.mcp.json`-Vertrags. Bei Story-Wortlaut
haette ein ARE-Projekt `are-mcp` in `.mcp.json`, aber nicht in
`.codex/config.toml` — eine halbe Spiegelung.

Mein Vorschlag: der Writer ist generisch (eine Tabelle pro gewuenschtem
Server), CP 10 projiziert **alle** gewuenschten Server in beide Formate. Kein
Sonderfall im Code, konzeptkonform. Konsequenz: bei `features.are: true` steht
`are-mcp` kuenftig auch im TOML — eine Verhaltensausweitung gegenueber dem
Story-Wortlaut.

**Frage:** generisch spiegeln (Empfehlung) oder streng nur
`story-knowledge-base`? Der Umschaltpunkt ist eine Zeile (die Server-Menge, die
an den Codex-Renderer geht).

### Q-2 — Der Bundle-Doppelgaenger ist ein dritter Writer (keine offene Frage mehr)

In Revision 1 stand hier „inerter Doppelgaenger, aufraeumen oder liegenlassen?".
Das war falsch: die Datei **wird** deployt (§1.2) und wuerde die MCP-Tabelle bei
jedem Folgelauf ueberschreiben. Damit ist es keine Aufraeum-Option, sondern eine
**notwendige Korrektheitsfolge derselben Aenderung** — genau die Kategorie, die
die Scope-Entscheidung des Orchestrators fuer die zwei gekoppelten Aufrufstellen
bereits als in-Scope eingeordnet hat, nur an einer dritten Stelle, die im
Briefing nicht stand.

Der Plan enthaelt deshalb die Loeschung von
`src/agentkit/bundles/target_project/.codex/config.toml` (§4.2, mit vier
Belegen, dass nichts daran haengt). Kein Sonderfall in
`_deploy_static_resource_files`, weil ein Workaround die zweite Quelle
konservieren wuerde.

**Kein Entscheidungsbedarf** — aber ausdruecklich zur Kenntnis, weil es eine
Datei ausserhalb der „Betroffene Dateien"-Tabelle der Story beruehrt. Widerspruch
bitte jetzt, nicht im Review.

### Q-3 — Zwei Aufraeumpunkte im Umfeld, ausdruecklich nicht eingeplant

- `codex_settings.remove_codex_settings` (`:47-61`) loescht die Datei
  **ungeschuetzt** und hat keinen Produktionsaufrufer (Uninstall laeuft ueber
  `detach`). Neben dem neuen, geschuetzten Pfad ist das ein Fallstrick.
- Der Wrapper-Name `agentkit-hook-codex` existiert dreimal als Literal
  (`codex_settings.py:19`, `detach.py:44-45`, `settings_writer.py:457`), plus
  `pyproject.toml:56`.
- `mcp_conformance.server_command_from_mcp_entry` (`check.py:202-227`) hat nach
  dieser Story **keinen** Produktionsaufrufer mehr (nur noch Tests). Es ist Teil
  der oeffentlichen AG3-164-Surface.

Ich plane fuer **keinen** dieser Punkte eine Aenderung ein (ausser dem
Durchreichen von `hook_command` in den Adapter, §4.1). **Frage:** stehenlassen,
oder soll einer davon mit? Ich frage, weil ZERO DEBT sonst gegen mich zeigt.

### Q-4 — Vollstaendiges Delta zwischen dem deklarierten und dem echten `env`-Vertrag

Der PO will die komplette Liste, nicht eine Teilmenge. FK-13 §13.4.3 deklariert
(gemessen, Zeilen 255-273) und der Prozess verlangt (gemessen, §1.6a):

| # | Element | FK-13 §13.4.3 deklariert | Prozess verlangt wirklich | Delta |
|---|---|---|---|---|
| 1 | `PROJECT_ID` | ja | ja | **stimmt** |
| 2 | Weaviate-Adresse | `WEAVIATE_HOST`, `WEAVIATE_HTTP_PORT`, `WEAVIATE_GRPC_PORT` (3 Keys) | `WEAVIATE_HTTP_ENDPOINT`, `WEAVIATE_GRPC_ENDPOINT` (2 Keys) | **ersetzt** — D2-Semantik „Endpunkt ist ein Konfigurationswert" |
| 3 | `GH_REPO` | ja | **nein** — der String kommt in `src/agentkit/` nirgends vor (gemessen) | **entfaellt** |
| 4 | `AGENTKIT_CONCEPTS_DIR` | **fehlt vollstaendig** | **Pflicht, ohne Default** (`engine.py:1272-1285`) | **fehlt im Konzept** — der wichtigste Punkt |
| 5 | `AGENTKIT_STORIES_DIR` | **fehlt vollstaendig** | optional (Default `"stories"`, `cwd`-relativ) | **fehlt im Konzept** |
| 6 | `args` | `["{agentkit_path}/vectordb/mcp_server.py"]` — Skriptpfad **und** Bibliotheksmodul | `["-m", "agentkit.backend.vectordb.engine"]` | **zweifach falsch** (Aufrufform + Modul) |
| 7 | `cwd` | fehlt | Containment-Grenze, von FK-76 §76.5.4 fuer die Codex-Tabelle gefordert und von der Story fuer beide Formate | **fehlt im Konzept** |

`AGENTKIT_CONCEPTS_DIR`/`AGENTKIT_STORIES_DIR` kommen in FK-13 **an keiner
Stelle** vor (gemessen: die Suche findet nur `concepts_dir` als Config-Begriff in
§13.9 und §13.13). Und dasselbe Modul-Problem (#6) steht ein zweites Mal in
FK-50 §50.3 CP 10 — das ist Q-1(c).

Ich entscheide das **nicht**. Der Code folgt zwingend dem Konsumenten (alles
andere ist ein garantiert nicht startender Server); die Konzeptkorrektur ist
PO-Sache. **Frage:** wird FK-13 §13.4.3 zusammen mit Q-1 nachgezogen (dann
vollstaendig entlang der Tabelle oben), oder ist FK-13 fuer diese Story tabu und
das Delta bleibt als benannter offener Punkt im Bericht?

### Q-5 — Additive Erweiterung des AG3-174-Resolvers

`resolve_authoritative_project_id` braucht ein optionales
`config_project_id`-Keyword, damit die Autoritaet auch dann verfuegbar ist,
wenn der Installer die `project.yaml` haelt, aber noch nicht geschrieben hat
(DRY_RUN/VERIFY; §3.4). Additiv, Default `None`, bestehende Aufrufer und die
Divergenzpruefung unveraendert. Es bleibt **eine** Implementierung der
Autoritaetsregel.

**Frage:** ist diese eine Zeile Signaturerweiterung an einem AG3-174-Modul in
Ordnung? Die Alternative waere, die Regel im Installer nachzubauen — das waere
eine zweite Wahrheit und damit schlechter.

### Weitere Risiken (ohne Frage, mit Umgang)

| Risiko | Umgang |
|---|---|
| `atomic_write_text` uebersetzt ohne `newline=""` auf Windows zu CRLF; Byte-Vergleiche und Idempotenz waeren plattformabhaengig | `newline=""` verbindlich fuer die Codex-Datei (§4.2). Einmaliges Neuschreiben auf Windows-Bestandsprojekten wird im Bericht genannt. |
| tomlkit-Layout weicht von der kanonischen Rendition ab → AK3-Datei wuerde als MIXED liegenbleiben | AK3_ONLY-Dateien werden **neu gerendert**, nicht gepatcht (§4.4), plus expliziter Invariantentest |
| `ProjectConfig.model_validate` auf der CP-5-Mapping koennte in einer Sonderkonfiguration scheitern | gemessen gruen fuer den Standard-Scaffold; Fehlschlag ist ein benannter `FAILED`/`configuration_invalid`, kein Absturz |
| Der Conformance-Check startet echte Prozesse; unter `-n 4` koennen Tests dadurch langsam werden | wie die bestehende CP-10-Suite: kleiner Fixture-Server, `--dist loadfile` haelt eine Datei auf einem Worker |
| `_reject_localhost` verbietet `localhost:50051`/`127.0.0.1:50051`, waehrend FK-13 den lokalen gRPC-Port `:50051` nennt | ratifizierte D2-Semantik, wird **nicht** angefasst; lokaler Betrieb muss den Host anders schreiben. Ein Test dokumentiert die Ablehnung, damit sie nicht kuenftig als Bug „repariert" wird. |
| AC 1 setzt in einem echten Lauf eine **laufende Weaviate** voraus, weil `compose_runtime` vor dem stdio-Serve verbindet (§1.6b) | keine Vertuschung: dreistufiger Beweis (§8.2a), T3 opt-in, und im Bericht steht getrennt, was die CI traegt und was nicht. Deckt sich mit AG3-176 Scope 1 („setzt die DB voraus") und der Story-Abgrenzung zu E2E. |
| Der Prozess braucht ausser unserer `env` auch Basis-Variablen (`PATH`, `USERPROFILE`, …) — meine erste Messung mit `env -i` scheiterte an „Could not determine home directory" | kein Produktionsrisiko: `build_minimal_env` (`mcp_conformance/process.py:67-77`) legt die Plattform-Basiskeys (`WIN_BASE_ENV_KEYS`, u. a. `USERPROFILE`/`HOMEDRIVE`/`APPDATA`/`PATH`) unter unsere `env`. Der Testaufbau in §8.2a erbt die Basis-Env bewusst und setzt nur unsere fuenf Keys. |
| Coverage ≥ 85 % | wird mit den CI-Kommandos aus §8.3 explizit gefahren und mit Ausgabe belegt; keine Zahl ohne `--cov`-Lauf |

---

## 10. Reihenfolge der Umsetzung (nach Freigabe)

1. `core_types/mcp_server_registration.py` (inkl. `REGISTERED_ENV_KEYS`,
   `AK3_MCP_SERVER_NAMES`) + Unit-Tests — reine Logik, keine Abhaengigkeiten.
2. `installer/mcp_registration.py`: Kommando-/Args-Korrektur auf
   `…vectordb.engine`, fuenf `env`-Keys, Spec → Desired → Render → Probe →
   Verify. Dazu **sofort** `test_registered_entry_starts.py` (§8.2a T1/T2) —
   dieser Test kommt vor allem anderen, weil er der Test ist, der den
   Beinahe-Fehler dieser Runde gefunden haette.
3. `harness_adapters/codex/config_toml.py` + Striktheits-/Erhaltungsmatrix
   (**haengt an D-1**).
4. `config/models.py` Endpunktfelder + `runner.py`
   `InstallConfig`/CP-5-Stanza.
5. `codex_settings.py` auf den Adapter umstellen; Bundle-Datei loeschen;
   `detach.py`-Praedikat.
6. `cp10.py` Zwei-Dateien-Koordination + Reasons.
7. Integration/Contract-Tests, Revert-Proben, Coverage-Lauf, `mypy`, `ruff`.

Schritt 3 haengt an **D-1** (tomlkit, liegt beim PO). Die Konzept-Nachzuege
(Q-1, Q-4) sind Dokumentationsschritte am Ende und blockieren die Schritte 1-7
nicht, muessen aber vor „fertig" entschieden sein.

### 10.1 Umsetzungsstand

| Schritt | Stand | Belege |
|---|---|---|
| 1 — `core_types/mcp_server_registration.py` | **fertig** (Commit `2f9ab00a`, erweitert um die Before-Image-Bindung) | 47 Tests in `tests/unit/core_types/test_mcp_server_registration.py` |
| 2 — `installer/mcp_registration.py` + Startbeweis | **fertig** (Commit `2720a51b`) | 30 Tests in `tests/unit/installer/test_mcp_registration.py`, 8 in `tests/unit/installer/test_registered_entry_starts.py`; Revert-Probe durchgefuehrt (7 rot), Konstante wiederhergestellt und erneut gruen |
| 3 — Codex-TOML-Writer | **fertig** (Commit `7b8e6d53`, D-1 vom PO freigegeben) | 42 Tests in `tests/unit/harness_client/test_codex_config_toml.py`; 13/13 tomlkit-Garantien gegen die installierte 0.15.1 nachgemessen |
| 4 — Endpunkt-Config | **fertig** (Commit `74af1adc`) | Shape-Negativmatrix + CP-5-Stanza |
| 5 — ein Writer, Bundle-Loeschung, Detach-Praedikat | **fertig** (Commit `74af1adc`) | 5 neue Detach-Tests |
| 6 — CP 10 Zwei-Dateien-Ordnung | **fertig** (Commit `74af1adc`) | 23 Tests in `test_cp10_dual_registration.py` |
| 7 — AC-Tests, Revert-Proben, Coverage | **fertig** | 7 Revert-Proben durchgefuehrt (alle RED), Coverage 91.12 % |

Abschlusslauf: `pytest tests/unit` → **8583 passed, 14 skipped**;
`pytest tests/contract tests/integration -m "not requires_gh"` → **2146 passed**;
**Total coverage 91.12 %** (Schwelle 85 % erreicht); `ruff check src tests` und
`mypy src` (1001 Dateien) sauber. Der Abschlussbericht mit AC-Nachweistabelle,
Revert-Proben, dem Konzept-Delta als Ratifizierungsvorlage (Q-1/Q-4) und der
Q-1b-Entscheidung ging als Ergebnisbericht an den Orchestrator.

**Zwei Plan-Aussagen wurden vom Code widerlegt** (beide im Bericht ausgewiesen):
Component-Groups tragen doch eine Exposure-Restriktion (`HarnessAdaptersCodex` ist
`exposure: internal`, `entities.md:433-447`), und der Architektur-Checker laeuft
doch gegen das echte Repo.

**Grund der Platzierungsabweichung — Konzeptvorrang, nicht Bequemlichkeit.** Die
Story zeigt als betroffene Datei auf `harness_adapters/codex/`; FK-76 §76.9 sagt
„konkrete Adapter sind nicht direkt importierbar", und das Architekturmodell
setzt das mit `exposure: internal` auf genau diesem Prefix durch. Bei einem
Konflikt zwischen Story-Dateizeiger und Konzept gilt **das Konzept**
(`stories/README.md` §4.2: Konzepte sind die Autoritaet fuer
Architekturentscheidungen, nicht das Story-Briefing). Deshalb liegt der Writer in
`harness_adapters/codex_config_toml.py` — ausserhalb des internen Prefix und
neben `settings_writer.py`, wo der `.codex/hooks.json`-Writer schon liegt. Das
`codex/`-Subpackage traegt Hook-**Mediation**, keine Settings-Writer. Die
Abweichung ist keine Umgehung des Story-Scopes, sondern seine konzepttreue
Ausfuehrung.

**R-1 (Orchestrator-Review) geschlossen.** Der neue gRPC-Validator akzeptierte
`http://h:1` (via `rpartition(":")`) und haette dem Weaviate-Client den Literal-Host
`"http://h"` uebergeben — ein plausibler Operator-Fehler waere erst als
Connect-Fehler aufgefallen. Die akzeptierte Menge beider Validatoren ist jetzt
**an den Konsumenten gebunden** (`engine._split_endpoint` / `._split_grpc`,
ratifizierter AG3-174-Code, unangetastet) und mit Tests belegt, die diese Bindung
behaupten statt sie nur zu dokumentieren.

Gemessen am Ende von Schritt 2:
`pytest tests/unit/installer tests/unit/core_types tests/unit/vectordb -q` →
**989 passed**; `ruff check` der fuenf Dateien → *All checks passed*;
`mypy src` → *Success: no issues found in 1000 source files*.

**Zwei Praezisierungen, die sich waehrend der Umsetzung ergaben** (beide im Code
so umgesetzt, hier zur Nachvollziehbarkeit):

1. **Das Before-Image musste in den Digest.** Der Plan behauptete in §7.2 eine
   „gebundene" Vor-Aufnahme. Bei der Umsetzung zeigte sich, dass die
   Digest-Signatur aus §2.4 das nicht leistete: ein ausgetauschtes Before-Image
   mit identischen Specs und Texten haette denselben Digest ergeben, die
   Zusicherung waere also falsch gewesen. `canonical_registration_payload`
   nimmt jetzt zusaetzlich `before_image` (als **Fingerprint**, nicht als
   Rohbytes — eine vorhandene Harness-Config kann ungueltiges UTF-8 sein und
   waere in einem JSON-Payload nicht einbettbar). Test:
   `test_verify_binding_detects_a_swapped_before_image`.
2. **`desired_server_from_spec` ist typisiert statt `object` + `getattr`.** Der
   erste Wurf nahm `spec: object` „um keine Importabhaengigkeit zu erzeugen".
   Das haette mypy-strict unterlaufen und ein falsches Objekt still akzeptiert.
   Geprueft, dass der typisierte Import erlaubt ist: `entities.md` definiert
   `may_import_*` an **Boundaries**, nicht an fachlichen Component-Groups, und
   `installer` ist eine Group; ausserdem sagt AG3-174s Moduldocstring
   ausdruecklich „consumed UNCHANGED by AG3-175".
