# AG3-176 — Codex Review Round 1

Datum: 2026-07-28  
Rolle: adversarialer Reviewer  
Geprüfter Stand: uncommitteter Working Tree auf
`feat/ag3-176-vectordb-installer-integration`

## Gesamturteil

**REJECT / nicht landbar.**

Der Stand hat echte positive Substanz: Der projektgebundene Preflight bezieht
seine Endpunkte aus einem typisierten `ProjectConfig`; der optionale
VectorDB-Flow ist entfernt; Git-Pfade werden als argv und NUL-separiert
behandelt; Git-Discovery scheitert nonzero; die Closure verwendet einen
retained Executor; Codex-TOML-Merge und -Detach sind in den geprüften Pfaden
semantisch chirurgisch. Auch sind weder `sonar-project.properties` noch
Jenkins-/Pyproject-Gate-Einstellungen aufgeweicht worden; im Diff wurde kein
`# NOSONAR` eingeführt.

Die zentralen Fail-Closed- und Freshness-Verträge sind trotzdem nicht erfüllt.
Es gibt **2 BLOCKER und 5 MAJOR**. Insbesondere beweisen die neuen Tests an zwei
Stellen nur lokale Artefakte bzw. Textmarker, während die produktive Grenze
bereits einen anderen Zustand publiziert. Die MAJOR+-Befunde sind damit
**echte Substanz**, kein Orchestrator- oder Stil-Feinschliff.

## Findings

### AG3-176-R1-001 — BLOCKER — Ein fehlgeschlagener Gesamt-Sync lässt bereits publizierte Freshness zurück

**Ort**

- `src/agentkit/backend/installer/cp10a_initial_sync.py:194-249`
- `src/agentkit/backend/vectordb/sync.py:606-645`
- `src/agentkit/backend/vectordb/sync.py:973-993`
- `tests/unit/installer/test_ag3_176_vectordb_integration.py:609-636`
- `tests/unit/installer/test_ag3_176_vectordb_integration.py:664-690`

**Fakten-Beleg**

`run_initial_sync()` ruft zuerst `story_sync()` und danach `concept_sync()` auf
(`cp10a_initial_sync.py:218-219`). Beide Aufrufe laufen über die AG3-174-Engine,
aber `SyncService.full_reindex()` führt jede Source einzeln aus
(`sync.py:633-644`). `sync_source()` publiziert am Ende jeder erfolgreichen
Source sofort eine immutable Completion über `store.set_receipt()`
(`sync.py:973-993`).

Damit sind Story-/Research-Completions bereits autoritativ, bevor
`concept_sync()` überhaupt beginnt. Schlägt `concept_sync()` oder eine spätere
Source desselben `full_reindex()` fehl, bleiben die vorherigen Completions und
deren Freshness sichtbar. Dasselbe Problem trifft den Post-Commit-Pfad: Ein
Fehler spät im `sync --full` lässt frühere Source-Completions der neuen Revision
stehen.

`_publish_pair()` rollt lediglich die zwei lokalen Dateien
`.agentkit/receipts/vectordb/{story_sync,concept_sync}.json` zurück. Ein Fehler
beim zweiten lokalen Write tritt sogar erst **nach** beiden Engine-Syncs ein;
die Engine-Completions werden dabei überhaupt nicht kompensiert.

Der Test `test_cp10a_partial_failure_publishes_no_success_or_freshness` injiziert
eine `_PartialFailureService` und prüft nur, dass die beiden lokalen JSON-Dateien
nicht existieren. Er beobachtet keinen Store, keine Completion und keine
Retrieval-Freshness. Der Second-Write-Test prüft ebenfalls nur lokale Bytes.
Die Assertion ist deshalb für die behauptete produktive Invariante nicht
aussagekräftig.

**Normverletzung**

- AC3: Partial-/Transport-/Receiptfehler muss Fehler **ohne**
  Success/Freshness sein.
- AC4/AC5: Im Post-Commit-Ring darf jeder Fehler vor Gesamtabschluss die alte
  Revision nicht vorziehen.
- FK-13 §13.7/§13.8 und FK-50 CP10a: Freshness folgt erst dem vollständigen
  Producer-Erfolg; kein partieller Erfolgszustand.
- FAIL-CLOSED / ZERO DEBT: Das lokale Receipt-Paar darf nicht als Beweis für
  einen bereits anders publizierten Engine-Zustand dienen.

