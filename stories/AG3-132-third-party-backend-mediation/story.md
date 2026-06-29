# AG3-132: Drittsystem-Backend-Vermittlung Sonar/Jenkins/ARE (Kern treibt, I2)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `verify-system` / `story-closure` / `installation-and-bootstrap` (querschnittlich) plus die zentrale BFF-/Server-Schicht `control_plane_http`. Fachlich geht es um die **Drittsystem-Hoheit des Kerns** (FK-10 I2): SonarQube, Jenkins und ARE werden in AK3-verantworteten Vorgaengen (Implementation-QA-Subflow, Closure-Pre-Merge, Setup-main-Green-Vorbedingung, Installer-Preflight) heute dev-/in-process instanziiert; diese Story verlagert das Treiben dieser Drittsysteme in den deterministischen Kern (REST-vermittelt). Die `integration_clients`-Adapter (Bluttyp R) bleiben unveraendert duenn; verschoben wird ausschliesslich der **Ausfuehrungsort**.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0` — Invariante **I2** (Drittsystem-Hoheit): „In von AK3 verantworteten Prozessen treibt **der Kern** ARE, GitHub, SonarQube, Jenkins und den LLM-Hub." Fail-closed: eine Dev-Komponente, die innerhalb eines AK3-verantworteten Vorgangs ein Drittsystem am Kern vorbei beruehrt (ausserhalb des Carve-out), ist Fehlbetrieb. Prozesstabelle §10.1.2: Hook/Edge/CLI sind duenne REST-Clients ohne Drittsystem-Zugriff.
- `FK-01 §1.1 / §1.1a` (Topologie und Betriebsmodell) — **Zwei-Kriterien-Carve-out**: direkter Dev→Infra-Zugriff ist auf Eigenbedarf des Agents oder von AK3 **explizit mandatierte fs/worktree-gebundene Mechanik** (`gh`/`git`) beschraenkt. API-/Metadaten-/Kontrollinteresse-Pfade (Sonar-Scan/Gate-Abfrage, Jenkins-Build/Status, ARE-Evidence-Abruf innerhalb von Phasen) sind **kern-vermittelt**; git-Mechanik (push/clone/worktree) bleibt Carve-out.
- `FK-33 §33.6 / §33.6.3` — Capability `sonarqube_gate`: Green-Gate-Semantik, commit-gebundene Attestation, Accepted-Ledger. `§33.8` Schicht-Sequenz/Gate-Logik. `FK-27 §27.6a` — SonarQube-Gate-Abfolge (nach Schicht 3, vor Schicht 4) im QA-Subflow.
- `FK-29 §29.1a` — Closure Pre-Merge-Scan-und-Merge-Block (SonarQube-Green + Jenkins-Scan des integrierten Kandidaten). `FK-22 §22.4c` — Setup SonarQube-main-Green-Vorbedingung (ruft die FK-33-Capability). `FK-35 §35.2` — Integrity-Gate-Dimension 9 prueft die commit-gebundene Sonar-Attestation.
- `FK-50 §50.3` — Installer-Checkpoints: Pflicht-Pruefung von SonarQube-/Jenkins-Verfuegbarkeit, Branch-Plugin und Conformance-Self-Test als fail-closed Vorbedingung (CP 10d).
- `FK-40` — ARE-Integration (optional, `features.are`-gated). `FK-12 §12.1 / §12.5` — GitHub als Code-Backend / Worktree-Management: git-Mechanik (Carve-out, **nicht** Gegenstand dieser Story).

---

## 1. Kontext / Ist-Zustand (belegt)

Die Drittsysteme werden in AK3-verantworteten Vorgaengen **in-process auf der Dev-/Server-Seite** instanziiert; eine Backend-REST-Vermittlung existiert nicht (Grep nach `Sonar`/`Jenkins`/`AreClient` in `src/agentkit/backend/control_plane_http/` ist leer):

- **Sonar (3 Loci):**
  - `src/agentkit/backend/cli/main.py:552` — `SonarClient(base_url, token, user=sonar_user)` (Installer-Preflight; Import `:549`, Self-Test `:614`).
  - `src/agentkit/backend/verify_system/sonarqube_gate/runtime_wiring.py:366` — `SonarClient(config.base_url, token)` (Implementation-QA-Subflow `sonarqube_gate`; `_build_client` `:358`).
  - `src/agentkit/backend/verify_system/pre_merge_runner/runtime_wiring.py:207` — `SonarClient(sonar_config.base_url, token)` (Closure Pre-Merge; Import `:192`).
