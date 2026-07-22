# AG3-176 — Verifikationsreview Runde 2

## Auftrag und Methode

Dies ist keine neue Flaechenreview, sondern die gezielte Wurzelverifikation der
Runde-1-Findings R1–R14 plus ein Check auf durch die Remediation eingefuehrte
Substanzfehler. Primaer wurden die produktiven Grenzen gelesen. Harmlos
reproduziert wurden nur drei lokale Temp-Verzeichnis-/In-Memory-Fehlerbilder;
es wurden keine Secrets, fremden Systeme oder missbrauchsartigen Payloads
verwendet.

Die vom Orchestrator gemeldeten 10.162 Tests werden nicht als
Korrektheitsbeweis gewertet. Eine fokussierte Stichprobe ueber Config,
CP10a, Hooks, Closure, Bundle, Codex-Settings und Mutex war lokal ebenfalls
gruen: **55 passed**. Gerade die unten dokumentierten Negativpfade fehlen aber
in dieser Evidenz.

## Verifikationsmatrix R1–R14

### AG3-176-R1 — BLOCKER — noch offen: Fresh Install wirkt vor der installer-spezifischen Config-Grenze

**Ort:**

- `src/agentkit/backend/installer/bootstrap_checkpoints/orchestrator.py:127-169`
- `src/agentkit/backend/installer/bootstrap_checkpoints/orchestrator.py:178-206`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp01_to_06.py:194-278`
- `src/agentkit/backend/installer/runner.py:385-397`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10_mcp.py:302-315`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10a_first_index.py:95-110`

**Verifiziert:** Fuer ein **bestehendes** `project.yaml` liegt
`load_project_config()` plus `require_installer_vectordb_endpoint()` jetzt vor
Bundle-Aufloesung, Engine und Dateiwirkungen. `features.vectordb: false` sowie
fehlender Endpoint brechen dort korrekt mit `configuration_invalid` ab. Die
Verschiebung der Endpoint-Existenzpflicht aus dem globalen Modell an die
Installer-Grenze ist an sich normtreu: globale/tuningbezogene Config-Nutzer
duerfen einen nur-teilweise vorhandenen Block laden; der Installer muss die
vollstaendige Pflicht vor seiner ersten Wirkung erzwingen.

**Noch offen / Fakten-Beleg:** Der Fresh-Install-Ast tut genau das nicht.
`orchestrator.py:167-169` verschiebt die Ablehnung ausdruecklich auf CP5/CP10.
CP5 validiert nur das bewusst gelockerte `ProjectConfig` und scaffoldet danach.
Eine harmlose Temp-Verzeichnis-Probe mit einem `InstallConfig` ohne Weaviate-
Endpoint lieferte:

```text
cp5=created, created_count=17, pipeline_vectordb=False
anschliessende Installer-Grenze: ValueError("installer requires pipeline.vectordb ... before any install effect")
```

Damit entstehen 17 Scaffold-/Config-Artefakte, bevor die Pflichtgrenze den
fehlenden Endpoint erkennt. Der vorhandene R1-Test deckt nur bestehende Config
ab; `make_config()` erfindet fuer alle anderen Installer-Tests immer einen
Test-Endpoint.

Zwei weitere Nachsichten bleiben:

1. Nach erfolgreicher Entry-Validierung faengt `orchestrator.py:194-204` beim
   erneuten Lesen **jede** Exception und faellt auf `model_dump()` zurueck. Ein
   Lese-/Parsefehler oder eine Aenderung zwischen den Reads muss abbrechen, nicht
   eine synthetische Mapping-Kopie in die Installation einspeisen.
2. CP10-Preflight und CP10a bevorzugen `InstallConfig.weaviate_*` vor dem strikt
   validierten `run_state.project_config`. Bei einem bestehenden Projekt kann
   daher Endpoint A validiert, aber Endpoint B registriert/indiziert werden.

**Normverletzung:** AG3-176 AC1/AC2/AC6; FK-13 §13.1/§13.8; FK-50 CP10;
Decision Record Rand 1. Die strikte Config-Grenze liegt nicht vor **jeder**
Installer-Wirkung und die validierte Config ist nicht die Endpoint-SSOT.

**Fix:** Vor Bundle-Aufloesung und Context-/Engine-Bau fuer beide Faelle genau
eine kanonische Candidate-Config herstellen, strikt als `ProjectConfig`
validieren und danach `require_installer_vectordb_endpoint()` aufrufen. Bei
bestehender Datei darf ein Re-Read-Fehler keinen Fallback haben. Alle CP10-/
CP10a-/Dual-Write-Ports muessen den Endpoint ausschliesslich aus dieser
validierten Candidate-Config beziehen; widersprechende `InstallConfig`-Werte
entweder gar nicht zulassen oder vor Wirkungen hart ablehnen.

### AG3-176-R2 — geschlossen und verifiziert

**Ort:**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/manifest.json:4`
- `src/agentkit/backend/skills/manifest_digest.py:18-23`
- `src/agentkit/backend/skills/top.py:74-93`
- `tests/contract/skills/test_skill_catalog_bundles.py:15-60`

