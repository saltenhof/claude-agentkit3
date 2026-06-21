# Codex Review R2: AG3-015 Prompt-Runtime FK-44-Completion

Rolle: unabhaengiger adversarial QA-Recheck auf `HEAD == 4731e18`
gegen die kumulative Diff `80ae0ce..HEAD`.

Concept-MCP `select:mcp__agentkit3-concepts__concept_search/get` war in
dieser Session nicht exponiert; geprueft wurden die lokalen Konzeptdateien
unter `concept/`, die Story, R1-Review und die kumulative Diff.

## Verdikt-Tabelle R1-Befunde

| Befund | Verdikt | Aktueller Beleg |
|---|---|---|
| E1 C2 in der Materialisierung | RESOLVED | Rendered liest Template-Text, Relpath und Template-SHA aus `resolve_run_prompt_binding()` und den `*_from_binding`-APIs, nicht mehr aus der aktuellen Lock-Datei: `src/agentkit/prompt_runtime/composer.py:253`, `src/agentkit/prompt_runtime/composer.py:258`, `src/agentkit/prompt_runtime/composer.py:259`, `src/agentkit/prompt_runtime/composer.py:263`. Static macht dasselbe fuer Relpath/SHA/Quelle: `src/agentkit/prompt_runtime/composer.py:510`, `src/agentkit/prompt_runtime/composer.py:515`, `src/agentkit/prompt_runtime/composer.py:520`. Der echte Materialize-Test nach `update_binding()` prueft rendered und static auf gepinnte v99-Bytes statt rebound v100: `tests/unit/prompt_runtime/test_runtime.py:323`, `tests/unit/prompt_runtime/test_runtime.py:347`, `tests/unit/prompt_runtime/test_runtime.py:356`, `tests/unit/prompt_runtime/test_runtime.py:362`. |
| E2 Producer-Verdrahtung | RESOLVED | `build_producer_registry()` ruft `register_prompt_runtime_producers()` produktiv: `src/agentkit/bootstrap/composition_root.py:61`, `src/agentkit/bootstrap/composition_root.py:62`. Der E2E-Test schreibt einen `prompt_audit`-Envelope ueber `build_artifact_manager()`, nicht ueber lokalen Registry-Seed: `tests/unit/bootstrap/test_composition_root.py:38`, `tests/unit/bootstrap/test_composition_root.py:53`, `tests/unit/bootstrap/test_composition_root.py:72`. |
| E3 ArtifactClass-Vollstaendigkeit | RESOLVED-BY-SCOPE-DECISION, legitim | Enum/DDL/Postgres/SQLite sind auf 9 Werte erweitert: `src/agentkit/core_types/artifact.py:41`, `src/agentkit/state_backend/sqlite_store.py:423`, `src/agentkit/state_backend/sqlite_store.py:426`, `src/agentkit/state_backend/store/artifact_repository.py:317`, `src/agentkit/state_backend/store/artifact_repository.py:320`, `src/agentkit/state_backend/postgres_schema.sql:301`, `src/agentkit/state_backend/postgres_schema.sql:304`. Postgres-Contract pinnt `set(ArtifactClass)`: `tests/contract/state_backend/test_artifact_repository_postgres.py:125`, `tests/contract/state_backend/test_artifact_repository_postgres.py:145`, `tests/contract/state_backend/test_artifact_repository_postgres.py:149`. `_ARTIFACT_CLASS_TO_TARGET_TYPE` nimmt `PROMPT_AUDIT` bewusst nicht als Verify-Target auf; das ist fachlich legitim, weil Prompt-Audit kein QA-reviewbares Deliverable ist, und fail-closed getestet: `src/agentkit/verify_system/_artifact_specs.py:83`, `tests/unit/verify_system/test_artifact_class_target_mapping.py:23`, `tests/unit/verify_system/test_artifact_class_target_mapping.py:38`, `tests/unit/verify_system/test_artifact_class_target_mapping.py:56`. |
| E4 Byte-Digests | RESOLVED | Rendered schreibt `prompt.md` mit `newline=""`, so `prompt.output_sha256 == sha256(prompt.content.encode("utf-8")) == sha256(file.read_bytes())`: `src/agentkit/prompt_runtime/composer.py:392`, `src/agentkit/prompt_runtime/composer.py:396`. Static berechnet `output_sha256` aus `prompt_path.read_bytes()`: `src/agentkit/prompt_runtime/composer.py:533`, und Runtime verwendet diesen Wert ohne Re-Encode: `src/agentkit/prompt_runtime/runtime.py:383`, `src/agentkit/prompt_runtime/runtime.py:389`. Tests pruefen rendered und static gegen `sha256(instance.prompt_path.read_bytes())`: `tests/unit/prompt_runtime/test_runtime.py:364`, `tests/unit/prompt_runtime/test_runtime.py:393`, `tests/unit/prompt_runtime/test_runtime.py:396`, `tests/unit/prompt_runtime/test_runtime.py:419`. |
| E5 verify_system Top-Surface | RESOLVED, aber siehe neuer ERROR N1 | `verify_system/prompt_audit.py` importiert `PromptRuntime` und `ComposeConfig`, keine Subsurface-Helper und kein `state_backend.store`: `src/agentkit/verify_system/prompt_audit.py:17`, `src/agentkit/verify_system/prompt_audit.py:18`. Der Materialize-Aufruf geht ueber `PromptRuntime.materialize_prompt`: `src/agentkit/verify_system/prompt_audit.py:74`, `src/agentkit/verify_system/prompt_audit.py:77`. Der alte `rendered-manifest.json`-Pfad ist nicht mehr produktiv; Test prueft explizit, dass er nicht entsteht: `tests/unit/verify_system/test_evaluators.py:201`. Die Run-Korrelation geht ueber `StoryContextQueryPort.resolve_run_scope()`: `src/agentkit/verify_system/prompt_audit.py:63`, mit Adapter in `state_backend`: `src/agentkit/state_backend/store/verify_story_context_repository.py:50`, `src/agentkit/state_backend/store/verify_story_context_repository.py:62`. |
| AK7 project_key | RESOLVED-BY-SCOPE-DECISION, legitim | `PromptRunPin` traegt `project_key: str | None`: `src/agentkit/prompt_runtime/pins.py:69`, `src/agentkit/prompt_runtime/pins.py:70`. Quelle ist `load_project_config()` und kein zweiter State: `src/agentkit/prompt_runtime/pins.py:88`, `src/agentkit/prompt_runtime/pins.py:95`, `src/agentkit/prompt_runtime/pins.py:99`. Test deckt Config-Fall und Bare-Fixture-Fall: `tests/unit/prompt_runtime/test_pins.py:220`, `tests/unit/prompt_runtime/test_pins.py:243`, `tests/unit/prompt_runtime/test_pins.py:250`. Die Scope-Entscheidung steht in der Story: `stories/AG3-015-prompt-runtime/story.md:346`, `stories/AG3-015-prompt-runtime/story.md:350`, `stories/AG3-015-prompt-runtime/story.md:353`. |

