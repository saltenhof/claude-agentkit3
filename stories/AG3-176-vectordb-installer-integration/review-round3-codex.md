# AG3-176 — Codex Review Round 3 (Verifikation)

Datum: 2026-07-29

Rolle: adversarialer Reviewer, Verifikationsrunde 3

Geprüfter Stand: uncommitteter Working Tree auf
`feat/ag3-176-vectordb-installer-integration`

## Gesamturteil

**NICHT FREIGEBEN — adversarial reproduzierte Restsubstanz.**

R1-003 ist an der Wurzel geschlossen. Die normalen R1-001-ACK-/Empty-Corpus-
Pfade und der direkte R2-001-Zwei-Writer-Race sind ebenfalls sauber repariert.
Die Remediation hat aber zwei produktiv relevante Restlücken:

1. **BLOCKER R1-001:** Der dauerhafte Recovery-Vertrag ist im produktiven
   Story-Index-Pfad abschaltbar und wird dort tatsächlich abgeschaltet.
2. **MAJOR R2-001:** Ein definitiv fehlgeschlagener bzw. falsch klassifizierter
   Race-Verlierer bleibt recovery-fähig und kann später gegen das bereits
   gemeldete Fehler-/Rollback-Ergebnis publiziert werden.

Es gibt keine zusätzlichen MINOR-/NIT-Befunde. Das Verbleibende ist
Konsistenz- und Commit-Semantik, nicht Feinschliff.

## Verifikationsbasis

- Code- und Diff-Lektüre der Remediation in `commit_recovery.py`,
  `engine.py`, `sync.py`, `contracts.py`, `schema.py`,
  `git_hook_dispatch.py` und der unmittelbaren produktiven Consumer.
- Benigne Real-Boundary-Reproduktionen für ACK-Verlust, fehlendes Journal,
  Zwei-Store-Race, Retry-Erschöpfung, Collision-Read-Ausfall,
  nichtleer→leer und reale Hook-Interpreter.
- Konsolidierte VectorDB-/Installer-/Hook-Suite:
  **267 passed in 11.86s**.
- Concept-Toolchain einschließlich `runmodel.py`,
  `incubator_check.py`, Anchor- und Reference-Checks:
  **374 passed in 44.82s**.
- VectorDB-Contract-, MCP- und Retrieval-Consumer-Suite:
  **82 passed in 3.21s**.
- `scripts/ci/check_concept_reference_integrity.py`:
  **PASS, 0 errors, 55 bekannte Reports**.
- Die vom Orchestrator bereits bestätigte vollständige Suite
  (**10895 passed**, Coverage 91 %) und der frische Sonar-Lauf
  (**PASSED/0**) wurden nicht redundant wiederholt.

## R1-001 — BLOCKER — teilweise geschlossen, Wurzellücke offen

### Geschlossen und verifiziert

**ACK-Verlust nach erfolgreichem Store-Insert**

- `WeaviateCorpusStore._publish_completion_run()` persistiert vor dem
  Conditional Create den exakt positionsgebundenen Kandidaten und führt nach
  `VectorDbWriteError` einen strikten Read-after-error-Abgleich durch
  (`src/agentkit/backend/vectordb/engine.py:572-697`).
- Ist unter derselben atomaren Position exakt derselbe Property-Satz vorhanden,
  wird der identische Run als Erfolg zurückgegeben; lokale Receipts werden
  nicht fälschlich restauriert.
- Gezielter Test:
  `test_cp10a_ack_loss_after_committed_insert_is_idempotent_success` — PASS.

**Unbekannter Ausgang im CP10a-/MCP-Runtime-Pfad**

- `compose_runtime()` bindet ein `FileCommitRecoveryJournal` unter
  `.agentkit/receipts/vectordb/pending-commits`
  (`src/agentkit/backend/vectordb/engine.py:1907-1944`).
