# AG3-176 — Codex Review Round 4 (finale Verifikation)

Datum: 2026-07-29

Rolle: adversarialer Reviewer, finale Verifikationsrunde 4

Geprüfter Stand: uncommitteter Working Tree auf
`feat/ag3-176-vectordb-installer-integration`

## Gesamturteil

**NICHT FREIGEBEN — kein BLOCKER, aber exakt ein verbleibender MAJOR in
R2-001.**

R1-001 ist an der Wurzel geschlossen. Die drei modellierten Commit-Ausgänge
von R2-001 sind mit typisierten Port-Fehlern konsistent und der terminale
`NOT_COMMITTED`-Zustand übersteht einen Prozessneustart. Der konkrete
Weaviate-Transport hält diesen Fehlervertrag jedoch noch nicht ein:
`_RealWeaviateClient.fetch_by_property()` lässt reale Query-Ausnahmen
unverändert entweichen. Damit wird der neue terminale Collision-Read-Zweig
umgangen; ein definitiv nicht commiteter Run bleibt recovery-fähig und wird
nach Neustart doch publiziert.

Das ist die einzige verbleibende BLOCKER-/MAJOR-Substanz. Es gibt keine
zusätzlichen MINOR-/NIT-Befunde. Der Rest ist lokal und noch sauber schließbar;
er ist kein zu verankerndes Restrisiko.

## Verifikationsbasis

- Vollständige Code- und Diff-Lektüre der Round-4-Remediation in
  `commit_recovery.py`, `engine.py`, `weaviate_index.py`,
  `composition_project.py`, `story_commands.py` und der CP10a-Fehlerbehandlung.
- Produktive Call-Site-Inventur für `WeaviateCorpusStore` und
  `WeaviateStoryIndex`.
- Gezielte Suite für Recovery-State-Machine, StoryIndex, Story-Export/-CLI und
  CP10a: **108 passed in 11.61s**.
- Gezieltes Ruff: **PASS**.
- Gezieltes mypy für die fünf geänderten Produktionsmodule: **PASS**.
- Benigne Neustart-Reproduktionen für `NOT_COMMITTED` und den realen
  Weaviate-Query-Fehlerrand.
- Die vom Orchestrator bereits bestätigte vollständige Suite
  (**10900 passed**, Coverage 91 %), Architecture-/Concept-Gates und der frische
  Sonar-Lauf (**PASSED/0**) wurden nicht redundant wiederholt.

## R1-001 — GESCHLOSSEN

### Verifiziert: schreibfähiger Store hat keinen journalfreien Publikationspfad

**Ort**

- `src/agentkit/backend/vectordb/engine.py:212-223`
- `src/agentkit/backend/vectordb/engine.py:428-483`

`WeaviateCorpusStore.recovery_journal` ist jetzt ein obligatorisches
Konstruktorfeld ohne Default. Die Konstruktion ohne Argument endet mit
`TypeError`; eine typwidrige explizite Übergabe von `None` kann zwar die
Python-Dataclass-Laufzeitprüfung umgehen, scheitert aber bereits beim
prämutativen `resolve_pending_commits()` und kann keinen Completion-Run
publizieren. Es gibt keinen stillen `None`-/No-op-Zweig mehr.

Benigne Reproduktion:

```text
omitted-journal-construction TypeError
explicit-none-publication AttributeError
run-record-count 0
```

Der frühere Falschclaim „recovery journal retained“ ist damit im gültigen
produktiven Vertrag verschwunden: Wenn `_read_run_after_error()` diese Aussage
ausgibt, existiert der obligatorische Journal-Owner und der vorher gestagte
Eintrag ist tatsächlich erhalten.

### Verifiziert: produktiver StoryIndex bindet einen dauerhaften Projekt-Owner

**Ort**

- `src/agentkit/backend/story_creation/weaviate_index.py:42-99`
- `src/agentkit/backend/vectordb/commit_recovery.py:149-160`
- `src/agentkit/backend/bootstrap/composition_project.py:157-184`
- `src/agentkit/backend/cli/story_commands.py:451-484`
- `src/agentkit/backend/vectordb/engine.py:1942-1973`

`WeaviateStoryIndex` baut ohne `sync`-Testseam keinen produktiven Sync-Service
mehr ohne `FileCommitRecoveryJournal`. Alle produktiven Kompositionen binden
den Journal-Owner an den existierenden Projekt-Root:

- Story-Split: der bereits autoritativ ermittelte `corpus_root`;
- Export/Repair-CLI: der explizite Projekt-Root beziehungsweise derselbe aus
  `story_dir`/`stories_root` abgeleitete Root, der auch dem Export übergeben
  wird;
- CP10a/MCP/Closure: `compose_runtime()` mit dem registrierten Projekt-`cwd`.

Der Pfad ist dauerhaft
`.agentkit/receipts/vectordb/pending-commits`, nicht in-memory, nicht unter
`var/` und nicht pro Prozess neu erzeugt.

### Verifiziert: unbekannter Ausgang blockiert vor der nächsten Mutation

**Ort**

