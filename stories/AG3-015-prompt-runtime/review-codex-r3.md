# Codex Review R3: AG3-015 Prompt-Runtime N1-Recheck

Rolle: unabhaengiger adversarial QA-Recheck auf `HEAD == 2fc1309`
gegen `git diff 80ae0ce..HEAD`; Fokus auf R2-BLOCK N1.

Concept-MCP `select:mcp__agentkit3-concepts__concept_search/get` war in
dieser Session nicht exponiert. Geprueft wurden die lokalen Konzeptdateien:
`concept/technical-design/44_prompt_bundles_materialization_audit.md`,
`concept/formal-spec/prompt-runtime/invariants.md`,
`concept/formal-spec/prompt-runtime/scenarios.md`,
`concept/formal-spec/prompt-runtime/commands.md` und
`concept/_meta/bc-cut-decisions.md`.

## Kurzverdikt

N1 ist RESOLVED. Der R2-BLOCK ist aufgehoben.

E1-E5 und AK7 bleiben weiterhin RESOLVED. Es gibt keinen neuen ERROR in der
N1-Remediation. Ein echter, aber nicht unmittelbar blockierender
Konzept-/Pipeline-Rand bleibt als WARNING W1: kein produktiver
Run-Start-Pinner in der Pipeline.

## N1 - RESOLVED

R2-Befund: `verify_system/prompt_audit.py` rief vor der Materialisierung
`runtime.create_run_pin(run_scope.run_id)` auf. Nach legitimem
`update_binding()` wurde dadurch gegen die aktuelle Lock-Datei revalidiert und
ein bereits gepinnter Run konnte mit `PROMPT_RUN_PIN_MISMATCH` abbrechen.

Aktueller Stand:

- `verify_system/prompt_audit.py:74-86` nutzt jetzt `PromptRuntime.ensure_run_pin`
  statt `create_run_pin`.
- `PromptRuntime.ensure_run_pin` delegiert auf
  `ensure_run_prompt_pin_present`: `src/agentkit/prompt_runtime/runtime.py:182-200`.
- `ensure_run_prompt_pin_present` laedt zuerst den vorhandenen Pin und gibt ihn
  unveraendert zurueck: `src/agentkit/prompt_runtime/pins.py:127-150`.
  Nur wenn kein Pin existiert, wird `initialize_prompt_run_pin()` aufgerufen.
- Damit wird ein bestehender Pin im Verify-Pfad nie gegen die aktuelle
  Projekt-Lock verglichen.

Das bricht die legitime Drift-Rejection nicht:

- `PromptRuntime.create_run_pin` delegiert unveraendert auf
  `initialize_prompt_run_pin`: `src/agentkit/prompt_runtime/runtime.py:168-180`.
- `initialize_prompt_run_pin` loest die aktuelle Projektbindung auf und ruft
  `ensure_prompt_run_pin`: `src/agentkit/prompt_runtime/pins.py:104-124`.
- `ensure_prompt_run_pin` bleibt write-once und rejected divergierende
  Koordinaten eines vorhandenen Pins: `src/agentkit/prompt_runtime/pins.py:182-221`.
- `git grep` zeigt keinen produktiven Aufrufer von `create_run_pin` ausser der
  Methode selbst; alle produktiven Verify-Pfade gehen ueber
  `materialize_qa_prompt_audit` -> `ensure_run_pin`.

Damit ist die geforderte Semantik sauber getrennt:

- Run-Start/Pin-Erzeugung: `create_run_pin`, drift-rejecting.
- Consumer/Verify-Audit: `ensure_run_pin`, create-if-absent, bestehende Pins
  nicht gegen die Lock revalidieren.
- Materialisierung: `materialize_prompt`/Composer loesen weiter aus dem
  pin-authoritativen Bundle auf (`composer.py:248-267`,
  `composer.py:364-368`, `composer.py:508-520`).

## Regressionstest

Der neue Regressionstest ist ein echter Reproducer:
`tests/unit/verify_system/test_evaluators.py:123-258`.

