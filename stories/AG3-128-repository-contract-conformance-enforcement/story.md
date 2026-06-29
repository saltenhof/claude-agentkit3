# AG3-128: Repository-Vertrag maschinell erzwingen — Konformanz-Suite + Formal-Spec schliessen die FK-07-§7.6-Luecke

**Typ:** Implementation / **Groesse:** M / **Bounded Context:** `architecture-conformance` (Formal-Spec + deterministische Konformanz-Suite, cross-cutting). FK-07 §7.6 stellt selbst fest, dass die vollumfaengliche maschinelle Durchsetzung der komponentenspezifischen Repository-Vertraege „als Soll definiert, aber nicht Teil der maschinell erzwungenen Invarianten" ist — genau diese Luecke konnte den BFF-Durchgriff (WP-I) erst entstehen lassen. Diese Story macht den Vertrag maschinell pruefbar: BFF-/A-Code darf nicht mehr direkt an den generischen `state_backend.store`-Repos haengen, und die neu veroeffentlichten Read-Ports (Story aus AG3-126, Telemetrie aus AG3-127) werden als verbindliche Read-Surfaces gepinnt.

**Quell-Konzepte (autoritativ):**
- `FK-07 §7.6` (`concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`) — die zu schliessende Luecke: „die vollumfaengliche maschinelle Durchsetzung der komponentenspezifischen Repository-Vertraege ist als Soll definiert, aber nicht Teil der maschinell erzwungenen Invarianten dieses Kapitels." Diese Story zieht diesen Satz nach (FIX THE MODEL: Soll -> erzwungen).
- `FK-07 §7.8 + §7.9` — die maschinell erzwungenen Import-/Read-Surface-Grenzen; insbesondere §7.9 Punkt 8 (Story-Read-Loader nur auf `story.repository`), Punkt 9 (Control-Plane-Reads nur auf `control_plane.repository`) und Punkt 10 (BFF komponiert aus veroeffentlichten BC-Ports, kein Persistenz-Durchgriff). Neue Read-Surfaces (Telemetrie) und die Anti-Mega-Fassaden-Regel werden hier ergaenzt.
- `formal.architecture-conformance.invariants` (`concept/formal-spec/architecture-conformance/invariants.md`) und `formal.architecture-conformance.entities` (`entities.md`) — die maschinenlesbare SSOT der Konformanz-Suite (FK-07 §7.7).

---

## 1. Kontext / Ist-Zustand (belegt) — gegen den CURRENT-Code re-verifiziert