**Konkreter Fix**

Den AG3-174-Port um eine echte run-weite Publish-Grenze ergänzen: Story-,
Research- und Concept-Syncs werden unter einer gemeinsamen Run-ID vorbereitet;
Source-Completions bzw. der für Retrieval maßgebliche Freshness-Zeiger werden
erst nach Erfolg **aller** Producer und der dauerhaften Receipt-Publikation
sichtbar. Bei zweitem Completion-/Receipt-Write-Fehler müssen vorheriger
Completion-/Freshness-Zustand und lokale Receipt-Bytes exakt wiederhergestellt
werden. Bereits geschriebene Chunks dürfen nur als nicht-autoritativ/stale
sichtbar sein, solange der Run nicht committed ist.

Erforderlich ist ein Integrationstest mit realem `McpToolService`,
`SyncService` und stateful Store-Double/Adapter: Fehler bei der zweiten Source,
beim zweiten Producer und beim zweiten lokalen Receipt-Write injizieren und
jeweils beweisen, dass Completion-Menge, maßgebliche Revision, Retrieval-
Freshness und lokale Bytes exakt dem Before-Image entsprechen.

### AG3-176-R1-002 — BLOCKER — Die strikte Config-Grenze ist vor der ersten Wirkung nicht mehr aktuell

**Ort**

- `src/agentkit/backend/installer/bootstrap_checkpoints/orchestrator.py:91-129`
- `src/agentkit/backend/installer/bootstrap_checkpoints/orchestrator.py:186-210`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp01_to_06.py:199-224`
- `src/agentkit/backend/installer/runner.py:730-735`

**Fakten-Beleg**

Der Orchestrator lädt die bestehende Config einmal strikt, erzeugt daraus aber
anschließend ein `candidate.model_dump()` (`orchestrator.py:104-112`) und hält
dieses Objekt über Preflight und Checkpoint-Lauf fest. Vor der ersten
Filesystem-Wirkung gibt es keinen strikten Re-Read bzw. keinen Vergleich gegen
das initial gelesene Before-Image.

CP5 erzeugt zunächst Corpus-/Scaffold-Verzeichnisse
(`cp01_to_06.py:217-221`) und liest die Config erst beim späteren
`_write_yaml_if_changed()` erneut. Dieser Re-Read benutzt ausgerechnet
`yaml.safe_load()` mit YAML-Last-Wins (`runner.py:730-734`), nicht die neue
duplicate-key-feste Ladegrenze. Ein Re-Read-Fehler kommt damit erst **nach**
Scaffold-Wirkung; eine zwischenzeitlich entstandene Duplicate-Key-Datei kann
sogar als „gleich“ gelten und unverändert liegen bleiben.

Benigne Reproduktion direkt an der tatsächlich von CP5 verwendeten Grenze:

```text
project.yaml:
feature: false
feature: true