- **Jenkins (2 Loci):**
  - `src/agentkit/backend/cli/main.py:584` — `JenkinsClient(...)` (Installer; Import `:582`).
  - `src/agentkit/backend/verify_system/pre_merge_runner/runtime_wiring.py:177` — `JenkinsClient(ci_config.base_url, token, user=ci_config.user)` → `JenkinsCiBackend` (Closure Pre-Merge Build/Test; Import `:168`).
- **ARE (1 Locus):**
  - `src/agentkit/backend/bootstrap/composition_root.py:1857` — `AreClient(...)` in `build_are_client_from_project_config` (`:1841`), gewired aus `src/agentkit/backend/implementation/phase.py:658` (`build_are_client_from_project_config(project_config)`), `features.are`-gated.

Die `integration_clients`-Adapter (`src/agentkit/integration_clients/{sonar,jenkins,are}/`) sind duenne R-Adapter; der **Transport** ist korrekt. Der Verstoss ist der **Ausfuehrungsort**: die Treiber laufen im Dev-/CLI- bzw. in-process-Phase-Handler statt vom Kern getrieben (FK-10 I2).

**Abgrenzung (Carve-out, konform — nicht anfassen):** git push/clone/Merge via `gh`/`git` in der Closure (`src/agentkit/backend/closure/multi_repo_saga.py` `git push`, `closure/merge_sequence.py` Subprocess) ist fs/worktree-gebundene Mechanik (FK-01 §1.1a, FK-12 §12.5) und bleibt direkte Dev-Kante.

> Hinweis: Saemtliche `pfad:zeile` sind gegen den aktuellen `main`-Stand re-verifiziert (Code liegt unter `src/agentkit/backend/`). Vor Umsetzung erneut per Grep/Read bestaetigen, da Vorgaenger-Stories Zeilen verschieben koennen.

## 2. Scope

### 2.1 In Scope

1. **Backend-REST-Vermittlung fuer Sonar, Jenkins und ARE** in der zentralen Server-Schicht (`control_plane_http` + zugehoerige BC-`http/`-Module `verify_system`, `closure`, ggf. `installer`/Setup), sodass die Treiber-Aufrufe in AK3-verantworteten Vorgaengen vom **Kern** ausgehen. Konkret kern-vermittelt werden:
   - Implementation-QA-Subflow `sonarqube_gate` (heute `verify_system/sonarqube_gate/runtime_wiring.py:366`).
   - Closure-Pre-Merge Sonar-Scan **und** Jenkins-Build/Test (heute `pre_merge_runner/runtime_wiring.py:207` / `:177`).
   - Setup-main-Green-Vorbedingung (FK-22 §22.4c, ruft die FK-33-Capability).
   - **Installer-Preflight Sonar/Jenkins (CP 10d) — explizit zu entscheiden, nicht still:** der Installer (`cli/main.py:552`/`:584`) instanziiert die Clients heute dev-seitig **vor** der Projekt-Registrierung am Kern. FK-50 §50.3 modelliert den Installer als produktive Composition-Boundary, die Adapter aus lokalen Secrets baut — das kollidiert mit „kern-vermittelt". **Default dieser Story:** der CP-10d-**Reachability-/Conformance-Self-Test** bleibt eine dokumentierte Pre-Flight-Ausnahme (Registrierung laeuft, bevor die Kern-Beziehung fuer das Projekt existiert); falls er stattdessen kern-vermittelt werden muss, ist **FK-50 §50.3 mitzuziehen** (Konzept-Aenderung). Diese Entscheidung wird im Execution-Plan getroffen, nicht implizit (CLAUDE.md: Konzeptkonflikt hart melden).
   - ARE-Evidence/-Gate innerhalb der Phasen (heute `composition_root.py:1857` aus `implementation/phase.py:658`), `features.are`-gated.