## Neue Befunde

### N1 - ERROR - Verify-Prompt-Audit repinnt vor der Materialisierung und bricht C2 nach Rebind

Die Remediation hat den direkten Subsurface-Zugriff im Verify-System durch
die Top-Surface ersetzt, aber der neue Pfad ruft vor jeder
Prompt-Materialisierung erneut `runtime.create_run_pin(run_scope.run_id)` auf:
`src/agentkit/verify_system/prompt_audit.py:73`, `src/agentkit/verify_system/prompt_audit.py:74`,
`src/agentkit/verify_system/prompt_audit.py:75`.

Das ist fuer einen bereits gepinnten Run nach legitimen `update_binding()`
falsch. `create_run_pin()` delegiert an `initialize_prompt_run_pin()`:
`src/agentkit/prompt_runtime/runtime.py:167`, `src/agentkit/prompt_runtime/runtime.py:179`.
`initialize_prompt_run_pin()` liest die aktuelle Projektbindung:
`src/agentkit/prompt_runtime/pins.py:104`, `src/agentkit/prompt_runtime/pins.py:107`.
`ensure_prompt_run_pin()` wirft bei abweichender bestehender Pin-Koordinate
`PROMPT_RUN_PIN_MISMATCH`: `src/agentkit/prompt_runtime/pins.py:173`,
`src/agentkit/prompt_runtime/pins.py:176`, `src/agentkit/prompt_runtime/pins.py:181`.

