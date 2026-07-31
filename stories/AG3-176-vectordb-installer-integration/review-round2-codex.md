# AG3-176 — Codex Review Round 2 (Verifikation)

Datum: 2026-07-28

Rolle: adversarialer Reviewer, Verifikationsrunde

Geprüfter Stand: uncommitteter Working Tree auf
`feat/ag3-176-vectordb-installer-integration`

## Gesamturteil

**NICHT FREIGEBEN.**

Fünf Runde-1-Findings sind an der Wurzel geschlossen: R1-002, R1-004,
R1-005, R1-006 und R1-007. R1-003 ist nur für `sh`-kompatible Fremdhooks
geschlossen und damit als allgemeiner Migrationsvertrag noch offen. R1-001
hat eine echte atomare Store-Publikation für die getesteten normalen
Fehlerpfade erhalten, ist aber wegen zweier nicht abgedeckter produktiver
Grenzfälle weiterhin BLOCKER. Zusätzlich hat die neue Run-Receipt-Lösung
eine Race Condition in der globalen Completion-Sequenz eingeführt.

Es verbleiben **1 BLOCKER und 2 MAJOR**. Das ist echte Substanz, kein
MINOR-/NIT-Feinschliff. Es gibt keine zusätzlichen MINOR- oder NIT-Befunde.

## Verifikationsbasis

- Code- und Diff-Lektüre der R1-Remediation und ihrer unmittelbaren
  Änderungsflächen.
- Gezielte Suite:
  `tests/unit/installer/test_ag3_176_vectordb_integration.py`,
  `tests/unit/installer/test_ag3_176_skill_bundle.py`,
  `tests/unit/concept_toolchain/test_docmodel_anchor_regression.py`,
  `tests/unit/installer/upgrade/test_hook_migration.py`,
  `tests/unit/state_backend/store/test_skill_binding_schema_bootstrap_idempotent.py`
  und
  `tests/unit/installer/checkpoint_engine/test_flow_structure.py`:
  **99 passed in 27.76s**.
- Benigne Real-Boundary-Reproduktionen gegen `McpToolService`,
  `SyncService`, `WeaviateCorpusStore` und den stateful
  `RecordingWeaviateClient`.
- Die vom Orchestrator bereits bestätigte vollständige Suite und der aktuelle
  Sonar-Lauf wurden nicht redundant erneut gestartet.

## R1-001 — BLOCKER — noch offen

### Was jetzt funktioniert

Die normale Multi-Source-/Multi-Producer-Publikation ist wesentlich besser:

- `PreparedSyncRun` hält Source-Completions bis zum gemeinsamen Commit zurück
  (`src/agentkit/backend/vectordb/sync.py:461-525`).
- `McpToolService.prepare_initial_sync()` merged Story/Research und Concept in
  einen Run (`src/agentkit/backend/vectordb/mcp_server.py:306-403`).
- Mehrere Completions werden als ein unveränderliches Run-Objekt publiziert
  (`src/agentkit/backend/vectordb/engine.py:426-495`).
- Die vorhandenen echten Grenztests für Fehler an der zweiten Source, am
  zweiten Producer, am zweiten lokalen Receipt-Write und vor dem
  Run-Receipt-Insert beweisen jeweils unveränderte Completion-Menge,
  Retrieval-Freshness und lokale Receipt-Bytes. Diese Tests waren in der
  gezielten Suite grün.
- Derselbe `full_reindex()`-Mechanismus schützt im Post-Commit-Ring normale
  Fehler an einer späteren Concept-Source vor partieller
  Completion-Publikation.

### Noch offene Wurzellücke 1: ACK-Verlust nach erfolgreichem Store-Commit

**Ort**

- `src/agentkit/backend/vectordb/engine.py:426-495`
- `src/agentkit/backend/vectordb/sync.py:488-525`
- `src/agentkit/backend/installer/cp10a_initial_sync.py:260-284`

`set_receipts()` führt genau einen `insert_object()` aus. Meldet der Transport
nach serverseitig erfolgreichem Insert einen Fehler, gibt es weder einen
deterministischen Read-after-error-Abgleich des Run-Records noch einen
persistierten Recovery-Zustand. `_commit_prepared()` nimmt deshalb an, die
Engine-Publikation sei ausgeblieben, restauriert nur die lokalen Bytes und
meldet ausdrücklich, auch die autoritative Freshness sei „restored exactly“.

