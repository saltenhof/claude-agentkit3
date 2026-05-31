# Codex Review R1: AG3-015 Prompt-Runtime FK-44-Completion

Rolle: adversarial QA-Review auf lokalem Commit `e2d61dc`.

Hinweis zur Pruefbasis: Der angeforderte Concept-VectorDB-Zugriff via `tool_search` auf `select:mcp__agentkit3-concepts__concept_search,mcp__agentkit3-concepts__concept_get` war in dieser Session nicht verfuegbar. Ich habe die verbindlichen Konzeptstellen aus den lokalen Dateien unter `concept/` gelesen, insbesondere FK-44, formal.prompt-runtime.*, bc-cut-decisions, FK-18 und FK-50.

## Harte Befunde

### E1 - C2 ist nur im Resolver gefixt, nicht in der tatsaechlichen Materialisierung

`resolve_run_prompt_binding` behandelt den Run-Pin korrekt als Autoritaet (`src/agentkit/prompt_runtime/pins.py:211-224`). Danach bricht die Materialisierung die Invariante aber wieder:

- `composer._resolve_prompt_source` loest zwar zuerst die gepinnte Binding-Metadaten (`src/agentkit/prompt_runtime/composer.py:246`), liest den Template-Text danach aber ueber `load_prompt_template(..., project_root=project_root)` (`src/agentkit/prompt_runtime/composer.py:247`).
- `load_prompt_template` geht ueber `prompt_template_path` (`src/agentkit/prompt_runtime/resources.py:397-406`), und `prompt_template_path` loest bei `project_root` wieder `_resolve_binding(project_root)` aus (`src/agentkit/prompt_runtime/resources.py:376-378`, `src/agentkit/prompt_runtime/resources.py:310-313`). Das ist die aktuelle Projektbindung, nicht der Run-Pin.
- Der statische Pfad macht dasselbe Muster: `materialize_static_prompt_instance` nimmt zwar `binding = resolve_run_prompt_binding(...)` (`src/agentkit/prompt_runtime/composer.py:565`), bestimmt `relpath` und `template_sha256` aber ueber die aktuelle Projektbindung (`src/agentkit/prompt_runtime/composer.py:566-570`).

Konsequenz: Nach einem legitimen `update_binding` kann ein bereits gepinnter Run beim naechsten `materialize_prompt` Template-Bytes oder Template-Metadaten aus der neuen Projektbindung ziehen, waehrend Audit und Pin weiterhin die alte Bundle-Version behaupten. Das verletzt FK-44 §44.3/§44.7 und formal `binding_changes_affect_only_future_runs` (`concept/formal-spec/prompt-runtime/invariants.md:34-36`). Der invertierte Test prueft nur den nackten Resolver (`tests/unit/prompt_runtime/test_pins.py:189-193`), nicht das Story-Szenario `run_pinned -> materialize-agent-prompt-instance` (`concept/formal-spec/prompt-runtime/scenarios.md:44-53`).

Severity: ERROR.

### E2 - Prompt-Audit-Producer ist definiert, aber nicht in der echten Composition-Root verdrahtet

`register_prompt_runtime_producers` existiert und registriert `ArtifactClass.PROMPT_AUDIT` (`src/agentkit/prompt_runtime/register.py:23-37`). Die normale App-Composition-Root ruft ihn aber nicht auf: `build_producer_registry()` erstellt die Registry und registriert nur Verify-Produzenten (`src/agentkit/bootstrap/composition_root.py:59-61`).

Das ist kein Testdetail. `ArtifactManager.write` validiert vor dem Schreiben (`src/agentkit/artifacts/manager.py:77-80`), `EnvelopeValidator` ruft die Registry auf (`src/agentkit/artifacts/validator.py:128-130`), und die Registry wirft bei unbekanntem Producer fail-closed (`src/agentkit/artifacts/producer_registry.py:110-118`). Die neuen Tests umgehen genau diesen Produktionspfad, indem sie lokal eine nackte `ProducerRegistry()` erzeugen und `register_prompt_runtime_producers(registry)` selbst aufrufen (`tests/unit/prompt_runtime/test_audit.py:42-46`, `tests/unit/prompt_runtime/test_runtime.py:112-120`).

Konsequenz: PromptRuntime-Audit-Persistenz ist ueber den normalen `build_artifact_manager()`-Pfad kaputt.

Severity: ERROR.

### E3 - `ArtifactClass.PROMPT_AUDIT` ist nicht vollstaendig durch alle gebundenen Stellen gezogen

Mehrere harte gebundene Stellen fehlen:

- `sqlite_store` hat im globalen SQLite-DDL noch nur acht Werte und kein `prompt_audit` (`src/agentkit/state_backend/sqlite_store.py:420-423`). Das ist kritisch, weil ein vorher durch `sqlite_store` angelegtes `artifact_envelopes`-Schema durch das spaetere `CREATE TABLE IF NOT EXISTS` in `artifact_repository` nicht korrigiert wird (`src/agentkit/state_backend/store/artifact_repository.py:302-329`). FK-18 verlangt Side-by-Side-Konsistenz fuer die neue Schema-Version (`concept/technical-design/18_relationales_abbildungsmodell_postgres.md:473-485`), nicht zwei konkurrierende DDL-Wahrheiten.
- `verify_system/_artifact_specs.py` kennt den neuen Enum-Wert nicht in `_ARTIFACT_CLASS_TO_TARGET_TYPE` (`src/agentkit/verify_system/_artifact_specs.py:82-88`), obwohl die Story explizit diese Mapping-Klasse als zu pruefende gebundene Stelle nennt (`stories/AG3-015-prompt-runtime/story.md:340-341`).
- Der Postgres-Contract-Test pinnt weiter "Alle acht" und laeuft nur ueber acht Klassen (`tests/contract/state_backend/test_artifact_repository_postgres.py:125-140`). Damit ist der wichtigste DB-Contract fuer den neuen Wert nicht fail-closed abgesichert.
- Die Producer-Registrierung ist nicht in der Composition-Root, siehe E2.

Konsequenz: Die Enum-Erweiterung ist halb umgesetzt. Genau der kritischste Scope-Punkt AK5b ist nicht erfuellt.

Severity: ERROR.

### E4 - Audit-Digests spiegeln nicht verlaesslich die konsumierten Bytes

FK-44 fordert Rekonstruierbarkeit, "welcher Prompt in welchen Bytes" genutzt wurde (`concept/technical-design/44_prompt_bundles_materialization_audit.md:299-310`). Der Code berechnet aber an mehreren Stellen Text-Digests statt Byte-Digests:

- `compute_prompt_audit_hash` hasht `template_text.encode("utf-8")` und `output_text.encode("utf-8")` (`src/agentkit/prompt_runtime/audit.py:80-84`).
- Der dynamische Pfad berechnet `output_sha256` vor dem Schreiben aus `content.encode("utf-8")` (`src/agentkit/prompt_runtime/composer.py:296-298`), schreibt danach aber mit `atomic_write_text` (`src/agentkit/prompt_runtime/composer.py:382-385`). `atomic_write_text` oeffnet im Textmodus ohne `newline=""` (`src/agentkit/utils/io.py:34`), also kann Windows `\n` zu `\r\n` materialisieren.
- Der statische Materializer berechnet zwar einmal einen Raw-Byte-Hash (`src/agentkit/prompt_runtime/composer.py:584-586`), aber `PromptRuntime._materialize_static` verwirft ihn und berechnet den Audit-Hash erneut ueber `read_text(...).encode(...)` (`src/agentkit/prompt_runtime/runtime.py:384-388`).

Bewertung des "Windows-Newline-Details": Fachlich waere es vertretbar, wenn `output_sha256` wirklich die Roh-Bytes der materialisierten Datei waere und deshalb von einem kanonischen Text-Template-Digest abweichen duerfte. Dieser Commit garantiert das Gegenteil: der Audit-Hash kann gerade nicht die konsumierten Bytes sein. Das ist kein Dokumentationsdetail, sondern ein Auditierbarkeitsbug.

Severity: ERROR.

### E5 - FK-44 §44.4.2 wird von Verify-System weiterhin umgangen

FK-44 sagt: `verify_system.LlmEvaluator` muss Templates ausschliesslich ueber `PromptRuntime.materialize_prompt` aufloesen (`concept/technical-design/44_prompt_bundles_materialization_audit.md:259-263`). Der bestehende Verify-Prompt-Audit-Pfad importiert und nutzt aber weiter die Submodule direkt:

- Direktimporte `compose_named_prompt`, `initialize_prompt_run_pin`, `write_rendered_prompt_artifact` (`src/agentkit/verify_system/prompt_audit.py:7-12`).
- Zusaetzlich direkter `state_backend.store`-Import (`src/agentkit/verify_system/prompt_audit.py:13`).
- Tatsaechlicher Ablauf: `initialize_prompt_run_pin` -> `compose_named_prompt` -> `write_rendered_prompt_artifact` (`src/agentkit/verify_system/prompt_audit.py:55-74`).

Das ist genau die Top-Surface-Umgehung, die AG3-015 beenden sollte. Nebenbei bleibt dort der lose `rendered-manifest.json`-Pfad aus `write_rendered_prompt_artifact` bestehen (`src/agentkit/prompt_runtime/composer.py:451-479`), statt Audit ueber `ArtifactManager` zu persistieren.

Severity: ERROR.

## Pruefpunkte 1-10