6. **FK-91 + Formal-Spec mitziehen (Konzept-Aenderung in Scope):** die neuen Sonar-/Jenkins-/ARE-Vermittlungs-Routen/Service-Ports werden im FK-91-Endpunkt-Katalog und in den formalen Command-Contracts ergaenzt (englische Pfade/Wire-Keys/`error_code`); die Konzept-Gates bleiben gruen.
2. **Verlagerung der Instanziierung** von `SonarClient`/`JenkinsClient`/`AreClient` hinter Kern-seitige Service-Ports/Routen. Die `integration_clients`-Adapter bleiben **duenn und unveraendert** im Transport; verschoben wird nur, **wo** sie instanziiert/getrieben werden (Server-Prozess statt Dev/CLI/in-process). Keine zweite Transport-Heimat, kein paralleler Pfad (FIX THE MODEL / SSOT).
3. **Fail-closed-Semantik erhalten:** unbekannte/nicht-verfuegbare Drittsysteme, fehlende Tokens, ungueltige Konfiguration blocken weiterhin fail-closed (FK-33 Gate, FK-50 Preflight). Die Gate-/Stage-Semantik (FK-33 §33.6.3 commit-gebundene Attestation, Accepted-Ledger) wird **nicht** re-implementiert — sie bleibt im `verify_system`-BC; diese Story aendert nur den Treib-Ort.
4. **Typisierte Request-/Response-Kontrakte** fuer die neuen Vermittlungs-Routen/Ports (Pydantic v2), keine Ad-hoc-Dicts; Korrelations-/Fehlerkontrakt (`X-Correlation-Id`, strukturierte Fehlerantwort) konsistent mit dem Bestand.
5. **Echter Mediations-Pfad-Test (keine Mock-only-Absicherung) + Negativpfade:** ein Integrationstest treibt die reale Strecke Phase-Handler → Kern-Route/Service-Port → Drittsystem-Adapter-Grenze; das **externe** System darf ein Fake-Server/-Transport sein, die **AK3-Vermittlungsschicht selbst** wird **nicht** gestubbt. Negativpfad je Vorgang (QA-Subflow-Gate, Closure-Pre-Merge): nicht-verfuegbares Drittsystem blockt fail-closed (kein stiller Bypass, kein in-process-Fallback).

### 2.2 Out of Scope (mit Owner)