Damit ist C2 im Runtime-Materializer zwar repariert, aber im produktiven
Verify-Evaluator-Pfad wieder gebrochen: Nach `run_pinned(v99)` und
`update_binding(v100)` erreicht der Verify-Prompt-Audit `materialize_prompt()`
nicht mehr, sondern scheitert beim Re-Pin gegen die rebound Lock. Das verletzt
FK-44 §44.4.2, weil Evaluator-Prompts aus dem gepinnten Bundle materialisiert
werden muessen (`concept/technical-design/44_prompt_bundles_materialization_audit.md:255`,
`:259`, `:262`), und die C2-Invariante
`binding_changes_affect_only_future_runs` (`concept/formal-spec/prompt-runtime/invariants.md:34`).

Ich habe das mit einem gezielten lokalen Python-Reproducer gegen den aktuellen
Stand bestaetigt: v99 pinnen, v100 in den Store schreiben, `runtime.update_binding("project-bound", "100")`,
dann `materialize_qa_prompt_audit(...)` mit `RunScope(run_id="run-1", ...)`
aufrufen. Ergebnis: `agentkit.backend.exceptions.ProjectError: Prompt run pin mismatch`.

Erwartung: Verify-System darf nicht vor jedem Evaluator-Prompt gegen die
aktuelle Lock repinnen. Der Pfad muss den bestehenden Run-Pin konsumieren
(`PromptRuntime.materialize_prompt()` fail-closed, falls der Pin fehlt) oder
eine explizite "ensure existing or create only if absent"-Semantik haben, die
bei vorhandenen Pins niemals die aktuelle Projekt-Lock als Vergleichswahrheit
verwendet. Dazu fehlt ein Regressionstest:
`verify_system`/`materialize_qa_prompt_audit` nach Rebind muss weiterhin die
gepinnten v99-Bytes und einen `prompt_audit`-Envelope liefern.

## Weitere harte Pruefpunkte

- Toter Code: `write_rendered_prompt_artifact` und `RenderedPromptArtifact`
  haben keine produktiven Restnutzer. `git grep` findet nur Dokumentations- und
  Test-Verbotsstrings, keine Definition oder Nutzung in `src/agentkit/prompt_runtime`.
- `atomic_write_text(newline=...)`: Die Signatur ist rueckwaertskompatibel,
  `newline` ist keyword-only und defaultet auf `None`: `src/agentkit/utils/io.py:20`,
  `src/agentkit/utils/io.py:24`, `src/agentkit/utils/io.py:45`. Bestehende
  Aufrufer ohne Argument behalten ihr Verhalten; nur der Prompt-Output setzt
  `newline=""`: `src/agentkit/prompt_runtime/composer.py:396`.
- `StoryContextQueryPort.resolve_run_scope`: Der bestehende `load()`-Vertrag
  bleibt erhalten: `src/agentkit/verify_system/protocols.py:49`,
  `src/agentkit/verify_system/protocols.py:60`. `VerifySystem` nutzt weiter
  `self.story_context_port.load(ctx.story_dir)`: `src/agentkit/verify_system/system.py:368`,
  `src/agentkit/verify_system/system.py:373`. Die neue Run-Scope-Aufloesung
  ist Port/Adapter-basiert, nicht direkter `state_backend.store`-Import im
  Verify-System: `src/agentkit/state_backend/store/verify_story_context_repository.py:29`,
  `src/agentkit/state_backend/store/verify_story_context_repository.py:62`.
