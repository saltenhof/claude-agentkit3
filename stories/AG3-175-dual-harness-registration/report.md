# AG3-175 — Story-Bericht

- **Story:** Projektlokale MCP-Registrierung fuer Claude Code UND Codex
- **Branch:** `feat/ag3-175-dual-harness-registration` (11 Commits, gegen `main`)
- **Review:** EINE Codex-Runde (PO-Budget), `review-1-codex.md` — 7x P1, 2x P2,
  1x P3, kein P0. **Alle zehn Findings eingearbeitet**, keine zweite Runde.
- **Status:** **NICHT** `completed`, **nicht** gemerged. Zwei PO-Entscheidungen
  offen (§8); das Konzept-Delta gehoert zum sauberen Abschluss.
- **Bindende Vorgaben:** `../AG3-174-vectordb-retrieval-engine/po-decisions.md`
  (D2, D4, D6) und **D-1** (tomlkit, PO-Freigabe im Verlauf dieser Story).

---

## 1. Was geliefert wurde

Ein **einmal** gerenderter, digestgebundener MCP-Server-Spec wird nach
bestandenem AG3-164-Conformance-Check in **beide** projektlokalen
Harness-Konfigurationen projiziert — ueber **einen** semantischen Writer je
Format, mit ehrlicher Zwei-Dateien-Fehlersemantik.

| Modul | Rolle |
|---|---|
| `backend/core_types/mcp_server_registration.py` | **neu** — BC-neutraler Vertrag: `DesiredMcpServer` (frozen), `REGISTERED_ENV_KEYS` (5), `AK3_SERVER_SHAPES` (erwartete Registrierung, SSOT), kanonischer Payload + Digest |
| `backend/installer/mcp_registration.py` | **neu** — Kommando/Args, `env`-Rendering, Spec-Projektion, verlustfreie Probe-Bruecke, `.mcp.json`-Projektion inkl. Kollisionsregel, `cwd`-Invariant, Probe-Quittung |
| `harness_client/harness_adapters/codex_config_toml.py` | **neu** — der EINE semantische Codex-TOML-Writer + zweistufiges Ownership-Praedikat |
| `backend/installer/codex_settings.py` | Installer-Rand: Pfad, Containment, atomarer Write, Idempotenz |
| `backend/installer/bootstrap_checkpoints/cp10.py` | Zwei-Dateien-Koordination, Phasenordnung, Rollback |
| `backend/config/models.py`, `installer/runner.py` | typisierte Endpunkte + Scaffold-Stanza |
| `backend/installer/lifecycle/detach.py` | **nur** das Klassifikationspraedikat |
| `bundles/target_project/.codex/config.toml` | **geloescht** — dritter Writer (§5) |

**Dependency:** `tomlkit==0.15.1`, exakt gepinnt, MIT, ohne transitive
Runtime-Deps. Installiert ausschliesslich ueber
`.venv\Scripts\python -m pip install -e ".[dev]"`. `pip show tomlkit` → `0.15.1`,
`Requires:` leer. **Kein `mypy`-Override** noetig: tomlkit liefert `py.typed`,
`mypy --strict` ist sauber — anders als `weaviate.*`/`tokenizers.*` also **kein**
`ignore_missing_imports`. Alle 13 Round-Trip-Garantien wurden gegen die
**installierte** Version nachgemessen (Fremd-Kommentare/-Tabellen/-Server,
Key-Reihenfolge, byte-identischer Zweit-Merge). Gegenprobe: `tomli-w` 1.2.0
loescht **jeden** Kommentar.

---

## 2. Akzeptanzkriterien — Verdikt, Evidenz, Delta zu Codex

Codex' Spalte ist der Stand **vor** der Einarbeitung; die letzte Spalte nennt das
Finding, ueber das sich der Status geaendert hat. Kein AC wird ohne benannte
Aenderung auf „erfuellt" gesetzt.

| AC | Codex (vorher) | jetzt | geaendert durch |
|---|---|---|---|
| AC1 | teilweise | **erfuellt** | R02 (konkurrierende Fremdaenderung nicht mehr verlierbar), R03 (kein stilles Ueberschreiben unter reserviertem Namen) |
| AC2 | erfuellt | **erfuellt** | — |
| AC3 | erfuellt | **erfuellt** | — |
| AC4 | teilweise | **erfuellt** | R04 (idempotenter PASS laeuft durch die Probe) |
| AC5 | teilweise | **erfuellt** | R05 (initial falscher `cwd`), R06 (nicht-substituierter Produktivpfad) |
| AC6 | teilweise | **erfuellt** | R02 (konsistenter Snapshot), R03 (`.mcp.json`-Konfliktpruefung), R08 (Beweis fuer gescheitertes Rollback) |
| AC7 | teilweise | **erfuellt** | R01 (Wert-Gate: veraenderte/leere reservierte Tabelle wird nicht mehr geloescht) |

### AC-Evidenz im Einzelnen

