# AG3-208 — Edge-/Kern-Distributionszielbild normativ festziehen

- **Typ:** concept
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`; entblockt **AG3-237** (Klassifikation/Symbolinventar) und **AG3-236** (Platzhalter-Nachzug). AG3-209 folgt erst nach AG3-237
- **Quell-Konzept:** FK-10 §10.1.1/§10.1.2/§10.1.3, FK-01
  (Trust Boundaries), FK-30 (Guard-Engine/Adapter-Schnitt)
- **Herkunft:** PO-Entscheidung vom 2026-08-03,
  `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md`.
  Der Record benennt AG3-208 als normativen und AG3-209 als technischen
  Umsetzungslocator.

## Kontext

### Normative Grundlage

Die Entscheidung ist getroffen: AK3 besteht aus einer Edge-Distribution, einer
Kern-Distribution und einem kleinen, von beiden importierten Vertragspaket.
Guard-Evaluation bleibt Edge-seitig; kanonischer Zustand bleibt Kern-Eigentum
und wird vom Edge ausschliesslich ueber HTTP erreicht. Diese Story waehlt keine
Alternative, sondern macht die bereits entschiedene Grenze in den zustaendigen
Konzepten implementierbar.

Heute beschreibt FK-10 den Laptop zwar als Edge, die Artefakt- und
Modulzuordnung loest das aber nicht ein. FK-01 bezeichnet den lokalen Arm in
`concept/technical-design/01_systemkontext_und_architekturprinzipien.md:87-96`
zugleich als „regelfrei“, waehrend der Decision Record §3.4 die lokale
Guard-Evaluation ausdruecklich festschreibt. FK-30
`concept/technical-design/30_hook_adapter_guard_enforcement.md:446-456` legt
die ausgefuehrten Guard-Module noch unter `agentkit.backend.*` fest. Diese
Prosa muss gegen die PO-Entscheidung widerspruchsfrei werden, bevor Code seine
neue Heimat erhaelt.

### Befund 1 — eine Distribution und drei vermischte Entry Points

| Locator | Befund |
|---|---|
| `pyproject.toml:14-52` | Eine gemeinsame Dependency-Menge enthaelt unter anderem `psycopg`, `psycopg-pool`, `mcp`, `weaviate-client`, `tokenizers` und `tomlkit`. |
| `pyproject.toml:74-77` | `agentkit` zeigt auf `agentkit.backend.cli.main:main`; die beiden Harness-Wrapper zeigen auf `harness_client`, importieren dort aber die Guard-Engine aus `backend`. |
| `pyproject.toml:79-80` | Das einzige Wheel packt `src/agentkit` vollstaendig. |
| `src/agentkit/backend/cli/main.py:9-26` | Das gemeinsame CLI importiert Installer-, Story-, Evidence-, Recovery- und Auth-Kommandos eager. |
| `src/agentkit/backend/cli/main.py:127-160` | Ein Dispatcher mischt Laptop-Kommandos (`register-project`, `run-phase`, `update`, `detach`) mit Kern-Kommandos (`serve`) und in-process Fachoberflaechen. |

> **KORREKTUR 2026-08-07 — die Zahlen in Befund 2 und 4 sind veraltet.**
> Bei der Umsetzung wurde neu gemessen: Es sind **49 Importstellen ueber 25
> Module**, nicht 40 ueber 20 — die Kopplung ist seit dem 2026-08-03
> **gewachsen**. In Befund 4 existieren drei Locatoren nicht mehr
> (`permission_projection.py`, `permission_request_block.py`, `ccag/cli.py`);
> sie sind mit AG3-226 entfallen. Nahezu alle Zeilennummern sind verschoben.
>
> Die Tabellen unten bleiben als **Beleg des Befundzeitpunkts** stehen und
> werden nicht nachgepflegt — die Ownership-Matrix in FK-10 §10.2.12 setzt auf
> den **neuen** Zahlen auf, und sie ist der Stand, der gilt. Wer hier eine Zahl
> zitieren will, misst neu.
>
> Das ist derselbe Mechanismus, den diese Session mehrfach belegt hat: Ein
> Sweep, der aus einem frueheren Stand stammt, ist eine Hypothese ueber den
> heutigen.

### Befund 2 — vollstaendige Kantenliste `harness_client -> backend`

Gemessen am 2026-08-03 mit
`rg -n --glob '*.py' '(?:from|import) agentkit\.backend' src/agentkit/harness_client`:
**40 Importstellen, 20 verschiedene Module**. `TYPE_CHECKING`-Kanten sind
aufgefuehrt, weil sie beim Paket- und Test-Schnitt ebenfalls aufloesbar sein
muessen. Klassifikation meint den importierten Inhalt an dieser Kante, nicht
pauschal das gesamte Quellmodul.

| Nr. | Datei:Zeile | Importierter Inhalt | Klasse |
|---:|---|---|---|
| 1 | `harness_client/harness_adapters/claude_code.py:27` | `governance.guard_evaluation.{HookEvent, PrincipalKind}` | Wire-Vertrag/DTO |
| 2 | `harness_client/harness_adapters/claude_code.py:31` | `governance.runner.{Governance, parse_hook_wrapper_args}` | ausfuehrende Engine |
| 3 | `harness_client/harness_adapters/claude_code.py:376` | `governance.guard_evaluation.evaluate_pre_tool_use` | ausfuehrende Engine |
| 4 | `harness_client/harness_adapters/codex/cli.py:19` | `governance.runner.{Governance, parse_hook_wrapper_args}` | ausfuehrende Engine |
| 5 | `harness_client/harness_adapters/codex/decision_mapping.py:10` | `governance.protocols.GuardVerdict` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 6 | `harness_client/harness_adapters/codex/event_mapping.py:10` | `governance.guard_evaluation.{HookEvent, Operation, PrincipalKind}` | Wire-Vertrag/DTO |
| 7 | `harness_client/harness_adapters/codex_config_toml.py:64` | `core_types.mcp_server_registration.{AK3_MCP_SERVER_NAMES, AK3_SERVER_SHAPES, DesiredMcpServer}` | Wire-Vertrag/DTO |
| 8 | `harness_client/harness_adapters/settings_writer.py:29` | `governance.errors.HookRegistrationError` | Wire-Vertrag/DTO |
| 9 | `harness_client/harness_adapters/settings_writer.py:30` | `utils.io.read_json_object` | Hilfsfunktion |
| 10 | `harness_client/harness_adapters/settings_writer.py:33` | `governance.hook_registration.HookDefinition` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 11 | `harness_client/harness_adapters/settings_writer.py:448` | `governance.runner.validate_hook_selector` | ausfuehrende Engine |
| 12 | `harness_client/projectedge/client.py:15` | 19 Request-/Response-/Bundle-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 13 | `harness_client/projectedge/client.py:36` | vier Typen aus `control_plane.third_party_models` | Wire-Vertrag/DTO |
| 14 | `harness_client/projectedge/client.py:42` | `exceptions.ControlPlaneApiError` | Wire-Vertrag/DTO |
| 15 | `harness_client/projectedge/client.py:43` | `utils.io.atomic_write_text` | Hilfsfunktion |
| 16 | `harness_client/projectedge/client.py:55` | `story_creation.create_flow.StoryCreationReconciler` (`TYPE_CHECKING`) | ausfuehrende Engine |
| 17 | `harness_client/projectedge/client.py:1002` | `story_creation.vectordb_reconciliation.AbgleichProtocol` | ausfuehrende Engine |
| 18 | `harness_client/projectedge/command_executor.py:29` | `code_backend.provider_port.{StoryRefWriteCredentialClass, StoryRefWriteCredentialResult}` | Wire-Vertrag/DTO |
| 19 | `harness_client/projectedge/command_executor.py:33` | `control_plane.edge_commands.is_executable_command_kind` | ausfuehrende Engine |
| 20 | `harness_client/projectedge/command_executor.py:34` | 14 Command-/Report-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 21 | `harness_client/projectedge/command_executor.py:50` | `control_plane.push_sync.{decide_push_gate, official_story_ref}` | ausfuehrende Engine |
| 22 | `harness_client/projectedge/command_executor.py:54` | `core_types.verify_evidence.CollectVerifyEvidenceCommandPayload` | Wire-Vertrag/DTO |
| 23 | `harness_client/projectedge/command_executor.py:55` | `utils.io.atomic_write_text` | Hilfsfunktion |
| 24 | `harness_client/projectedge/command_executor.py:70` | `config.models.ProjectConfig` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 25 | `harness_client/projectedge/command_executor.py:71` | drei Command-Queue-Typen aus `control_plane.models` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 26 | `harness_client/projectedge/governance_client.py:26` | 14 Governance-/Telemetry-/Health-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 27 | `harness_client/projectedge/governance_client.py:42` | `exceptions.ControlPlaneApiError` | Wire-Vertrag/DTO |
| 28 | `harness_client/projectedge/governance_client.py:312` | `config.loader.load_project_config` | Hilfsfunktion |
| 29 | `harness_client/projectedge/merge_local.py:9` | drei Merge-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 30 | `harness_client/projectedge/merge_local.py:18` | `config.models.ProjectConfig` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 31 | `harness_client/projectedge/permission_projection.py:11` | `utils.io.atomic_write_text` | Hilfsfunktion |
| 32 | `harness_client/projectedge/reconcile.py:20` | fuenf Takeover-/Worktree-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 33 | `harness_client/projectedge/reconcile.py:32` | `config.models.ProjectConfig` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 34 | `harness_client/projectedge/runtime.py:14` | `config.loader.load_project_config` | Hilfsfunktion |
| 35 | `harness_client/projectedge/runtime.py:15` | vier Bundle-/Sync-Typen aus `control_plane.models` | Wire-Vertrag/DTO |
| 36 | `harness_client/projectedge/runtime.py:21` | `control_plane.ownership.canonical_binding_revocation_reason` | ausfuehrende Engine |
| 37 | `harness_client/projectedge/runtime.py:30` | `core_types.operating_mode.OperatingMode` | Wire-Vertrag/DTO |
| 38 | `harness_client/projectedge/verify_evidence.py:14` | neun Evidence-Grenzwerte/-Typen aus `core_types.verify_evidence` | Wire-Vertrag/DTO |
| 39 | `harness_client/projectedge/verify_evidence.py:29` | `config.models.ProjectConfig` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |
| 40 | `harness_client/projectedge/verify_evidence.py:30` | `core_types.verify_evidence.{VerifyEvidenceRepository, VerifyEvidenceRequest}` (`TYPE_CHECKING`) | Wire-Vertrag/DTO |

Ergebnis: 25 DTO-/Vertragskanten, 9 Engine-Kanten, 6 Hilfsfunktionskanten.
Die DTO-Zahl ist kein Argument fuer ein grosses Shared-Paket: AG3-209 darf nur
die tatsaechlich beidseitig benoetigten HTTP/Wire-Modelle in das Vertragspaket
nehmen; lokale Config-, Hook- und Provider-Typen gehoeren zu ihrem
ausfuehrenden Besitzer.

### Befund 3 — welcher Code tatsaechlich auf dem Laptop laeuft

| Einstieg / Locator | Laufzeitspur auf dem Entwicklerrechner |
|---|---|
| `agentkit-hook-claude`, `pyproject.toml:76` | `claude_code.main` liest stdin (`claude_code.py:256-280`) und ruft `Governance.run_hook(...)` (`:283-288`). Der projektlokale Sammel-Hook ruft `evaluate_pre_tool_use(...)` (`:335-379`). Damit laufen `backend/governance/runner.py` und `backend/governance/guard_evaluation.py` samt Guard-Kette im Hook-Prozess. |
| `agentkit-hook-codex`, `pyproject.toml:77` | `codex.cli.main` liest stdin (`codex/cli.py:32-56`) und ruft `Governance.run_hook(...)` (`:58-63`). Auch hier laeuft die Guard-Engine lokal. |
| `agentkit`, `pyproject.toml:75` | `backend/cli/main.py:92-104` registriert Edge- und Kern-Kommandos gemeinsam; der Dispatcher `:127-160` entscheidet erst nach dem eager Import der Backend-CLI-Module. Schon `agentkit --help` braucht deshalb die Einheitsdistribution. |
| deployter Project-Edge-Launcher | `bundles/target_project/tools/agentkit/projectedge.py:20-44` importiert Config, Wire-Modelle, `backend/story_creation` und den VectorDB-Adapter. `create-story` baut bei `:284-287` den echten Reconciler und `client.create_story` fuehrt ihn bei `harness_client/projectedge/client.py:973` aus. `backend/story_creation/` ist damit Laptop-Engine, nicht Kerncode. |
| Edge-Command-Loop | `harness_client/projectedge/command_executor.py:712-812` dispatcht lokale Git-/Worktree-/Evidence-Auftraege. Die importierten Credential-Typen aus `backend/code_backend/provider_port.py` werden im lokalen Service-Identity-Port `command_executor.py:102-136` verwendet. |

`backend/code_backend/provider_port` ist an der gemessenen Kante DTO/Portvertrag;
seine konsumierende Port- und Credential-Aufloesung laeuft dennoch lokal. Der
neue Schnitt darf den Port deshalb nicht als Vorwand im Kern belassen.

### Befund 4 — Gegenrichtung `backend -> harness_client`

Ja. Der stabile `HEAD` vor den parallelen, noch uncommitteten Arbeiten enthaelt
folgende Gegenkanten; Zeilen sind Import-Locatoren, Mehrfachzeilen desselben
Moduls sind bewusst zusammengefasst:

| Bereich | Locatoren | Bedeutung fuer den Schnitt |
|---|---|---|
| Composition/CLI | `backend/bootstrap/composition_project.py:623`; `backend/cli/_operator_ownership_commands.py:17,34,39`; `_operator_recovery_admin.py:13`; `_operator_recovery_phase.py:20,62,67`; `backend/cli/main.py:29` | Bediener-/Update-CLI und ProjectEdge-Transport liegen unter dem Backend-Namespace. Das ist gemischte Deployment-Heimat, keine legitime Core->Edge-Laufzeitabhaengigkeit. |
| Guard-Engine | `backend/governance/guard_evaluation.py:27`; `runner.py:48,291,652,798,1064,1365,1493,1563,1629,2034`; `permission_request_block.py:19`; `rest_edge.py:21,41`; `ccag/cli.py:48` | Die angebliche Backend-Engine liest Edge-Bundle, ruft den Edge-REST-Client und schreibt Harness-Settings. Die Zyklen verschwinden nur, wenn die vollstaendige lokale Engine zum Edge zieht. |
| Hook-seitige Repositories | `backend/telemetry/rest_emitter.py:28`; `backend/implementation/worker_health/rest_repository.py:18` | Diese `TYPE_CHECKING`-Kanten benennen explizit hook-seitige REST-Implementierungen unter dem Backend-Namespace; auch sie brauchen eine Edge-Heimat. |
| Installer | `backend/installer/runner.py:84,1730`; `installer/codex_settings.py:26`; `installer/lifecycle/detach.py:44`; `installer/upgrade/hook_migration.py:30`; `installer/bootstrap_checkpoints/cp10_mcp_registration.py:77` | Projektregistrierung, Hook-/MCP-Materialisierung, Update und Detach laufen am Laptop und importieren Harness-Adapter. Der Installer ist Teil des Edge-Schnitts. |

Parallele, uncommittete Auth-Arbeiten koennen diese Liste erweitern; AG3-209
erhebt beide Richtungen unmittelbar vor dem Schnitt erneut und das neue Gate
prueft den dann tatsaechlichen Graphen. Aus einer echten Kern-Distribution darf
danach keine Edge-Distribution transitiv erreichbar sein.

### Befund 5 — weitere Kopplungen der Einheitsdistribution

| Beruehrung | Beleg | Konsequenz |
|---|---|---|
| Installer | `backend/cli/installer_commands.py:14-171,321-459`; `backend/installer/runner.py:1387,1729-1732` | `register-project`, `verify-project`, `upgrade-project`, Hook-Registrierung und ProjectEdge-Transport sind Laptop-Funktionen trotz Backend-Heimat. |
| Entry Points | `pyproject.toml:74-80` | Ein Projektname, drei Scripts und ein Wheel muessen in drei Artefakte mit eindeutiger Script-Ownership zerlegt werden. |
| Zielprojekt-Bundle | `bundles/target_project/tools/agentkit/projectedge.py:20-50,251-332,369-405,540-544` | Der deployte Launcher startet Story-Reconciliation und Command-Loop lokal; alle alten Backend-Importpfade muessen im selben Zug verschwinden. |
| MCP-Registrierung | `backend/core_types/mcp_server_registration.py:151-160`; `backend/installer/mcp_registration.py:54-56,96-152` | Der Installer bindet heute denselben Interpreter an `agentkit.backend.vectordb.engine`. Das Zielbild muss Besitzer, Distribution und Dependency der lokal gestarteten MCP-Prozesse explizit zuordnen. |
| Deployment-Regeln | `PROJECT_STRUCTURE.md:88-165,203-217,236-240` | Die Datei nennt Deployment-Unit-first, fuehrt aber `backend/installer`, Backend-CLI und Harness-Code unter einem gemeinsamen `src/agentkit`-Artefakt. |
| Architektur-Conformance | `concept/formal-spec/architecture-conformance/entities.md:378-437,1174-1310,1418-1458` | Die Formal-Spec kennt Backend-Governance, Backend-CLI, ProjectEdge und Shared Foundations, aber keine Distribution-/Vertragspaket-Grenze. |
| Test-Layout | `tests/unit/{governance,installer,projectedge,harness_client,core_types}` sowie `tests/integration/{governance_hooks,installer,control_plane_http}` | 68 Tests importieren `harness_client`, 766 `backend`, 64 beide (Messung am Arbeitsstand). Ein gruener Monorepo-Test beweist keine installierbare Distribution; Tests und Build-Probes brauchen explizite Artefaktkontexte. |

### AG3-129 — geleistet und nicht zu wiederholen

AG3-129 ist `completed`. Sie hat Guard-Counter, Worker-Health und Telemetrie aus
dem direkten PostgreSQL-Pfad auf Backend-REST gezogen. Belege sind unter anderem
`backend/telemetry/rest_emitter.py:1-15`,
`backend/implementation/worker_health/rest_repository.py:1-8` und
`harness_client/projectedge/governance_client.py:1-15`. Die Datenebene ist
damit getrennt: der Hook besitzt keine DB-Credentials. Diese Story und AG3-209
erhalten den REST-Vertrag und verschieben nur Artefakt-, Modul- und
Dependency-Ownership. Kein zweiter HTTP-Client, kein Direkt-DB-Fallback und kein
erneuter Endpunktbau gehoeren in diesen Strang.

## Scope

### In Scope

- FK-10 §10.1.1/§10.1.2/§10.1.3 sowie die Deployment-/Versionsabschnitte so
  nachziehen, dass Edge-Prozesse, Kernprozesse, Vertragspaket, Artefakte,
  Entry Points, Dependencies und Kommunikationsrichtungen eindeutig sind.
- FK-01s Trust-Boundaries gegen die Entscheidung harmonisieren: Der lokale Arm
  besitzt keine kanonische Wahrheit, fuehrt aber die explizit mandatierte,
  deterministische Guard-Evaluation und fs/worktree-gebundene Engine aus.
- FK-30s Guard-Engine/Adapter-Schnitt und Hook-Registrierung auf eine lokal
  ausgelieferte, harness-neutrale Edge-Engine erden; Harness-Adapter bleiben
  duenn, die Engine bleibt lokal und spricht fuer kanonischen Zustand HTTP.
- Die Ownership-Matrix festlegen, **soweit sie ohne Messung belegbar ist**:
  `frontend`, `integration_clients`, `bundles`, Paket-Root, jede beim Schnitt
  vorhandene Deployment Unit, die Drittsystem-Adapter und die Dependencies.
  Jede Einheit bekommt genau einen Auslieferungsbesitzer: Edge, Kern oder
  Vertragspaket.

  **Die Klassifikation der 44 Backend-Subpakete gehoert nicht hierher**
  (Zuschnittkorrektur 2026-08-07, siehe AC 3). Sie ist Gegenstand von AG3-237.
  AG3-208 stellt nur fest, dass es 44 sind, und liefert die Regel, unter der
  eine Zuordnung ueberhaupt zulaessig ist.
- `PROJECT_STRUCTURE.md` und die Architektur-Conformance-Spezifikation so
  normieren, dass Distributionen und erlaubte Import-Richtungen maschinell
  ausdrueckbar sind.
- Test- und Build-Topologie normieren: Core-, Edge- und Contract-Tests sowie
  Clean-Install-/Wheel-Nachweise sind voneinander unterscheidbar.
- Auswirkungen auf AG3-187/189/206/193 explizit festhalten, ohne diese Storys
  umzuschneiden oder ihren Status zu veraendern.

### Out of Scope

- Produktionscode, Paket-Metadaten, Entry Points oder Tests verschieben —
  **Owner: AG3-209**.
- Neue REST-Endpunkte oder eine Wiederholung der DB-Mediation — **Owner:
  bestehende BC-Story bei einem konkreten fachlichen Gap; AG3-129 bleibt die
  abgeschlossene Grundlage**.
- AG3-187, AG3-189 oder AG3-206 umschneiden, obsolet setzen oder
  umpriorisieren — **Owner: Product Owner**.
- Eine Kompatibilitaets-, Alias- oder Uebergangsstrategie — **kein Owner, durch
  PO-Grundregel verboten**.
- Release-Automation ausserhalb der fuer den Schnitt notwendigen Build- und
  Gate-Vertraege — **Owner: eigener PO-Auftrag, falls nach AG3-209 noch ein
  nachgewiesenes Gap besteht**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/10_runtime_deployment_speicher.md` | geaendert | autoritativer Edge-/Kern-Prozess-, Deployment-, Versions- und Installationsschnitt |