Benigne Reproduktion: Ein Client-Double führte das echte bedingte Insert
zunächst vollständig aus und warf danach einen
`VectorDbWriteError` als simulierten ACK-Verlust. Ergebnis:

```text
reported-error CP10a engine completion failed; local receipt bytes and authoritative freshness were restored exactly
completion-before-image False
freshness-before-image False
local-bytes-before-image True
```

Die Story- und Concept-Freshness standen nach dem gemeldeten Fehler bereits
auf den neuen Revisionen. Der Fehlertext behauptet somit nachweislich das
Gegenteil des Store-Zustands. Der bestehende Test
`test_atomic_engine_completion_failure_restores_local_and_store_before_image`
injiziert nur **vor** dem Insert und deckt diese reale Transportgrenze nicht ab.

### Noch offene Wurzellücke 2: erfolgreicher Übergang auf leere Korpora

**Ort**

- `src/agentkit/backend/vectordb/sync.py:751-784`
- `src/agentkit/backend/vectordb/sync.py:826-876`
- `src/agentkit/backend/vectordb/engine.py:442-443`
- `src/agentkit/backend/vectordb/engine.py:542-638`

Vanished Sources werden während `prepare_full_reindex()` gelöscht, erzeugen
aber keinen Completion-Kandidaten. Sind danach alle Story-/Concept-Quellen
verschwunden, ist `receipts` leer und `set_receipts()` publiziert überhaupt
nichts. CP10a schreibt trotzdem lokale Success-Receipts mit der neuen
Empty-Corpus-Revision.

Benigne Reproduktion: Zuerst je einen Story- und Concept-Stand erfolgreich
publiziert, dann beide Dateien entfernt und CP10a erneut erfolgreich
ausgeführt:

```text
local-end-revisions
  8e141ea8...,
  8e141ea8...
engine-freshness
  concept=e78f3215...
  story=5d77832d...
local-story-matches-engine False
local-concept-matches-engine False
remaining-chunks 0
```

Damit quittiert CP10a Erfolg, obwohl lokale maßgebliche Revision und
Retrieval-Freshness auseinanderlaufen. Der Test
`test_empty_corpora_publish_typed_zero_receipts` prüft nur lokale
`InitialSyncReceipt`s auf einem frisch leeren Store; er beobachtet keine
Engine-Completion und keinen Übergang von nichtleer zu leer. Derselbe Defekt
betrifft den Post-Commit-`concept sync --full`, wenn der letzte
Concept-Source verschwindet.

### Erforderlicher Root-Fix

1. Das Run-Commit braucht einen auflösbaren, idempotenten Commit-Vertrag:
   deterministischer Run-Key plus strikter Read-after-error-Abgleich des exakt
   erwarteten Payloads. Ein nachweislich vorhandener identischer Run ist
   Erfolg, nicht Fehler. Ist der Ausgang wegen eines Read-Ausfalls unbekannt,
   darf der Code weder Before-Image noch Rollback behaupten; er braucht einen
   dauerhaften `commit_outcome_unknown`-/Recovery-Zustand, der vor dem nächsten
   Lauf aufgelöst wird.
2. Die autoritative Revision muss auch einen erfolgreichen Producer mit null
   Sources darstellen können. Dafür braucht der Run-Record eine
   producer-/source-type-weite Completion-Zusammenfassung (oder ein
   gleichwertiges fachliches Tombstone-Modell), aus der
   `story_list_sources.last_revision` auch bei leerem Korpus abgeleitet wird.
   Ein erfundener Fake-Source-Pfad wäre kein sauberer Fix.
3. Regressionstests müssen ACK-Verlust **nach** erfolgreichem Insert sowie
   nichtleer→leer für Story, Concept und den Post-Commit-Pfad beweisen.

## R1-002 — geschlossen und verifiziert

**Ort**