_write_yaml_if_changed(path, {"feature": True})
=> CHANGED False
=> INVALID_DUPLICATES_REMAIN True
```

Der Lauf kann folglich mit dem alten validierten `model_dump` aktivieren,
registrieren und preflighten, während die auf Disk liegende SSOT inzwischen
strict-invalid oder gültig, aber abweichend ist. Bei einer validen
Endpoint-Änderung wäre zudem der geprüfte Endpoint nicht mehr der installierte
Endpoint.

**Normverletzung**

- AC2: vollständige strikte Configvalidierung muss **vor jeder** Wirkung für
  Fresh und Existing gelten.
- Vorgabe „Re-Read-Fehler ohne model_dump-Fallback“: Das festgehaltene
  `model_dump` darf keinen später abweichenden/unlesbaren SSOT-Stand kaschieren.
- Endpoint-SSOT: Die für Wirkung verwendete Config muss dieselbe validierte
  Config sein, deren aktuelle Bytes auf Disk liegen.
- FAIL-CLOSED: Duplicate Keys dürfen an keiner Re-Read-Grenze Last-Wins werden.

**Konkreter Fix**

Beim ersten Load das bytegenaue Config-Before-Image bzw. einen Digest halten.
Unmittelbar vor **der ersten** Wirkung die Datei erneut über
`load_project_config()`/`parse_project_config()` strikt lesen und zusätzlich
prüfen, dass Bytes/Digest und typisiertes Modell unverändert sind. Jede
Abweichung, Unlesbarkeit, Duplicate-Key-Situation oder Symlink-/Targetänderung
muss als benannter `configuration_changed`/`configuration_invalid`-Fehler
enden, bevor Verzeichnisse, Registrierungen oder Hook-Config entstehen.
`_write_yaml_if_changed()` darf für `project.yaml` nicht mit `yaml.safe_load`
entscheiden und nie auf das frühere `model_dump` zurückfallen.

Ein Grenztest muss den Config-Wechsel innerhalb eines benignen Preflight-Doubles
auslösen und danach ein vollständig leeres Wirkungs-Before-Image beweisen.

### AG3-176-R1-003 — MAJOR — Die Hook-Migration erzeugt nicht genau einen Owner und ist nicht chirurgisch

**Ort**

- `src/agentkit/backend/installer/git_hook_dispatch.py:57-100`
- `src/agentkit/backend/vectordb/hook_dispatch.py:15-36`
- `src/agentkit/backend/vectordb/hook_dispatch.py:99-126`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:780-825`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp11_to_12.py:124-169`
- `tests/unit/installer/upgrade/test_hook_migration.py:167-181`

**Fakten-Beleg**

Ein bestehender, anhand des Textmarkers erkannter AgentKit-Pre-Commit wird
vollständig behalten und der neue Dispatch wird angehängt
(`git_hook_dispatch.py:83-88`). Der neue Dispatch führt Secret-Detection aber
selbst immer aus (`hook_dispatch.py:110-120`). Ein realer alter Hook mit
Secret-Scan-Befehl enthält danach zwei Managed-Ausführungen bzw. einen
veralteten Aufruf plus den neuen Owner. Das ist keine Migration zu genau einem
Owner.

Der neue Test schreibt nur den Kommentar
`# agentkit secret-detection (global)`, hängt den Block an und prüft, dass der
Markertext noch vorkommt. Er führt keinen realen Legacy-Hook aus und zählt
keine Secret-Scan-Ausführungen.

Zusätzlich wird jede bestehende `post-commit`-Datei zwar als `.bak` gesichert,
aber anschließend vollständig durch `_POST_DISPATCH_BLOCK` ersetzt
(`git_hook_dispatch.py:94-100`). Fremdes Post-Commit-Verhalten ist danach nicht
mehr aktiv. Pre- und Post-Commit werden nicht als Paar zurückgerollt. Da CP11
`core.hooksPath=tools/hooks/` bereits vor CP10b aktiviert, kann ein Fehler beim
zweiten Hook-Write einen fehlgeschlagenen Installer mit bereits umgebogenem und
partiellem Hook-Ring hinterlassen.

Die guten Teile sind ausdrücklich anerkannt: `_changed_paths()` ist
NUL-separiert und fail-closed; die Commands werden argv-sicher erzeugt; VERIFY
prüft `--staged` sowie Build-vor-Sync.

**Normverletzung**

- AC4: bestehende Secret-Detection muss über **genau einen**
  Migration-/Dispatch-Owner erhalten bleiben.
- AC4 REGISTER/VERIFY/Idempotenz: „Marker vorhanden“ ist kein Nachweis einer
  einmaligen, tatsächlich feuernden Ausführung.
- ZERO DEBT / chirurgische Migration: Ein Backup allein erhält fremdes
  Post-Commit-Verhalten nicht im aktiven Ring.
- FAIL-CLOSED: Ein fehlgeschlagener CP10b darf keinen aktivierten Teilzustand
  hinterlassen.

**Konkreter Fix**

Den alten kanonischen AgentKit-Secret-Block erkennen und **ersetzen**, nicht
unverändert plus neuem Owner weiterführen. Der neue Dispatch ist danach der
einzige Secret-Scan-Owner. Fremde Pre-/Post-Commit-Kommandos müssen über einen
klar abgegrenzten, erhaltenen Block oder einen argv-sicheren Chain-Owner aktiv
bleiben. Pre-/Post-Dateien und `core.hooksPath` als eine Installationsmutation
mit Before-Images behandeln; Hook-Paar zuerst vollständig schreiben/verifizieren
und den Git-Pfad zuletzt aktivieren, bei Fehler exakt restaurieren.

Tests müssen einen benignen echten Git-Hook ausführen, eine instrumentierte
Secret-Scan-Ausführung exakt einmal beobachten, fremde Pre-/Post-Kommandos
weiter feuern sehen und Faults am zweiten Write sowie an der Aktivierung
abdecken.