Der v5-Digest wird jetzt mit demselben `compute_manifest_digest()` berechnet,
den der Runtime-Binder verwendet. Der Katalog-Contract globbt `*/*/manifest.json`
und prueft damit alle ausgelieferten SemVer-Verzeichnisse statt nur 4.0.0. Die
fokussierten Contracts sind gruen. **R2 ist an der Wurzel geschlossen.**

### AG3-176-R3 — geschlossen und verifiziert

**Ort:**

- `tests/contract/skill_bundles/test_create_userstory_core_v5.py:95-130`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/`

`{{concepts_dir}}` kommt im v5-Bundle nicht mehr vor. Der produktive
Materializer wird ueber alle Markdown-Dateien mit einer realen Substitution
ausgefuehrt; die fokussierte Stichprobe lief gruen. **R3 ist geschlossen.**

### AG3-176-R4 — MAJOR — noch offen: zweiter Completion-Fehler publiziert partielle Freshness

**Ort:**

- `src/agentkit/backend/vectordb/first_index.py:121-189`
- `src/agentkit/backend/vectordb/first_index.py:191-279`
- `src/agentkit/backend/vectordb/first_index.py:289-335`
- `tests/unit/vectordb/test_first_index_receipts.py:171-246`

**Verifiziert:** `story_sync` und `concept_sync` laufen jetzt real mit
`publish_completion=False`; der Concept-Fehlerpfad laesst die Story-Freshness
unveraendert. Empty Corpus erzeugt ohne Exception-Erfolg zwei reale
Nullmengen-Receipts. Auch ein Fehler beim zweiten Receipt entfernt das zuerst
geschriebene Receipt.

**Noch offen / Fakten-Beleg:** Die beiden Completion-Staende werden danach
sequenziell publiziert. Schlaegt der zweite `publish_completion()`-Aufruf fehl,
entfernt der Handler nur die Receipts, restauriert aber den bereits
fortgeschriebenen Story-Completion-Stand nicht. Eine harmlose In-Memory-Probe,
die nur den zweiten lokalen Completion-Write fehlschlagen liess, ergab:

```text
reason=completion_publish_failed
story_freshness_published=True
concept_freshness_published=False
```

Genau dieser Ast hat keinen Test. Bei einem zweiten Receipt-Fehler wird zudem
ein eventuell vorhandenes altes Story-Receipt geloescht statt bytegenau
restauriert. Die angeblichen Invarianten in `_assert_owned()` und
`_assert_completion_unchanged()` bestehen jeweils nur aus `pass`; sie beweisen
und erzwingen nichts. `_read_completion_revision()` schluckt schliesslich jede
Exception als leere Revision.

**Normverletzung:** AG3-176 AC3; FK-50 CP10a; Wahrheit von Freshness/Receipt.
Ein Partialfehler darf weder einen neuen Teil-Completion-Stand noch den Verlust
eines vorher gueltigen Receipts hinterlassen.

**Fix:** Vor der Publikation alte Bytes aller vier Artefakte sichern und bei
jedem Fehler exakt restaurieren, oder einen einzigen atomar publizierten
Commit-/Manifest-Stand als Wahrheitsgrenze verwenden. Ownership-Mismatch und
unlesbare Vorstaende muessen benannt fehlschlagen; die beiden `pass`-Invarianten
sind durch echte Checks/Restoration zu ersetzen. Einen Test fuer Fehler beim
zweiten Completion-Write **mit bereits vorhandenen alten Staenden** ergaenzen.

### AG3-176-R5 — geschlossen und verifiziert

**Ort:**

- `src/agentkit/backend/installer/mcp_registration/dual_write.py:129-154`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10b_hooks.py:30-60`