| `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` | geaendert | Trust Boundary und lokaler Guard-Engine-Carve-out |
| `concept/technical-design/30_hook_adapter_guard_enforcement.md` | geaendert | Guard-Engine/Adapter-/Registrierungs-Ownership |
| `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md` | geaendert | importierbare Deployment-/Vertragspaket-Grenzen und Gate-Owner |
| `PROJECT_STRUCTURE.md` | geaendert | drei paketierte Artefakte, Quell- und Test-Heimaten |
| `concept/formal-spec/architecture-conformance/{entities,invariants}.md` | geaendert | maschinenlesbare Distribution-/Import-Invarianten |
| `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md` | Referenz/ggf. im selben Diff | bestehende PO-Entscheidung und W4-Anker; keine Neuentscheidung |

## Akzeptanzkriterien

1. **FK-10 besitzt das Zielbild.** §10.1.1/§10.1.2/§10.1.3 benennt fuer
   Edge, Kern und Vertragspaket Prozess, Lebensdauer, Startakteur,
   Netzrichtung, State-Ownership, lokale Engine und Deployment-Artefakt. Die
   Laptop-Nichterreichbarkeit ist explizit: nur Edge->Kern HTTP, nie
   Kern->Laptop.
2. **FK-01 und FK-30 widersprechen der PO-Entscheidung nicht mehr.** „Duenn“
   und „regelfrei“ werden so praezisiert, dass lokale Guard-Evaluation und
   fs/worktree-gebundene Ausfuehrung erlaubt und gefordert sind, ohne lokale
   kanonische Wahrheit oder freie Fachautoritaet einzufuehren.