- **git/gh git-Mechanik** (push/clone/worktree/Merge in Closure) — **Carve-out**, FK-01 §1.1a / FK-12 §12.5. Wird **nicht** durch das Backend geroutet. Owner bleibt der Closure-/GitHub-Mechanik-Pfad.
- **Allgemeine In-Process→Server-Verlagerung der Pipeline/Dispatch** (Capability-503-Stubs, `project_root`/Worktree-Kopplung, WP-D) und die Kern-seitige Mediations-Grundlage, auf der diese Story aufsetzt — **AG3-125** (`depends_on`). Diese Story ergaenzt ausschliesslich die drei Drittsystem-Treiber.
- **LLM-Hub-Eval-Locus + Verify-Layer-2-Anbindung** (WP-C) — Schwester-Story **AG3-133**.
- **C2 Exploration-Fine-Design Hub-Locus** (`composition_root.py:839`) — **AG3-125** (in-process-Locus).
- **FK-33-Gate-Semantik / Stage-Registry** selbst (Attestation, Accepted-Ledger, Trust-Klassen) — bleibt im `verify_system`-BC, nur referenziert.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/control_plane_http/app.py` + `verify_system/closure/http/`-Routen | Neu/Aendern (Sonar/Jenkins/ARE-Vermittlungs-Routen) |
| `src/agentkit/backend/verify_system/sonarqube_gate/runtime_wiring.py` (`:366`), `pre_merge_runner/runtime_wiring.py` (`:177`/`:207`) | Aendern (Treiber kern-vermittelt statt in-process) |
| `src/agentkit/backend/bootstrap/composition_root.py` (`:1857`) ← `implementation/phase.py` (`:658`) | Aendern (ARE kern-vermittelt) |
| `src/agentkit/backend/cli/main.py` (`:552`/`:584`) | Aendern/Pruefen (CP-10d Pre-Flight-Entscheidung, §2.1) |
| `concept/technical-design/91_api_event_katalog.md` (+ ggf. FK-50 §50.3) + `concept/formal-spec/**` | Aendern (Vermittlungs-Endpunkt-Vertraege) |
| `tests/integration/verify_system/**`, `tests/integration/closure/**`, `tests/contract/**`, Architektur-Konformanz | Neu/Aendern (echter Mediations-Pfad, Static-Import-Check, Carve-out-Regression) |

## 3. Akzeptanzkriterien

1. In AK3-verantworteten **Phasen-Vorgaengen** (Implementation-QA-Subflow `sonarqube_gate`, Closure-Pre-Merge Sonar+Jenkins, Setup-main-Green-Vorbedingung, ARE-Phasen-Gate) gehen die Drittsystem-Treiber-Aufrufe ueber den **Kern**. **Statischer Architektur-/Import-Check (kein Mock-only):** die produktiven verify/closure/setup-Phase-Handler **importieren/instanziieren** `SonarClient`/`JenkinsClient`/`AreClient` **nicht mehr** direkt (erlaubt bleiben: die `integration_clients`-Adapter-Module selbst, type-only-Importe, Integration-Client-Unit-Tests). Installer-CP-10d gemaess Scope §2.1 (Pre-Flight-Entscheidung).
2. Es existiert eine **typisierte Backend-REST-/Service-Vermittlung** mit konkreten Vertraegen (Pydantic v2) statt eines blossen „grep nicht leer": Sonar (Scan-Trigger/Gate-/Attestation-Read), Jenkins (Build-Trigger/Status-Read), ARE (Coverage-Gate/Evidence-Read) — je mit `X-Correlation-Id`, strukturiertem `error_code`-Fehlervertrag und fail-closed-Verhalten; die `integration_clients`-Adapter bleiben im Transport unveraendert duenn.
3. **Fail-closed:** nicht-verfuegbares Drittsystem / fehlendes Token / ungueltige Config blockt den jeweiligen Vorgang (QA-Gate, Pre-Merge, Preflight) fail-closed, ohne in-process-Fallback und ohne Aufweichung der FK-33-Gate-Semantik (Negativpfad-Test je Vorgang).
4. **git/gh-Mechanik unveraendert:** der Closure-git-Pfad (`gh`/`git` push/clone/worktree) wird **nicht** geroutet/veraendert (Carve-out bleibt; Regressionstest belegt unveraendertes Verhalten).
5. **ARCH-55:** alle neuen Bezeichner, Routenpfade, `error_code`-Werte, Wire-/Schema-Felder englisch; keine unerklaerten `noqa`/`type: ignore`.
6. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest` (unit/integration/contract, `-n0`); Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py` (FK-91-Aenderung zieht diese mit).
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–6 erfuellt; QA-Gate (Codex-Review) **PASS** + Standard-Pflichtbefehle + Remote-Gates (Jenkins + Sonar) gruen.
- Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Negativpfad-Testnamen je Vorgang (QA-Gate / Pre-Merge / Preflight), Architektur-Beleg, dass die sechs Ist-Loci nicht mehr selbst instanziieren.
- Implementierung/Commit erst nach Freigabe; `depends_on` (AG3-125) muss `completed` sein.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** der Treib-Ort wird modelliert (Kern-Vermittlung), keine zweite Transport-Heimat oder Schattenpfad neben dem `integration_clients`-Adapter.
- **SINGLE SOURCE OF TRUTH:** genau **eine** Vermittlungsschicht je Drittsystem; kein in-process-Parallelpfad bleibt erreichbar.
- **FAIL CLOSED:** nicht-verfuegbares Drittsystem / fehlendes Token blockt; kein in-process-Fallback, keine Aufweichung der FK-33-Gate-Regeln.
- **NO ERROR BYPASSING:** keine Umgehung der QA-/Gate-/Preflight-Pruefungen ueber einen direkten Dev-Pfad.
- **ARCH-55:** englische Bezeichner/Pfade/Keys.
- **GAC-2 / ARCH-NN:** Architektur-Guardrails (`guardrails/architecture-guardrails.md`) verbindlich; `integration_clients/` bleiben duenne Adapter, keine Fachlogik in Adaptern. Konflikt = hart stoppen und melden.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Sechs Ist-Loci re-verifizieren (Zeilen koennen wandern): Sonar `cli/main.py:552`, `sonarqube_gate/runtime_wiring.py:366`, `pre_merge_runner/runtime_wiring.py:207`; Jenkins `cli/main.py:584`, `pre_merge_runner/runtime_wiring.py:177`; ARE `composition_root.py:1857` ← `implementation/phase.py:658`.
- **Carve-out respektieren:** git/gh push/clone/worktree NICHT durch das Backend routen (FK-01 §1.1a, FK-12 §12.5). Nur API-/Metadaten-/Kontrollinteresse-Pfade (Sonar-Scan/Gate, Jenkins-Build/Status, ARE-Evidence) werden kern-vermittelt.
- **Gate-Semantik nicht re-implementieren:** die FK-33-Capability `sonarqube_gate` (Attestation, Accepted-Ledger) bleibt im `verify_system`-BC; diese Story verschiebt nur den Treib-Ort. Bei Konflikt zwischen Story und FK-33/FK-10: hart stoppen und melden.
- Aufsatzpunkt ist die von **AG3-125** bereitgestellte Kern-seitige Server-Mediation (Sibling-Story, anderer Agent-Range). Nicht die Pipeline/Dispatch-Verlagerung (WP-D) miterledigen.
- `integration_clients`-Adapter bleiben duenn (keine Fachlogik). Kein Commit ohne Auftrag; „done" nur mit Beleg (Diff, Tests, gruene Pflichtbefehle).

## 7. Vorbedingungen

- `depends_on`: **AG3-125** (`completed`-Pflicht) — Kern-seitige In-Process→Server-Mediations-Grundlage. Solange offen: `status: blocked`.
- `unblocks`: keine.
- Diese Story zieht **FK-91 (+ ggf. FK-50 §50.3)** und die formalen Command-Contracts fuer die neuen Vermittlungs-Routen mit (Konzept-Aenderung in Scope, §2.1.6); Konzept-Gates bleiben gruen.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