Die produktiven projektgebundenen Pfade verwenden nun die validierte
`ProjectConfig` beziehungsweise `bind_project()` und erfinden weder
`root/concepts` noch den String `"concepts"`. Binding-Fehler werden typisiert
als `configuration_invalid` zurueckgegeben. Die R1-Re-Read- und Endpoint-SSOT-
Probleme sind separat oben erfasst. **R5 selbst ist geschlossen.**

### AG3-176-R6 — MAJOR — teilweise behoben, aber CP10b ist weiter fail-open verifizierbar

**Ort:**

- `src/agentkit/backend/vectordb/git_hooks.py:61-90`
- `src/agentkit/backend/vectordb/git_hooks.py:117-140`
- `src/agentkit/backend/vectordb/git_hooks.py:143-275`
- `src/agentkit/backend/vectordb/hook_dispatch.py:54-114`
- `src/agentkit/backend/vectordb/hook_dispatch.py:117-171`
- `tests/unit/installer/checkpoint_engine/test_ag3_176_flow_and_hooks.py:125-174`

**Verifiziert:** Der Default-Pre-Commit enthaelt wieder den realen globalen
Secret-Scan. Bei einem erkannten AgentKit-Hook wird nur der markierte Dispatch-
Block ersetzt/angehaengt; die vorhandene Secret-Detection bleibt aktiv. Der
Python-Dispatcher ruft `validate --staged` ueber eine argv-Liste auf und ordnet
Post-Commit `build` vor `sync`; bei Build-/Sync-Fehler wird kein nachfolgender
Erfolgspfad ausgefuehrt.

**Noch offen / Fakten-Beleg:**

1. `pre_commit_is_current()` prueft zwar vermeintlich `--staged`/`validate`,
   fuehrt bei deren Fehlen aber nur `pass` aus. Beide VERIFY-Funktionen suchen
   ansonsten Marker und Textfragmente; ein Hook, dessen Befehle entfernt und
   dessen Kommentare/Marker stehen gelassen wurden, kann weiterhin PASS sein.
   Die Tests lesen lediglich Strings aus Hook und Python-Quelldatei; sie
   materialisieren und manipulieren keinen realen Candidate-Hook.
2. `_staged_paths()` macht Start-/Git-Fehler zu `[]`; `_pre_commit()` deutet
   `[]` als "keine Concept-Aenderung" und beendet mit 0. Kann der Candidate-
   Corpus nicht bestimmt werden, feuert die Pflichtvalidierung also gerade
   nicht fail-closed.
3. Die Shell-Quelle interpoliert `concepts_dir` in doppelte Anfuehrungszeichen.
   Das ProjectConfig-Pfadmodell verbietet absolut/Drive/`..`, aber nicht alle
   von der Shell ausgewerteten Zeichen. Der spaetere Python-Subprozess ist
   argv-sicher; die vorgelagerte Shell-Zeile ist es fuer jeden sonst legalen
   Verzeichnisnamen noch nicht.
4. Der bestehende `hook_migration`-Owner wird nur fuer Marker importiert. Die
   eigentliche chirurgische Migration wird in `git_hooks.py` erneut
   implementiert; damit existieren zwei Owner mit driftfaehiger Semantik.

**Normverletzung:** AG3-176 AC4/AC5; FK-50 CP10b; FK-51-Erhaltungsowner;
Secret-Detection- und Candidate-Corpus-Vertrag.