3. **Die Ownership-Matrix ist vollstaendig, soweit sie AG3-208 gehoert.**

   **ZUSCHNITTKORREKTUR 2026-08-07 (Orchestrator), nach dem dritten
   AC-10-Review.** Die urspruengliche Fassung verlangte hier die vollstaendige
   Klassifikation **auch der Backend-Subpakete**. Drei Reviewrunden haben
   gezeigt, dass diese Klassifikation ohne Messung nicht zu haben ist: Sie
   wurde dreimal behauptet und dreimal widerlegt — zuletzt stand `cli` als
   „vollstaendig Edge" zehn Zeilen neben der Feststellung, dass es geteilt ist.
   Eine Klassifikation ohne Messung ist keine Spezifikation, sondern eine
   Vermutung mit Zahlen daran.

   **Die Klassifikation der 44 Backend-Subpakete ist deshalb aus dieser Story
   herausgenommen und Gegenstand von AG3-237** (Zaehleinheit definieren,
   messen, zuordnen). AG3-208 liefert dafuer die Regel
   (`symbol_boundary_is_the_rule`), den Mechanismus (`NOT_RUN` statt `PASS`,
   solange die Klassifikation offen ist) und die Feststellung, dass es 44 sind.

   **Was AG3-208 weiterhin vollstaendig festlegt:** die drei Artefakte und ihre
   Importwurzeln, `frontend`, `integration_clients`, `bundles`, Paket-Root,
   jede beim Schnitt vorhandene Deployment Unit, die Drittsystem-Adapter und
   jede Runtime-Dependency aus `pyproject.toml` — je mit genau einem
   begruendeten Artefaktbesitzer.

   Das Vertragspaket enthaelt nur beidseitig benoetigte HTTP-/Wire-Modelle und
   ist ein I/O-freies Blatt; es wird kein Ablageort fuer beliebigen
   Shared-Code. **Sein Inhalt** wird von AG3-237 spezifiziert — hier steht nur
   die Regel, die er erfuellen muss.