- Test-Abschwaechung: Keine neuen `xfail`/`skip` im AG3-015-Pfad gefunden.
  Die vorhandenen Skip-Marker liegen in Skills/Postgres-Umfeld und sind nicht
  Teil der Remediation. Allerdings fehlt genau der N1-Regressionstest.

## Aktualisierte AK-Matrix

| AK | Urteil | Beleg |
|---|---|---|
| AK1 Top-Surface vorhanden | PASS | Klasse und vier Methoden existieren: `src/agentkit/prompt_runtime/runtime.py:133`, `:167`, `:185`, `:230`, `:257`. |
| AK2 Materialisierung + ArtifactManager-Audit | PASS fuer PromptRuntime, ERROR im Verify-Konsum | Runtime persistiert ueber ArtifactManager: `src/agentkit/prompt_runtime/runtime.py:432`, `:445`; Composition-Root-Producer ist verdrahtet. Verify-Konsum repinnt aber vor Materialisierung und kann C2 brechen, siehe N1. |
| AK3 Statischer Materializer | PASS | Pin-authoritative Quelle und Raw-Byte-Digest: `src/agentkit/prompt_runtime/composer.py:510`, `:520`, `:533`. |
| AK4 Dynamischer Materializer | PASS | Pin-authoritative Source und Materialize-Test nach Rebind: `src/agentkit/prompt_runtime/composer.py:253`, `tests/unit/prompt_runtime/test_runtime.py:323`. |
| AK5 PromptAuditHash typisiert | PASS | Pydantic v2 frozen/extra forbid: `src/agentkit/prompt_runtime/audit.py:39`, `:53`; Contract-Test: `tests/contract/prompt_runtime/test_prompt_audit_schema.py:23`. |
| AK5b ArtifactClass vollstaendig | PASS | 9-Werte-DDL/Contracts/Registry vorhanden; Verify-Mapping kennt `PROMPT_AUDIT` als bewusste Nicht-Zielklasse. |
| AK6 C2-Invariantenfix | ERROR | Runtime-Materializer ist gefixt, aber Verify-Prompt-Audit ruft `create_run_pin()` gegen die aktuelle Lock und bricht active-run-stability nach Rebind, siehe N1. |
| AK7 Run-Pin Pydantic + project_key | PASS | Pydantic-Modell mit `project_key`/`pinned_at` und Roundtrip-Tests: `src/agentkit/prompt_runtime/pins.py:44`, `:69`, `:75`; `tests/unit/prompt_runtime/test_pins.py:220`. |
| AK8 Stale-Cache-Reject | PASS | Check nutzt pin-resolved Binding/Relpath: `src/agentkit/prompt_runtime/runtime.py:473`, `:477`, `:481`. |
| AK9 Installer-Delegation | PASS | Delegation an `PromptRuntime.update_binding`: `src/agentkit/installer/runner.py:339`, `src/agentkit/installer/runner.py:357` plus bestehender Integrationstest aus R1-Basis. |
| AK10 Negativpfade | ERROR | Gute Negativtests fuer Pin/DDL/Registry existieren; es fehlt und bricht der entscheidende Verify-System-Negativ-/Regressionstest "bereits gepinnter Run nach Rebind materialisiert Evaluator-Prompt weiter aus dem Pin", siehe N1. |

## Gesamturteil

Der R1-BLOCK ist nicht aufgehoben. E1-E5/AK7 sind im engeren R1-Sinn
remediiert, aber die Remediation hat mit N1 einen neuen ERROR in den
produktiven Verify-System-Prompt-Audit-Pfad eingebaut. Solange ein bereits
gepinnter Run nach legitimen Rebind im Evaluator-Pfad wieder gegen die aktuelle
Projekt-Lock repinnt und `PROMPT_RUN_PIN_MISMATCH` werfen kann, ist FK-44 nicht
abgeschlossen.

Gesamturteil: BLOCK