### AG3-176-R1-004 — MAJOR — Das neue Skill-Bundle ist weder vollständig noch kann es sein Freshness-Gate ausführen

**Ort**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.1.0/SKILL.md:10-16`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.1.0/SKILL.md:58-80`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.0.0/SKILL.md:205-250`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.0.0/SKILL.md:345-369`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.0.0/SKILL.md:917-921`
- `src/agentkit/backend/vectordb/mcp_server.py:188-223`
- `tests/unit/installer/test_ag3_176_skill_bundle.py:30-42`

**Fakten-Beleg**

Version 4.1.0 enthält nicht den vollständigen Workflow. Sie erklärt lediglich,
sie „retains“ den Workflow aus `../4.0.0/SKILL.md` und ersetzt einige Schritte.
Ein Harness lädt jedoch das gepinnte `SKILL.md`; eine solche Prosa-Referenz ist
keine ausführbare Include-/Overlay-Semantik. Selbst bei manueller Lektüre des
Vorgängers enthält 4.0.0 weiterhin:

- Story-`grep` und einen ausdrücklichen Structural-Search-Fallback
  (`4.0.0:215-250`);
- Grep als Pflicht-Primärpfad und `concept_search` nur optional
  (`4.0.0:345-369`);
- ein weiteres optionales `concept_search` im Review
  (`4.0.0:917-921`).

Damit ist weder ein eigenständiges immutable Bundle ausgeliefert noch eindeutig
definiert, welche alten Instruktionen tatsächlich ersetzt sind.

Das geforderte Freshness-Gate ist außerdem nicht operationalisiert. 4.1.0
fordert, dass erneute `concept_search`-Ergebnisse zur aktuellen validierten
Corpus-Revision passen (`4.1.0:67-70`), nennt aber keinen Aufruf und kein
Receipt, aus dem beide Revisionen gelesen werden. `concept_search()` liefert
produktiv nur `project_id` und `results` (`mcp_server.py:220-223`), keine
`corpus_revision`. Der Agent kann die geforderte Gleichheit somit weder prüfen
noch einen spezifischen Mismatch feststellen; er kann nur immer stoppen oder
die Prüfung behaupten.

Der Test sucht ausschließlich Schlagwörter im 4.1.0-Text. Insbesondere
ignoriert er den referenzierten Vorgänger und führt keine Freshness-Grenze aus.

**Normverletzung**

- AC7 und FK-43: neues unveränderliches Bundle muss den vollständigen,
  deterministischen Skill-Inhalt der gepinnten Version tragen.
- AC7: kein Grep-/Filescan-Fallback und harte Stops bei fehlender/staler
  Revision.
- FAIL-CLOSED: Ein nicht beobachtbarer Revisionsvergleich ist kein Gate.

**Konkreter Fix**

4.1.0 als vollständiges, selbständiges `SKILL.md` ausliefern. Alle Grep-,
Glob-/Filescan-, Optional- und Best-Effort-Pfade müssen in der effektiven
Instruktion entfernt sein, nicht nur in einem Overlay-Absatz.

Danach eine tatsächlich konsumierbare typisierte Freshness-Oberfläche
verwenden: aktuelle validierte Graph-/Corpus-Revision und die maßgebliche
Concept-Completion-Revision müssen über einen vorhandenen oder normativ
ergänzten MCP-/CLI-Read verfügbar sein und im Skill explizit verglichen werden.
Der Contract-Test muss den **effektiv installierten gepinnten Skill** prüfen und
den realen Revisionsvergleich für Match, Mismatch, fehlende Completion und
Toolfehler ausführen.

### AG3-176-R1-005 — MAJOR — VERIFY akzeptiert fremde oder nachträglich veränderte Skill-Inhalte als gepinnt

**Ort**

- `src/agentkit/backend/skills/top.py:77-100`
- `src/agentkit/backend/skills/top.py:714-739`
- `src/agentkit/backend/skills/binding.py:74-103`
- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.1.0/manifest.json:1-11`
- `tests/unit/installer/test_ag3_176_skill_bundle.py:64-87`

**Fakten-Beleg**

`verify_pinned_binding()` prüft, dass beide Links auf dasselbe aufgelöste Ziel
zeigen und dass dessen selbst gelesene Manifestfelder `bundle_id` und
`bundle_version` zum Persistenzrecord passen. Es prüft aber weder, dass das Ziel
unter `SkillBundleStore.store_root/{bundle_id}/{bundle_version}` liegt, noch
gegen einen aus dem Store aufgelösten erwarteten Zielpfad
(`top.py:724-738`).