4. **Entry-Point- und Namensvertrag ist eindeutig.** Fuer jedes heutige
   Console-Script und jedes CLI-Verb ist festgelegt, welche Distribution es
   ausliefert und auf welcher Maschine es laeuft. Es gibt keinen Alias, Shim,
   Re-Export oder Zeitraum mit beiden Wegen.
5. **Installer, Bundle und MCP sind im Zielbild enthalten.** Das Konzept sagt,
   welche Distribution Projektregistrierung/Update/Detach, Hook- und
   MCP-Registrierung, ProjectEdge-Launcher und lokal gestartete MCP-Server
   ausliefert. Die zugehoerigen Dependencies folgen dem Laufzeitbesitzer und
   nicht dem historischen Namespace.
6. **Maschinelle Grenze ist spezifiziert.** Die Formal-Spec definiert mindestens:
   Kern darf Edge nicht importieren; Edge und Kern duerfen nur das
   Vertragspaket teilen; das Vertragspaket importiert weder Edge noch Kern;
   Wheel-/Dependency-Reachability prueft die gebauten Artefakte; eine
   Clean-Edge-Installation muss ohne jede als kern-only klassifizierte
   Distribution/Dependency einen echten Hook ausfuehren. Das Gate ist
   blockierend, baseline-frei und unterscheidet „nicht gelaufen“ von PASS.