- `src/agentkit/backend/vectordb/sync.py:671-700`
- `src/agentkit/backend/vectordb/sync.py:813-829`
- `src/agentkit/backend/vectordb/sync.py:884-900`

`sync_source()`, `prepare_reconcile_sources()` und `prepare_full_reindex()`
rufen den Recovery-Owner vor Claim, Upsert oder Delete auf. Die produktive
StoryIndex-Reproduktion erzeugte nach ACK-Verlust plus Read-back-Ausfall genau
einen Pending-Eintrag. Der zweite Story-Lauf blieb vor seinem ersten Upsert
stehen; erst nach lesbarer Auflösung wurde die zweite Mutation ausgeführt.

Der Regressionstest
`test_story_index_owns_durable_recovery_and_resolves_before_next_mutation`
lief grün. R1-001 hat keine verbleibende BLOCKER-/MAJOR-Substanz.

## R2-001 — MAJOR OFFEN

### Geschlossen und verifiziert: die drei modellierten terminalen Ausgänge

**COMMITTED**

Ein erfolgreicher Insert oder ein exakter Read-after-error-Treffer entfernt
den Recovery-Eintrag. Scheitert dieses Finish, wird
`CommitOutcomeUnknownError` geworfen; Erfolg wird nicht falsch behauptet
(`engine.py:799-806`).

**NOT_COMMITTED**

Eine bekannte Kollision terminalisiert jeden verlorenen Versuch über
`finish_not_committed()`. Auch der letzte erschöpfte Versuch bleibt als
`state=not_committed` atomar auf Disk und wird von `list_pending()` bewusst
nicht geladen (`commit_recovery.py:67-103`,
`engine.py:584-649`).

Benigne Reproduktion mit neuer Journal- und Store-Instanz als simulierter
Prozessneustart:

```text
reported VectorDbWriteError
durable-terminal not_committed
republished-after-restart False
pending-after-restart 0
```

Der frühere Round-3-Fehler „erschöpfter Retry wird später publiziert“ ist damit
geschlossen.

Ein typisierter Collision-Read-Ausfall nach `insert_object() == False` wird
ebenfalls terminal `NOT_COMMITTED`, wirft `VectorDbUnavailableError` und kann
von CP10a im normalen Fehlerzweig mit Before-Image-Rollback behandelt werden.
Ein späteres `resolve_pending_commits()` publiziert diesen Run nicht.

**OUTCOME_UNKNOWN**

Nur der Pfad „Write kann den Server erreicht haben, ACK verloren und strikter
Read-back ebenfalls ausgefallen“ hält den gestagten Eintrag recovery-fähig und
wirft `CommitOutcomeUnknownError` (`engine.py:700-720`). CP10a fängt diesen Typ
vor dem allgemeinen `SyncError`-/`VectorDbError`-Zweig, behält die
Candidate-Receipts und behauptet ausdrücklich keinen Before-Image-Rollback
(`cp10a_initial_sync.py:260-291`).

Scheitert die Persistierung des terminalen `NOT_COMMITTED`-Zustands, übersetzt
`_finish_not_committed()` das ehrlich in `CommitOutcomeUnknownError`; der
Aufrufer darf deshalb ebenfalls keinen sicheren Rollback behaupten
(`engine.py:1227-1238`). Der neue Negativtest ist grün.

### Verbleibender MAJOR: konkreter Weaviate-Read bricht den Typvertrag

**Ort**

- `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:576-608`
- `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:632-700`
- `src/agentkit/backend/vectordb/engine.py:626-640`
- `src/agentkit/backend/installer/cp10a_initial_sync.py:260-291`

`_RealWeaviateClient.insert_object()` normalisiert Transportfehler korrekt zu
`VectorDbWriteError`. Der konkrete Leseweg
`fetch_by_property()`/`_fetch_all_pages()` normalisiert dagegen weder den
Collection-Zugriff noch `query.fetch_objects()`. Ein realer
`weaviate.exceptions.WeaviateQueryError` ist kein
`VectorDbUnavailableError`.

Der neue Engine-Zweig fängt beim Lesen des Collision-Owners ausschließlich
`VectorDbUnavailableError`. Deshalb umgeht ein echter Query-Ausfall
`_finish_not_committed()`, obwohl `insert_object() == False` den Ziel-Run
bereits definitiv als nicht committed klassifiziert hat. Der gestagte
`OUTCOME_UNKNOWN`-Eintrag bleibt liegen. CP10a sieht weder
`CommitOutcomeUnknownError` noch `VectorDbError`; seine konsistente
Abort-/Rollback-Entscheidung wird ebenfalls umgangen.

Benigne Real-Boundary-Reproduktion über den konkreten
`_RealWeaviateClient.fetch_by_property()` mit einem fehlschlagenden
Query-Transport:

```text
exception WeaviateQueryError
pending 1
republished True
```

Nach einer neuen Journal-/Store-Instanz publizierte
`resolve_pending_commits()` also genau den Run, dessen Conditional Create
bereits eindeutig `False` geliefert hatte. Die typisierten
`RecordingWeaviateClient`-Tests beweisen den gewünschten Branch, aber nicht den
produktiven Exception-Vertrag an der Adaptergrenze.