**AC1 — beide Konfigurationen registriert, idempotent, Fremdeintraege erhalten**
- `tests/integration/installer/test_codex_mcp_registration.py::test_both_configs_registered_and_mcp_table_survives_a_second_run` — die MCP-Tabelle ueberlebt die CP-8-Region des **zweiten** Laufs (der Kern von Befund B).
- `…::test_bundle_no_longer_ships_a_competing_codex_config` — der dritte Writer existiert nicht mehr.
- `tests/unit/installer/checkpoint_engine/test_cp10_dual_registration.py::test_register_writes_both_harness_configurations`, `::test_second_run_is_pass_and_writes_nothing`, `::test_foreign_entries_in_both_files_are_preserved`.
- `test_cp10_review_findings.py::test_concurrent_foreign_mcp_json_change_is_never_silently_lost` und `…_codex_change_…` — eine gleichzeitige Fremdaenderung **ueberlebt oder** der Lauf schreibt nichts; nie stilles Verschwinden.

**AC2 — feldweise Wertgleichheit + `required = true`**
- `tests/contract/installer/test_mcp_registration_binding.py::test_shared_field_is_value_equal_in_both_formats[command/args/cwd/env]`, `::test_env_carries_project_id_and_both_endpoints_in_both_formats`, `::test_codex_entry_declares_required_true`, `::test_format_specific_fields_do_not_leak_across_formats`.

**AC3 — niemals Userspace, projektlokal, keine Alias-Ausbrueche**
- `test_codex_mcp_registration.py::test_junctioned_codex_dir_is_refused_without_writing_the_target` — echte Junction, Ziel bleibt leer. **Revert-rot.**
- `::test_isolated_codex_home_is_never_written` und `::test_registration_is_invisible_from_a_second_project_folder` — **Regressionssperren, keine Revert-Rot-Beweise** (§4).

**AC4 — Registrierung erst nach bestandenem Check**
- `test_cp10_dual_registration.py::test_failed_conformance_writes_neither_file`.
- `test_cp10_review_findings.py::test_idempotent_rerun_still_probes_and_fails_when_the_server_broke` — ein unveraenderter Eintrag mit **kaputtem** Server ergibt FAILED, nicht PASS (R04).
- `::test_idempotent_pass_is_reached_only_through_a_passing_probe`, `::test_read_only_modes_still_never_start_a_process`.
- `tests/unit/installer/test_mcp_registration.py::test_probe_bridge_carries_cwd_and_env_losslessly` und `::test_probe_bridge_does_not_lose_cwd_the_way_the_json_entry_path_does` — pinnt, **warum** die Bruecke `server_command_from_mcp_entry` umgeht (das kann `cwd` strukturell nicht tragen, `mcp_conformance/check.py:227`).

**AC5 — digest-/wertgleiche Bindung + Negativmatrix**
- `test_mcp_registration_binding.py::test_any_field_changed_after_the_probe_is_detected[4 Faelle]`, `::test_any_env_value_changed_after_the_probe_is_detected[5 Keys]`.
- `test_cp10_dual_registration.py::test_field_mutation_after_the_probe_prevents_both_writes`.
- `test_cp10_review_findings.py::test_cwd_other_than_the_project_root_is_refused_before_probing` — initial falscher, nicht-leerer `cwd`, **vor** der Probe (R05).
- `::test_real_derivation_produces_the_production_spec_unsubstituted` (null Doubles) und `::test_real_derivation_is_what_the_probe_receives`, plus `test_codex_mcp_registration.py::test_full_cp8_to_cp10_region_uses_the_real_derivation` (R06).
- Negativmatrix: Nicht-Default-Endpunkte wortgleich, leerer/falscher `cwd`, fehlende `env`-Felder (`test_mcp_registration.py::test_projection_rejects_a_missing_registered_env_key`), abweichende `PROJECT_ID`.

**AC6 — ehrliche Zwei-Dateien-Fehlersemantik**
- `test_cp10_dual_registration.py::test_codex_parse_error_yields_zero_writes`, `::test_io_error_after_first_write_rolls_back_and_names_the_error`, `::test_rollback_deletes_a_file_that_did_not_exist_before`, `::test_retry_after_incomplete_registration_converges`, `::test_crash_window_state_converges_when_only_codex_is_missing`.
- `test_cp10_review_findings.py::test_failed_rollback_is_reported_honestly_with_the_residual_state` — Assertion auf die **Restbytes** (R08), plus `::test_successful_rollback_does_not_claim_failure`.
- `::test_phase_two_reads_each_file_exactly_once` — struktureller Pin gegen den Doppel-Read (R02).
- `::test_locked_mcp_json_is_a_named_result_not_a_raw_exception`, `::test_locked_codex_config_…`, `::test_cp8_wraps_a_locked_codex_config_in_installation_error` — echter Share-Lock (R09).