- `src/agentkit/backend/installer/config_boundary.py:30-114`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp01_to_06.py:193-240`
- `src/agentkit/backend/installer/runner.py:728-744`

Verifikation:

- Das initiale Before-Image bindet Existenz, Bytes, SHA-256 und aufgelöstes
  Symlink-Ziel und wird strikt mit `parse_project_config()` geparst.
- Direkt am Eintritt von CP5, vor Scaffold oder Config-Write, wird erneut
  strikt gelesen. Zielpfad, Bytes, Digest und typisiertes Modell müssen exakt
  unverändert sein.
- Gültige Änderung und Duplicate-Key-Mutation innerhalb des Preflights
  enden mit `configuration_changed` bzw. `configuration_invalid`; die Tests
  beweisen ein unverändertes Wirkungs-Before-Image.
- `_write_yaml_if_changed()` vergleicht `ProjectConfig` gegen den strikt
  geparsten Ist-Stand. `yaml.safe_load()`/Last-Wins ist dort entfernt.
- Es gibt am Re-Read keinen Fallback auf das zuvor gehaltene `model_dump()`.
  Ein verändertes Symlink-Ziel wird über `resolved != before.resolved_target`
  abgewiesen.

Kein verbleibender BLOCKER/MAJOR.

## R1-003 — MAJOR — noch offen

### Was jetzt funktioniert

- Der markierte Legacy-Secret-Owner wird entfernt; der neue Dispatcher ist der
  einzige AgentKit-Secret-Owner
  (`src/agentkit/backend/installer/git_hook_dispatch.py:110-143`).
- Die grüne Real-Hook-Probe beobachtet genau einen Managed-Pre-Dispatcher und
  erhält einfache fremde Pre-/Post-Kommandos aktiv.
- Pre-/Post-Datei, beide Preserved-Dateien und `core.hooksPath` werden als eine
  Mutation behandelt. Fehler am zweiten Write und Fehler nach Aktivierung
  restaurieren die getesteten Before-Images exakt
  (`git_hook_dispatch.py:301-401`).

### Noch offene Wurzellücke: Fremdhook-Interpreter wird zerstört

**Ort**

- `src/agentkit/backend/installer/git_hook_dispatch.py:131-156`
- `src/agentkit/backend/installer/git_hook_dispatch.py:301-319`

`_foreign_body()` entfernt jede vorhandene Shebang. Die Preserved-Datei wird
anschließend immer mit `#!/bin/sh` neu erzeugt, und der Canonical Hook ruft sie
explizit als `sh "$PRESERVED_HOOK"` auf. Damit bleiben nur
`sh`-kompatible Fremdhooks aktiv. Ein legitimer Hook mit
`#!/usr/bin/env python3`, Bash-spezifischem Code oder einem anderen
Interpreter ist nach der Migration nicht mehr ausführbar.

Benigne Reproduktion mit einem syntaktisch gültigen Python-Hook:

```text
original-python-syntax 0
preserved-sh-syntax 2
preserved-sh-error ... syntax error near unexpected token `"foreign.log"'
preserved-shebang #!/bin/sh
```

Das ist keine exotische Missbrauchsannahme, sondern eine normale
Git-Hook-Oberfläche. Die vorhandenen Tests verwenden ausschließlich
`#!/bin/sh` plus `printf` und können den Verlust der Interpretersemantik nicht
sehen.

**Erforderlicher Root-Fix**

Die erhaltene Fremdlogik muss ihre ursprüngliche Interpreterbindung behalten.
Die Preserved-Datei ist mit passender Shebang und ausführbarem Modus zu
materialisieren und direkt als `"$PRESERVED_HOOK" "$@"` aufzurufen, nicht über
erzwungenes `sh`. Für die Secret-Block-Entfernung braucht es eine
sprach-/formatbewusste, fail-closed Erkennung; unbekannte Strukturen dürfen
nicht halb umgeschrieben werden. Tests: mindestens `sh`, Bash und ein
benigner Python-Pre-/Post-Hook, jeweils tatsächlich ausgeführt.

## R1-004 — geschlossen und verifiziert