- Fällt der Read-after-error aus, bleibt der strikt typisierte Pending-Eintrag
  erhalten. CP10a behält die Candidate-Receipts und behauptet ausdrücklich
  keinen Before-Image-Rollback
  (`src/agentkit/backend/installer/cp10a_initial_sync.py:260-291`).
- `sync_source()`, `prepare_reconcile_sources()` und
  `prepare_full_reindex()` rufen die Recovery vor der ersten neuen
  Korpusmutation auf (`src/agentkit/backend/vectordb/sync.py:671-729`,
  `813-855`, `884-926`).
- Gezielter Test:
  `test_cp10a_unknown_ack_outcome_is_durable_and_resolved_before_retry` —
  PASS.

**Nichtleer→leer**

- Jeder vorbereitete Producer erzeugt nun unabhängig von der Zahl seiner
  Sources eine `ProducerCompletion`; ein leerer Producer belegt genau eine
  reale atomare Position, aber keinen erfundenen Source-Pfad
  (`src/agentkit/backend/vectordb/sync.py:813-926`,
  `src/agentkit/backend/vectordb/engine.py:628-675`).
- `story_list_sources.last_revision` berücksichtigt diese strikt gelesenen
  Producer-Completions. `source_count` und `chunk_count` bleiben null.
- Verifiziert für Story+Research und Concept über CP10a sowie für
  Post-Commit `concept sync --full`:
  `test_cp10a_nonempty_to_empty_publishes_authoritative_producer_revisions`
  und
  `test_post_commit_full_concept_sync_nonempty_to_empty_advances_freshness`
  — PASS.

### Offen: produktiver Store darf den dauerhaften Recovery-Vertrag abschalten

**Ort**

- `src/agentkit/backend/vectordb/engine.py:218-221`
- `src/agentkit/backend/vectordb/engine.py:478-483`
- `src/agentkit/backend/vectordb/engine.py:589-597`
- `src/agentkit/backend/vectordb/engine.py:776-785`
- `src/agentkit/backend/story_creation/weaviate_index.py:59-72`
- `src/agentkit/backend/bootstrap/composition_project.py:178`
- `src/agentkit/backend/cli/story_commands.py:463`

`WeaviateCorpusStore.recovery_journal` ist optional und standardmäßig `None`.
Alle Journaloperationen werden in diesem Zustand still übersprungen.
`WeaviateStoryIndex._build_sync()` verwendet genau diesen produktiven Default.
Damit ist der neue Engine-Run-Commit-Vertrag nicht allgemein dauerhaft:
`_read_run_after_error()` meldet sogar „recovery journal retained“, obwohl
keines existiert, und `resolve_pending_commits()` ist vor dem nächsten Lauf
ein No-op.

Benigne Real-Boundary-Reproduktion über den echten `SyncService` und zwei
unterschiedliche Story-Sources:

```text
first-run CommitOutcomeUnknownError ... recovery journal retained
journal-configured False
upserts-after-unknown 1
next-run VectorDbUnavailableError simulated run-receipt read outage
upserts-after-next-run 2
second-corpus-mutation-happened True
```

Der zweite Lauf hat also bereits seinen StoryContext-Upsert ausgeführt, obwohl
der unbekannte Ausgang des ersten Runs weder dauerhaft repräsentiert noch
aufgelöst war. Das verletzt genau die geforderte „vor dem nächsten Lauf
auflösen“-Invariante und ist eine reale Produktionsfläche, kein Test-only
Konstruktor.

**Erforderlicher Root-Fix**

Ein produktiv publikationsfähiger `WeaviateCorpusStore` darf nicht ohne
durablen Recovery-Owner konstruiert werden. Das Journal muss verpflichtender
Konstruktorbestandteil sein oder die Store-Komposition muss zentral einen
zwingenden, projektgebundenen Recovery-Pfad ableiten. Alle produktiven
Consumer, einschließlich `WeaviateStoryIndex`, müssen denselben Vertrag
verwenden. Ein Store ohne Journal darf höchstens explizit read-only sein und
keine Completion publizieren.