7. **Realitaetsnachweis des Ist-Befunds:** In einer wegwerfbaren, zuvor leeren
   venv auf Windows oder macOS wird das heutige Einzel-Wheel installiert. Der
   Nachweis listet die tatsaechlich installierten Distributionen, belegt die
   Anwesenheit der Kern-Dependencies und fuehrt einen echten
   `agentkit-hook-claude`- oder `agentkit-hook-codex`-Prozess mit realem stdin
   aus. Das Ergebnis darf den Ist-Zustand rot/belegt zeigen; ein Unit-Test oder
   `pip --dry-run` ersetzt diesen Lauf nicht.
8. **Konzept-Impact-Sweep und W4 sind vollstaendig.** Alle normativen Treffer
   fuer „ein Paket“, `agentkit`-Distribution, Installer-/CLI-Heimat,
   Guard-Engine und Deployment Unit werden namentlich bewertet. Decision
   Record im Diff oder Commit-Trailer
   `Concept-Decision: 2026-08-03-edge-und-kern-sind-zwei-distributionen`;
   Betroffenheitsmatrix und `check_concept_decision_record.py` sind gruen.
9. **Deterministische Konzept-Gates gruen:**
   `check_concept_frontmatter.py`, `compile_formal_specs.py`,
   `check_concept_reference_integrity.py`, `check_concept_code_contracts.py`,
   `check_architecture_conformance.py` und
   `check_concept_decision_record.py`. W2/W3 sind kein Abnahmekriterium und
   werden nicht als „gruen“ ueberbehauptet.