Benigne Reproduktion: legitimes 4.1.0-Bundle binden, danach beide Harness-Links
auf ein Verzeichnis **außerhalb** des Stores umhängen, dort ein Manifest mit
demselben ID-/Versionswert und selbst berechnetem `manifest_digest` ablegen.
Ergebnis:

```text
VERIFIED 4.1.0
TARGET_OUTSIDE_STORE True
```

Der Digest schützt zudem nur die Manifest-Metadaten gegen einen
selbstdeklarierten Wert. `SKILL.md` ist nicht Bestandteil des Digests, und
`SkillBinding` persistiert keinen erwarteten Inhaltsdigest. Nach Änderung von
`SKILL.md` am gebundenen Ziel ergab eine zweite benigne Reproduktion:

```text
VERIFY_AFTER_SKILL_CHANGE VERIFIED
```

Der vorhandene Test deckt nur „zweiter Link zeigt auf **andere Version**“ ab.
Gleiche behauptete Version außerhalb des Stores und Content-Drift fehlen.

**Normverletzung**

- AC7: VERIFY muss gegen den **installierten Pin**, nicht gegen selbstbehauptete
  Metadaten des aktuellen Linkziels prüfen.
- FK-43 §43.4.1/§43.5.2/§43.5.3: Projektlinks zeigen auf die konkrete,
  systemweite, unveränderliche Bundle-Version; beide Harnesses konsumieren
  dieselbe SSOT.
- Symlink-/Junction-Containment und FAIL-CLOSED.

**Konkreter Fix**

Die gepinnte `(bundle_id, bundle_version)` über den `SkillBundleStore` exakt
auflösen, ohne Highest-Version-Auswahl, und beide Linkziele byte-/pfadgenau
gegen dessen kanonisch aufgelösten `bundle_root` prüfen. Das erwartete
Content-Manifest bzw. der Digest der relevanten Bundle-Dateien muss beim Pin
vertrauenswürdig festgehalten werden; `SKILL.md` muss in diesen Digest
einfließen. Ein Digest, dessen Erwartungswert aus demselben frei austauschbaren
Ziel gelesen wird, ist kein Integritätsnachweis.

Negative Tests: beide Links auf dasselbe Outside-Store-Ziel, Store-Symlink-
Escape, gleichnamige Version mit fremdem Inhalt, veränderte `SKILL.md`,
selbstneu berechneter Manifestdigest und nur ein abweichender Harness-Link.

### AG3-176-R1-006 — MAJOR — Sonar-Komplexitätsrefactor lässt ungültige Referenzanker passieren

**Ort**

- `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/docmodel.py:183-239`
- `tests/unit/concept_toolchain/test_reference_check.py`
- `tests/unit/concept_toolchain/test_units.py`

**Fakten-Beleg**

Vor dem Refactor erkannte die Regex explizite HTML-Anker nur als
`<a ... id="...">`. Die neue manuelle Suche nimmt jedes `<a`-Präfix und sucht
anschließend die bloße Teilzeichenfolge `id=` ohne Attributgrenze
(`docmodel.py:220-229`).

Benigne Reproduktion gegen den produktiven `anchor_slugs()`:

```text
'<aside data-id="ghost"></aside>' -> ['ghost']
'<abbr id="abbr"></abbr>'         -> ['abbr']
'<a data-id="wrong"></a>'         -> ['wrong']
'<a id="right"></a>'              -> ['right']
```

Insbesondere `data-id="ghost"` erzeugt keinen HTML-`id`-Anker. Dennoch kann
eine Konzeptreferenz auf `#ghost` nun den Reference-Guard passieren. Die
vorhandenen Tests sind grün, enthalten aber keine Attributgrenzen bzw.
Nicht-`a`-Tags als Gegenbeispiele.

Das ist genau die geforderte riskante Stichprobe der breiten Sonar-Refactors:
Die Komplexität wurde zwar reduziert, aber das Verhalten des bereits
gelandeten Concept-Guards aufgeweicht.

**Normverletzung**

- AC9: Sonar-Bereinigung muss Ursachen beheben, nicht Guard-Verhalten ändern
  oder Befunde verstecken.
- ZERO DEBT / FAIL-CLOSED: Nicht existierende Anker dürfen keinen
  Referenzintegritäts-False-Pass erzeugen.
