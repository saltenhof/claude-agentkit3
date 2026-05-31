# AG3-015: Prompt-Runtime — FK-44-Completion (Top-Surface, Audit, Materialisierung, Pin-Invariante)

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** keine (FK-71/ArtifactManager bereits vorhanden)
**Quell-Konzept:** FK-44 (vollstaendig), FK-50 §50.5 (Installer-Bindung), FK-71 (ArtifactManager), bc-cut-decisions §BC 10, formal.prompt-runtime.*

---

## Realignment-Notiz (CHANGELOG)

- **2026-05-31 — Story an Ist-Stand angeglichen.** Die urspruengliche
  Greenfield-Praemisse ("Im AK3-Code existiert kein
  `src/agentkit/prompt_runtime/`, das gesamte BC fehlt") ist **veraltet
  und falsch**. Das Paket `src/agentkit/prompt_runtime/` existiert seit
  der THEME-001 W6-Migration (commit `42b112b`,
  `agentkit.prompt_composer -> agentkit.prompt_runtime`) mit den Modulen
  `__init__.py`, `composer.py`, `pins.py`, `resources.py`,
  `selectors.py`, `sentinels.py`, `templates.py` und vollstaendigen
  Unit-Tests unter `tests/unit/prompt_runtime/`.
- **C1 der GAP-Analyse (`stories/prompt-runtime-gap-analyse.md`, Stand
  2026-05-16) ist damit erledigt** (Modul-Prefix-Verletzung
  `prompt_composer` -> `prompt_runtime` ist behoben). Die GAP-Analyse
  bleibt als Input gueltig, ist aber in Modulpfaden veraltet; alle hier
  uebernommenen Punkte wurden gegen den heutigen Code verifiziert.
- **Konsequenz:** AG3-015 wird von "Greenfield-Neuanlage" auf
  "**Completion des existierenden `prompt_runtime` zur
  FK-44/formal-Konformitaet**" umgeschnitten. Es duerfen **keine
  Parallel-Module** zu den existierenden angelegt werden (kein
  `bundle_pinning.py` neben `pins.py`, kein `bundle_store.py` neben
  `resources.py`, kein `materialization.py` neben `composer.py`) —
  das waere zweite operative Wahrheit (Verstoss gegen SINGLE SOURCE OF
  TRUTH und FIX THE MODEL).

---

## Kontext

FK-44 (§44.1) trennt drei Schichten strikt:

1. **Kanonische Prompt-Bundles** (systemweit, immutable, versioniert)
2. **Projektlokale Prompt-Bindung** ueber den expliziten
   `.agentkit/config/prompt-bundle.lock.json`-Datensatz (lock-autoritativ;
   `prompts/` ist nur read-only Projektion)
3. **Run-gebundene Prompt-Instanzen** unter
   `{project_root}/.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`

Diese drei Schichten sind im Code **bereits weitgehend vorhanden**:
`resources.py` loest die lock-autoritative Projektbindung auf,
`pins.py` materialisiert Run-Pins unter
`.agentkit/manifests/prompt-pins/{run_id}.json`, `composer.py`
rendert Templates und schreibt run-scoped Instanzen mit voller
Digest-Kette (`template_sha256`, `render_input_digest`,
`output_sha256`).

Was AG3-015 noch leisten muss, ist die **FK-44/formal-Konformitaet
oben drauf**:

- die normierte **Top-Surface-Klasse `PromptRuntime`** mit den vier
  Methoden (`materialize_prompt`, `create_run_pin`, `update_binding`,
  `compute_audit_hash`) — bc-cut-decisions §BC 10, FK-44 §44.3/§44.4/§44.6.
  Diese Klasse existiert heute **nicht**; andere BCs
  (`verify_system.LlmEvaluator` per FK-44 §44.4.2, `installation-and-bootstrap`
  per FK-50 §50.5) referenzieren sie aber als einzige zulaessige Schnittstelle.
- typisiertes **Pydantic-v2 `PromptAuditHash`** (FK-44 §44.6: Felder
  `template_sha256`, `render_input_digest`, `output_sha256`), Owner
  Sub `materialization`. Heute nur lose Felder in der
  `ComposedPrompt`-Dataclass.
- **Audit-Persistenz via `artifacts.ArtifactManager`** (FK-44 §44.6:
  "einzige zulaessige Persistenzschicht … direktes Schreiben … loser
  JSON-Dateien ist unzulaessig"). Heute schreibt `composer.py` lose
  `manifest.json` neben `prompt.md`.
- **Hardlink/Symlink-Materializer fuer statische Prompts**
  (FK-44 §44.4.1). Heute wird auch der statische Pfad per
  `atomic_write_text`-Kopie geschrieben.
- **Behebung des C2-Invariantenbugs** in `pins.py`:
  `resolve_run_prompt_binding` verletzt
  `binding_changes_affect_only_future_runs` (Detail unten).
- **Kommando `reject-stale-local-prompt-cache`** und ggf. die formale
  State-Machine (`formal.prompt-runtime.state-machine`,
  `formal.prompt-runtime.commands`).

## Scope

### In Scope

Alle Aenderungen erweitern **bestehende** Module bzw. fuegen genau die
fachlich begruendeten neuen Module hinzu, die die Modul-Map aus
bc-cut-decisions §BC 10 (`agentkit.prompt_runtime.bundle_store`,
`.bundle_pinning`, `.materialization`) vorsieht. Wo ein bestehendes
Modul fachlich bereits den Sub abdeckt, wird **dieses** Modul der Owner,
ohne Parallel-Anlage.

1. **Top-Surface `PromptRuntime` (neu: `runtime.py`)** — duenne,
   typisierte Fassade, die die bestehenden Funktionen aus `composer.py`,
   `pins.py` und `resources.py` orchestriert. Begruendung neue Datei:
   die Top-Surface ist ein eigener Schnitt (BC-Top, `exposure: top`),
   den keines der bestehenden Sub-Module besitzen soll.
   - `materialize_prompt(...)` -> run-scoped `PromptInstance`
     (delegiert an `composer.write_prompt_instance`/Materializer)
   - `create_run_pin(run_id) -> RunPromptPin` (delegiert an
     `pins.initialize_prompt_run_pin`)
   - `update_binding(bundle_id, version) -> None` (FK-44 §44.3 /
     FK-50 §50.5; aktualisiert die Projektbindung fuer **zukuenftige**
     Runs)
   - `compute_audit_hash(...) -> PromptAuditHash`
2. **`PromptAuditHash` als Pydantic-v2-Schema (neu: `audit.py` oder in
   `materialization`-Sub)** — Felder `template_sha256`,
   `render_input_digest`, `output_sha256` (FK-44 §44.6,
   formal.prompt-runtime.entities `prompt-instance`). Begruendung neue
   Datei: das Audit-Schema ist laut FK-44 §44.6 Eigentum des
   `materialization`-Subs und ein eigenes versioniertes Artefaktmodell.
3. **Audit-Persistenz via `ArtifactManager`** — Audit-Record als
   typisierter `ArtifactEnvelope` ueber `artifacts.ArtifactManager.write`
   persistieren; `artifact_path`/Artefakt-ID fliesst in den Record
   zurueck (FK-44 §44.6, FK-71). Loese `manifest.json`-Schreibwege in
   `composer.py` werden auf den ArtifactManager-Pfad umgestellt bzw. als
   reine Agent-Dateipfad-Bereitstellung (nicht als Audit-Wahrheit)
   re-positioniert.
4. **Statischer Materializer via Hardlink/Symlink** — `composer.py`
   bzw. ein `materialization`-Modul bekommt einen `render_mode=static`-Pfad,
   der die gepinnte zentrale Bundle-Datei per Hardlink/Symlink/Junction
   nach `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md` projiziert,
   statt sie zu kopieren (FK-44 §44.4.1). Fallback auf Kopie nur, wenn
   Hardlink/Symlink plattformseitig fehlschlaegt, dabei `render_mode`
   korrekt setzen.
5. **C2-Invariantenfix in `pins.py`** — `resolve_run_prompt_binding`
   muss den **Run-Pin als Autoritaet** behandeln und das gepinnte Bundle
   stabil aus dem zentralen Store aufloesen, auch wenn der
   `prompt-bundle.lock.json` nach einem legitimen `update_binding`
   inzwischen auf eine neue Version zeigt (Invariante
   `binding_changes_affect_only_future_runs`, Szenario
   `mid_run_rebind_does_not_mutate_active_run`). Echte Korruption (Pin
   zeigt auf nicht mehr existierendes/inkonsistentes Bundle) bleibt
   fail-closed.
6. **`PromptRunPin` nach Pydantic-v2** — Migration der `@dataclass`
   `PromptRunPin` (und ggf. `PromptBundleBinding`) auf Pydantic v2 fuer
   Schema-Contract-Tests (CLAUDE.md: Pydantic v2 fuer Artefaktmodelle;
   formal.prompt-runtime.entities `run-prompt-pin` inkl. `pinned_at`).
7. **`reject-stale-local-prompt-cache`** — Pruefmechanismus, der eine
   mutable projektlokale Prompt-Quelle/stale Kopie zurueckweist
   (Invariante `project_local_prompt_copy_is_never_authoritative`,
   command `reject-stale-local-prompt-cache`, Szenario
   `stale_project_prompt_cache_is_rejected`).
8. **Installer-Anschluss (FK-50 §50.5)** — Der Installer ruft die
   Bundle-Bindung kuenftig ueber die kanonische Top-Surface
   `PromptRuntime.update_binding(bundle_id, version)` auf, analog zu
   `Skills.bind_skill`. Heute schreibt `installer/runner.py` den
   Lock direkt (`_write_prompt_bundle_lock`); dieser Schreibweg ist auf
   die Top-Surface zu delegieren (Owner-BC-Prinzip), ohne den
   bestehenden fail-closed-Pfad zu schwaechen.
9. **Tests** (siehe Akzeptanzkriterien) inkl. reproduzierendem
   C2-Bugfix-Test und State-Machine-/Szenario-Abdeckung.

### Out of Scope

- Event-Emission `prompt_used` (FK-44 §44.6: in diesem BC **nicht**
  eingefuehrt; falls je eingefuehrt, vorher TelemetryContract-Registrierung).
- Frontend-Lese-API fuer Prompt-Audit.
- Migration alter Prompt-Bundles.
- Garbage-Collection-Schutz fuer referenzierte Bundles
  (Invariante `referenced_prompt_bundles_are_not_garbage_collected_...`
  — eigener Retention-Schnitt, nicht Teil dieser Story).

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/prompt_runtime/runtime.py` | Neu | Top-Surface-Klasse `PromptRuntime` (4 Methoden), duenne Fassade ueber bestehende Subs |
| `src/agentkit/prompt_runtime/audit.py` | Neu | Pydantic-v2 `PromptAuditHash` + AuditRecord-Aufbau (Owner: materialization-Sub, FK-44 §44.6) |
| `src/agentkit/prompt_runtime/__init__.py` | Modifiziert | Re-Export von `PromptRuntime`, `PromptAuditHash` |
| `src/agentkit/prompt_runtime/pins.py` | Modifiziert | C2-Fix (Pin-Autoritaet), `PromptRunPin` -> Pydantic v2, `pinned_at` |
| `src/agentkit/prompt_runtime/composer.py` | Modifiziert | Static-Materializer (Hardlink/Symlink), Audit-Persistenz via ArtifactManager statt loser JSON, `render_mode` static/rendered |
| `src/agentkit/prompt_runtime/resources.py` | Modifiziert | `update_binding`-Schreibpfad fuer Lock; ggf. `PromptBundleBinding` -> Pydantic; stale-cache-Reject-Pruefung |
| `src/agentkit/installer/runner.py` | Modifiziert | CP-8: Lock-Schreiben an `PromptRuntime.update_binding` delegieren (FK-50 §50.5) |
| `src/agentkit/core_types/artifact.py` | Modifiziert | Neuer `ArtifactClass.PROMPT_AUDIT = "prompt_audit"` (Entscheidung 1) |
| `src/agentkit/state_backend/.../postgres_schema.sql` (+ Migration) | Modifiziert | `artifact_class`-CHECK-Constraint um `prompt_audit` erweitern; Schema-Version + idempotente Migration |
| `src/agentkit/prompt_runtime/register.py` (o.ae.) | Neu/Modifiziert | Producer `prompt_runtime` fuer `ArtifactClass.PROMPT_AUDIT` registrieren |
| `tests/contract/.../test_artifact_class*.py` (+ Golden) | Modifiziert | Wire-Werte-Menge 8→9 pinnen (FAIL-CLOSED); `prompt_audit` aufnehmen |
| `tests/unit/prompt_runtime/test_runtime.py` | Neu | Top-Surface-Tests (4 Methoden) |
| `tests/unit/prompt_runtime/test_audit.py` | Neu | PromptAuditHash-Determinismus + ArtifactManager-Persistenz |
| `tests/unit/prompt_runtime/test_pins.py` | Modifiziert | C2-Reproduktionstest; bestehender `test_resolve_run_prompt_binding_rejects_binding_drift` ist an die korrigierte Invariante anzupassen (siehe Offene Entscheidungen) |
| `tests/unit/prompt_runtime/test_composer.py` | Modifiziert | Static-Hardlink-Materialisierung |
| `tests/contract/prompt_runtime/...` | Neu/erweitert | Schema-Contract `PromptAuditHash`, formal-Spec-Konformitaet (entities/state-machine) |

## Akzeptanzkriterien

1. **Top-Surface vorhanden:** `agentkit.prompt_runtime.PromptRuntime`
   existiert als Klasse mit `materialize_prompt`, `create_run_pin`,
   `update_binding`, `compute_audit_hash`; Signaturen typisiert, mypy
   strict ohne `type: ignore`. (bc-cut-decisions §BC 10)
2. **Materialisierung Agent-Prompt:** `materialize_prompt(...)` liefert
   Pfad `{project_root}/.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`
   und persistiert einen `PromptAuditHash`-haltigen Audit-Record **ueber
   `ArtifactManager`** (kein loser JSON-Schreibweg als Audit-Wahrheit).
   (FK-44 §44.4.1, §44.6)
3. **Statischer Materializer:** statische Prompts werden via
   Hardlink/Symlink/Junction auf die gepinnte zentrale Bundle-Datei
   projiziert; Test weist nach, dass Quelle und Ziel denselben Inhalt
   teilen (z. B. gleiche Inode bei Hardlink) und `render_mode == "static"`.
   (FK-44 §44.4.1)
4. **Dynamischer Materializer:** dynamische Prompts werden gerendert;
   `render_input_digest` ist deterministisch (gleicher Input -> gleicher
   Hash) und `render_mode == "rendered"`. (FK-44 §44.4.1, §44.6)
5. **`PromptAuditHash` typisiert:** Pydantic-v2-Modell mit
   `template_sha256`, `render_input_digest`, `output_sha256`;
   Contract-Test friert das Schema ein; gleicher Input -> identischer
   Hash. (FK-44 §44.6, formal.prompt-runtime.entities)
5b. **Neue ArtifactClass `prompt_audit` vollstaendig durchgezogen
   (Entscheidung 1):** `ArtifactClass.PROMPT_AUDIT` existiert in
   `core_types/artifact.py`; der Postgres-`artifact_class`-CHECK-Constraint
   enthaelt `prompt_audit` (idempotente Migration, Schema-Version erhoeht);
   Contract-/Golden-Tests pinnen die 9-Werte-Menge; Producer `prompt_runtime`
   ist fuer die Klasse registriert; alle `ArtifactClass`-Mappings kennen den
   neuen Wert (keine halbe Enum-Erweiterung). Audit-Records (AK 2) werden mit
   `artifact_class=PROMPT_AUDIT` persistiert. (FK-44 §44.6, AG3-023 §2.1.4)
6. **C2-Invariantenfix (Bugfix mit Reproduktionstest):** Nach einem
   legitimen `update_binding(bundle_id, neue_version)` bleibt ein bereits
   gepinnter aktiver Run stabil — `resolve_run_prompt_binding(run_id)`
   loest weiterhin das **gepinnte** Bundle auf und wirft **keinen**
   `PROMPT_RUN_PIN_MISMATCH`. Ein reproduzierender Test bildet das
   Szenario `mid_run_rebind_does_not_mutate_active_run` ab
   (run_pinned -> instance_materialized, nicht rejected). Echte
   Pin-Korruption bleibt fail-closed (getrennter Negativtest).
   (formal.prompt-runtime.invariants `binding_changes_affect_only_future_runs`,
   formal.prompt-runtime.scenarios, FK-44 §44.3/§44.7)
7. **Run-Pin als Pydantic-Artefakt:** `PromptRunPin` ist ein
   Pydantic-v2-Modell mit `run_id`, `resolved_prompt_bundle_version`,
   `resolved_prompt_bundle_manifest_digest`, `pinned_at`; Roundtrip
   (write/read) verprobt. (formal.prompt-runtime.entities `run-prompt-pin`)
8. **Stale-Cache-Reject:** Eine mutable projektlokale Prompt-Quelle, die
   von der gebundenen Bundle-Version abweicht, wird zurueckgewiesen;
   Test bildet `stale_project_prompt_cache_is_rejected` ab
   (binding_resolved -> rejected). (FK-44 §44.5,
   formal.prompt-runtime.commands `reject-stale-local-prompt-cache`)
9. **Installer-Delegation:** `installer/runner.py` aktualisiert die
   Prompt-Bundle-Bindung ueber `PromptRuntime.update_binding`; partielle
   Bindung bleibt fail-closed (Projektregistrierung scheitert). Test
   weist den Delegationspfad nach. (FK-50 §50.5)
10. **Negativpfade:** fehlender Run-Pin, inkonsistentes/fehlendes
    gepinntes Bundle, malformter Lock fuehren weiterhin zu klaren
    Fehlern (FAIL-CLOSED), nachgewiesen durch Tests.
11. Tests gruen, `ruff` clean, `mypy src` strict clean, Coverage >= 85%.

## Definition of Done

- Build kompiliert (`.venv\Scripts\python -m pip install -e ".[dev]"`).
- Tests gruen (`.venv\Scripts\python -m pytest`), inkl. neuer
  Runtime-/Audit-/C2-/Static-Materializer-/Stale-Cache-Tests.
- `.venv\Scripts\python -m ruff check src tests` clean.
- `.venv\Scripts\python -m mypy src` strict clean.
- Coverage gesamt >= 85%.
- Keine Parallel-Module zu bestehenden `pins.py`/`resources.py`/
  `composer.py`; keine zweite operative Wahrheit.
- Keine losen JSON-Dateien mehr als Audit-Wahrheit; Audit laeuft ueber
  ArtifactManager.
- FK-44/formal-Referenzen in den Modul-Docstrings der geaenderten/neuen
  Module.

## Konzept-Referenzen

- **FK-44** (`technical-design/44_prompt_bundles_materialization_audit.md`)
  - §44.2 Kanonische Quelle / Lock-Autoritaet / read-only Projektion
  - §44.3 Bindung und Run-Pinning; `PromptRuntime.update_binding`
    (Aufrufer ausschliesslich FK-50)
  - §44.4.1 Agent-Prompts (run-scoped Pfad, static via Hardlink/Symlink,
    rendered)
  - §44.4.2 Evaluator-Prompts (`PromptRuntime.materialize_prompt` als
    einzige Aufloesungsschnittstelle)
  - §44.5 keine langlebige lokale Prompt-Cache-Autoritaet;
    `ProjectPromptPin`-Schema im Sub `bundle_pinning`
  - §44.6 Audit: `PromptAuditHash`-Pydantic-Schema (Owner
    `materialization`), Persistenz ausschliesslich via ArtifactManager;
    `prompt_used`-Event nicht eingefuehrt
  - §44.7 geringe Menschenlast (aktive Runs bleiben stabil)
- **formal.prompt-runtime.invariants** — `project_prompt_binding_is_lock_authoritative`,
  `project_local_prompt_copy_is_never_authoritative`,
  `active_run_uses_one_pinned_bundle`,
  `binding_changes_affect_only_future_runs` (C2),
  `every_agent_prompt_consumption_uses_run_scoped_instance`,
  `prompt_usage_is_auditable_to_exact_template_and_output_digest`
- **formal.prompt-runtime.state-machine** — Zustaende `binding_resolved`,
  `run_pinned`, `instance_materialized` (terminal), `rejected` (terminal);
  Transition `run_pinned -> run_pinned` (Rebind ohne Mutation)
- **formal.prompt-runtime.commands** — `pin-run-prompt-bundle`,
  `materialize-agent-prompt-instance`, `render-evaluator-prompt`,
  `reject-stale-local-prompt-cache`
- **formal.prompt-runtime.events** — `run.prompt_bundle_pinned`,
  `prompt.instance_materialized`, `prompt.rendered`,
  `prompt.stale_cache_detected` (Emission ist Folge-Inkrement, sofern an
  TelemetryContract gebunden)
- **formal.prompt-runtime.entities** — `prompt-bundle`,
  `project-prompt-binding`, `run-prompt-pin` (inkl. `pinned_at`),
  `prompt-instance`
- **formal.prompt-runtime.scenarios** —
  `static_prompt_is_materialized_from_pinned_bundle`,
  `dynamic_prompt_is_rendered_and_audited`,
  `mid_run_rebind_does_not_mutate_active_run` (C2),
  `stale_project_prompt_cache_is_rejected`
- **bc-cut-decisions §BC 10** (= formal.architecture-conformance.entities,
  component_group `prompt_runtime`) — Top `PromptRuntime` (`exposure: top`),
  Subs `bundle_store` (resources), `bundle_pinning` (pins),
  `materialization` (composer/audit); Modul-Prefix `agentkit.prompt_runtime`
- **FK-50 §50.5** — Installer ruft `PromptRuntime.update_binding(bundle_id,
  version)` analog zu `Skills.bind_skill`; fail-closed
- **FK-71 / ArtifactManager** (`agentkit.artifacts.ArtifactManager.write`)
  — einzige zulaessige Audit-Persistenzschicht (typisierter
  `ArtifactEnvelope`)

## Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH:** kanonische Bundles im System-Store, lokal
  nur read-only Projektion; **keine Parallel-Module** zu den
  existierenden `prompt_runtime`-Modulen; Audit nur via ArtifactManager,
  keine zweite Wahrheit in losen JSON-Dateien.
- **FIX THE MODEL, NOT THE SYMPTOM:** C2 wird am Modell behoben (Run-Pin
  ist Autoritaet), nicht durch Symptomunterdrueckung; bestehender
  Drift-Test, der die fehlerhafte Semantik festschreibt, wird an die
  korrekte Invariante angepasst.
- **ZERO DEBT:** kein "Pinning/Audit spaeter"; Top-Surface, Audit und
  C2-Fix sind Teil des vereinbarten Scopes.
- **FAIL-CLOSED:** ohne validen Run-Pin / gepinntes Bundle / validen
  Lock kein Materialize; echte Korruption blockiert weiterhin.

## Entschieden (2026-05-31, Stefan)

1. **ArtifactClass fuer Prompt-Audit-Records → NEUE Klasse `prompt_audit`
   (Variante b).** Prompt-Audit-Records bekommen eine **eigene**
   `ArtifactClass.PROMPT_AUDIT` (Wire-Wert `prompt_audit`), nicht die
   `pipeline`-Sammelklasse. Konsequenz und Pflicht-Scope dieser Story:
   - `core_types/artifact.py`: neuer `ArtifactClass`-Enum-Wert
     `PROMPT_AUDIT = "prompt_audit"`.
   - Postgres-CHECK-Constraint (analog AG3-023 §2.1.4, `postgres_schema.sql`
     bzw. die `artifact_class`-CHECK-Liste) um `prompt_audit` erweitern;
     Schema-Version + Migration nachziehen (idempotent).
   - Contract-/Golden-Tests fuer die `ArtifactClass`-Wire-Werte aktualisieren
     (die feste 8→9-Werte-Liste; FAIL-CLOSED-Tests, die die Menge pinnen).
   - Producer-Registry: Producer `prompt_runtime` fuer die neue Klasse
     registrieren (analog `verify_system/register.py`).
   - `_ARTIFACT_CLASS_TO_TARGET_TYPE`/sonstige Klassen-Mappings pruefen und
     den neuen Wert vollstaendig einpflegen (keine halbe Enum-Erweiterung).
   Begruendung: fachlich sauberer Owner-Schnitt; Prompt-Audit ist kein
   Pipeline-Artefakt. ZERO DEBT: die Enum-Erweiterung wird vollstaendig durch
   alle gebundenen Stellen (DB-Constraint, Contract-/Golden-Tests, Registry,
   Mappings) gezogen, nicht nur im Enum.
3. **AK7 `project_key` am `PromptRunPin` → ergaenzt (Review R1).** Die
   formale Entity `prompt-runtime.entity.run-prompt-pin`
   (`concept/formal-spec/prompt-runtime/entities.md`) fuehrt `project_key`
   als Attribut. `PromptRunPin` traegt es jetzt als
   `project_key: str | None`. Quelle ist die kanonische Projektkonfiguration
   (`config.loader.load_project_config`) — KEINE zweite project-key-Wahrheit;
   in bare/bootstrap-Fixtures ohne Config bleibt es `None` (fail-soft, da der
   Pin auch ohne project_key run-eindeutig ist). Eine vollstaendige
   Propagierung von `project_key` in den Lock-Datensatz
   (`project-prompt-binding`) bleibt bewusst ausgeklammert (eigener
   Installer-/Lock-Format-Schnitt; nicht Teil dieser Story).

2. **C2-Drift-Test invertieren → JA.** Der bestehende Test
   `test_resolve_run_prompt_binding_rejects_binding_drift`
   (`tests/unit/prompt_runtime/test_pins.py:162`) schreibt die **fehlerhafte**
   C2-Semantik fest (erwartet Mismatch nach Lock-Versionswechsel). Er wird
   umgebaut zu „Run-Pin bleibt nach legitimem Rebind stabil"
   (`mid_run_rebind_does_not_mutate_active_run`) **plus** separater Negativtest
   fuer echte Pin-Korruption (Pin → nicht existentes/inkonsistentes Bundle
   bleibt fail-closed). Bugfix gemaess FK-44-Invariante
   `binding_changes_affect_only_future_runs`.

## Offene Folge (Codex-Review r3, WARNING W1 — owner-zugeordnet, NICHT in AG3-015)

- **W1 (PASS-MIT-WARNINGS, r3):** Es existiert **kein produktiver
  Run-Start-Pinner in der Pipeline**. Der Run-Pin entsteht aktuell *lazy* beim
  ersten Verify-Prompt-Audit (`PromptRuntime.ensure_run_pin`, create-if-absent).
  FK-44/bc-cut-decisions §BC 10 nennen `create_run_pin` „bei Run-Start". Das ist
  ein echter Konzept-/Pipeline-Rand, aber **kein Blocker fuer AG3-015** (N1
  RESOLVED; die lazy-Semantik ist konsistent und fail-closed) und liegt
  fachlich im **Setup-/Pipeline-Engine-BC**, nicht in prompt-runtime.
  Disposition: als Setup-/Pipeline-Folgeschnitt fuehren (analog AG3-035 #4 →
  AG3-028 owner-zugeordnet). Aktiv an Stefan zu spiegeln (Severity-Regel:
  WARNING wird nicht still liegengelassen) — **offene User-Entscheidung**:
  eigene Folgestory „Pipeline-Run-Start-Pinning" ODER bewusste Beibehaltung der
  lazy-Pin-Semantik. Bis zur Entscheidung bleibt der Hinweis hier getrackt.