**Fix:** Materialisierung und Erhalt ueber genau einen Hook-Migration-Owner
fuehren. VERIFY muss den kanonischen markierten Block beziehungsweise seinen
Digest/strukturell exakten Befehl pruefen, nicht Kommentarfragmente. Fehler der
Staged-Path-Ermittlung muessen Pre-Commit mit nonzero beenden. Den Shell-Aufruf
kanonisch quoten oder den konfigurierten Pfad erst im Python-Dispatcher aus der
strikt geladenen Projektconfig beziehen. Tests muessen einen bestehenden realen
Secret-Scan erhalten, den materialisierten Hook ausfuehren und fehlende/
umgeordnete Befehle negativ pruefen.

### AG3-176-R7 — geschlossen und verifiziert

**Ort:**

- `src/agentkit/backend/vectordb/sync_task_registry.py:37-145`
- `src/agentkit/backend/closure/runtime_ports.py:220-269`
- `tests/unit/closure/test_runtime_ports.py:257-338`

Der daemonisierte Einweg-Thread ist entfernt. Ein nicht-daemonisierter
`ThreadPoolExecutor` uebernimmt den Task erst nach erfolgreichem Submit, vergibt
eine Task-ID, haelt Status/Fehler und bietet `drain()`/`shutdown()`. Die Task-ID
wird geloggt; Worker-Fehler werden sowohl geloggt als auch als FAILED-Record
gehalten. Die Tests warten real auf Ausfuehrung und pruefen Success, Failure und
Shutdown. Das ist fuer den normierten nicht-blockierenden Closure-Pfad kein
verlorenes Fire-and-Forget mehr. **R7 ist geschlossen.**

### AG3-176-R8 — MAJOR — VERIFY prueft beide Links, bricht aber Altprojekt-Pins gegen "latest"

**Ort:**

- `src/agentkit/backend/installer/bootstrap_checkpoints/cp07_to_09.py:125-188`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp07_to_09.py:266-370`
- `src/agentkit/backend/installer/runner.py:864-928`
- `src/agentkit/backend/skills/bundle_store.py:434-480`
- `tests/unit/installer/checkpoint_engine/test_ag3_176_flow_and_hooks.py:86-109`

**Verifiziert:** CP8 VERIFY liest nun beide Harness-Links und prueft
Bundle-ID, Version, deklarierten Digest und Runtime-Digest. Fehlende Links
werden korrekt abgelehnt.

**Noch offen / Fakten-Beleg:** Das erwartete Bundle stammt auch im VERIFY aus
`_resolve_mandatory_skill_bundles()`. Der Store waehlt fuer eine Bundle-ID die
hoechste vorhandene SemVer. VERIFY liest nicht den bestehenden Binding-/Pin-
Stand als Soll. Sobald 5.0.0 im Store liegt, wird daher ein voellig gueltiges
Altprojekt, dessen Claude- und Codex-Link beide unveraendert auf 4.0.0 zeigen,
als `expected ...@5.0.0` abgelehnt. Das verletzt genau die in R8 verlangte
Garantie "Alt-Projekte bleiben bis explizitem Reinstall/Upgrade gepinnt". Der
neue Test prueft nur den fehlenden Link, nicht einen konsistenten alten Pin.

**Normverletzung:** AG3-176 AC7; FK-43 §43.4/§43.5/§43.8.

**Fix:** VERIFY muss den persistierten installierten Binding-/Lock-Stand als
Soll lesen und dann beweisen, dass **beide** Links auf genau dessen immutable
ID/Version/Digest zeigen. Die hoechste Store-SemVer darf nur REGISTER bei
explizitem Install/Upgrade auswaehlen. Negativ-/Positivtest mit gleichzeitig
vorhandenem 4.0.0 und 5.0.0 ergaenzen.

### AG3-176-R9 — geschlossen und verifiziert

**Ort:**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/`
- `tests/contract/skill_bundles/test_create_userstory_core_v5.py:55-93`

Im v5-Bundle gibt es keinen `IF_STORY_VECTORDB`-Ast und keine ausfuehrbaren
Grep-/rg-Kommandos mehr. Der Contract prueft diese Abwesenheit semantisch
negativ; die Stichprobe ist gruen. **R9 ist geschlossen.**

### AG3-176-R10 — MAJOR — Uninstall ist chirurgisch, Fresh Install zerstoert weiterhin fremde Codex-Config

**Ort:**

