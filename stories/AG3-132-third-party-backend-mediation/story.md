# AG3-132: Backend besitzt die Drittsystem-Erreichbarkeits-Validierung; der Installer prueft nicht mehr direkt (I2)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `installation-and-bootstrap` (Installer-Checkpoints) + zentrale Server-Schicht `control_plane_http` (nur **Host/Router**). Fachlicher Owner der Validierung ist ein **Kern-Service** (in-process Capability, z. B. `installation_and_bootstrap`/`third_party_preflight`) — **nicht** `verify_system` als HTTP-Surface (reconciled FK-72: „Verify = kein HTTP-Owner"); der Sonar-Gate-Owner `verify_system` bleibt reine in-process Capability und wird hier nicht als HTTP-Mount beruehrt. Fachlich geht es um die **Drittsystem-Hoheit des Kerns** (FK-10 I2) an der **einen** Stelle, die NICHT durch die kern-seitige Phasenausfuehrung abgedeckt wird: dem **Installer-Register/Verify-Preflight**. Heute instanziiert der Installer `SonarClient`/`JenkinsClient` dev-seitig und prueft Drittsystem-Erreichbarkeit/Config selbst. Diese Story verlagert das **Treiben/Erreichen** der Drittsysteme in den **Kern** und laesst den Installer nur noch das (fail-closed durchgereichte) Backend-Ergebnis konsumieren.