1. **Top-Surface PromptRuntime**: ERROR. Die vier Methoden existieren (`src/agentkit/prompt_runtime/runtime.py:166`, `:184`, `:229`, `:256`), und `runtime.py` importiert nicht aus `state_backend`. Der Vertrag ist trotzdem nicht korrekt erfuellt, weil Materialisierung intern ueber die aktuelle Projektbindung statt den Pin liest (E1) und Verify-System die Top-Surface weiter umgeht (E5).

2. **PromptAuditHash / Audit-Persistenz / render_input_digest**: ERROR. Pydantic v2 frozen/extra=forbid ist korrekt (`src/agentkit/prompt_runtime/audit.py:39-57`), und `render_input_digest` sortiert Keys (`src/agentkit/prompt_runtime/audit.py:81-83`). Audit-Persistenz ueber `ArtifactManager` ist im isolierten Pfad vorhanden (`src/agentkit/prompt_runtime/audit.py:166-182`), aber produktiv nicht verdrahtet (E2) und Byte-Digests sind falsch (E4).

3. **ArtifactClass `prompt_audit` Vollstaendigkeit**: ERROR. Enum und Validator sind erweitert (`src/agentkit/core_types/artifact.py:41`, `src/agentkit/artifacts/validator.py:90-93`), Postgres-Schema und `artifact_repository` enthalten den Wert (`src/agentkit/state_backend/postgres_schema.sql:301-305`, `src/agentkit/state_backend/store/artifact_repository.py:317-321`). Trotzdem fehlen `sqlite_store`, `_ARTIFACT_CLASS_TO_TARGET_TYPE`, der Postgres-Contract und die Composition-Root-Registrierung (E2/E3). SCHEMA_VERSION ist zwar auf 3.7.0 gesetzt (`src/agentkit/state_backend/config.py:14-17`), aber die DDLs sind nicht konsistent.

4. **Statischer Materializer**: ERROR. Hardlink/Symlink/Copy-Fallback ist implementiert (`src/agentkit/prompt_runtime/composer.py:495-513`) und Tests pruefen Bytes/Inode (`tests/unit/prompt_runtime/test_composer.py:491-545`). Aber der statische Pfad nimmt Relpath/SHA aus der aktuellen Projektbindung statt vollstaendig aus dem Pin (`src/agentkit/prompt_runtime/composer.py:565-570`) und der Audit-Hash nutzt nicht die Roh-Bytes (E4).

5. **C2-Invariantenfix / Drift-Test-Inversion**: ERROR. Der Resolver-Fix ist sauber (`src/agentkit/prompt_runtime/pins.py:211-224`), der invertierte Test prueft Stabilitaet (`tests/unit/prompt_runtime/test_pins.py:162-193`), und echte Pin-Korruption wird negativ getestet (`tests/unit/prompt_runtime/test_pins.py:196-235`). Der Fix greift aber zu kurz, weil die Materializer danach wieder ueber die aktuelle Projektbindung lesen (E1).

6. **PromptRunPin / PromptBundleBinding Pydantic v2**: WARNING. Beide sind Pydantic v2, frozen und extra=forbid (`src/agentkit/prompt_runtime/pins.py:44-70`, `src/agentkit/prompt_runtime/resources.py:37-54`), `pinned_at` ist vorhanden und die formalen Alias-Properties existieren (`src/agentkit/prompt_runtime/pins.py:72-80`). Aber die formale Entity enthaelt `project_key` (`concept/formal-spec/prompt-runtime/entities.md:40-47`), das Modell nicht. Das ist mindestens Konzeptschuld, falls Story AK7 das bewusst ausklammert.

7. **reject-stale-local-prompt-cache**: ERROR. Der Basisfall ist implementiert und getestet (`src/agentkit/prompt_runtime/resources.py:244-298`, `tests/unit/prompt_runtime/test_runtime.py:348-364`). Fuer aktive Runs wird der Template-Relpath aber wieder aus der aktuellen Projektbindung geholt (`src/agentkit/prompt_runtime/runtime.py:468-478` plus `src/agentkit/prompt_runtime/resources.py:310-313`), nicht aus der gepinnten Binding-Wahrheit. Das ist dieselbe C2-Luecke wie E1. Zusaetzlich sind die Digests Text-Digests (`src/agentkit/prompt_runtime/resources.py:57-58`, `:285-287`).

8. **Installer-Delegation FK-50 §50.5**: OK. `_write_prompt_bundle_lock` delegiert an `PromptRuntime.update_binding` (`src/agentkit/installer/runner.py:339-357`), nutzt die gemeinsame Lock-Komposition (`src/agentkit/prompt_runtime/runtime.py:63-110`) und der Spy-Test belegt den Delegationspfad (`tests/integration/project_ops/install_fresh/test_install_fresh.py:242-265`).