**AC7 — Striktheits-/Erhaltungsmatrix**
- `tests/unit/harness_client/test_codex_config_toml.py::test_rejection_matrix[17 Faelle]`, `::test_foreign_occupation_of_an_ak3_server_name_is_rejected`, `::test_preservation_matrix_keeps_every_foreign_element`.
- `test_cp10_dual_registration.py::test_rejection_matrix_leaves_both_files_byte_identical[9 Faelle]` — dieselbe Matrix am Checkpoint, **beide** Dateien byte-identisch.
- Wert-Gate (R01): `::test_altered_values_under_an_ak3_name_are_not_ak3_owned[4]`, `::test_empty_reserved_table_is_not_ak3_owned`, `::test_ak3_registration_of_another_project_is_not_ak3_owned_here`, `::test_recognition_helper_accepts_only_the_expected_shape`.
- Nicht-Schwaechung von `preserved_foreign_files`: `tests/integration/installer/test_detach.py::test_detach_preserves_an_ak3_only_config_carrying_a_user_comment`, `::test_detach_preserves_config_with_a_foreign_table_alongside_the_mcp_entry`, `::test_detach_preserves_an_unparsable_codex_config`, `::test_detach_removes_an_ak3_config_stored_with_crlf`.

**Ausdruecklich nicht erfunden:** TOML hat keinen Nicht-Tabellen-Root
(`tomllib.loads` liefert stets ein `dict`), also existiert AC 7s „falsche
Root-Shape" in TOML nicht. Das ist an `CodexConfigRejection` dokumentiert statt
als Pseudo-Testfall gebaut; die aequivalenten Faelle sind `hooks_not_table` und
`mcp_servers_not_table`.

### Messwerte

```
pytest tests/unit -q --cov=src            -> 8651 passed, 14 skipped (6:08)
pytest tests/contract tests/integration -m "not requires_gh" -q --cov=src --cov-append
                                          -> 2148 passed (4:22)
                                          -> Total coverage 91.14% (Schwelle 85 % erreicht)
ruff check src tests                      -> All checks passed!
mypy src                                  -> Success: no issues found in 1001 source files
```

Coverage der neuen/geaenderten Module: `mcp_server_registration.py` **100 %**,
`codex_config_toml.py` 99 %, `mcp_registration.py` 98 %, `codex_settings.py` 96 %,
`detach.py` 92 %, `cp10.py` 91 % — zusammen **95 %**. Neue Tests: 136 in acht
Dateien.

---

## 3. Die zehn Review-Findings

| # | Sev | Kern | Behebung |
|---|---|---|---|
| R01 | P1 | Ownership-Vergleich war **selbstreferenziell** (gegen ein Rendering der gefundenen Werte) → fremde Tabelle unter reserviertem Namen galt als AK3-eigen, Detach loeschte die ganze Datei | Zweistufiges Praedikat: **Wert-Gate** gegen die *erwartete* Registrierung (`AK3_SERVER_SHAPES` + `cwd`==Project-Root), dann Spelling-Gate. Ambivalentes → MIXED (erhalten). Writer lehnt leere reservierte Tabelle ab. |
| R02 | P1 | **Zwei Reads je Datei**: neueres Before-Image an aelteres Rendering gebunden; der Waechter autorisierte das veraltete Ueberschreiben | **Ein** Read je Datei in Phase 2; Parsen, Rendern und Before-Image aus genau diesen Bytes. `raw=` ist ein **Pflicht**-Keyword, der Zweit-Read ist strukturell unmoeglich. |
| R03 | P1 | `.mcp.json` ueberschrieb fremden Eintrag unter AK3-Namen still (Codex lehnte ab) **und** verwarf unbekannte Felder bei Identitaetstreffer | Dieselbe Identitaetsregel (`command`+`args`, FK-76 §76.5.1) in beiden Formaten; bei Treffer feldweiser Upsert mit **Erhalt** unbekannter Felder |
| R04 | P1 | Byte-identische Registrierung ergab PASS **ohne** Handshake — eine von dieser Story eingefuehrte Regression gegen `main` | Probe zurueck **vor** das idempotente Verdikt; DRY_RUN/VERIFY bleiben prozessfrei |
| R05 | P1 | Ein von Anfang an falscher, nicht-leerer `cwd` wurde akzeptiert | `assert_cwd_is_project_root` an der Projektionsgrenze, **vor** der Probe |
| R06 | P1 | Produktive Verdrahtung durch Testdoubles ersetzt, Evidenzbehauptung zu stark | Echtes Produktions-Repository in der Integration; drei nicht-substituierte Tests; ehrliche Double-Liste (§6) |
| R07 | P1 | Konzept-Delta liess FK-03 aus | Vorschlag auf **zehn** Positionen erweitert (§8.1) — **keine** Konzeptdatei angefasst |
| R08 | P2 | Meldung eines **gescheiterten** Rollbacks ungetestet | Test mit zweitem simulierten Fehler; Assertion auf die **Restbytes** |
| R09 | P2 | Read-`OSError` entkam als rohe Exception | Uebersetzung in `configuration_invalid` vor jedem Write; CP 8 huellt in `InstallationError`. **Echter** Share-Lock als Testauslöser |
| R10 | P3 | Stale Writer-Pfad im Dependency-Kommentar | korrigiert (auch vier Vorkommen in `impl-plan.md`) |