10. **Unabhaengiges Konzeptreview:** Ein anderer Principal in einer anderen
    Session prueft (1) normative Zielstellen/Scope-Owner, (2) innere und
    bestandsweite Widerspruchsfreiheit, (3) Problemraum und Umsetzbarkeit ohne
    eigene Annahmen. Befunde werden an der Wurzel behoben; „nicht pruefbar“ ist
    niemals PASS.

## Definition of Done

- AC 1-10 erfuellt, jeweils mit Locator, Kommando oder Reviewbeleg.
- Der Ist-Realitaetsnachweis aus AC 7 liegt mit Environment-Inventar und
  vollstaendiger Hook-Ausgabe im Story-Record.
- Alle deterministischen Konzept-Gates sowie Jenkins und Sonar gemaess
  `AGENTS.md` gruen; Sonar `violations=0`, `critical_violations=0`,
  `security_hotspots=0`.
- Unabhaengiges Review erreicht eines der Abbruchkriterien aus `CLAUDE.md`.
- **AG3-237** wird nach `status: completed` dieser Story `ready`; **AG3-209** erst nach `status: completed` von AG3-237. AG3-208 allein entblockt AG3-209 nicht — die Klassifikation der 44 Backend-Subpakete fehlt bis dahin.

## Beantwortete Fragen — PO-Entscheidung 2026-08-03