9. **Windows-Newline-Detail**: ERROR. Fachlich waere Raw-Byte-`output_sha256` korrekt; der Code berechnet Audit-Digests aber aus Text vor/nach Textmode-I/O und verwirft den vorhandenen Raw-Byte-Hash im statischen Pfad (E4). Das ist ein Determinismus- und Auditierbarkeitsbug.

10. **Negativpfade / FAIL-CLOSED**: ERROR. Es gibt gute Negativtests fuer fehlenden Pin, Pin-Korruption, Digest-Drift, fehlenden Manager und unbekannten `render_mode` (`tests/unit/prompt_runtime/test_pins.py:151-159`, `:196-235`; `tests/unit/prompt_runtime/test_runtime.py:281-318`). Es fehlen aber die entscheidenden Negativ-/Regressionstests fuer Produktionsverdrahtung (`build_artifact_manager` + prompt_audit), Materialisierung nach Rebind, sqlite_store-vorinitialisierte DB mit `prompt_audit`, Raw-Byte-Newline-Audit und `prompt_audit` in gebundenen ArtifactClass-Mappings.

## Weitere Befunde

- `ProducerRegistry`-Docstring spricht weiter von "alle acht" ArtifactClass-Werten (`src/agentkit/artifacts/producer_registry.py:68-72`). Das ist nicht der Blocker, aber bei einer Enum-Erweiterung mit ZERO DEBT ist solche Drift ein schlechtes Signal.
- Der Top-Surface-Contract fuer `compute_audit_hash` ist als Text-API modelliert (`src/agentkit/prompt_runtime/runtime.py:229-250`). Fuer FK-44 §44.6 ist eine Byte-orientierte API oder ein explizit normalisierter, auditierter Byte-Kontrakt noetig.

## AK-Matrix

| AK | Urteil | Beleg |
|---|---|---|
| AK1 Top-Surface vorhanden | OK mit Einschraenkung | Klasse und vier Methoden vorhanden (`runtime.py:132-266`), aber Exklusivnutzung verletzt durch Verify-System (E5). |
| AK2 Materialisierung + AuditManager | ERROR | Runtime persistiert ueber Manager (`audit.py:166-182`), aber Produktions-Registry fehlt (E2), Verify-Pfad schreibt weiter lose Manifestdaten (E5), Byte-Digests falsch (E4). |
| AK3 Statischer Materializer | ERROR | Link-Projektion vorhanden (`composer.py:495-513`), aber nicht vollstaendig pin-stabil und Audit nicht raw-byte-korrekt (E1/E4). |
| AK4 Dynamischer Materializer | ERROR | Renderpfad existiert, aber Template-Text kommt nach Rebind aus aktueller Projektbindung (`composer.py:246-247`, `resources.py:310-313`). |
| AK5 PromptAuditHash typisiert | OK | Pydantic v2, frozen, extra=forbid und Schema-Test vorhanden (`audit.py:39-57`, `tests/contract/prompt_runtime/test_prompt_audit_schema.py:23-45`). |
| AK5b ArtifactClass vollstaendig | ERROR | `sqlite_store`, Verify-Mapping, Postgres-Contract und Composition-Root fehlen (E2/E3). |
| AK6 C2-Invariantenfix | ERROR | Resolver/Test OK, Materialisierung bleibt driftfaehig (E1). |
| AK7 Run-Pin Pydantic | WARNING | Pydantic + `pinned_at` + Alias-Properties OK (`pins.py:44-80`), `project_key` aus formal Entity fehlt (`formal...entities.md:40-47`). |
| AK8 Stale-Cache-Reject | ERROR | Basisfall OK, aber active-run/pinned-binding und Raw-Byte-Semantik nicht sauber (Pruefpunkt 7). |
| AK9 Installer-Delegation | OK | Delegation und Integrationstest vorhanden (`runner.py:339-357`, `test_install_fresh.py:242-265`). |
| AK10 Negativpfade | ERROR | Wichtige Negativpfade fehlen: Produktions-Registry, Materialisierung nach Rebind, sqlite_store-DDL, Byte-Newline-Audit, ArtifactClass-Mapping. |

## Gesamturteil

BLOCK.

Begruendung: AG3-015 behauptet FK-44-Completion, aber die Kerninvariante "aktive Runs bleiben stabil" ist nur im Resolver, nicht im Materializer, erfuellt. Prompt-Audit ist ueber den normalen ArtifactManager-Pfad nicht verdrahtet, `prompt_audit` ist an mehreren gebundenen ArtifactClass-Stellen unvollstaendig, und die Audit-Digests spiegeln nicht verlaesslich konsumierte Bytes. Das sind ERRORs, keine nachlaufenden Warnings.