### Drei Loecher im selben Praedikat — die Lehre dieser Story

Das Ownership-Praedikat hatte **drei** unabhaengige Loecher, gefunden auf drei
verschiedene Weisen:

1. **Unbekannte Felder** — von einem **eigenen** Test gefunden: der kanonische
   Renderer gab unbekannte Harness-Felder mit aus, wodurch eine Datei mit einem
   solchen Feld byte-identisch re-renderte und beim Detach geloescht worden waere.
2. **CRLF** — von einem **bestehenden** Test gefunden: eine mit CRLF gespeicherte
   AK3-Datei bestand den Byte-Gate nie, Detach liess AK3s eigene Datei liegen.
3. **Wert-/Provenienz-Identitaet (R01)** — von **Codex** gefunden: der Vergleich
   gegen ein Rendering der *gefundenen* Werte kann per Konstruktion keine
   Wertabweichung sehen.

(1) und (2) waren Symptome, (3) war die Ursache. Erst der Wert-Gate macht das
Praedikat tragfaehig.

---

## 4. Revert-Rot-Ledger

Jede Negativzusicherung wurde durch **Zurueckdrehen der Produktionsaenderung**
geprueft, der Test ausgefuehrt, die Datei wiederhergestellt und der Gruen-Stand
erneut bestaetigt. **23 Mutationen, 23x rot, 0x gruen.**

| # | Mutation | Test | Ergebnis |
|---|---|---|---|
| 1 | Byte-Gleichheit in `write_codex_settings` wieder eingesetzt | Zwei-Lauf-Ueberlebenstest | RED |
| 2 | Kanonischer Byte-Gate in `classify_ownership` entfernt | Kommentar-Erhalt (Detach) | RED |
| 3 | `verify_binding()` zur No-Op | AC-5-Bindung | RED |
| 4 | Rollback zur No-Op | Rollback-Test | RED |
| 5 | Containment-/Junction-Guard **komplett** entfernt | Junction-Test | RED |
| 6 | Conformance-Gate uebersprungen | Null-Writes-Test | RED |
| 7 | Modul auf `…vectordb.mcp_server` zurueckgedreht | 7 Tests | RED |
| 8 | gRPC-Scheme-Guard entfernt | Endpunktmatrix | RED (4) |
| 9 | HTTP-Path/Query/Fragment-Guard entfernt | Endpunktmatrix | RED (3) |
| 10 | HTTP-Userinfo-Guard entfernt | Endpunktmatrix | RED |
| 11 | gRPC-Host-Delimiter-Guard entfernt | Endpunktmatrix | RED |
| 12 | R01 Wert-Gate entfernt | Wert-Gate-Matrix | RED (5) |
| 13 | R01b leere Tabelle als freier Slot | Writer-Ablehnung | RED |
| 14 | R04 Probe hinter das Idempotenz-Return | kaputter Server → PASS? | RED |
| 15 | R03a Kollisionspruefung (CP-10-Ebene) entfernt | Zwei-Dateien-Null-Write | RED |
| 16 | R05 `cwd`-Invariant entfernt | Pre-Probe-Ablehnung | RED |
| 17 | R06 Ableitung auf `mcp_server` zurueck | 2 nicht-substituierte Tests | RED |
| 18 | R02 Zwei-Read-Form wiederhergestellt | Concurrent + Strukturtest | RED (2) |
| 19 | R08 Rollback-Fehlermeldung geschluckt | Restbytes-Test | RED |
| 20 | R09 `.mcp.json`-Read-`OSError` ungeschuetzt | Share-Lock-Test | RED |
| 21 | R09 CP-8-`OSError` entkommt untypisiert | CP-8-Share-Lock | RED |
| 22 | R03a Kollisionsablehnung (Unit-Ebene) entfernt | Merge-Ablehnung | RED |
| 23 | R03b Erhalt unbekannter Felder entfernt | Merge-Erhalt | RED |

**Zwei Fehler im Revert-Verfahren selbst — beide gefunden, weil die Reverts
tatsaechlich gefahren wurden:**

- Der erste AC-3-Revert war **zu schmal**: nur `is_directory_link` abzuschalten
  liess den Containment-Check greifen, der Test blieb gruen. Erst das Entfernen
  des **gesamten** Guards ist rot (Zeile 5).
- Die erste R02-Reproduktion war **gruen aus dem falschen Grund**: sie patchte nur
  `read_bytes`, waehrend der veraltete Parse-Read ueber `read_text` lief. Mit
  einem gemeinsamen Zaehler ueber **beide** APIs — wie ein echter Nebenlaeufer —
  ist die Zwei-Read-Form rot (Zeile 18).

**Ausserhalb des Nenners — Regressionssperren, KEINE Revert-Rot-Beweise:**