## R2-001 — MAJOR — Race geschlossen, Retry-Endzustand noch fehlerhaft

### Geschlossen und verifiziert

- Die atomare Create-Identität ist jetzt
  `uuid5(project_id|sequence_start)`, nicht mehr `project_id|run_id`
  (`src/agentkit/backend/vectordb/engine.py:628-675`, `791-798`).
- Zwei Store-Instanzen, die denselben High-Water-Mark lesen, konkurrieren
  dadurch um dasselbe Objekt. Der Verlierer liest den Gewinner strikt,
  springt auf `collision.sequence_end + 1` und versucht eine neue Range
  (`src/agentkit/backend/vectordb/engine.py:580-626`).
- Der geforderte Zwei-Store-Race
  `test_two_store_race_reserves_unique_global_completion_ranges` terminiert
  und liefert global eindeutig `[1, 2, 3, 4]`; die Freshness entspricht der
  ProducerCompletion mit der höchsten Sequenz.
- `_verify_global_completion_ranges()` weist überlappende persistierte Ranges
  zusätzlich fail-closed zurück (`src/agentkit/backend/vectordb/engine.py:
  1547-1563`).

### Offen: erschöpfter Retry wird später trotz definitivem Fehler publiziert

**Ort**

- `src/agentkit/backend/vectordb/engine.py:580-626`
- `src/agentkit/backend/vectordb/engine.py:485-570`

Der Retry ist auf 256 Versuche begrenzt und terminiert. Vor jedem Versuch wird
aber derselbe Run als Pending neu gestaged. Bei einer bekannten Kollision wird
auf die nächste Range gewechselt, ohne den alten Pending-Zustand zu beenden.
Ist auch der letzte Versuch nachweislich verloren, wirft der Code einen
definitiven `VectorDbWriteError`, lässt aber den letzten Pending-Eintrag stehen.
Die nächste Recovery interpretiert ihn als fortzusetzenden unbekannten Ausgang
und publiziert den zuvor definitiv fehlgeschlagenen Run nachträglich.

Benigne Reproduktion mit herabgesetztem Versuchslimit und einem atomaren
Recording-Store, der pro Versuch eine gültige konkurrierende Range gewinnt:

```text
publish VectorDbWriteError could not atomically reserve a completion range after 2 attempts
pending-after-definitive-failure 1
target-present-before-resolve False
target-present-after-resolve True
pending-after-resolve 0
```

Dasselbe Grundproblem tritt bereits bei einer einzigen realen Kollision plus
Read-Ausfall auf. Der Verlierer erhält von `insert_object()` eindeutig
`False`; der anschließende `_read_run_at_uuid()`-Fehler wird im
Collision-Zweig nicht in `CommitOutcomeUnknownError` übersetzt und beendet den
Aufruf als gewöhnlicher `VectorDbUnavailableError`, obwohl der Pending-Eintrag
recovery-fähig stehen bleibt:

```text
reported VectorDbUnavailableError simulated run-receipt read outage
pending 1
target-before-resolve False
target-after-resolve True
```

CP10a behandelt genau diesen Exception-Typ im allgemeinen
`VectorDbError`-Zweig als restaurierbaren Fehler und stellt die alten lokalen
Bytes wieder her. Die spätere Recovery publiziert dennoch die neue Engine-
Revision. Damit ist die falsche Rollback-/Recovery-Kombination nicht auf 256
Kollisionen beschränkt.

Damit können Aufrufer nach dem definitiven Fehler lokale Receipts restaurieren,
während ein späterer Lauf die Engine-Freshness des angeblich fehlgeschlagenen
Runs doch noch vorschiebt. Das ist neue Race-Remediation-Substanz und kein
Livelock, aber eine falsche terminale Semantik.

**Erforderlicher Root-Fix**