- ARCH-55: Das ausgelieferte Concept-Tooling ist ein deterministischer Guard,
  kein best-effort Parser.

**Konkreter Fix**

Die alte präzise Semantik wiederherstellen oder einen kleinen deterministischen
HTML-Opening-Tag-Parser verwenden: exakter Tagname `a` und exakte
Attributgrenze für `id`, niemals `data-id`, `grid=` o. Ä. Positive und negative
Regressionstests für Groß-/Kleinschreibung, Attributreihenfolge, Quote-Arten,
`data-id`, Nicht-`a`-Tags und mehrere Tags pro Zeile ergänzen.

### AG3-176-R1-007 — MAJOR — `cp10.py` bleibt das ausdrücklich verbotene God-File

**Ort**

- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:1-1173`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:367`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:711`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:780`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:830`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:1021`
- `src/agentkit/backend/installer/bootstrap_checkpoints/registry.py`

**Fakten-Beleg**

Die Datei hat 1173 Zeilen und besitzt weiterhin fünf eigenständige
Checkpoint-Verantwortungen:

- CP10 MCP-Registrierung;
- CP10a Initial-Sync;
- CP10b Git-Hook-Migration;
- CP10c ARE-Scope-Validierung;
- CP10d Sonar-/Third-Party-Prüfung.

Zwar wurden produktive Helfer für Initial-Sync und Hook-Dispatch ausgelagert,
doch Checkpoint-Orchestrierung, Fehlerabbildung, MCP-Rendering,
ARE-Fachlogik und Sonar-Adapterlogik bleiben in einem Modul. Der Registry-Schnitt
importiert weiterhin alles aus diesem Sammelmodul. Das ist nicht „cp10 dünn,
CP10a/b/c/d eigene Module über Ports“.

**Normverletzung**

- Expliziter Review-Schwerpunkt 7: kein God-File.
- ARCH-55 / klare Owner- und Portgrenzen.
- Testbarkeit: Die zentrale Datei koppelt unabhängige Failure Domains und
  begünstigt die in R1-001/R1-003 sichtbaren inner-helper Tests.

**Konkreter Fix**

Je Checkpoint ein eigenes dünnes Handler-Modul anlegen, z. B.
`cp10_mcp_registration.py`, `cp10a_initial_sync_checkpoint.py`,
`cp10b_hook_dispatch_checkpoint.py`, `cp10c_are_scope.py` und
`cp10d_sonarqube.py`. Gemeinsame reine MCP-Render-/Before-Image-Helfer in ein
kleines explizites Support-Modul verschieben. `registry.py` importiert nur die
fünf Handler; produktive Arbeit bleibt hinter den jeweiligen Ports.

## Konzepttreue und Gate-Befund

Die Änderungen in `src/agentkit/concepts/frontmatter.py` für `doc_kind:
detail`, String-/Dict-`defers_to` und strukturierte
`supersedes {target, scope, reason}` sind **keine unautorisierte neue
Produktentscheidung**: Diese Formen sind bereits in
`concept/technical-design/00_index.md:252,303-305` normiert. Das zusätzliche
`override_note` bildet ein bereits vorhandenes Feld in FK-25 ab. Der Parser-
Nachzug repariert hier eine inkonsistente Implementierung der bestehenden
Concept-SSOT. Dazu gibt es kein eigenes Finding.

Deterministische Gates:

- `check_concept_frontmatter.py`: PASS, 90 Dokumente.
- `compile_formal_specs.py`: PASS, 192 Dokumente / 1802 IDs / 2344 Referenzen.
- `check_concept_decision_record.py --base HEAD`: PASS.
- `git diff --check`: PASS.

W2/W3 sind reproduzierbar extern blockiert:

- W2: `EVALUATION_TRANSPORT_FAILURE` —
  `W2 Hub epoch lease omitted a configured backend`.
- W3 `--scope installer`: `HUB_UNREACHABLE` mit derselben Ursache und deshalb
  `INCOMPLETE_SWEEP completed=0 expected=5`.

Die Blockade ist plausibel Infrastruktur/Hub-Kapazität und kein Codefix dieses
Reviews. Der Diff ist formal für einen erneuten W2/W3-Lauf vorbereitet; wegen
der BLOCKER/MAJOR-Befunde ist er unabhängig davon noch nicht landbar.

## Test- und Sonar-Stichprobe