### Erforderlicher Root-Fix

Der konkrete Weaviate-Leseadapter muss sämtliche Client-/Query-Fehler an seiner
Transportgrenze konsistent als `VectorDbUnavailableError` normalisieren. Das
muss den Collection-Zugriff und alle Seitenabrufe einschließen; ein breites
Fangen erst in der Engine wäre die falsche Ownership und könnte
Programmierfehler als Transportzustand maskieren.

Danach muss ein Regressionstest am `_RealWeaviateClient`-Transportseam
beweisen:

1. `insert_object() == False` plus echter Query-Fehler erreicht den terminalen
   `NOT_COMMITTED`-Zweig und wirft den von CP10a behandelten typisierten Fehler;
2. eine frische Journal-/Store-Instanz nach simuliertem Prozessneustart
   republiziert den Run niemals;
3. CP10a führt den normalen Abort-/Before-Image-Rollback aus;
4. ein wirklich unbekannter Write-Ausgang bleibt weiterhin
   `CommitOutcomeUnknownError` und wird nicht versehentlich terminalisiert.

Der Fix ist klein, lokal und in dieser Branch-Runde noch vollständig
schließbar. Er ist **kein** sinnvoll zu verankernder Rest.

## Neu eingeführte Substanz / Story-Creation / AC9

### Journal-Pflicht-Verdrahtung

Die neue Verdrahtung bricht die bestehende Story-Creation-Semantik nicht:

- Export und Repair leiten weiterhin denselben autoritativen Projekt-Root aus
  ihren bestehenden Pfaden ab und verwenden ihn nun zusätzlich für den
  Recovery-Owner.
- Story-Split verwendet den bereits vorhandenen `corpus_root`; es gibt keinen
  CWD-, Temp- oder In-memory-Fallback.
- Fehlender/nicht existierender Projekt-Root, fehlende Config, fehlender
  Corpus-Port oder fehlendes Journal stoppen vor dem Story-Upsert.
- Der `sync`-Parameter in `WeaviateStoryIndex` bleibt ein expliziter
  Test-/Transportseam; keine produktive Komposition nutzt ihn als
  journalfreien Default.

Die einschlägigen 108 Tests blieben grün. Es wurde keine neue fail-open
Story-Creation-Stelle gefunden.

### Journal-/Engine-Änderungen

`CompletionCommitJournalEntry` ist strict, frozen und extra-forbid.
`NOT_COMMITTED` wird als echter atomarer Terminalzustand persistiert und
`list_pending()` filtert ausschließlich `OUTCOME_UNKNOWN`. Es wurde kein
neues `.get(default)` und keine Koerzierung gefunden, die beschädigte
Journal- oder Run-Daten als gültig repariert.

Die einzig relevante neue Exception-Lücke ist der oben belegte konkrete
Weaviate-Leseadapter. Innerhalb von Journal und Engine wurden keine weiteren
BLOCKER-/MAJOR-Pfade gefunden.

### AC9 / Gates

Im Diff gibt es kein neues `NOSONAR`, keine Sonar-/Coverage-Exclusion, kein
`--no-cov` und keine Quality-Gate-Aufweichung. `pyproject.toml`,
`Jenkinsfile` und Sonar-Konfiguration sind für diese Remediation unverändert.
Die gezielten Ruff-/mypy-Läufe sind grün; der bestätigte Full-Suite- und
Sonar-Stand bleibt glaubwürdig, kann den real reproduzierten R2-Typbruch aber
nicht kompensieren.

AC8 W2/W3 (LLM-Hub) und Jenkins-Auth bleiben wie vorgegeben extern und sind
nicht Teil dieses Fixes. Der Code wäre nach Schließen des einen R2-MAJOR für
diese externen Landungsschritte bereit.

## Finale Landungsentscheidung

**NICHT FREIGEBEN.**

Exakt verbleibende BLOCKER-/MAJOR-Liste:

1. **MAJOR R2-001 — konkreter Weaviate-Query-Ausfall umgeht die terminale
   Commit-Semantik.** Ein eindeutig abgelehnter Collision-Run bleibt als
   `OUTCOME_UNKNOWN` recovery-fähig und wird nach Prozessneustart publiziert,
   weil `_RealWeaviateClient` den Query-Fehler nicht zu
   `VectorDbUnavailableError` normalisiert.

**Schließbarkeit:** lokal, klar begrenzt und noch vollständig schließbar;
kein verankerbarer Rest.

R1-001 ist freigabefähig geschlossen. Für R2-001 sind Retry-Erschöpfung,
terminales `NOT_COMMITTED`, echter unbekannter Ausgang und fehlgeschlagene
Terminalisierung im typisierten Zustandsautomaten korrekt. Nach der
Transport-Normalisierung plus Real-Adapter-Neustarttest gibt es aus dieser
Vier-Runden-Prüfung keinen weiteren BLOCKER-/MAJOR-Handlungsauftrag.