Er baut einen installierten Projektzustand mit FlowExecution/RunScope,
pinnt `run-rebind-001`, klont das Bundle in eine materiell andere Version,
ruft `PromptRuntime.update_binding(..., "999")` auf und materialisiert danach
den Verify-Prompt-Audit ueber den produktiven
`materialize_qa_prompt_audit`-Pfad.

Wichtige Assertions:

- `audit["status"] == "materialized"` und `run_id == "run-rebind-001"`:
  der alte `create_run_pin`-Pfad haette hier nach Rebind nicht materialisiert,
  sondern `PROMPT_RUN_PIN_MISMATCH` gefangen und `skipped` geliefert.
- der materialisierte Prompt enthaelt keinen `rebound v999`-Marker:
  die Verify-Materialisierung konsumiert weiter die gepinnten Bytes.
- Missing Pin plus entfernte Lock wird sauber als
  `{"status": "skipped", "reason": "materialization_failed"}` gemeldet,
  kein QA-Subflow-Crash.

Ergaenzende Pin-/Runtime-Tests pruefen die neue Semantik direkt:

- `test_ensure_run_prompt_pin_present_creates_when_absent`
- `test_ensure_run_prompt_pin_present_does_not_revalidate_after_rebind`
- `TestCreateRunPin.test_ensure_run_pin_is_idempotent_across_rebind`
- bestehend: `test_ensure_prompt_run_pin_rejects_mid_run_drift`

Hinweis: Der Verify-Regressionstest koennte die persistierte
`prompt_audit`-Envelope noch explizit aus dem `ArtifactManager` zuruecklesen.
Das ist keine neue Blockade, weil `PromptRuntime.materialize_prompt` ohne
persistierte Audit-Envelope keinen `audit_reference` liefern kann und die
Envelope-Persistenz separat durch `prompt_runtime/audit.py`,
Composition-Root- und Runtime-Tests abgedeckt ist. Fuer den N1-Reproducer ist
die aktuelle Assertion stark genug.

## E1-E5 / AK7

| Befund | R3-Verdikt | Beleg |
|---|---|---|
| E1 C2 in der Materialisierung | weiter RESOLVED | Rendered und static loesen Template-Text/Relpath/Digest aus `resolve_run_prompt_binding()` bzw. binding-basierten APIs, nicht aus der aktuellen Lock: `composer.py:248-267`, `composer.py:508-520`. |
| E2 Producer-Verdrahtung | weiter RESOLVED | `build_producer_registry()` registriert `register_prompt_runtime_producers`: `composition_root.py:44-64`; Audit-Envelopes werden mit `ArtifactClass.PROMPT_AUDIT` gebaut: `audit.py:158-175`. |
| E3 ArtifactClass-Vollstaendigkeit | weiter RESOLVED-BY-SCOPE-DECISION | Keine Regression in Enum/DDL/Mapping-Pfaden; `PROMPT_AUDIT` bleibt eigene Artefaktklasse, aber kein Verify-Target. |
| E4 Byte-Digests | weiter RESOLVED | Rendered schreibt `prompt.md` mit `newline=""`: `composer.py:390-396`; static berechnet `output_sha256` aus `prompt_path.read_bytes()`: `composer.py:530-541`. |
| E5 Verify-System Top-Surface | RESOLVED | Verify importiert `PromptRuntime`/`ComposeConfig`, nutzt `materialize_prompt` und keine Subsurface-Composer-/Pin-Helper: `verify_system/prompt_audit.py:17-19`, `:86-97`. Der alte N1-Fehler ist entfernt. |
| AK7 Run-Pin Pydantic + project_key | weiter RESOLVED | `PromptRunPin` ist Pydantic v2, frozen, mit `project_key`, `pinned_at` und Alias-Properties: `pins.py:44-85`. |

## Neuer Befund

### W1 - WARNING - Kein produktiver Run-Start-Pinner in der Pipeline

Das ist ein echter fachlicher Mangel, aber kein neuer N1-ERROR.

Normativ verlangen FK-44 und BC-Cut:

- FK-44 §44.3: aktive Runs arbeiten gegen einen bei Run-Start aufgeloesten und
  eingefrorenen Prompt-Stand; bei `setup` bzw. Run-Erzeugung wird ein eigener
  Run-Pin geschrieben (`44_prompt_bundles_materialization_audit.md:188-198`).
- Formalinvariante `active_run_uses_one_pinned_bundle`: jeder aktive Run muss
  vor der ersten Prompt-Invocation genau eine Bundle-Version und einen
  Manifest-Digest pinnen (`invariants.md:31-36`).
- BC-Cut: `pipeline-framework -> prompt-runtime`: `create_run_pin` bei
  Run-Start (`bc-cut-decisions.md:966`).

Code-Realitaet:

- `git grep` findet keinen produktiven `create_run_pin`-Aufrufer ausser der
  Methode selbst in `PromptRuntime`.
- Die Pipeline schreibt `FlowExecution`/`run_id` in
  `pipeline_engine/runtime_state.py:95-132`, ruft dabei aber keinen
  `PromptRuntime.create_run_pin` auf.
- Der aktuelle Verify-Audit-Pfad kann einen fehlenden Pin lazy per
  `ensure_run_pin` erzeugen. Das ist fuer den N1-Consumer-Fix akzeptabel, aber
  nicht der normativ gewollte Run-Start-Schnitt.

Severity-Einordnung: WARNING.

Begruendung: AG3-015 fordert im Scope die Top-Surface, C2-Fix,
Materialisierung und Verify-/Installer-Anschluesse, aber keinen
Pipeline-Framework-Umbau. Den R2-Block wegen N1 darf dieser Rand nicht
kuenstlich offen halten. Gleichzeitig darf der Befund nicht still liegen
bleiben: bevor PromptRuntime als genereller Worker-/Evaluator-Spawn-Pfad
produktiv genutzt wird, muss die Pipeline bei Run-Erzeugung explizit
`create_run_pin` ausfuehren und das negativ testen.

Frage an den Auftraggeber: wie wollen wir hier vorgehen - eigene Folgestory
fuer Pipeline-Run-Start-Pinning oder Scope von AG3-015 noch erweitern?

## Test-Abschwaechung / neue Risiken

Keine neuen `xfail`/`pytest.mark.skip` im AG3-015-Pfad gefunden. Die Treffer
auf `skipped` sind Statuswerte der Prompt-Audit-Metadaten, keine
pytest-Skips.

Der N1-Test ist nicht zu schwach fuer den alten Fehler: mit dem alten
`create_run_pin` im Verify-Pfad waere `audit["status"]` nach Rebind nicht
`materialized`, sondern `skipped/materialization_failed`.

## Eigene Verifikation

Lokal ausgefuehrt:

```text
.venv\Scripts\python -m pytest tests/unit/prompt_runtime/test_pins.py::test_ensure_prompt_run_pin_rejects_mid_run_drift tests/unit/prompt_runtime/test_pins.py::test_ensure_run_prompt_pin_present_does_not_revalidate_after_rebind tests/unit/prompt_runtime/test_runtime.py::TestCreateRunPin::test_ensure_run_pin_is_idempotent_across_rebind tests/unit/verify_system/test_evaluators.py::TestPromptAuditPinStabilityAfterRebind -q
```

Ergebnis: `5 passed in 1.11s`.

Die vom Auftraggeber gelieferte Gesamtevidenz (`2644 passed/25 skipped`,
`ruff` clean, `mypy` 329 files, 4 Gates OK, Coverage 87.64%) ist mit dem
geprueften Diff konsistent; ich habe sie in dieser Runde nicht vollstaendig
erneut ausgefuehrt.

## Gesamturteil

Der R2-BLOCK ist aufgehoben. N1 ist RESOLVED, E1-E5/AK7 bleiben RESOLVED, und
es gibt keinen neuen ERROR. W1 ist als echter, aufschiebbarer
Pipeline-Konzeptbefund aktiv zu entscheiden.

Gesamturteil: PASS-MIT-WARNINGS