Die drei beim Schnitt offenen Fragen sind entschieden. Sie sind hier
festgehalten, weil AG3-209 sie umsetzt und nicht neu aufwerfen darf.

**F1 — Artefaktnamen. `agentkit` gehoert keinem der beiden Artefakte.**
„AgentKit" ist der **Framework-Name**. Das Framework hat ein Backend und einen
Client (Project Edge); die Artefaktnamen sind entsprechend **zusammengesetzt**.
Keine Distribution traegt den blossen Namen `agentkit`, und keine
beansprucht ihn allein.

**Abgeleitete Folge — der Importname faellt mit.** Diese Folge trifft AG3-209,
nicht den PO, und ist hier nur zur Sichtbarkeit notiert: AK2 liefert ein
**regulaeres** Paket namens `agentkit` aus. Ein regulaeres Paket und
Namespace-Portionen gleichen Namens koennen in einer Umgebung nicht
verlaesslich koexistieren — das zuerst gefundene regulaere Paket verdeckt die
uebrigen vollstaendig. Behielte AK3 `agentkit.*` als Importwurzel, waere der
Zustand vom 2026-08-02 reproduziert, und zwar genau dort, wo er weh tut: auf
dem Entwicklerrechner, auf dem AK2 ebenfalls liegt. Jedes Artefakt bekommt
deshalb eine **eigene, kollisionsfreie Importwurzel**.