Nach einer eindeutig verlorenen letzten Kollision muss der Journalzustand
terminal als **nicht committed** beendet werden; er darf nicht als
`commit_outcome_unknown` recovery-fähig bleiben. Der Negativtest muss beweisen,
dass nach erschöpftem Retry ein späteres `resolve_pending_commits()` den
fehlgeschlagenen Run nicht publiziert. Fehler beim Beenden des Journalzustands
müssen ihrerseits fail-closed sichtbar bleiben. Zusätzlich muss eine
unlesbare Collision-Position entweder ohne späteres Republish terminal
fehlschlagen oder als expliziter `commit_outcome_unknown`-Zustand behandelt
werden, bei dem Aufrufer gerade **keinen** Before-Image-Rollback behaupten.

## R1-003 — MAJOR — geschlossen und verifiziert

**Ort**

- `src/agentkit/backend/installer/git_hook_dispatch.py:115-199`
- `src/agentkit/backend/installer/git_hook_dispatch.py:301-510`

Verifikation:

- Fremde Pre- und Post-Hooks werden mit vollständiger ursprünglicher Shebang
  in ausführbare `.bak`-Dateien materialisiert und vom kanonischen Shell-Hook
  direkt als Executable aufgerufen. Es gibt kein erzwungenes `sh` mehr.
- Die realen Ausführungsproben für `#!/bin/sh`,
  `#!/usr/bin/env bash` mit Bash-Array-Syntax und
  `#!/usr/bin/env python3` liefen für Pre und Post tatsächlich durch; der Log
  enthielt jeweils exakt `pre`, `post`.
- Ein Legacy-Secret-Owner wird nur unter erkanntem `sh`/Bash-Interpreter,
  exaktem Marker und exakt geparstem kanonischem argv entfernt. Ein unbekannter
  Marker bzw. eine unbekannte Struktur führt vor jeder Mutation zu
  `ValueError`; Pre/Post bleiben byte-identisch, Preserved-Dateien und
  `core.hooksPath` entstehen nicht.
- Die Real-Hook-Probe beobachtet genau einen Managed-Pre-Dispatcher, keinen
  verbliebenen Legacy-Secret-Aufruf und weiterhin je einmal das fremde
  Pre-/Post-Verhalten. Der Dispatcher-Vertrag führt Secret-Scan genau einmal
  und danach gegebenenfalls staged Concept-Validation aus.
- Fehler am zweiten Hook-Write sowie ein Fehler nach bereits erfolgter
  `core.hooksPath`-Aktivierung restaurieren Pre, Post, beide Preserved-Dateien,
  Dateimodi und den vorherigen Configwert über die gemeinsame Mutation.

Gezielte Hook-Suite: **8 passed**. Kein verbleibender BLOCKER/MAJOR.

## Neue Substanz / Consumer-Semantik / AC9

### Fail-closed-Prüfung

`PendingCompletionCommit` ist strict/frozen/extra-forbid typisiert; Journal-
Dateien werden atomar geschrieben, nur als reguläre UTF-8-JSON-Dateien
akzeptiert und vollständig geparst. Run-Records verlangen exakte Feldmengen,
strikte Projektbindung, positionsgebundene UUID, Batch-Digest, UTC-Zeit,
kontiguierliche Range, exakte Producer-Typen und einen erneut abgeleiteten
semantischen `run_id`. Es wurde kein `.get(default)`-/Koerzierungspfad
gefunden, der einen beschädigten neuen Run-Record als gültig repariert.

Die zwei gefundenen fail-open Stellen sind nicht versteckt oder
heruntergestuft:

- optionales `recovery_journal` auf einem schreibfähigen produktiven Store
  (R1-001);
- recovery-fähiger Pending-Eintrag nach normalem Fehler-/Rollback-Ausgang
  (R2-001).

### `ProducerCompletion` und bestehende Consumer

`ProducerCompletion` ist eine interne, strikt verifizierte producer-weite
Completion-Zusammenfassung. Die bestehenden öffentlichen Rückgabetypen bleiben
erhalten:

