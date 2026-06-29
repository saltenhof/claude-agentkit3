# AG3-122: Install-Dreifaltigkeit — ebenen-spezifische Lifecycle-Verben (`serve`/`update`/`detach`/`decommission`)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `installation-and-bootstrap` (FK-10/FK-50/FK-51) + `cli` (Operator-Adapter). FK-10 §10.2.0 definiert drei Installationsebenen (Dreifaltigkeit): **1 Zentral (Core)**, **2 Entwicklermaschine**, **3 Projektraum** — jede mit eigener Install/Update/Uninstall-Semantik und **getrennten** Verben. Das CLI traegt heute ein Grundgeruest (`register-project`, `verify-project`, `upgrade-project`, `serve-control-plane`, generisches `install`/`uninstall`), aber die ebenen-spezifischen Lifecycle-Verben des SOLL fehlen (`serve`, `update`, `detach`, `decommission`) und das generische `install` konflatiert Ebenen. Die Story zieht die CLI-Verben an die Dreifaltigkeit heran.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.2.0` — Die drei Installationsebenen (Dreifaltigkeit): je eigene Install/Update/Uninstall-Semantik; „der Installer" ohne Qualifizierung = **nur Ebene 3** (`register-project`); Grundregel: eine niedrigere Ebene loescht nie kanonischen Zustand einer hoeheren (`10_runtime_deployment_speicher.md:270-287`).
- `FK-10 §10.2.5` — Ebene 1 Bootstrap des Core: `agentkit serve --ui-bff`, `agentkit serve --project-api`, `agentkit ui` (`10_runtime_deployment_speicher.md:421-445`; Port-/Befehlstabelle `:870-871`, `:907-908`).
- `FK-10 §10.2.6` — Ebene 2 Provisionierung der Entwicklermaschine (`agentkit`-Paket + immutable Bundle-Store) (`10_runtime_deployment_speicher.md:447-466`).
- `FK-10 §10.2.8` — Update-Treibermodell: hybrid, `agentkit update` zieht Paket-/Bundle-Version lokal auf Server-Hinweis; kein Server-Push von Executables (`10_runtime_deployment_speicher.md:494-524`).
- `FK-10 §10.2.9` — Uninstall/Decommission mit getrennten Verben: **Projekt-Detach** (Ebene 3), **Maschinen-Uninstall** (Ebene 2), **Core-Decommission** (Ebene 1, destruktiv, Pflicht-Export) (`10_runtime_deployment_speicher.md:526-545`).
- `FK-50 §50.2` — `register-project`/`verify-project` (Checkpoint-Installer, Ebene 3); `FK-51 §51.9` — operative Uninstall-/Decommission-Mechanik (`51_upgrade_migration_customization_preservation.md`).
- `FK-91 §91.1a` — `GET /v1/compat`: das Versionsfenster, das `agentkit update` (§10.2.8) liest (`91_api_event_katalog.md:107`); der Endpunkt selbst ist AG3-121.
- `FK-43 §43.4.1.1` — Symlink/Junction-Erkennung und sichere Entfernung (`isjunction`-Check vor `unlink`/`rmdir`, nie `rmtree` durch den Link); normative Basis fuer den `detach`-Footgun-Schutz.

---

## 1. Kontext / Ist-Zustand (belegt)

> Re-verifiziert gegen `src/agentkit/backend/cli/main.py`. Deckt sich mit WP-F.