- **Checker:** `scripts/ci/check_architecture_conformance.py` ist ein duenner CLI-Wrapper (~96 Zeilen); die gesamte Logik liegt in `tools/concept_compiler/architecture_conformance.py`. Flow: `compile_formal_specs` -> `load_architecture_conformance_config` (liest `entities.md` + `invariants.md` in typisierte Regel-Tupel) -> `audit_architecture_conformance` (baut AST-Import-Graph, ruft die `_check_*`-Funktionen) -> `split_violations_by_severity` + `raise_on_architecture_violations` (fail-closed bei `severity="error"`).
- **Regel-Buckets (datengetrieben aus `invariants.md`, Violation-Codes im Checker):** `dependency_rules` -> **AC001**; `acyclic_group_sets` -> AC002; `mutation_surface_rules` -> AC003; `read_surface_rules` -> **AC004**; `bloodtype_dependency_rules` -> AC005; `effect_surfaces` -> AC006; `type_taint_rules` -> AC007; **AC008/AC009 sind belegt** (Modul-Completeness, `architecture_conformance.py:267/788`); Boundary-Regeln -> AC010/**AC011** (`importable_by`-Inbound-Verstoss, default **ERROR**)/AC012. **Korrektur ggue. Erst-Fassung: AC008 ist NICHT frei.** Bevorzugter Weg ist **kein** neuer Code: entweder eine `read_surface_rule` (AC004), eine `dependency_rule` (AC001) oder das Einschraenken von `boundary.state_backend_repository.importable_by` (heute `any`) -> der Checker meldet den Durchgriff dann automatisch als **AC011-ERROR**. Erst wenn keine dieser Mechaniken reicht, ein neuer Regel-Typ mit einem **freien Code nach AC012 (z. B. AC013)**.
- **Bereits vorhanden (re-verifiziert) in `invariants.md`:**
  - `dependency_rules`: `…rule.story_dashboard_control_plane_must_not_depend_on_raw_state_drivers` (`:36-44`, verbietet `postgres_store`/`sqlite_store`); `…rule.control_plane_http_must_not_depend_on_state_backend_repository` (`:51-57`, verbietet `state_backend.store` aus `control_plane_http`/`control_plane.http`).
  - `read_surface_rules`: `…rule.story_read_surface` (`:148-160`, Story-Loader nur aus `state_backend` + `story.repository`); `…rule.control_plane_runtime_read_surface` (`:161-169`).
- **Die offene Luecke (Belege):**
  - **Telemetrie-Event-Reads sind nicht gepinnt:** `load_execution_events_for_project_global` (genutzt in `telemetry/sse_stream.py:10`, nach AG3-127 in den State-Backend-Adapter verlagert) hat **keine** `read_surface_rule` — anders als die Story-Loader. Jede A-Komponente koennte ihn heute direkt importieren.
  - **`state_backend.store` ist fuer alle importierbar:** `entities.md:1354-1376` (`boundary.state_backend_repository`, Prefix `agentkit.backend.state_backend.store`) hat `importable_by: any`. Das ist das Schlupfloch hinter FK-07 §7.6: die generische Repository-Fassade ist fuer beliebigen A-Code erreichbar; nur einzelne Loader-Symbole sind via `read_surface_rules` begrenzt, nicht die Fassade als Kopplungsziel fuer Read-Modelle.
  - `boundary.control_plane_http` (`entities.md:1202-1225`) verbietet `state_backend`-Repos bereits — die Regel existiert also fuer den BFF-Entry, aber **nicht** als generelle „A-Code-Read-Modelle haengen nicht an der Mega-Fassade"-Invariante.
- **Baseline:** GAC-1 ist gruen (0 Violations). Diese Story haelt sie gruen — die neuen Regeln duerfen erst dann scharf geschaltet werden, wenn AG3-126/127 die Ports gebaut haben (sonst wuerde die Suite zu Recht rot).

## 2. Scope

### 2.1 In Scope

1. **Telemetrie-Read-Surface pinnen:** neue `read_surface_rule` in `invariants.md`, die die projekt-skopierten Execution-Event-Read-Loader (`load_execution_events_for_project_global`, ggf. weitere) ausschliesslich auf `agentkit.backend.state_backend` + die in AG3-127 veroeffentlichte Telemetrie-Read-Surface beschraenkt (analog `story_read_surface`). -> AC004, **kein** neuer Python-Code.
2. **Story-Read-Port-Vertrag haerten:** sicherstellen, dass nach AG3-126 die `story_read_surface`-Regel weiterhin greift und der Story-BC die Loader nicht mehr direkt importiert (ggf. `allowed_module_prefixes` an die neue Port-Realitaet anpassen, falls der Adapter umzieht). Keine Aufweichung — nur Praezisierung.
3. **Anti-Mega-Fassaden-Invariante fuer Read-Modelle:** den Durchgriff von BFF-/A-Code-Read-Pfaden auf die generischen `state_backend.store`-Repos verbieten. **Bevorzugter No-New-Rule-Pfad:** `entities.md` `boundary.state_backend_repository.importable_by` von `any` auf die legitimen Importeure (Composition-Root-Wiring, Owner-BC-Repository-Adapter im State-Backend) einschraenken — der Checker meldet jeden anderen Importeur automatisch als **AC011-ERROR** (kein Python-Code noetig). Alternativ/ergaenzend `dependency_rules` (Prefix-basiert, mirror/erweitern von `…control_plane_http_must_not_depend_on_state_backend_repository`). Variante so waehlen, dass **keine** legitime Verdrahtung bricht; die Wahl im Story-Bericht begruenden. Nur falls `importable_by`/Prefix-/Symbol-Regeln nachweislich nicht reichen, ein **neuer Regel-Typ** mit Dataclass + `_optional_mapping_list`-Loader + `_check_*` + **freiem Code nach AC012 (z. B. AC013)** + Checker-Contract-/Golden-Tests. **AC008/AC009 sind belegt — nicht verwenden.**
4. **FIX THE MODEL — Formal-Spec mitziehen:** zu jeder neuen ausfuehrbaren Regel den passenden deklarativen Eintrag unter `invariants:` (`scope: static-analysis`, beschreibende `id` + `rule`) ergaenzen, damit die menschenlesbare Invariantenmenge synchron bleibt (verbotene zweite Wahrheitsquelle). `version`-Felder der Spec-Dokumente hochziehen.
5. **Prosa-Nachzug FK-07 §7.6/§7.8/§7.9:** den FK-07-Satz „nicht maschinell erzwungen" entschaerfen/aktualisieren und die neue/n Invariante/n in §7.8/§7.9 als nun erzwungene Grenze benennen (FIX THE MODEL: das Konzept beschreibt das jetzt erzwungene Soll). Minimal und prazise; keine ungaenderten Regeln umschreiben.
6. **Tests:** Konformanz-Suite-Contract-/Golden-Tests, die (a) die neuen Regeln laden, (b) einen kuenstlichen Verstoss (A-Code importiert generischen `state_backend.store`-Repo / Telemetrie-Loader ausserhalb der Surface) als **ERROR** fail-closed melden, (c) den konformen Zustand (nach AG3-126/127) als 0-Violations gruen belegen. `compile_formal_specs`-/Frontmatter-Gates bleiben gruen.

### 2.2 Out of Scope (mit Owner)

- **Bau der Read-Ports selbst** — Story-Port **AG3-126**, Telemetrie-/Projekt-Port **AG3-127** (`depends_on`). AG3-128 pinnt nur, was dort gebaut wurde.
- **Andere WP-I-fremde Invarianten** (Zyklen, Mutation-Surfaces, Bloodtype) — nicht anfassen, ausser eine neue Regel beruehrt sie nachweislich.
- **503-Stub-Capabilities** (`pipeline_engine`/`execution_planning` Read-Routen, WP-D) — eigener Strang; hier nur, falls sie dieselbe Mega-Fassaden-Regel verletzen wuerden (dann melden, nicht miterledigen).

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `concept/formal-spec/architecture-conformance/invariants.md` | Aendern (neue `read_surface_rule` + ggf. `dependency_rule`; deklarative `invariants:`-Eintraege; `version`) |
| `concept/formal-spec/architecture-conformance/entities.md` | Aendern (`boundary.state_backend_repository.importable_by` von `any` einschraenken; `version`) |
| `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md` | Aendern (FK-07 §7.6/§7.8/§7.9-Prosa-Nachzug: „nicht erzwungen" → erzwungen) |
| `tools/concept_compiler/architecture_conformance.py` | **Nur falls** genuin neuer Regel-Typ noetig (Dataclass + `_check_*` + Code nach AC012); sonst unveraendert |
| `tests/unit/tools/concept_compiler/test_architecture_conformance.py`, `tests/contract/**` | Neu/Aendern (positiver Konform-Fall, kuenstlicher Verstoss → ERROR/non-zero, Formal-Spec-Round-Trip) |

## 3. Akzeptanzkriterien (nummeriert, testbar)

1. `invariants.md` enthaelt eine neue `read_surface_rule`, die die Telemetrie-Execution-Event-Read-Loader auf `state_backend` + die Telemetrie-Read-Surface (AG3-127) beschraenkt; ein Test belegt, dass ein Import dieser Loader aus beliebigem A-Code ausserhalb der Surface fail-closed als **ERROR** (AC004) gemeldet wird.
2. Der Durchgriff von BFF-/A-Code-Read-Pfaden auf die generischen `state_backend.store`-Repos ist maschinell verboten (bevorzugt via eingeschraenktem `boundary.state_backend_repository.importable_by` → AC011; alternativ `dependency_rules`). **CLI-Level-Negativpfad:** ein kuenstlicher Verstoss laesst `scripts/ci/check_architecture_conformance.py` mit **non-zero Exit** (ERROR) fail-closed scheitern; ein positiver erlaubter Import (ueber den veroeffentlichten Port) bleibt 0-Violations. Die gewaehlte Mechanik ist im Bericht begruendet.
3. Die Story- (AG3-126) und Telemetrie-/Projekt-Read-Ports (AG3-127) gelten als die einzigen erlaubten Read-Surfaces; der konforme CURRENT-Zustand laeuft mit **0 Violations** (Exit 0).
4. Zu jeder neuen ausfuehrbaren Regel existiert ein synchroner deklarativer `invariants:`-Eintrag (FIX THE MODEL / keine zweite Wahrheitsquelle); `entities.md`/`invariants.md` `version` ist hochgezogen.
5. FK-07 §7.6/§7.8/§7.9-Prosa ist nachgezogen: der „nicht maschinell erzwungen"-Satz spiegelt den neuen Stand; die neue/n Invariante/n ist/sind als erzwungene Grenze benannt.
6. **Bevorzugt kein neuer Regel-Typ:** explizit belegt, dass `boundary.state_backend_repository.importable_by`-Einschraenkung (AC011) bzw. die bestehenden Buckets (AC001/AC004) reichten. Falls dennoch ein neuer Regel-Typ noetig war: neuer `ACxxx`-Code **nach AC012 (z. B. AC013) — NICHT AC008/AC009** (belegt), neue Dataclass + Loader (`_optional_mapping_list`) + `_check_*` + `violations.extend(...)` in `audit_architecture_conformance`, mit Checker-Contract-/Golden-Tests.
7. **ARCH-55:** alle Regel-`id`s, Symbol-/Prefix-Namen, `message`-Texte englisch; keine `noqa`/`type: ignore` ohne Begruendung.
8. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `pytest` unit/integration/contract (`-n0`); Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`).
   - `mypy src` (default + `--platform linux`); `ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py` (Exit 0, 0 Errors — die Suite prueft sich nach der Erweiterung selbst gruen), `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1-8 erfuellt; Diff + gruene Pflichtbefehle + GAC-1 + Konzept-Gates; QA-Gate (Codex-Review) PASS.
- Die FK-07-§7.6-Luecke ist geschlossen: der Repository-Vertrag ist maschinell erzwungen, nicht nur Soll. Kein Schlupfloch (`importable_by: any` auf der Mega-Fassade) bleibt fuer Read-Modelle offen.
- `unblocks: []` (terminale Story des Strangs).

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** der Drift entstand, weil der Vertrag nicht erzwungen war; die Story erzwingt das Modell (Spec + Checker), statt Einzeldurchgriffe nachzubessern. Formal-Spec, Checker, Prosa und Tests werden gemeinsam gezogen.
- **SINGLE SOURCE OF TRUTH:** `formal.architecture-conformance.*` ist die maschinenlesbare SSOT; deklarative und ausfuehrbare Regelmenge bleiben synchron — keine zweite Wahrheitsquelle.
- **NO ERROR BYPASSING / FAIL-CLOSED:** neue Verstoesse sind ERROR (blockierend); die Regeln werden nicht aufgeweicht, um gruen zu werden. Greift eine Regel zu Unrecht, ist der **Code** (Port) zu fixen, nicht die Regel.
- **ZERO DEBT:** keine `severity: warning`-Hintertuer fuer einen Befund, der real blockieren muss; kein Scharfschalten vor den Ports (sonst falsche Rot-Baseline).
- **ARCH-55 / GAC-2:** Bezeichner englisch; `guardrails/architecture-guardrails.md` verbindlich; Konflikt = hart stoppen und melden.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Mechanik (belegt):** neue Prefix-/Symbol-Regeln und `importable_by`-Einschraenkungen sind reine YAML-/Spec-Eintraege (`invariants.md`/`entities.md`; Loader iteriert die Listen automatisch, kein Python noetig). **`importable_by`-Einschraenkung auf `boundary.state_backend_repository` ist der bevorzugte Weg** (Checker meldet automatisch AC011-ERROR). Erst ein **genuin neuer** Regel-Typ braucht Dataclass + `_optional_mapping_list` + `_check_*` + neuen Code **nach AC012 (z. B. AC013) — NICHT AC008/AC009** (die sind bereits fuer Modul-Completeness vergeben, `architecture_conformance.py:267/788`) + `violations.extend(...)` + Contract-/Golden-Tests.
- IST vor der Arbeit re-verifizieren: `invariants.md:26-57` (dependency_rules), `:148-169` (read_surface_rules), `:170-198` (deklarative invariants); `entities.md:1202-1225` (boundary.control_plane_http), `:1354-1376` (boundary.state_backend_repository, `importable_by: any`). Checker-Dispatch in `tools/concept_compiler/architecture_conformance.py` (die `_check_*`-Liste).
- **Reihenfolge-Disziplin:** erst gegen den CURRENT-Code (nach AG3-126/127) verifizieren, dass die konforme Welt 0 Violations ergibt, **dann** die Regeln scharf schalten. Wuerde eine Regel den konformen Code rot faerben, ist die Regel zu eng — melden, nicht den Code verbiegen.
- Konzept-Aenderung ist hier **explizit beauftragt** (Formal-Spec + FK-07-Prosa-Nachzug). Minimal, prazise, keine ungaenderten Regeln umschreiben.
- Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Testnamen (positiver Konform-Test + kuenstliche Verstoss-Tests), gruene Pflichtbefehle + GAC-1 + Konzept-Gates.

## 7. Vorbedingungen

- `depends_on: AG3-126, AG3-127` muessen **beide** `completed` sein (Story- und Telemetrie-/Projekt-Read-Ports existieren) — bis dahin `status: blocked`. Ein Scharfschalten ohne die Ports erzeugt eine falsche Rot-Baseline.
- Venv-Pflicht: alle Python-Befehle ueber `.venv\Scripts\python`; keine globalen Installs (AK2/AK3 teilen `agentkit`).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`. **Hinweis:** Diese Story aendert bewusst die Architektur-Soll-Grenzen; die Formal-Spec (`entities.md` + `invariants.md`) wird mitgezogen (FIX THE MODEL), der Check wird **nicht** umgangen und keine Regel aufgeweicht, um gruen zu werden.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