**Damit ist der AK2-Namenskonflikt aufgeloest, nicht laenger nur isoliert.**
`AG3-189` haelt fest, eine Umbenennung waere „eine eigene Grundentscheidung"
und der Konflikt werde vorerst nur isoliert. Diese Grundentscheidung ist mit
F1 getroffen. Die Wirkung auf AG3-189 ist vom PO zu bewerten, **nicht** von
AG3-209 stillschweigend mitzuerledigen.

**F2 — Versionierung ist synchron und haengt am Repository-Stand.**
Beide Artefakte werden aus **einem** Repository gebaut und tragen dieselbe
Version. Keine unabhaengigen SemVer-Reihen, kein Kompatibilitaetsbereich,
keine Matrix — eine Matrix waere die Kompatibilitaetsschicht, die
`CLAUDE.md` ausnahmslos verbietet. Der bestehende `/v1/compat`-Handshake
(AG3-121) deckt die Drahtebene ab; mehr ist nicht vorzusehen.

**F3 — Der Story-Knowledge-MCP und `weaviate-client` gehoeren zum Edge.**
Der heute vom Harness lokal gestartete Prozess
(`mcp_server_registration.py:151-160`) laeuft auf dem Entwicklerrechner und
bleibt dort. `weaviate-client` ist damit eine **Edge-Abhaengigkeit**. Das ist
eine bewusst getragene Last: der Rand wird dadurch nicht so duenn, wie er es
ohne diese Abhaengigkeit waere. Die Alternative — Suche ueber den Kern
vermitteln — haette jede Abfrage auf den Netzweg gelegt; der PO hat sich
dagegen entschieden.

## Konzept-Referenzen

- `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md`
- `concept/technical-design/10_runtime_deployment_speicher.md`
  §10.1.0-§10.1.3, §10.2, §10.2.7
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md`
  §1.1, §1.2.2, Trust Boundaries
- `concept/technical-design/30_hook_adapter_guard_enforcement.md`
  §30.2, §30.3, §30.11
- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.7-§7.9
- `concept/formal-spec/architecture-conformance/`

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS“ — ein
  Zielpfad, keine Uebergangsarchitektur.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT“ — jeder Code- und
  Vertragstyp hat genau eine Heimat.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN“ — AC 7.
- `AGENTS.md` deterministische Konzept-Gates und unabhaengiges
  Drei-Achsen-Review fuer normative Aenderungen.