**Ort**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/4.1.0/SKILL.md`
- `tests/unit/installer/test_ag3_176_skill_bundle.py:176-232`

Verifikation:

- 4.1.0 ist mit 1095 Zeilen ein vollständiges eigenständiges `SKILL.md`; es
  enthält keine Include-/Overlay-Referenz auf 4.0.0.
- Der wirksame Story-/Concept-Discovery-Pfad hat keinen Grep-, Glob-,
  Filescan-, lokalen oder Best-Effort-Fallback.
- Das Freshness-Gate ist über vorhandene Oberflächen ausführbar:
  `python -m agentkit.backend.vectordb.cli ... validate --corpus --strict`
  liefert `VALIDATED_CONCEPT_REVISION`; danach wird
  `story_list_sources` gelesen und exakt ein Concept-Eintrag mit
  nichtleerem `last_revision`, `stale_chunk_count == 0` und
  `last_revision == VALIDATED_CONCEPT_REVISION` verlangt
  (`SKILL.md:788-818`).
- Der Real-Boundary-Test unterscheidet Match, Mismatch, fehlende Completion
  und Toolausfall. Es wurde kein neues FK-13-MCP-Tool erfunden; verwendet
  werden CLI `concept validate` und das bestehende
  `story_list_sources`.

Kein verbleibender BLOCKER/MAJOR.

## R1-005 — geschlossen und verifiziert

**Ort**

- `src/agentkit/backend/skills/bundle_store.py:37-69`
- `src/agentkit/backend/skills/bundle_store.py:410-479`
- `src/agentkit/backend/skills/top.py:750-807`
- `src/agentkit/backend/skills/binding.py:76-105`

Verifikation:

- `verify_pinned_binding()` lädt exakt den persistierten
  `(bundle_id, bundle_version)`-Pin über `get_bundle_version()`; keine
  Highest-Version-Wahl.
- Beide Harness-Links müssen echte Directory-Links sein und auf dasselbe
  kanonisch aufgelöste Ziel zeigen.
- Raw-Bindings müssen exakt auf den kanonischen Store-Bundle-Root zeigen;
  materialisierte Bindings dürfen nur im definierten digest-keyed
  Materialized-Store-Layout liegen.
- `bundle_content_digest()` bindet Pfadnamen und Bytes aller regulären
  Bundle-Dateien, einschließlich `SKILL.md`, und lehnt Symlinks im Bundle ab.
  Der erwartete Digest wird beim Bind persistiert und nicht aus dem aktuellen
  Linkziel übernommen.
- Beide R1-Angriffe sind jetzt fail-closed: gleich deklarierte Outside-Store-
  Ziele und eine nachträglich geänderte `SKILL.md` (auch mit neu berechnetem
  Manifest-Digest) werden abgewiesen. Ebenso grün: ein abweichender Harness-Link
  und Store-Symlink-Escape.

Kein verbleibender BLOCKER/MAJOR.

## R1-006 — geschlossen und verifiziert

**Ort**

- `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/docmodel.py:214-240`
- `tests/unit/concept_toolchain/test_docmodel_anchor_regression.py`

`HTMLParser` sammelt nur bei exaktem Tag `a` das exakte Attribut `id`.
Die vier geforderten Fälle ergaben:

```text
<aside data-id="ghost"></aside> -> []
<abbr id="abbr"></abbr>         -> []
<a data-id="wrong"></a>         -> []
<a id="right"></a>              -> ["right"]
```

Groß-/Kleinschreibung, Attributreihenfolge, beide Quote-Arten und mehrere Tags
pro Zeile sind zusätzlich abgedeckt. Kein verbleibender BLOCKER/MAJOR.

## R1-007 — geschlossen und verifiziert

**Ort**

- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10_mcp_registration.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10a_initial_sync_checkpoint.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10b_hook_dispatch_checkpoint.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10c_are_scope.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10d_sonarqube.py`
- `src/agentkit/backend/installer/bootstrap_checkpoints/registry.py:26-40`

Verifikation:

- `cp10.py` ist auf 40 Zeilen reduziert und enthält nur einen
  Kompatibilitätsalias für alte Import-/Patch-Stellen.
- CP10 MCP, CP10a, CP10b, CP10c und CP10d besitzen jeweils genau ein
  Handler-Modul.
- CP10a delegiert an den Initial-Sync-Owner, CP10b an den
  Git-Hook-Dispatch-Owner, CP10d an den bestehenden Third-Party-Owner; es
  existiert keine zweite produktive Implementierung dieser Fachlogik.
- `registry.py` importiert die fünf Handler ausschließlich aus ihren
  jeweiligen Modulen. Der AST-Contract-Test dafür ist grün.

Kein verbleibender BLOCKER/MAJOR.

## Neuer Befund R2-001 — MAJOR — Run-Completions vergeben konkurrierend dieselben Positionen

**Ort**

- `src/agentkit/backend/vectordb/engine.py:426-495`
- `src/agentkit/backend/vectordb/engine.py:497-540`
- `src/agentkit/backend/vectordb/engine.py:570-638`

Der neue Run-Record ist als einzelnes Objekt atomar, seine globale
Completion-Sequenz aber nicht. Zwei Writer lesen unabhängig denselben
`_highest_completion_sequence()`. Da der bedingte Create-Key aus
`project_id|run_id` statt aus der reservierten Position abgeleitet wird,
können beide Run-Objekte erfolgreich dieselben Sequenzen enthalten.