| Test | Warum kein Beweis |
|---|---|
| `test_isolated_codex_home_is_never_written` | AK3 liest `CODEX_HOME` **nirgends** (geprueft: kommt in `src/` und `tools/` nicht vor). Es gibt keine Produktionszeile, deren Entfernen den Test rot macht. Er sperrt eine kuenftige Regression, er beweist keinen Fix. |
| `test_registration_is_invisible_from_a_second_project_folder` | Strukturelle Zusicherung (projektrelativer Pfad), nicht revert-rot gegen eine Aenderung **dieser** Story. |

Bilanz: **25 negative Zusicherungen**, davon **23 revert-rot belegt** und **2
ausdruecklich als Regressionssperren ausgewiesen**. Codex hat diese Einordnung
als korrekt bewertet.

---

## 5. Vorbestehender Datenverlust-Defekt, in Vorbeigehen geschlossen

**Kein Aufraeumen, sondern ein Datenverlustpfad im Ist-Zustand.**

`runner._deploy_static_resource_files` (`runner.py:543-558`) kopiert **jede**
Nicht-`templates`-Datei aus dem Bundle ins Zielprojekt, aufgerufen in
`runner.py:1147` — also in **CP 8** und **vor** `write_codex_settings`
(`runner.py:1186`). Am echten Produktionspfad gemessen, mit nutzererweiterter
Datei:

```
BEFORE: AK3-Hook + "# user note: my own Codex settings, please keep" + [user.custom]
AFTER : AK3-Hook
USER CONTENT SURVIVED: False
```

Ein Zielprojekt verlor seine eigene Codex-Konfiguration beim naechsten
Installationslauf — waehrend `detach.py:340-362` ausdruecklich den Umweg geht,
genau diesen Fremdinhalt zu **erhalten** und als `preserved_foreign_files` zu
melden (FK-10 §10.2.9). **Die Installation zerstoerte, was das Detach schuetzt.**

**Zwei Ursachen**, beide behoben: die Bundle-Kopie (Datei geloescht) **und** der
Fixstring-Byte-Vergleich in `write_codex_settings` (semantischer Writer). Die
Bundle-Loeschung allein genuegt nicht — deshalb ist der Beweis
`test_user_extended_codex_config_survives_two_install_runs` gegen **beide**
Ursachen revert-rot.

**Severity: ERROR, nicht WARNING.** Nach SEVERITY-SEMANTIK ist ein stiller
Verlust von Nutzereigentum kein aufschiebbarer Handlungsauftrag: er ist
irreversibel, unbemerkt und trifft fremdes Eigentum. Ein Warning waere hier
faktisch ein ignorierter Befund gewesen.

---

## 6. Test-Doubles — vollstaendige, korrigierte Liste

Die frueher im `impl-plan.md` stehende Behauptung „**genau ein Stub**" war
**falsch**. Eine unzutreffende Ehrlichkeitsaussage ist schlimmer als keine,
deshalb steht die Korrektur hier im dauerhaften Protokoll und nicht nur im Plan.

| # | Double | Warum | Blindstelle | Was sie schliesst |
|---|---|---|---|---|
| 1 | simulierter `OSError` beim **zweiten** Write | Pfad „I/O-Fehler nach dem ersten Write" ist anders unerreichbar | — | — |
| 2 | simulierter `OSError` beim **Rollback** | Pfad „Rollback scheitert ebenfalls" ist anders unerreichbar (R08) | — | — |
| 3 | Substitution von `_desired_mcp_servers` in den CP-10-Mechanik-Tests | die Conformance-Probe kann ohne laufende Weaviate sonst nicht bestehen | **CP 10 koennte aufhoeren, die produktive Ableitung zu benutzen — alle bleiben gruen. Genau diese Klasse liess R04 durch.** | `test_real_derivation_produces_the_production_spec_unsubstituted` (null Doubles), `test_real_derivation_is_what_the_probe_receives`, `test_full_cp8_to_cp10_region_uses_the_real_derivation` |
| 4 | Substitution von `check_mcp_conformance` in Negativ-/Ordnungstests | gezielte Probe-Ausgaenge sind anders nicht deterministisch herstellbar | Probe-Ergebnis nicht echt | die echten Probe-Laeufe gegen `tests/fixtures/minimal_mcp_server.py` in denselben Suites |