- `src/agentkit/backend/installer/mcp_registration/detach_story_kb.py:40-117`
- `src/agentkit/backend/installer/lifecycle/detach.py:319-408`
- `src/agentkit/backend/installer/runner.py:559-565`
- `src/agentkit/backend/installer/codex_settings.py:32-56`
- `tests/unit/installer/checkpoint_engine/test_ag3_176_flow_and_hooks.py:29-84`

**Verifiziert:** Das urspruengliche Uninstall-Leck ist geschlossen.
`story-knowledge-base` wird aus `.mcp.json` und `.codex/config.toml`
chirurgisch entfernt; Fremdserver und Fremdtabellen bleiben. Die alte
`count("[") <= 2`-Heuristik ist entfernt. Auch Static-Deploy kopiert
`.codex/config.toml` nicht mehr blind.

**Noch offen / Fakten-Beleg:** Der danach aufgerufene `write_codex_settings()`
ist weiterhin ein Full Replace, wenn eine bestehende Datei den AK3-Hook noch
nicht enthaelt. Eine harmlose Temp-Probe mit
`[user_preferences]\ncolor = "blue"` ergab nach dem Writer:

```text
changed=.codex/config.toml, foreign_preserved=False
```

Erhalten wird Fremdinhalt nur, wenn der AK3-Hook bereits vorhanden ist. Der
Fresh-Install-Fall mit einer fremden, hooklosen Codex-Konfiguration ist nicht
getestet und wird zerstoert.

**Normverletzung:** AG3-176 AC4/AC7 und Uninstall-/Dual-Write-Symmetrie;
FK-43/FK-51 Customization Preservation.

**Fix:** Auch den Codex-Hook als chirurgischen, eindeutig markierten TOML-Block
beziehungsweise ueber einen semantischen TOML-Owner mergen. Bei unparsebarer
oder konfliktierender Fremdconfig fail-closed, niemals Full Replace. Den
spiegelbildlichen Remove-Pfad und einen Test mit rein fremder Ausgangsdatei
ergaenzen.

### AG3-176-R11 — fachlich geschlossen; W2/W3 in diesem Workspace nicht reproduzierbar gruen

**Ort:**

- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:473-565`
- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:861-920`

Die widerspruechlichen FK-50-Passagen sind bereinigt: CP10/CP10a sind Pflicht,
`false` ist `configuration_invalid`, und kein normativer
`SKIPPED/vectordb_disabled`-Fall bleibt. Frontmatter- und Formal-Spec-Gates
liefen lokal gruen.

Die ausdruecklich verlangte W2-/W3-Bestaetigung kann ich jedoch nicht geben:

```text
check_concept_authority_prose.py --mode pre-merge --base HEAD~1  -> exit 1
check_concept_scope_consistency.py --scope installer             -> exit 1
E-SCHEMA-003 (_meta/bc-cut-decisions.md): doc_kind 'decision-log' nicht zugelassen
```

Das blockierende Dokument ist tracked und nicht Teil des AG3-176-Diffs; dies
ist daher **kein wieder offenes R11-Konzeptfinding**, wohl aber eine reale
Gate-Reproduzierbarkeitsblockade, die vor Landung aufgeloest werden muss.

### AG3-176-R12 — MAJOR — Testevidenz verbessert, deckt die realen Restfehler aber nicht

**Ort:**

- `tests/unit/config/test_strict_config_boundary.py:115-230`
- `tests/unit/vectordb/test_first_index_receipts.py:116-246`
- `tests/unit/installer/checkpoint_engine/test_ag3_176_flow_and_hooks.py:86-174`
- `tests/unit/closure/test_runtime_ports.py:257-338`
- `tests/unit/installer/test_codex_settings.py`
- `tests/unit/concept_toolchain/test_mutex_race.py:74-105`

Die alten Vakuumerfolge sind teilweise beseitigt: bestehende invalid Config
geht durch `run_checkpoint_install`, CP10a produziert echte Receipts, Closure
drained reale Registry-Tasks, Bundle/Materializer laufen produktiv.

Die entscheidenden Grenzen fehlen aber weiterhin:

- Fresh Install ohne Endpoint vor CP5/Scaffold (R1),
- Fehler beim **zweiten Completion-Write** mit alten Staenden (R4),
- materialisierter Hook bei Git-/Staged-Ermittlungsfehler und tampered Commands
  (R6),
- konsistenter Altprojekt-Pin bei gleichzeitig neuer Store-Version (R8),
- rein fremde `.codex/config.toml` vor Fresh Install (R10).

Die 55 fokussierten Tests waren deshalb trotz drei direkt nachweisbarer
Produktionsfehler gruen. **R12 ist nicht an der Wurzel geschlossen.** Die Tests
muessen an den oben genannten echten Grenzen ergaenzt werden; reine Source-
Substring-Assertions reichen nicht.

### AG3-176-R13 — geschlossen und verifiziert

**Ort:**

- `src/agentkit/backend/config/loader.py:77-98`
- `src/agentkit/backend/config/strict_yaml.py:114-154`
- `tests/unit/config/test_strict_config_boundary.py:95-113`

UTF-8-Decodierfehler werden als `ConfigError(configuration_invalid)` typisiert;
parsernahe `RecursionError`-/Depth-Fehler werden an der Strict-YAML-Grenze in
einen stabilen Fehlervertrag ueberfuehrt. Die Datei-Loader-Tests sind gruen.
**R13 ist geschlossen.**

### AG3-176-R14 — MINOR — Split erfolgt, aber ein zweiter MCP-Pfad bleibt im 832-Zeilen-Modul

**Ort:**

- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:1-42`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10_mcp.py:61-251`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10_mcp.py:254-430`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10_mcp.py:676-832`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10a_first_index.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10b_hooks.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10c_are.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10d_sonar.py`

Der geforderte fachliche Split ist weitgehend erfolgt: `cp10.py` ist nur noch
42 Zeilen; CP10a/b/c/d sind eigene Module und CP10a ruft die bestehende
First-Index-Engine auf.

Nicht ganz geschlossen ist der "nur Ports, keine zweite Implementierung"-Teil:
`cp10_mcp.py` hat noch 832 Zeilen und enthaelt neben dem produktiven
`mcp_registration.dual_write`-Port einen eigenen JSON-Load/Merge/Write-
Registrierungspfad. Welcher Pfad laeuft, wird ueber die **Funktionsidentitaet**
von `_desired_mcp_servers` entschieden; Monkeypatch-Tests schalten dadurch die
alternative Implementierung produktionsseitig frei. Das ist keine aktuelle
AC1–AC7-Funktionsblockade, aber verbleibende Owner-/Test-Seam-Schuld.

**Fix:** Den Legacy-Single-File-Pfad in den kanonischen
`mcp_registration`-Owner ueberfuehren und Tests Ports/Fakes injizieren lassen,
nicht Produktionsrouting durch Monkeypatch-Identitaet veraendern. Schweregrad
bleibt **MINOR**.

## Neu durch die Remediation

### AG3-176-N1 — MAJOR — Mutex-Race-Test maskiert den bekannten 2/2-Livenessfehler mit Retries

**Ort:**

- `tests/unit/concept_toolchain/test_mutex_race.py:74-105`
- `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:312-397`

**Fakten-Beleg:** Der alte Test verlangte fuer genau ein Rennen um einen
abgelaufenen Mutex mindestens einen Gewinner. Die Remediation dokumentiert nun
selbst, dass beide Prozesse gelegentlich mit `[2, 2]` abbrechen, loescht danach
Mutex und Intent von aussen und wiederholt das Rennen bis zu fuenfmal. Das
beweist nicht die Liveness des urspruenglichen Rennens; es ersetzt sie durch
"irgendein spaeterer, vom Test bereinigter Versuch gewinnt". In Produktion gibt
es diesen Test-Cleanup-/Retry-Orchestrator nicht. Der Fehler wurde nicht im
Mutex-Algorithmus behoben, sondern im Test toleriert.

**Normverletzung:** Test-Substanz/ZERO DEBT; die bestehende fail-closed
Safety-Invariante rechtfertigt nicht, dass bei einem einzelnen legitimen
Takeover-Rennen alle Teilnehmer ohne Gewinner aussteigen.

**Fix:** Die Intent-Arbitration so korrigieren, dass bei einem abgelaufenen
Mutex genau ein Contender den Takeover fortsetzt und die Verlierer abbrechen.
Danach wieder ein einzelnes Rennen ohne externes Loeschen/Retry pruefen. Falls
eine fachlich normierte Caller-Retry-Semantik gewollt ist, muss sie produktiv
implementiert und konzeptionell entschieden werden; ein Testloop allein ist
keine Remediation.

## Gesamturteil

**NICHT FREIGEBEN.** R2, R3, R5, R7, R9, R11 (inhaltlich) und R13 sind
geschlossen. R14 ist nur noch Feinschliff. Die verbleibenden BLOCKER/MAJORs
sind jedoch reale Funktions-, Datenwahrheits- und Preservation-Fehler und keine
Reviewer-Nachkarten:

### MUSS-fixen vor Freigabe

1. **R1 / BLOCKER:** Fresh-Install-Endpointpflicht und eine kanonische
   validierte Config muessen vor CP5/Scaffold und allen weiteren Wirkungen
   liegen; Re-Read- und Endpoint-Override-Nachsicht entfernen.
2. **R4 / MAJOR:** CP10a muss auch beim zweiten Completion-/Receipt-Fehler alte
   Staende restaurieren und darf keine partielle Freshness publizieren.
3. **R6 / MAJOR:** Hook-VERIFY substanziell machen, Staged-Ermittlungsfehler
   fail-closed behandeln, Shell-Argumentgrenze korrigieren und den
   Hook-Migration-Owner wirklich wiederverwenden.
4. **R8 / MAJOR:** VERIFY gegen den installierten Pin statt gegen die hoechste
   Store-SemVer pruefen; Altprojekte duerfen nicht implizit hochgezogen werden.
5. **R10 / MAJOR:** Fresh Install muss eine rein fremde Codex-TOML chirurgisch
   erhalten.
6. **R12 / MAJOR:** Genau diese produktiven Negativgrenzen testen.
7. **N1 / MAJOR:** Mutex-Liveness im Algorithmus beheben; Retry-Maskierung im
   Test entfernen.
8. **Gate:** W2/W3 muessen nach Beseitigung der tracked
   `doc_kind=decision-log`-Schema-Inkompatibilitaet reproduzierbar gruen laufen.

### Orchestrator-Feinschliff

- **R14 / MINOR:** verbleibenden CP10-MCP-Zweitpfad/Monkeypatch-Routing in den
  kanonischen Owner ueberfuehren.

## Ehrliche Substanzbewertung

Die MAJOR+-Liste ist echte Substanz. Drei Fehlerbilder wurden an lokalen,
harmlosen produktiven Grenzen direkt nachgewiesen; R6 und R8 folgen unmittelbar
aus den ausgefuehrten Branches und ihren fehlenden Invarianten. Nur R14 ist
Feinschliff, den der Orchestrator selbst abraeumen kann. Bei einem Fix nur der
oben genannten Punkte ist kein weiterer Flaechenreview noetig; dann genuegt eine
erneute gezielte Verifikation dieser Restliste.

## Gate-Status zum Verifikationszeitpunkt

- Fokussierte Remediation-Stichprobe: **55 passed**.
- `check_concept_frontmatter.py`: **OK** (90 Dokumente).
- `compile_formal_specs.py`: **OK** (192 Dokumente, 149 Szenarien).
- W2/W3: **nicht gruen**, beide brechen vor der eigentlichen Bewertung an der
  oben dokumentierten tracked `doc_kind=decision-log`-Inkompatibilitaet ab.
- `git diff --check` fuer dieses Review-Artefakt: **sauber**.
- Sonar separat read-only verifiziert: **Quality Gate OK**,
  `violations=0`, `critical_violations=0`, `security_hotspots=0`.
- Der vorgeschriebene Remote-Gate-Helper konnte trotz Laden von
  `T:\seu\agentkit3-secrets.cmd` Jenkins nicht attestieren: Das Job-API
  antwortete mit HTTP 401. Das ist kein Beleg fuer einen roten Build, aber die
  geforderte Jenkins-Gruenbestaetigung ist in dieser Verifikationsrunde nicht
  reproduzierbar.