Benigne Zwei-Writer-Reproduktion über zwei echte `WeaviateCorpusStore`-
Instanzen auf demselben atomaren Recording-Store:

```text
run-a (1, 2)
run-b (1, 2)
all-sequences [1, 1, 2, 2]
unique False
```

Das verletzt den dokumentierten store-monotonen Completion-Order-Vertrag.
`_list_run_receipts()` prüft nur die Kontiguität **innerhalb** eines Runs und
erkennt die Überlappung zwischen Runs nicht. Bei zwei disjunkten
Single-Source-/Producer-Runs derselben Source-Type können dadurch
`_last_completed_revision()` und sein Source-File-Tiebreak eine andere als
die tatsächlich letzte Revision wählen.

**Konkreter Fix**

Die Position bzw. Range muss über eine gemeinsame atomare
Compare-and-Create-Identität für Single- und Batch-Completions reserviert
werden. Der verlierende Writer muss mit einer neuen, anschließend erneut
verifizierten Range retryen. Alternativ ist die globale Sequenz durch einen
wirklich atomaren Run-Order-Vertrag zu ersetzen. Ein negativer Zwei-Store-
Race-Test muss globale Eindeutigkeit und korrekte letzte Revision beweisen.

## Schema 3.32 und breite Remediation-Flächen

### Schema 3.32 — PASS

- `SCHEMA_VERSION` ist konsistent auf `3.32.0` angehoben
  (`state_backend/config.py:193`).
- PostgreSQL und SQLite besitzen dieselbe verpflichtende
  Lowercase-64-Hex-Constraint für `content_digest`.
- Repository-Upserts und Mapper führen das Feld in beiden Richtungen.
- Fresh Bootstrap und wiederholter Bootstrap sind getestet.
- Rückwärtsverträglichkeit folgt dem normativen Side-by-Side-Modell aus
  FK-18 §18.9a: die alte versionierte DB/das alte Schema bleibt unangetastet,
  3.32 wird frisch angelegt. Alte VERIFIED-Bindings ohne vertrauenswürdigen
  Digest werden dadurch nicht nachsichtig übernommen. Der
  `test_old_schema_db_untouched`-Pfad ist grün.

### Breite Änderungen — kein weiterer MAJOR+

Die zusätzlichen Änderungen in `skills/top.py`, `binding.py`,
`materialize.py` und `git_hook_dispatch.py` wurden auf neue Defaults,
Exception-Swallowing und Koerzierung geprüft. Abgesehen vom oben benannten
Interpreterverlust wurden keine weiteren fail-open Pfade mit BLOCKER-/MAJOR-
Substanz gefunden. Digest-Abweichungen, unreadable/outside-store Ziele und
Rollback-Residuals werden fail-closed sichtbar gemacht.

### AC9 / Gate-Disziplin — PASS

Im Diff wurde kein neues `NOSONAR`, keine Sonar-Exclusion und keine
Coverage-/Quality-Gate-Aufweichung gefunden. R1-006 ist als echte
Verhaltenskorrektur mit Negativmatrix repariert. Die gemeldeten und vom
Orchestrator bestätigten Full-Suite-/Sonar-Ergebnisse werden durch diese
Verifikationsrunde nicht angezweifelt; grüne Gates kompensieren jedoch die
oben reproduzierten Vertragsfehler nicht.

## Externe Punkte

AC8 W2/W3 (LLM-Hub) und die externe Jenkins-Auth bleiben wie vorgegeben
außerhalb dieses Fix-Auftrags. Sie sind nicht Ursache der Ablehnung. Der Code
wäre nach Schließen der drei oben genannten Substanzpunkte für die erneute
Gate-/Landungsprüfung bereit.

## Landungsentscheidung

**NICHT FREIGEBEN.**

Vor einer Freigabe sind konkret zu schließen:

1. **BLOCKER:** R1-001 — ACK-Verlust nach committed Run-Insert und
   nichtleer→leer müssen Engine-Completion, maßgebliche Revision,
   Retrieval-Freshness und lokale Receipts ehrlich konsistent halten.
2. **MAJOR:** R1-003 — Fremdhooks müssen unabhängig von ihrer ursprünglichen
   Interpreter-Shebang aktiv bleiben.
3. **MAJOR:** R2-001 — Completion-Positionen/Ranges müssen storeweit atomar
   und global eindeutig sein.

Alles Verbleibende ist **keinesfalls bloßer Feinschliff**.