Selbst ausgeführt:

- 52 AG3-176-/Hook-Tests: PASS.
- 77 Concept-Reference-/Parser-Tests: PASS.
- 84 MCP-Conformance-Tests: PASS.
- 128 Strict-JSON-/Sync-/Weaviate-Tests: PASS.
- 117 Codex-TOML-/MCP-Registration-Tests: PASS.
- 44 Closure-/Detach-Tests: PASS.
- Summe der gezielten Stichprobe: **502 passed**.

Diese grünen Tests widerlegen die Findings nicht; die fehlenden Gegenbeispiele
sind jeweils oben benannt und für R1-002, R1-005 und R1-006 benign
reproduziert.

Das Remote-Gate-Script konnte nicht erfolgreich authentifizieren:

- Jenkins antwortete auch mit der extern geladenen Secret-Datei `401`.
- Sonar antwortete mit den extern geladenen Credentials `401`.

Damit konnte die gemeldete frische Sonar-PASS-Messung nicht unabhängig über
die API bestätigt werden. Die Auth-Blockade ist extern und kein Fixauftrag.
Unabhängig vom API-Status ist AC9 wegen der reproduzierten Guard-Regression
R1-006 materiell nicht erfüllt. Es wurden keine Sonar-Excludes,
CPD-Excludes, Coverage-Schwellen oder `NOSONAR`-Unterdrückungen im Diff
gefunden.

## Akzeptanzkriterien — Reviewstatus

| AC | Urteil | Begründung |
|---|---|---|
| AC1 | PASS mit AC2-Abhängigkeit | Projektgebundener Preflight nutzt validierte explizite Endpunkte; kein localhost-/Start-Fallback gefunden. Der Config-Drift aus R1-002 muss davor geschlossen werden. |
| AC2 | **FAIL** | R1-002: Wirkung vor aktuellem striktem Re-Read; CP5 nutzt Last-Wins. |
| AC3 | **FAIL** | R1-001: partielle Engine-Completions/Freshness bleiben trotz Gesamtfehler. |
| AC4 | **FAIL** | R1-001 und R1-003: partielle Sync-Freshness sowie nicht-eindeutige/nicht-chirurgische Hook-Migration. |
| AC5 | PASS | Closure-Port ist nicht-blockierend, retained und beobachtet Fehler; Producer verwenden die AG3-174-Engine. |
| AC6 | PASS | `features.vectordb=false` ist hart; optionaler VectorDB-Branch/Skip ist entfernt. |
| AC7 | **FAIL** | R1-004/R1-005: Skill-Inhalt/Freshness nicht ausführbar; Pin-VERIFY ohne Store-/Content-Integrität. |
| AC8 | EXTERN BLOCKIERT | W2/W3 erreichen wegen Hub-Lease keinen Evaluator; deterministische Konzept-Gates sind grün. |
| AC9 | **FAIL** | Keine Unterdrückung gefunden, aber R1-006 ist eine echte Verhaltensregression aus der Sonar-Bereinigung; Remote-PASS war wegen 401 nicht unabhängig prüfbar. |

## Muss-fixen vor der nächsten Reviewrunde

**BLOCKER**

1. AG3-176-R1-001 — run-weite Completion-/Freshness-Atomizität für CP10a und
   Post-Commit.
2. AG3-176-R1-002 — aktuelle strikte Config-Grenze unmittelbar vor jeder
   ersten Wirkung; kein Last-Wins-/stales `model_dump`.

**MAJOR**

1. AG3-176-R1-003 — genau ein Secret-Detection-Owner, chirurgische und
   rollback-fähige Hook-Migration.
2. AG3-176-R1-004 — vollständiger effektiver 4.1.0-Skill und tatsächlich
   beobachtbares Freshness-Gate.
3. AG3-176-R1-005 — Pin-VERIFY gegen kanonischen Storepfad und erwarteten
   Bundle-Inhalt.
4. AG3-176-R1-006 — False-Pass im HTML-Ankerparser beseitigen.
5. AG3-176-R1-007 — CP10/10a/10b/10c/10d in getrennte dünne Handler-Module
   schneiden.

## Orchestrator-Feinschliff

**MINOR/NIT: keine.** Die offenen Punkte sind nicht aufschiebbarer Feinschliff,
sondern betreffen Korrektheit, Freshness, Integrität oder den ausdrücklich
geforderten Architekturschnitt.