> **Neuschnitt (ersetzt den urspruenglichen Zuschnitt vollstaendig).** Der urspruengliche Plan — dedizierte `verify_system/http`- und `closure/http`-Mediations-Routen — ist **hinfaellig**: Diese Mounts sind zurueckgebaut (Commit `95d5ac1`) und kollidieren direkt mit dem rekonziliierten FK-72 §72.8.2 („Verify = in-process Capability-Subflow, **kein HTTP-Owner**"). Die **phasen-seitige** Sonar/Jenkins/ARE-Hoheit (Implementation-QA-Subflow, Closure-Pre-Merge) ist damit **kein** Gegenstand dieser Story mehr — sie folgt aus der **kern-seitigen Phasenausfuehrung** (AG3-130-Achse + breitere In-Process→Server-Migration). Uebrig bleibt exakt der Installer-Preflight, und der wird hier geerdet.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I2` (Drittsystem-Hoheit): In AK3-verantworteten Vorgaengen treibt **der Kern** ARE/GitHub/SonarQube/Jenkins/LLM-Hub. Eine Dev-Komponente, die in einem AK3-Vorgang ein Drittsystem am Kern vorbei beruehrt (ausserhalb des git-Carve-out), ist Fehlbetrieb.
- `FK-01 §1.1a` (Zwei-Kriterien-Carve-out): direkter Dev→Infra-Zugriff nur fuer Agent-Eigenbedarf oder AK3-mandatierte fs/worktree-Mechanik (`gh`/`git`). API-/Kontroll-Pfade (Sonar-Reachability/Gate, Jenkins-Reachability/Build-Status, ARE-Abruf) sind **kern-vermittelt**.
- `FK-50 §50.2 / §50.3` (Installer-Checkpoints, **Konzept-Aenderung in Scope**): Register/Verify-Checkpoints und die CP-10d-Pflichtpruefungen (Sonar/Jenkins-Verfuegbarkeit, Branch-Plugin, Conformance-Self-Test). Diese Story schaerft §50.3 so, dass die Drittsystem-Erreichbarkeit **kern-validiert** ist, nicht dev-seitig.
- `FK-33 §33.6` (Sonar-Green-Gate-Semantik) / `FK-27 §27.6a` — bleiben **unveraendert** (Gate-Logik lebt im `verify_system`-BC; diese Story aendert nur den **Erreichbarkeits-Preflight**, nicht die Gate-Semantik).
- `FK-72 §72.8.2` (reconciled): kanonische Server-Surface `control_plane_http`; neue HTTP-Surface nur bei verankertem Konsument, stereotyp gebaut (Ebene-2-Bauplan). Kein per-BC-Mount-Wiederaufbau.

---

## 1. Kontext / Ist-Zustand (belegt, re-verifiziert gegen `main`)

- **`register-project`/`verify-project` laufen rein lokal ueber die Checkpoint-Engine — ohne Backend-Kontakt:** `cli/main.py:848` `_cmd_register_project` → `installer/bootstrap_checkpoints/orchestrator.run_checkpoint_install(config, mode)` (`:854-865`). Kein REST-Client, keine `/v1`-Route wird gerufen (`urllib`-Import `:12` ist nur URL-Parsing).
- **Der Installer instanziiert die Drittsystem-Clients dev-seitig:** `cli/main.py:580` `SonarClient(base_url, token, user=sonar_user)`, `:613` `JenkinsClient(...)`; die Preflight-Logik liegt in `installer/integration_checkpoints/sonar_preflight.py`, `installer/integration_checkpoints/branch_plugin_self_test.py`, `installer/integration_checkpoints/jenkins_selftest_harness.py` und `installer/runner.py:166-226/2193-2207` (`SonarClientScannerHarness`, `_self_test`).
- **Register-Ist weicht vom FK-10-Sollbild ab:** FK-10 §10.2.1 fordert Registrierung **ueber das Backend** (`INS->>BE: Projekt registrieren (REST)`, `BE->>STATE: Projekt-Record schreiben — nur Backend, I1`) und §10.2.2 listet „AK3 Backend erreichbar (REST /v1) = **Pflicht**, CP7". Real schreibt der Installer den Register-Record aber **lokal** (Checkpoint-Engine/Repository-Adapter aus `project_root`, `installer/runner.py:1565-1587`), nicht ueber die Backend-Route. Es **existiert** eine unscoped `POST /v1/projects`-Route (`create_project`, `project_management/http/routes.py:200/506`), aber der Installer nutzt sie nicht.
- **KEINE Drittsystem-Erreichbarkeits-Validierung im Backend:** weder `control_plane_http` noch `project_management` validiert Sonar/Jenkins/ARE-Erreichbarkeit; der einzige „preflight"-Treffer `project_management/_flow_constants.py:51/72` ist ein Setup-**Phasen**-Schritt-Name, kein Check. Diese Backend-Operation ist neu zu bauen.
- **Die `integration_clients`-Adapter** (`integration_clients/{sonar,jenkins,are}/`) sind korrekt duenne R-Adapter (Transport ok). Der Verstoss ist der **Ausfuehrungsort** des Preflights: er laeuft dev-seitig statt kern-getrieben (FK-10 I2).

**Kernaussage:** Der Installer-Preflight ist die einzig verbleibende Drittsystem-Dev-Kante; sie ist real und heute nicht kern-vermittelt.

## 2. Scope

### 2.1 In Scope
1. **Kern-seitige Drittsystem-Erreichbarkeits-Validierung (neue Backend-Faehigkeit).** Eine deterministische Backend-Operation validiert fuer eine gegebene Projekt-Konfiguration die **Erreichbarkeit + Token-Gueltigkeit + leichte Config-Pruefung** (inkl. Branch-Plugin-Presence) von SonarQube und Jenkins (und ARE, `features.are`-gated), indem **das Backend selbst** die Systeme erreicht (I2).
   - **Fachlicher Owner = ein Kern-Service**, z. B. `installation_and_bootstrap`/ein dedizierter `third_party_preflight`-Service (in-process Capability). `control_plane_http` **hostet/delegiert nur** (FK-72 §72.8.2: genau ein Host; **kein** `verify_system/http`- oder `closure/http`-Mount, „Verify = kein HTTP-Owner"). Die Logik NICHT in `app.py` legen.
   - **Route (verbindlich):** projekt-skopiert `POST /v1/projects/{project_key}/installation/third-party-validation` (FK-72 §72.8.2 Ebene-2-Stereotyp). Falls die Validierung **vor** der Projektanlage laufen muss (Pre-Tenant), ist die unscoped Bootstrap-Variante zu waehlen **und** die Ausnahme in FK-72/FK-91 explizit zu begruenden — im Execution-Plan entscheiden, nicht implizit.
   - **Kontrakt:** typisierte Request/Response (Pydantic v2) mit `op_id` (Idempotenz), `X-Correlation-Id`, Version-Handshake, **Ergebnis pro System**, strukturierte `error_code`s; **Secret-Redaction** (nie Token in Logs/Antworten).
2. **Installer konsumiert das Backend-Ergebnis statt selbst zu pruefen.** Die Register/Verify-Checkpoints (`sonar_preflight`, Jenkins-Reachability) instanziieren **keinen** `SonarClient`/`JenkinsClient` mehr dev-seitig, sondern rufen die Backend-Route und reichen deren fail-closed Verdikt in die bestehende Checkpoint-Ergebnis-/Exit-Semantik durch. Die dev-seitige Client-Instanziierung (`cli/main.py:580/613`) entfaellt fuer diese Vorgaenge.
3. **CP-10d Conformance-Self-Test entkoppeln.** Der **schwere** Branch-Plugin-Conformance-Self-Test (echter Fixture-Scan, nebenwirkungsbehaftet) wird als **explizite, on-demand Backend-Operation** gefuehrt (das Backend besitzt die Sonar-Interaktion), **getrennt** von der leichten Erreichbarkeits-Validierung aus (1) — er laeuft **nicht** implizit bei jeder Registrierung.
4. **FK-50 §50.3 (+ §50.2) nachziehen (Konzept-Aenderung in Scope):** der Installer-Preflight fuer Drittsysteme ist kern-validiert; der Installer fuehrt keine direkten Sonar/Jenkins-Clients mehr. Neue Backend-Route im **FK-91-Endpunkt-Katalog** + formale Command-Contracts ergaenzen (englische Pfade/Wire-Keys/`error_code`); die 4 Konzept-Gates bleiben gruen.
5. **Logik verlagern, nicht neu bauen.** Die bestehende Preflight-/Self-Test-Logik (`sonar_preflight`, `jenkins_selftest_harness`, `SonarClientScannerHarness`) wird **server-seitig wiederverwendet/verlagert**, nicht dupliziert; `integration_clients` bleiben duenn; **kein** zweiter Transport (SSOT).
6. **Echter Pfad-Test + Negativpfade.** Integrationstest: `register-project` → reale `control_plane_http`-Validierungs-Route → Drittsystem-Adapter-Grenze (externes System als Fake-Server/-Transport zulaessig; die **AK3-Vermittlungsschicht** wird nicht gestubbt). Negativpfade: Backend unerreichbar → Installer fail-closed Exit != 0; Sonar/Jenkins unerreichbar → Backend liefert fail-closed, Installer reicht durch. Regressionspin: `register-project` instanziiert **keinen** `SonarClient`/`JenkinsClient` mehr im Dev-Prozess.

### 2.2 Out of Scope (mit Owner)
- **Phasen-seitige Sonar/Jenkins/ARE-Hoheit** (Implementation-QA-Subflow `verify_system/sonarqube_gate`, Closure-Pre-Merge `pre_merge_runner`) — **nicht hier**; folgt aus der **kern-seitigen Phasenausfuehrung** (AG3-130 + In-Process→Server-Migration). Diese Story beruehrt die Gate-Treiber in `verify_system/*/runtime_wiring.py` **nicht**.
- **Backend-Mediation des Projekt-Registrierungs-*Records* selbst** (heute lokale Checkpoint-Engine-Mutation) — **eigene Folge-Story** (dieselbe I1/I3-Achse wie AG3-129/130). Diese Story fuegt **nur** die Drittsystem-Erreichbarkeits-Validierung als Backend-Faehigkeit hinzu, die der Installer ruft; sie macht die Registrierung selbst nicht end-to-end backend-mediiert. **Praemissenabhaengigkeit s. §7.**
- **FK-33-Gate-Semantik / Stage-Registry / Accepted-Ledger** — bleibt im `verify_system`-BC, nur referenziert.
- **git/gh git-Mechanik** (push/clone/worktree/Merge) — Carve-out (FK-01 §1.1a / FK-12 §12.5).
- **Der urspruengliche `verify/closure/http`-Mediations-Zuschnitt** — verworfen (durch Rueckbau `95d5ac1` + reconciled FK-72 kontraindiziert).

### 2.3 Betroffene Dateien
| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/control_plane_http/app.py` | Neu (Drittsystem-Erreichbarkeits-Validierungs-Route; Conformance-Self-Test-On-demand-Route) |
| `src/agentkit/backend/verify_system/**` bzw. neue Kern-Service-Heimat der Validierung | Neu/Aendern (server-seitige Validierungs-/Self-Test-Faehigkeit, verlagert aus `installer/integration_checkpoints/**`) |
| `src/agentkit/backend/cli/main.py` (`_cmd_register_project`/`_add_sonar_ci_availability_flags`, `:580/:613`) | Aendern (keine dev-seitige `SonarClient`/`JenkinsClient`-Instanziierung; Backend-Route rufen, Ergebnis durchreichen) |
| `src/agentkit/backend/installer/integration_checkpoints/{sonar_preflight,jenkins_selftest_harness,branch_plugin_self_test}.py`, `installer/runner.py:166-226/2193-2207` | Aendern (Preflight-Checkpoints delegieren an Backend statt lokaler Clients; Logik server-seitig wiederverwendet) |
| `src/agentkit/harness_client/projectedge/client.py` | Aendern (Client-Methode fuer die Validierungs-Route, `ProjectEdgeClient`-Muster) |
| **Konzept (bewusste Edits, alle mitziehen — sonst Konzept-Gates rot):** `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md` §50.2/§50.3 (kern-validierter Preflight statt dev-seitiger Client/Env-Secret-Aufloesung); `concept/formal-spec/installer/{commands,invariants,state-machine}.md` (neue Backend-Preflight-Command/Invariante; Split light-validation vs. on-demand conformance-self-test; `verify-project`-Read-only-Semantik mit Live-Probe); `concept/technical-design/91_api_event_katalog.md` (neuer Endpunkt: Pfad/Methode/Request/Response/`error_code`/`op_id`/`X-Correlation-Id`); `concept/technical-design/03_*` bzw. Config-Modell-Stellen (`sonarqube.token_env`/`ci.token_env` werden **backend-seitig** aufgeloest); FK-10 §10.2.1/§10.2.2 als Sollbild-Referenz | Aendern |
| `tests/integration/**`, `tests/unit/{cli,installer}/**`, `tests/contract/**` | Neu/Aendern (register-project→Backend-Route echt; fail-closed-Negativpfade; Kein-dev-Client-Regression) |

## 3. Akzeptanzkriterien
1. **Kern erreicht die Drittsysteme:** eine `control_plane_http`-Route validiert Sonar-/Jenkins-(/ARE-)Erreichbarkeit+Token **server-seitig**; echter Integrationstest belegt, dass die Erreichung vom Backend-Prozess ausgeht (kein dev-seitiger Client).
2. **Installer prueft nicht mehr direkt:** `register-project`/`verify-project` instanziieren **keinen** `SonarClient`/`JenkinsClient` mehr im Dev-Prozess (Static-/Import-Regression + Test); sie rufen die Backend-Route und reichen das Ergebnis in die Checkpoint-/Exit-Semantik durch.
3. **Fail-closed durchgereicht:** Backend unerreichbar → Installer Exit != 0, strukturierte Meldung, **kein** dev-seitiger Fallback-Check. Sonar/Jenkins unerreichbar → Backend liefert strukturierte fail-closed Antwort, Installer bricht den Checkpoint fail-closed ab.
4. **Conformance-Self-Test entkoppelt:** der schwere Branch-Plugin-Fixture-Scan ist eine **explizite, on-demand** Backend-Operation und laeuft nicht implizit bei jeder Registrierung; die leichte Erreichbarkeits-Validierung ist davon getrennt.
5. **Gate-Semantik unveraendert:** FK-33/§27.6a-Gate-Logik und Accepted-Ledger sind **nicht** angefasst; nur der Erreichbarkeits-Preflight ist verlagert.
6. **SSOT/duenne Adapter:** `integration_clients` unveraendert duenn; kein zweiter HTTP-Transport; Korrelations-/Fehlerkontrakt konsistent.
7. **ARCH-55** englisch; keine unbegruendeten `noqa`/`type: ignore`.
8. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform): pytest unit/integration/contract `-n0`, Coverage ≥85 %; mypy `src` (strict) + `--platform linux`; ruff; die 4 Konzept-Gates (FK-50/FK-91/formal ziehen mit); Remote-Gates (Jenkins gruen, Sonar Zero-Violation New Code).

## 4. Definition of Done
- AK 1–8 erfuellt; QA-/Code-Gate (Codex-Review) PASS; Status-Update gemaess `stories/README.md`. Implementierung/Commit erst nach Execution-Plan-Freigabe; die FK-50/FK-91-Konzept-Edits werden dem Auftraggeber vor Uebernahme vorgelegt.
- Globale Akzeptanzkriterien (unten) erfuellt.

## 5. Guardrail-Referenzen
- **FIX THE MODEL / I2:** Der Kern erreicht die Drittsysteme; die Dev-Seite (Installer) konsumiert nur das Verdikt. Kein zweiter Treib-Ort.
- **FAIL-CLOSED:** nicht erreichbares Backend/Drittsystem → Abbruch, kein Bypass, kein dev-seitiger Fallback.
- **SSOT / KEINE FACHLOGIK IN ADAPTERN:** Gate-Semantik bleibt im `verify_system`-BC; `integration_clients` duenn; eine Validierungs-Heimat.
- **KONZEPTTREUE:** reconciled FK-72 §72.8.2 (kein per-BC-Mount-Wiederaufbau, Ebene-2-Stereotyp); FK-50-Aenderung explizit, nicht implizit.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ist-Anker (re-verifizieren): `cli/main.py:848` (`_cmd_register_project` → `run_checkpoint_install`), `:580/:613` (Sonar/Jenkins-Client), `_add_sonar_ci_availability_flags:732`; `installer/integration_checkpoints/{sonar_preflight,jenkins_selftest_harness,branch_plugin_self_test}.py`; `installer/runner.py:166-226/2193-2207`. Backend: `control_plane_http/app.py` (keine register-Route heute).
- **NICHT** die phasen-seitigen Gate-Treiber (`verify_system/sonarqube_gate/runtime_wiring.py`, `pre_merge_runner/runtime_wiring.py`) anfassen — das ist die Phasen-Migrations-Achse (AG3-130), nicht diese Story.
- **NICHT** die `verify_system/http`-Mounts wiederbeleben (reconciled FK-72: kein HTTP-Owner). Die neue Route lebt in `control_plane_http` (kanonischer Host).
- Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Test-Namen (inkl. Negativpfade + Kein-dev-Client-Regression), gruene Pflichtbefehle + Konzept-Gates.

## 7. Vorbedingungen / Praemissen (explizit — vor Umsetzung zu bestaetigen)
- **P1 (traegt — FK-10-Sollbild, kein neuer Entscheid):** Die Backend-Erreichbarkeit zur Register-/Preflight-Zeit ist **bereits Pflicht** (FK-10 §10.2.2: „AK3 Backend erreichbar (REST /v1) = Pflicht, CP7"; §10.2.1: Registrierung laeuft ueber das Backend). Der Installer muss den Kern also ohnehin erreichen — die Validierungs-Route zu rufen ist konzeptkonform. **Abgrenzung:** dass der Register-**Record** heute lokal geschrieben wird (Abweichung vom Sollbild, `installer/runner.py:1565-1587`) ist eine **eigene Folge-Story** (I1-Angleichung), NICHT diese; diese Story setzt nur auf der bereits geforderten Backend-Erreichbarkeit auf. Umzusetzen: Backend-URL/Auth/Version-Handshake fuer den Installer-Aufruf ueber das etablierte `ProjectEdgeClient`-/Config-Muster aufloesen (keinen neuen Discovery-Mechanismus erfinden).
- **P2 (teilweise — bestaetigt gegen Code):** Die **leichte** Validierung (Jenkins-Reachability `ci_preflight.py`, grosse Teile `sonar_preflight.py`) ist server-seitig gut wiederverwendbar (duenne, client-injizierte Protocols). **Wackelt** beim lokalen `repo_root`/Default-Profile-Check (`sonar_preflight.py:133/136`) und beim **schweren** Branch-Plugin-Conformance-Self-Test (`jenkins_selftest_harness.py` — langlaufend, Jenkins-Job/Artefakt-Polling). Konsequenz (§2.1.3): der schwere Self-Test ist eine **eigene on-demand Backend-Operation mit langlaufendem Operations-Kontrakt** (`op_id`/Operation-Status, idempotent), damit der HTTP-Request nicht blockiert; die leichte Validierung ist synchron.
- **P3 (entschieden — kein Secret-Transfer):** Die Config-Modelle fuehren **Secret-Referenzen** (`sonarqube.token_env`/`ci.token_env`, `config/models.py:291/296/380/384`), nicht Inline-Secrets. **Design:** das Backend loest diese `*_env`-Referenzen in **seiner** Umgebung auf und erreicht die Drittsysteme selbst; der Installer uebertraegt **keine** Secret-*Werte*, nur die Config-/Referenz-Payload. Redaction in Logs/Antworten Pflicht.
- **Verify-Read-only-Klarstellung:** `verify-project` (Read-only) darf Live-Backend-/Drittsystem-Reads ausloesen (Erreichbarkeits-Probe), aber **keine** mutierenden Ops; heutige CP10d-Read-only-Modi (`cp10.py:455/466`) sind entsprechend anzupassen.
- Erreichbares zentrales State-Backend + Fake-Drittsysteme fuer Integrationstests; Test-DB auf ephemerem Port.

---

## Globale Akzeptanzkriterien (verbindlich)
Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md`:
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` Exit 0 (`PYTHONPATH=src`).
- **GAC-2:** `guardrails/architecture-guardrails.md` (ARCH-NN) eingehalten; Konflikt = hart stoppen und melden.