**Nicht mehr vorhanden:** die In-Memory-`registration_repo` in der
**Integrations**abdeckung. Dort laeuft jetzt das echte
`StateBackendProjectRegistrationRepository` (SQLite-Pfad, dieselbe Klasse, die der
Composition-Root verdrahtet). Dass CP 10 die Registry **gar nicht** anfasst, ist
bewiesen statt angenommen:
`test_registration_repository_is_never_touched_by_cp10`. In den Unit-Tests bleibt
das In-Memory-Repository — dort ist es die CLAUDE.md-Ausnahme („isolierter
Unit-Test technisch sonst nicht moeglich").

**Einordnung:** Die CP-10-Mechanik-Tests sind **Unit-/Functional-Abdeckung** der
Zwei-Dateien-Mechanik. Sie sind **kein** Beweis der produktiven Verdrahtung; den
tragen ausschliesslich die drei nicht-substituierten Tests.

---

## 7. Restrisiken — ungeschminkt

1. **AC 1 setzt produktiv eine erreichbare Weaviate voraus.** `compose_runtime`
   (`engine.py:1204-1211`) verbindet und legt Collections an, **bevor** der
   stdio-Server laeuft; die Conformance-Probe kann ohne Weaviate nicht bestehen.
   **Die CI beweist AC 1 NICHT mit dem produktiven Kommando.** Sie beweist die
   CP-10-Mechanik (echter `minimal_mcp_server.py` als Kommando-Substitut) und die
   Startbarkeit + `env`-Vollstaendigkeit des produktiven Eintrags **offline**
   (`test_registered_entry_starts.py`: der Prozess erreicht die
   Weaviate-Connect-Schicht, die unmittelbar nach jeder `env`-Pruefung liegt). Das
   Zusammenspiel bleibt dem opt-in-E2E-Layer. Konsistent mit AG3-176 Scope 1 und
   der E2E-Abgrenzung der Story.
2. **Gefaelschte Probe-Quittung ist nicht verhinderbar.** Frozen macht
   In-place-Mutation unmoeglich, der Digest erkennt jede Substitution, und es gibt
   keinen Write-Pfad ohne Quittung. Wer den Digest jedoch **mitberechnet**,
   faelscht keine Feldaenderung mehr, sondern eine Quittung — dagegen schuetzt
   kein Sprachmittel. Der richtige Umgang ist neu proben.
3. **Zwei-Dateien-Crashfenster.** Es gibt **keine** gemeinsame
   Dateisystemtransaktion. Jeder Einzelwrite ist atomar (`temp` + `fsync` +
   `os.replace`), die **Paarung** nicht. Ein harter Abbruch dazwischen laesst
   `.mcp.json` aktualisiert und `.codex/config.toml` nicht. Der Zustand ist
   **erkennbar** (fehlende `[mcp_servers.story-knowledge-base]`-Tabelle) und
   konvergiert beim naechsten Lauf. **Keine Atomizitaetsbehauptung.**
4. **Einmaliges kosmetisches Neuschreiben.** Die kanonische Rendition
   unterscheidet sich um eine Leerzeile nach dem Kopfkommentar (tomlkit) und
   schreibt LF statt plattformabhaengiger Zeilenenden (`newline=""`).
   Bestandsprojekte bekommen die Datei **einmal** neu geschrieben. Kein
   Inhaltsverlust.
5. **`write_codex_settings` wirft jetzt** bei unlesbarer/ungueltiger
   Bestandsdatei (`InstallationError`) statt sie zu ueberschreiben. Bewusste
   Verhaltensaenderung; FK-76 §76.5.4 verlangt genau das („unparsable TOML … ist
   ein harter Fehler ohne Mutation").
6. **`localhost:50051`/`127.0.0.1:50051` bleiben gesperrt**, waehrend FK-13 den
   lokalen gRPC-Port `:50051` nennt. Ratifizierte D2-Semantik aus AG3-174, hier
   **nicht** aufgerollt; ein Test pinnt die Ablehnung, damit sie nicht kuenftig
   als Bug „repariert" wird.
7. **Zurueckgezogene Zusicherung.** Bis R02 behoben war, war „die
   Zwei-Dateien-Koordination schliesst das Stale-Write-Fenster" **falsch** — und
   zwar genau im konkurrierenden Fall, fuer den sie gedacht war. Sie gilt erst
   seit dem konsistenten Ein-Read-Snapshot. Im `impl-plan.md` §7.1 steht die
   Korrektur samt Grund.
8. **Vorbestehender Telemetrie-Importzyklus** (`audit_bundle` ↔
   `projection_accessor`) — nur umgangen (Lazy-Import in `codex_settings`), nicht
   behoben. CLAUDE.md verbietet zirkulaere Abhaengigkeiten; das ist ein Befund
   fuer eine eigene Story. Von diesem Diff unberuehrt (Codex bestaetigt).

---

## 8. Offene PO-Entscheidungen — **nicht** von mir zu schliessen

### 8.1 Konzept-Delta (zehn Positionen) — Autorisierung erbeten

**Keine Konzeptdatei wurde angefasst.** Code folgt dem Konsumenten; die Dokumente
folgen der PO-Entscheidung.

| # | Konzept | Aenderung | Grund (gemessen) |
|---|---|---|---|
| 1 | FK-13 §13.4.3 | `args` → `["-m", "agentkit.backend.vectordb.engine"]` | Das Beispiel nennt eine **Skriptdatei** des **Bibliotheks**moduls. `python -m …mcp_server` endet mit Exit 0 ohne zu serven; der stdio-Einstiegspunkt ist `engine.main` (`engine.py:1258`, `:1311-1312`). Der bisherige Wert erzeugt einen toten Eintrag. |
| 2 | FK-13 §13.4.3 | `WEAVIATE_HOST`/`_HTTP_PORT`/`_GRPC_PORT` → `WEAVIATE_HTTP_ENDPOINT` + `WEAVIATE_GRPC_ENDPOINT` | `runtime_binding.REQUIRED_ENV_KEYS:33-37` verlangt die zwei **Endpunkte**; D2 ratifiziert „Endpunkt ist ein Konfigurationswert". Mit Host+Port startet der Server nicht. |
| 3 | FK-13 §13.4.3 | `GH_REPO` entfaellt | Der String kommt in `src/agentkit/` **nirgends** vor. |
| 4 | FK-13 §13.4.3 | `AGENTKIT_CONCEPTS_DIR` **neu** | `engine.py:1272-1285` verlangt ihn **ohne Default** und beendet sich sonst mit Exit 1 (N20/D2). Fehlt im Konzept vollstaendig. |
| 5 | FK-13 §13.4.3 | `AGENTKIT_STORIES_DIR` **neu**, plus `cwd` | Optional (Default `"stories"`), wird aber explizit gerendert: der Default loest gegen die Prozess-`cwd` auf, und D2 verbietet `cwd` als zweite Konfigurationsquelle. `cwd` fehlt im Beispiel, ist aber Containment-Grenze. |
| 6 | FK-50 §50.3 CP 10 | Beispielblock: `env` (5 Keys), `cwd`, korrigiertes Modul | Dasselbe falsche Modul ein zweites Mal; ohne `env` schreibt das Konzept den Defektzustand fest, den AC 2 schliesst. |
| 7 | FK-50 §50.3 CP 10 | Reason-Tabelle: `configuration_invalid` + `registration_incomplete`; `mcp_configuration_invalid` auf **beide** Spiegel-Dateien praezisieren | Beide Codes werden produktiv emittiert. `configuration_invalid` ist PO-ratifizierte D4-Vokabel, `registration_incomplete` von D6/AC 6 vorgegeben. FK-76 §76.5.4 erklaert dieselben Regeln fuer beide Formate, die FK-50-Tabelle nennt nur `.mcp.json`. |
| 8 | FK-76 §76.5.4 | Absatz „Zwei-Dateien-Fehlersemantik" | PO-Regel: ein unvermeidbarer Rest wird dokumentiert, nie als Atomizitaet verkauft (§7.3). |
| 9 | **FK-03 §3.1** | Beide Endpunktfelder dokumentieren, samt Validierungs-/Default-Semantik **und** ihrer CP-5-/Scaffold-Herkunft | FK-03 erklaert sich zur vollstaendigen Definition der AgentKit-Konfiguration; **jeder** konfigurierbare Parameter muss dort dokumentiert sein (`:25`). Das VectorDB-Beispiel enthaelt weiterhin nur Threshold-/Candidate-Werte (`:157`). Die operator-eigenen Werte reisen `InstallConfig` → CP 5 → `project.yaml`; eine handgepflegte Stanza wuerde der naechste Lauf loeschen. |
| 10 | FK-76 §76.5.4 **+** FK-50 §50.3 CP 10 | Gleichnamen-Kollisionsidentitaet fuer **beide** Spiegel-Dateien explizit: `command`+`args`; Treffer = eigene Felder upserten, unbekannte erhalten | R03 hat aufgedeckt, dass diese Identitaet **unausgesprochen** war — genau deshalb gaben die zwei Formate unterschiedliche Antworten auf „ist dieser Eintrag unser". |

Codex hat die Positionen 1-8 als **einzeln korrekt** bewertet; 9 und 10 sind
Vollstaendigkeit, keine Korrektur.

### 8.2 ARE-Spiegelung — bewusste Ausweitung, Ratifizierung erbeten

**Umgesetzt: der generische Pfad.** Der Codex-Writer projiziert **alle**
gewuenschten Server, nicht nur `story-knowledge-base`.

- **Warum:** FK-76 §76.5.4 formuliert den Vertrag generisch („Je Server eine
  Tabelle `[mcp_servers.<id>]`") und ausdruecklich als **Spiegelung** des
  `.mcp.json`-Vertrags. Codex bewertet das als die **bessere** Konzeptlesung und
  das generische Verhalten ausdruecklich als **keinen** Defekt.
- **Konsequenz, die der PO wissentlich ratifizieren muss:** Ein Projekt mit
  `features.are: true` erhaelt kuenftig **auch** eine
  `[mcp_servers.are-mcp]`-Tabelle in `.codex/config.toml`. Das geht ueber den
  Story-Wortlaut hinaus (Scope 3, AC 1/2 nennen einen Server im Singular).
  Praktisch heute ohne Wirkung: `agentkit-are-mcp` existiert nicht, CP 10
  scheitert fuer ARE-Projekte ohnehin fail-closed (AG3-164).
- **Umschaltpunkt:** eine Zeile — die Server-Menge, die in `_render_both` an
  `render_project_codex_config` geht, auf `story-knowledge-base` filtern. Zwei
  Tests waeren anzupassen.

---

## 9. Abweichungen vom Story-Text

**1. Platzierung des Writers — Konzeptvorrang, nicht Bequemlichkeit.**
Die Story nennt als betroffene Datei `harness_adapters/codex/`. FK-76 §76.9 sagt
„konkrete Adapter sind nicht direkt importierbar", und das Architekturmodell
setzt das durch: `architecture-conformance.group.harness_adapters_codex` traegt
`module_prefixes: agentkit.harness_client.harness_adapters.codex` mit
`exposure: internal` (`entities.md:433-447`). Der Architektur-Konformanz-Check
schlug mit **9 AC001-Verstoessen** gegen das echte Repo fehl. Bei Konflikt
zwischen Story-Dateizeiger und Konzept gilt **das Konzept**
(`stories/README.md` §4.2). Der Writer liegt daher in
`harness_adapters/codex_config_toml.py` — ausserhalb des internen Prefix und
neben `settings_writer.py`, wo der `.codex/hooks.json`-Writer schon liegt; das
`codex/`-Subpackage traegt Hook-**Mediation**, keine Settings-Writer. Codex hat
die Aufloesung als **korrekt** bestaetigt.

**2. Scope-Ausweitung — notwendige Korrektheitsfolge.**
Writer-Konsolidierung, `write_codex_settings`, Detach-Klassifikation und
Loeschung der Bundle-Kopie schliessen **einen** Architekturuebergang; sie stehen
zu lassen hiesse, alte und neue Semantik parallel herumzutragen (ZERO DEBT). Die
Bundle-Loeschung war im Briefing **nicht** benannt und kam als dritter Writer
hinzu (§5). Codex: „Scope-Ausweitung korrekt und notwendig", **kein** weiterer
aktiver `.codex/config.toml`-Writer und **kein** weiterer
byte-gleichheits-gekoppelter Aufrufer gefunden.

**3. Zwei Plan-Aussagen wurden vom Code widerlegt** und sind im `impl-plan.md`
korrigiert: Component-Groups tragen doch eine Exposure-Restriktion, und der
Architektur-Checker laeuft doch gegen das echte Repo. Beide Fehler entstanden aus
**Schluss statt Messung** — derselben Klasse wie der in Plan-Revision 1
widerlegte „Blocker".

---

## 10. Nicht verifizierte Gates — ohne Beschoenigung

Diese Flaechen sind **ungeprueft**. Der Bericht behauptet an keiner Stelle, sie
seien gruen, und keine Evidenz in §2 haengt von ihnen ab.

- **`llm_hub` war nicht verfuegbar.** Beide Versuche erreichten
  `127.0.0.1:9600` und liefen in `ECONNREFUSED`. **Codex' eigene vorgeschriebene
  Gegen-Review ist damit nicht gelaufen.**
- **Jenkins und Sonar liefen in Timeouts**, `check_remote_gates.ps1` hatte keine
  Credentials. Es gibt **keine** unabhaengige Aussage, dass diese Pflicht-Gates
  gruen sind.
- **Codex konnte keinen einzigen Revert-Rot-Lauf ausfuehren** (Read-only-Modus:
  keine Checkouts, Worktrees oder temporaeren Kopien), ebenso **keine**
  dateisystem-mutierenden Write-, Rollback- oder Junction-Tests und **keine**
  Suite-, Coverage-, mypy- oder ruff-Laeufe. Alle Zahlen in §2 sind meine eigenen,
  vom Orchestrator unabhaengig reproduziert.
- **Ein produktiver MCP-Conformance-Erfolg gegen eine laufende Weaviate bleibt
  unverifiziert** (§7.1).

---

## 11. Bestaetigt ausserhalb des Scopes

| Punkt | Einordnung |
|---|---|
| `codex_settings.remove_codex_settings` | kein produktiver Aufrufer; Detach ist der echte Lifecycle-Pfad. Unveraendert gelassen. |
| Drei `agentkit-hook-codex`-Literale + Console-Entry | vorbestehende Namensdopplung ohne neue Verhaltenskopplung |
| `mcp_conformance.server_command_from_mcp_entry` | jetzt ohne produktiven Aufrufer, bleibt bestehende oeffentliche AG3-164-Oberflaeche |
| Vorbestehender Telemetrie-Importzyklus | von diesem Diff unberuehrt, nicht an die Dual-Registrierung gekoppelt (§7.8) |
| `.codex/config.toml` in zwei Pfad-Registries | reine Namenskonstanten, kein I/O |

---

## 12. Definition of Done

| Punkt | Stand |
|---|---|
| Alle Akzeptanzkriterien erfuellt | **ja** (§2) — jedes mit Test und benanntem Delta |
| `pytest` gruen | **ja** — 8651 + 2148, 14 skipped, 0 failed |
| Coverage haelt 85 % | **ja** — 91.14 % (explizit mit `--cov` gemessen) |
| `mypy src` sauber | **ja** — 1001 Dateien |
| `ruff check src tests` sauber | **ja** |
| Eine Codex-Review-Runde, Findings eingearbeitet | **ja** — 10/10, keine zweite Runde |
| Konzept-Gates | **offen** — Delta wartet auf PO-Autorisierung (§8.1) |
| Merge | **nicht erfolgt**, `status.yaml` **nicht** auf `completed` — bewusst, bis §8.1 und §8.2 entschieden sind |