- **F1 — Vorhandene Verben:** `install` (Parser `:58`, Dispatch `:329`), `uninstall` (Parser `:147`, Dispatch `:330`), `register-project` (Dispatch `:331`, Parser `:668`, Handler `:814`), `verify-project` (`:332`, Parser `:704`, Handler `:841`), `upgrade-project` (`:333`, Parser `:876`, Handler `:907`), `serve-control-plane` (Dispatch `:340`, Parser `:253-254`, Handler `:1283`). Grundgeruest da.
- **F2 — `install` konflatiert Ebenen:** `install` (`cli/main.py:58-115`, „Install AgentKit into a target project") steht neben dem ebenen-spezifischen `register-project`; das SOLL kennt fuer Ebene 3 nur `register-project` (FK-10 §10.2.0: „der Installer" = nur Ebene 3). Generisches `install`/`uninstall` mischt Ebene-2/3-Semantik (Mark & Ask #5: zugunsten ebenen-spezifischer Verben zurueckbauen).
- **F3 — bare `serve` fehlt:** nur `serve-control-plane` (`:253-254`) existiert; SOLL §10.2.5 verlangt `agentkit serve --ui-bff` / `agentkit serve --project-api` (und `agentkit ui`). Ein blankes `serve` mit Profil-Flags ist absent.
- **F4 — `update` fehlt:** kein `update`-Subparser; SOLL §10.2.8 verlangt den hybriden Update-Treiber `agentkit update` (Ebene-2-Pull auf Server-Hinweis). Absent.
- **F5 — `detach`/`decommission` fehlen:** nur generisches `uninstall` (`:147`). SOLL §10.2.9 verlangt ebenen-getrennte Verben: **Projekt-Detach** (Ebene 3), **Maschinen-Uninstall** (Ebene 2), **Core-Decommission** (Ebene 1). Absent.

## 2. Scope

### 2.1 In Scope

1. **`agentkit serve` (Ebene 1, §10.2.5):** ein `serve`-Subparser mit Profil-Flags `--ui-bff` und `--project-api` (Ports gemaess `10_..:907-908`: 9701/9702) **plus `agentkit ui`** (Frontend-Bereitstellung, §10.2.5). `serve` ist der kanonische Bootstrap-Befehl des Core. `serve-control-plane` wird zum **Compat-Alias** auf `serve --project-api` zurueckgebaut — **eine** Implementierung, kein Parallel-Transport (FIX THE MODEL), kein zweiter Serve-Pfad. **Port-/Cert-Migration belegen:** der heutige `serve-control-plane`-Default (`9080`, `--certfile`/`--keyfile`-Pflicht, `cli/main.py:253-260/1283`) geht in `serve --project-api` (Default `9702`) ueber; die Cert/Key-Flags bleiben funktional kompatibel; der Alias delegiert nachweislich auf dieselbe Serve-Implementierung.
2. **`agentkit update` (Ebene 2, §10.2.8):** ein `update`-Subparser als hybrider Update-Treiber, der die lokale Paket-/Bundle-Version auf Server-Hinweis aktualisiert (Pull, kein Server-Push). Liest das Kompatibilitaets-Fenster (`min`/`recommended`/`blocked`) vom Core (`GET /v1/compat`, AG3-121) und meldet fail-closed, wenn die lokale Runtime unter `min`/in `blocked` liegt. Re-Install-Pflicht-Hinweis (laufende Harness-Sessions neu starten) gemaess §10.2.8.
3. **`agentkit detach` (Ebene 3, §10.2.9):** Projekt-Detach — entfernt Skill-Junctions, AK3-Hook-Registrierung (nur AK3-Bloecke, chirurgisch), Project-Edge-Launcher und `.agentkit/`-Bindungen; **bewahrt** Projektcode, fremde Hooks und den zentralen State des Projekts. Junction-Entfernung nur via `unlink`/`rmdir` nach `isjunction`-Check, nie `rmtree` durch den Link (Footgun-Schutz §10.2.9).
4. **`agentkit decommission` (Ebene 1/2, §10.2.9):** ebenen-getrennte Uninstall-Verben:
   - **Maschinen-Uninstall** (Ebene 2): `agentkit`-Paket + Bundle-Store + Shims; gepinnte Projekte vor Bundle-Entfernung als `orphaned` warnen.
   - **Core-Decommission** (Ebene 1): Backend-/Frontend-Dienste, ggf. DB — **destruktiv**, nur nach expliziter Bestaetigung **und** Pflicht-Export des State-Backends (Audit-Trail/Closure/QA). Kopplung von DB-Volume-Loeschung an Dienst-Uninstall (`down -v`) ist verboten.
   Die Ebenen-Zuordnung ist typisiert (Flag/Subkommando), nicht als String-Kaskade.
5. **`install`/`uninstall`-Konflation aufloesen (F2, Mark & Ask #5):** das generische `install` wird zugunsten der ebenen-spezifischen Verben zurueckgebaut. Verbindlich entschieden: generisches `install`/`uninstall` wird **retired** und auf die richtigen Ebenen-Verben (`register-project` fuer Ebene 3, `decommission` fuer Ebene 1/2, `serve` fuer Ebene 1) abgebildet; falls Abwaertskompatibilitaet noetig ist, bleibt hoechstens ein **explizit** dokumentierter, deprecated Compat-Alias (kein stiller Doppel-Pfad).
6. **Grundregel-Durchsetzung (§10.2.0/§10.2.9):** jedes Uninstall-Verb erzwingt fail-closed, dass eine niedrigere Ebene **keinen** kanonischen Zustand einer hoeheren loescht (Negativpfad: `detach` ruehrt zentralen Projekt-State nicht an; `decommission --core` verlangt Pflicht-Export).

### 2.2 Out of Scope (mit Owner)

- **Checkpoint-Engine / `register-project`-Interna** (Ebene-3-Registrierung, CP1-CP12) — **AG3-088** / FK-50; bereits vorhanden (`cli/main.py:668`), wird hier nicht umgebaut.
- **`upgrade-project`-Mechanik** (Re-Bind/Re-Run, Customization-Preservation) — **AG3-089** / FK-51; vorhanden (`:876`), nicht Teil dieser Story. `update` (Ebene 2) und `upgrade-project` (Ebene 3) bleiben getrennte Verben.
- **`GET /v1/compat`-Endpunkt + Server-Handshake** — **AG3-121** (WP-G). `update` konsumiert den Endpunkt, baut ihn nicht.
- **Tatsaechliche Core-Bootstrap-Routine / DB-Migrationsschritte** (§10.2.5 manuelle Anteile, ops-getrieben) — Owner Ops; `serve`/`agentkit ui` starten die Dienste, provisionieren aber weder Postgres noch fuehren sie die DB-Migration aus.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/cli/main.py` | Aendern (Subparser `serve`/`ui`/`update`/`detach`/`decommission` + Dispatch-Map; `serve-control-plane`/`install`/`uninstall` retire/alias) |
| `src/agentkit/backend/installer/runner.py` | Aendern (Detach/Decommission-Teardown; sichere Junction-Entfernung statt `_remove_tree`/`shutil.rmtree` `:2229`/`:2243`; `orphaned`-Warnung) |
| `src/agentkit/backend/installer/` (neue Lifecycle-/Update-Module fuer `update`/`detach`/`decommission`) | Neu |
| `src/agentkit/backend/control_plane_http/` bzw. `harness_client/` (Compat-Lese-Surface fuer `update`) | Aendern (konsumiert `GET /v1/compat`, AG3-121) |
| `tests/integration/installer/**`, `tests/unit/cli/**`, `tests/contract/**` | Neu/Aendern (echte FS-Integration: Temp-Projekt, Junction create/unlink; serve-Single-Impl; update-fail-closed; decommission-Schutz) |

## 3. Akzeptanzkriterien

1. `agentkit serve --ui-bff`, `agentkit serve --project-api` und `agentkit ui` existieren, starten die jeweiligen Profile (Ports 9701/9702 gemaess FK-10) und teilen sich **eine** Serve-Implementierung mit dem zurueckgebauten `serve-control-plane` (Compat-Alias); ein Test belegt, dass kein zweiter Transport-Pfad entsteht und der Alias auf dieselbe Implementierung delegiert (inkl. Port-Default-Migration `9080`→`9702` und Cert/Key-Flag-Kompatibilitaet).
2. `agentkit update` existiert, liest das Kompatibilitaets-Fenster vom Core (`/v1/compat`, FK-91 §91.1a) und meldet fail-closed (Nicht-PASS-Exit), wenn die lokale Runtime unter `min`/in `blocked` liegt; ein Test deckt den fail-closed-Pfad und den Re-Install-Hinweis ab.
3. `agentkit detach` entfernt nur AK3-Bindungen (Junctions, AK3-Hook-Bloecke, Edge-Launcher, `.agentkit/`) und laesst Projektcode, fremde Hooks und zentralen Projekt-State unangetastet. **Echter FS-Integrationstest (keine Stub-Absicherung):** reales Temp-Projekt mit echtem Symlink/Junction (Windows-Junction wo plattformseitig moeglich) und echtem **fremdem** Hook-Block; der Test beweist, dass `unlink`/`rmdir` nach `isjunction`-Check verwendet wird, der Bundle-Store-Zielinhalt **ueberlebt** (kein `rmtree` durch die Junction, FK-43 §43.4.1.1) und fremde Hook-Bloecke erhalten bleiben; Negativpfad: `detach` loescht **keinen** kanonischen Zustand (Grundregel §10.2.0/§10.2.9).
4. `agentkit decommission` trennt Maschinen-Uninstall (Ebene 2, `orphaned`-Warnung) von Core-Decommission (Ebene 1, destruktiv): Core-Decommission verlangt explizite Bestaetigung **und** Pflicht-Export und koppelt DB-Volume-Loeschung **nicht** an den Dienst-Uninstall (`down -v` verboten). **Echte Tests** fuer beide Ebenen inkl. Abbruch ohne Bestaetigung/Export (fail-closed) und Nachweis, dass das DB-Volume bei Dienst-Uninstall erhalten bleibt.
5. Generisches `install`/`uninstall` ist retired bzw. nur als explizit deprecated Compat-Alias vorhanden; ein Test belegt, dass die Ebenen-Semantik nicht mehr konflatiert ist (jede Ebene hat ihr eigenes Verb).
6. Alle neuen Verben sind im CLI-Dispatch (`cli/main.py` Kommando-Map) registriert und als Operator-Adapter auf die jeweilige Bootstrap-/Update-/Teardown-Logik verdrahtet (kein Stub-Echo als „done").
7. **Testpyramide / keine Stub-Absicherung (testing-guardrails §2):** Lifecycle-Verben, die FS/Junctions/Registrierung anfassen (`detach`/`decommission`), werden **nicht** durch Mocks der Removal-/FS-Logik unter Test erfuellt, sondern durch echte Filesystem-Integrationstests; Unit-Tests decken die reine Dispatch-/Flag-Logik ab.
8. **ARCH-55:** Subkommando-Namen, Flags, Exit-Codes und Bezeichner englisch; keine `noqa`/`type: ignore` ohne Begruendung.
9. **Quality-Gates gruen** (aus Repo-Root, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`, `.venv\Scripts\python -m pytest` (unit/integration/contract), Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`);
   - `.venv\Scripts\python -m mypy src` (strict) **und** `--platform linux`, `.venv\Scripts\python -m ruff check src tests`;
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`;
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–9 erfuellt; ebenen-spezifische Verben (`serve`/`ui`/`update`/`detach`/`decommission`) real verdrahtet; `serve-control-plane`/`install`-Konflation aufgeloest mit **einer** Serve-Implementierung (kein Parallel-Pfad).
- Grundregel (§10.2.0/§10.2.9: niedrige Ebene loescht nie hohen kanonischen State) fail-closed durchgesetzt und durch **echte FS-Integrationstests** belegt.
- Pflichtbefehle + Konzept-Gates gruen; **Jenkins-Build gruen, SonarQube Zero-Violation gruen** (AC 9); QA-Subflow/Code-Review PASS; Status erst nach belegtem Diff + gruenen Befehlen auf `completed`.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** die Verben folgen der fachlichen Dreifaltigkeit (Ebene 1/2/3), nicht kurzfristiger CLI-Bequemlichkeit; `serve-control-plane`/`install` werden an das Soll-Modell herangezogen statt durch neue Sonderpfade stabilisiert.
- **SINGLE SOURCE OF TRUTH:** **eine** Serve-Implementierung (Alias statt zweitem Transport); jede Ebene hat genau **ein** Lifecycle-Verb-Set.
- **FAIL CLOSED:** Uninstall-Verben erzwingen die Grundregel (keine Loeschung hoeheren kanonischen States durch niedrigere Ebene); Core-Decommission ohne Bestaetigung/Export bricht ab.
- **ZERO DEBT / NO ERROR BYPASSING:** keine Stub-Verben; die `install`-Konflation wird nicht stillschweigend doppelt weitergetragen.
- **Testing-Guardrails (`guardrails/testing-guardrails.md`):** Lifecycle-Verben gegen echtes Filesystem (Temp-Projekt, echte Junction/Symlink), nicht gegen Stubs der Removal-Logik (§2); Precondition-Enforcement (Bestaetigung/Export bei Decommission) nachgewiesen.
- **ARCH-55:** englische Verb-/Flag-/Exit-Bezeichner.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Anknuepfungspunkt: `src/agentkit/backend/cli/main.py` — Subparser-Block (`:58` ff.) und die Kommando-Dispatch-Map (`:329-340`). `serve-control-plane`-Handler `:1283` ist die Basis fuer `serve`; nicht duplizieren, sondern darauf aliasen.
- Reihenfolge: zuerst `serve` (+ `serve-control-plane`-Alias) als saubere Basis, dann `update` (konsumiert `/v1/compat` aus AG3-121), dann `detach`, dann `decommission` (Ebene-2/1-Trennung). `install`/`uninstall`-Konflation zuletzt aufloesen, wenn die Ziel-Verben stehen.
- Footguns strikt beachten (§10.2.9): nie `rmtree` durch eine Junction; `isjunction`-Check vor `unlink`/`rmdir`; AK3-Hook-Bloecke chirurgisch entfernen; keine `down -v`-Kopplung. AK2 NICHT beschaedigen (geteilter Paketname `agentkit`).
- `register-project`/`verify-project`/`upgrade-project` NICHT umbauen (AG3-088/089-Owner). `.mcp.json`/AK2 NICHT anfassen. Kein Commit ohne Auftrag.
- „done" nur mit Beleg: Diff, Testnamen (serve-Profile + Single-Impl, update-fail-closed, detach-Negativpfad, decommission Ebene-2/1, install-Retire), gruene Pflichtbefehle.

## 7. Vorbedingungen

- **`depends_on: ["AG3-121"]`** — `agentkit update` (Ebene 2) liest das Kompatibilitaets-Fenster ueber `GET /v1/compat` (AG3-121); ohne den Endpunkt ist der Update-Server-Hinweis nicht real testbar. Erst startbar, wenn AG3-121 `completed` ist.
- `unblocks`: keine.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed).
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