- `SyncService.sync_source()` liefert weiter `SyncResult`;
- Reconcile/Full-Reindex liefern weiter `list[SyncResult]`;
- `set_receipts()` liefert ausschließlich die versiegelten
  `SyncReceipt`s zurück;
- der `story_list_sources`-Wire-Shape bleibt unverändert.

Die fachliche Änderung an `last_revision` ist bewusst und erforderlich:
Ein erfolgreicher Producer kann seine echte Corpus-Revision nun auch bei null
Sources für alle von ihm besessenen Source-Typen darstellen. Bei nichtleeren
Runs liegt die ProducerCompletion auf derselben Run-Endposition und trägt
dieselbe Corpus-Revision wie die Source-Completions; bestehende Latest-
Completion-Semantik wird dadurch nicht umsortiert. Die 82 Contract-/MCP-/
Retrieval-Tests waren grün. Keine zusätzliche stille Consumer-Semantikänderung
gefunden.

### Reference-Integrity-Baseline

Die Baseline-Änderung fügt **keinen** neuen Suppression-Eintrag hinzu und
ändert weder Code, Pfad, Referenz noch Begründung. Sie verschiebt ausschließlich
die beiden bereits bekannten Einträge für
`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md`
von Zeile 296→297 und 459→460. Im Dokument wurde vor beiden Referenzen eine
normative Zeile ergänzt; an den Zielstellen steht weiterhin exakt
`tools/agentkit`, die materialisierte Zielprojekt-Location.

Der aktuelle Reference-Integrity-Lauf findet genau diese Einträge an 297 und
460 und endet mit 0 Fehlern. Die Anpassung ist daher legitime
Positionsnachführung und verdeckt keinen neuen Reference-Integrity-Verstoß.
Die Sonar-Komplexitätsrefactors in `runmodel.py`/`incubator_check.py` haben
keinen zusätzlichen Baseline-Ausnahmeeintrag erhalten; ihre vollständige
Concept-Toolchain-Suite war grün.

### Gate-Disziplin / AC9

Im Diff wurde kein neues `NOSONAR`, keine Sonar-Exclusion, keine Coverage-
Ausnahme und keine Quality-Gate-Aufweichung gefunden. Die Complexity-
Remediation ist als echte Extraktion/Strukturierung umgesetzt und nicht über
Suppressions erkauft. Abgesehen von den oben reproduzierten Commit-/Recovery-
Fehlern wurde keine weitere neue Verhaltensänderung mit BLOCKER-/MAJOR-
Substanz gefunden.

## Externe Punkte

AC8 W2/W3 (LLM-Hub) und Jenkins-Auth bleiben wie vorgegeben außerhalb dieses
Fix-Auftrags. Sie sind nicht Ursache der Ablehnung. Der gemeldete grüne
Full-Suite-/Coverage-/Sonar-Stand ist glaubwürdig, kompensiert aber die beiden
reproduzierten Commit-Vertragsfehler nicht.

## Landungsentscheidung

**NICHT FREIGEBEN.**

Vor einer Freigabe sind konkret zu schließen:

1. **BLOCKER R1-001:** Jeder produktiv schreibfähige Store, insbesondere der
   `WeaviateStoryIndex`, muss einen zwingenden durablen Recovery-Owner besitzen
   und einen unbekannten Ausgang vor jeder nächsten Mutation auflösen.
2. **MAJOR R2-001:** Race-Retry und Journal müssen terminal dieselbe Wahrheit
   liefern. Ein normal/definitiv fehlgeschlagener Aufruf darf nie später
   automatisch publiziert werden; ein tatsächlich recovery-fähiger Ausgang
   muss als `commit_outcome_unknown` gemeldet werden und darf keinen
   Before-Image-Rollback auslösen.

R1-003 sowie ACK-Read-after-error, producer-weite Empty-Corpus-Revisions und
die atomare globale Range-Identität selbst sitzen. Die verbleibenden zwei
Punkte sind klar begrenzbar, aber **echte Restsubstanz und kein Feinschliff**.
