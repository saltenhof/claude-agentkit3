---
concept_id: META-DEC-2026-08-04-QA-POLICY-FALLBACKS
title: Concept-Decision-Record — Eindeutige QA- und Policy-Zuordnungen
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, verify-system, policy-engine, stage-registry, AG3-191]
formal_scope: prose-only
---

# Concept-Decision-Record — Eindeutige QA- und Policy-Zuordnungen

Datum: 2026-08-04. Record gemaess META-CONCEPT-CONSISTENCY P3/W4 fuer
AG3-191.

## 1. Anlass

Im `verify_system` konnten sechs fachliche Entscheidungen ueber insgesamt acht
Locator-Gruppen auf ungenauere oder doppelt implementierte Pfade ausweichen:
Check-Provenienz auf einen Schichtwert, MAJOR-Schwellwerte auf einen typenlosen
Skalar, Stage-Erkennung auf zwei Kopien derselben Suffix-Abbildung, QA-Zahlen
auf Findings, QA-Persistenz auf Teilstaende sowie die Default-Komposition auf
freie Keyword-Overrides. Damit konnte die QA-Schicht auch dann urteilen oder
persistieren, wenn die praezise Zuordnung fehlte.

FK-33 §33.2 und §33.7 setzen die Anker: Die Registry besitzt Stage-Identitaet
und Check-Herkunft, die Policy-Engine evaluiert Stage-Geltung und Schwellwerte
nach Story-Typ. FK-27 §27.7 setzt den Orchestrierungsanker fuer den
verpflichtenden `story_type`-Input.

## 2. Entscheidung

### 2.1 Check-Provenienz ist vollstaendig und pro Check

Der Outcome-Emitter akzeptiert ausschliesslich die per-Check-Herkunftstabelle.
Die StageRegistry loest Stage-Definitionen und ihre explizite Tabelle nativer
Sub-/Meta-Checks ueber eine gemeinsame API auf. Ein Registry-Eintrag liefert
fuer die jeweilige `check_id` `CHK-NNNN`; ein Check ohne FC-Herkunft liefert
`None`. Die Mapping-Struktur selbst ist Pflicht
und enthaelt fuer jede ausgefuehrte `check_id` einen Eintrag. Fehlende
Mitgliedschaft bricht die Emission mit benanntem Fehler ab; nur ein
ausdruecklicher `{check_id: None}`-Eintrag bezeichnet einen nativen Check.
Auch `LayerResult.metadata.executed_check_ids` ist als vollstaendiges
Ausfuehrungsprotokoll Pflicht. Es wird weder aus Findings rekonstruiert noch
bei fehlendem oder missgebildetem Wert als leer angenommen. Jedes Finding mit
nicht-leerer `check`-ID muss in diesem Protokoll enthalten sein; eine
Diskrepanz bricht die Emission mit benanntem Fehler ab. Ein einzelner
Origin-Wert fuer eine gesamte Schicht existiert nicht.

Adversarial-Targets uebernehmen ihre Provenienz aus der beim Spawn erzeugten,
typisierten Zuordnung von Target-ID zu kanonischem Quell-Artefakt, Quell-Result,
Quell-Finding-Index und Quell-Check. Der Spawn validiert die exakte Mitgliedschaft
des Findings und des ausgefuehrten Checks im kanonischen Layer-2-Artefakt seiner
Erzeugungsrunde; die Folgerunde konsumiert genau diesen vorherigen Spawn-
Envelope. Auch ein leerer Target-Snapshot wird dauerhaft geschrieben und fuehrt
zum explorativen Layer-3-Spawn. Die Schreibweise `<result>.<check>` allein
beweist keine Herkunft; Target-IDs duerfen von dieser Schreibweise abweichen.
Die Zuordnung wird im typisierten Runtime-Datenfluss weitergegeben und aendert
nicht das FK-48-eigene `adversarial.json`-Schema 3.1.

### 2.2 Stage-zu-Result-Namen gehoeren der Registry

`StageDefinition.layer_result_name` ist die einzige Abbildung von Registry-
Stage auf `LayerResult.layer`; `None` bedeutet Identitaet mit `stage_id`. Die
einzige abweichende Standardbelegung ist
`doc_fidelity_impl -> doc_fidelity`, weil Registry-Stage und Evaluatorrolle
fachlich verschiedene Identitaeten sind. Policy-Engine und QA-Projektionen
konsumieren dieses Feld. Generisches Abschneiden von `_impl` und lokale Kopien
der Abbildung sind verboten.
Die Registry stellt zugleich die Rueckaufloesung von `LayerResult.layer` auf
die kanonische Stage-ID bereit. Stage-Result-, Finding- und Check-Outcome-
Projektion erhalten dieselbe gebundene Registry-Instanz und persistieren
ausschliesslich diese kanonische ID. Zulaessige Stage- und Aggregat-
Resultnamen sind explizit registriert; unbekannte oder mehrdeutige Namen
werden bei Konstruktion beziehungsweise Aufloesung abgewiesen. Der
`doc_fidelity`-Resultname wird daher als `doc_fidelity_impl` gespeichert.
Nur `None` bezeichnet die Identitaet von Resultname und Stage-ID; leere oder
nur aus Leerzeichen bestehende Stage- und Resultnamen werden bei der Registry-
Konstruktion abgewiesen.

Die Registry besitzt auch die zulaessige Stage-Abdeckung je Result/Aggregat.
Sie wird mit dem aktiven Ausfuehrungsplan geschnitten; zusaetzliche Abdeckung
muss durch das vollstaendige Check-Protokoll belegt sein. Producer-
`metadata.stage_ids` kann keine Stage freischalten und muss, falls vorhanden,
dem abgeleiteten Wert exakt entsprechen.

Artefakt-Dateinamen sind eine getrennte Materialisierungskonvention. Sie sind
weder zusaetzliche Result-Namen noch alternative Stage-IDs.

### 2.3 Policy urteilt nur mit exaktem Story-Type-Schwellwert

`story_type` ist Pflichtinput jedes Policy-Urteils. Die Policy-Engine liest den
MAJOR-Schwellwert ausschliesslich aus der Story-Type-Tabelle. Fehlt der Eintrag,
entsteht ein benannter Konfigurationsfehler und kein Verdict. Der bisherige
typenlose Skalarpfad entfaellt. Die Schwellwerte selbst bleiben unveraendert;
die kanonische Standardtabelle fuehrt weiterhin den Wert 3 fuer alle vier
Story-Typen.

### 2.4 QA-Stage-Reads besitzen einen Speicherpfad

`FacadeQAStageResultsRepository` ist trotz seines historischen Klassennamens
der kanonische, vom `ProjectionAccessor` komponierte Storage-Adapter. Sein
Read dispatcht direkt auf den aktiven State-Backend-Treiber; eine zusaetzliche
Read-Fassade oder Kompatibilitaetsdelegation wird nicht konsultiert. Der
Klassenname bleibt bestehen, weil das Mandat kein produktives Modul oder eine
oeffentliche Schnittstelle ausserhalb der benannten Locators umbenennt.

### 2.5 Policy-Traversierung ist ein Pflichtinput

Die ausgefuehrte QA-Route uebergibt der Policy-Engine die exakte Menge
`traversed_layers`. Sie kann nicht aus vorhandenen Ergebnissen oder einem
`max_layer_reached` abgeleitet werden, weil gueltige Routen nicht
zusammenhaengend sein muessen. Die Menge enthaelt ausschliesslich Schichten 1
bis 4, ist nicht leer und enthaelt Schicht 4. Fehlt oder verletzt die
Routenevidenz diesen Vertrag, entsteht kein Verdict.

### 2.6 Der Policy-Decision-Export heisst `decision.json`

Der seit AG3-026 produktiv geschriebene Policy-/Verify-Decision-Record
`decision.json` ist die einzige kanonische Materialisierung. Ein alternativer
Policy-Dateiname wird weder geschrieben noch als erlaubter Export gefuehrt.

### 2.7 QA-Protokoll, Kennzahlen und Persistenz sind eine Einheit

`executed_check_ids` ist die einzige Quelle fuer `total_checks`; Findings
liefern ausschliesslich die fehlgeschlagenen beziehungsweise warnenden
Teilzaehlungen. Mitgelieferte Metadatenzahlen muessen exakt uebereinstimmen.
Vor dem ersten Write werden alle Resultnamen, Ausfuehrungsprotokolle und
Provenienzen des QA-Laufs validiert. Danach werden Stage-, Finding- und
Check-Outcome-Projektionen in einem Transaktions-Batch geschrieben. Ein
abgewiesener Lauf hinterlaesst keine Teilzeilen dieser Projektionen.
`CheckOutcomeEmitter` baut Records und besitzt keinen Persistenzparameter. Der
fruehere State-Backend-Writer fuer Stage/Findings mit leerer Outcome-Menge ist
entfernt. Der Batch behandelt seinen Eingang als vollstaendigen Attempt-
Snapshot: Er prueft zuerst fuer jedes Result die tatsaechlich existierende
kanonische `artifact_envelopes`-Referenz, loescht dann alle drei
Projektionsfamilien fuer den Attempt und schreibt den neuen Gesamtsatz in
derselben Transaktion. Jede Outcome-Zeile muss exakt zum Project-, Story-,
Run- und Attempt-Scope dieses Snapshots gehoeren; doppelte vollstaendige
Outcome-Identitaeten werden vor der Mutation abgewiesen. Ein Run-Reset loescht die drei Familien ebenfalls in
einer Transaktion ueber den gemeinsamen QA-Batch-Port. Oeffentliche
Einzel-Purges und frei synthetisierte `artifact_id`-Werte entfallen.
Legacy-Dateien sind keine Quelle dieser Projektionen; ein Import-, Backfill-,
Migrations- oder Kompatibilitaetspfad existiert nicht.

AG3-191 R8 schliesst den dadurch offengelegten produktiven Identitaetskonflikt
ohne Schemaaenderung: Wiederholte fachliche Pruefungen innerhalb derselben
Stage und desselben Attempts muessen je Ausfuehrung eine eigene registrierte
`check_id` liefern. Die Structural-Phasenpruefungen und ihre Findings verwenden
`phase_snapshots.<phase>`. Damit entsprechen `total_checks` und die Zahl der
Outcome-Zeilen einander; `failed_checks` und `warning_checks` bleiben die nach
Finding-Severity gebildeten Teilmengen derselben Check-Identitaeten.

### 2.8 Verify-Defaults besitzen einen typisierten Vertrag

`VerifySystemDefaultOptions` ist der einzige Default-Konfigurationsweg der
produktiven Komposition. Freie Keyword-Overrides und ein Merge-Helfer sind
entfernt; alle Aufrufer konstruieren das typisierte Optionsobjekt atomar.

## 3. Entfernte Pfade

| Gruppe | Locator aus AG3-191 und Review | Disposition |
|---|---|---|
| L1 | `check_outcome_emitter.py:109` | Schichtweiter Parameter und sein Vertrag entfernt; per-Check-Mapping ist Pflicht. |
| L1 | `check_outcome_emitter.py:50-61` | Findings-Ableitung entfernt; fehlende oder missgebildete `executed_check_ids` werfen `ValueError`. |
| L1 | `check_outcome_emitter.py:170-171` | Bedingter Rueckfall entfernt; fehlendes Mapping oder fehlende Check-Mitgliedschaft wirft `ValueError`. |
| L1 | `check_outcome_emitter.py:62` | Findings ausserhalb von `executed_check_ids` werden als unvollstaendiges Ausfuehrungsprotokoll zurueckgewiesen. |
| L2 | `policy_engine/engine.py:165-167` | Skalarer Konstruktorparameter und interner Skalarzustand entfernt. |
| L3 | `policy_engine/engine.py:414,444-445` | Lokale Namensfunktion entfernt; Consumer liest `StageDefinition.result_name`. |
| L4 | `stage_coverage_mapping.py:28` | Tote zweite Namensfunktion entfernt; das Modul ordnet nur noch ausgefuehrte Routen zu Stages zu. |
| L5 | `telemetry_projection_repository_qa.py:33` | Falscher Kompatibilitaetsvertrag entfernt; direkter kanonischer Backend-Read dokumentiert und verprobt. |
| L6 | `policy_engine/engine.py:216,373` | Optionalen `traversed_layers`-Input, `max_layer_reached`-Rueckfall und Ergebnisheuristik entfernt; exakte Routemenge ist Pflicht. |
| L7 | `stage_registry/registry.py:202,229`; `qa_read_models.py:20,43` | Resultnamen werden explizit und eindeutig aufgeloest; alle drei Projektionen erhalten dieselbe gebundene Registry. |
| L7 | `implementation/phase.py:361,397` | Gesamtvalidierung liegt vor dem ersten Write; die drei QA-Projektionen werden gemeinsam persistiert. |
| L7 | `qa_read_models.py:45,124` | Kennzahlen werden nur aus Ausfuehrungsprotokoll und Findings gebildet; Metadatenabweichungen werden abgewiesen. |
| L7 | `state_backend/verify_artifact_store.py:26,49`; `check_outcome_emitter.py:229,275` | Beide Split-Writer entfernt; der Emitter baut nur Records, alle drei QA-Projektionen gehen ausschliesslich gemeinsam ueber den Accessor-Batch. |
| L7 | `state_backend/store/telemetry_projection_repository_common.py`; `telemetry_projection_repository_qa.py` | Die QA-Repository-Protokolle und Adapter sind read/purge-only; oeffentliche Stage-, Finding- oder Outcome-Einzelwriter existieren nicht. |
| L7 | `stage_registry/registry.py:316`; `policy_engine/engine.py:315` | Result-Abdeckung gehoert der Registry und dem aktiven Plan; fremde bekannte Producer-Claims werden im produktiven Policy-Aufruf abgewiesen. |
| L7 | `stage_registry/stages.py:107,146` | Nur `None` bildet auf `stage_id` ab; leere und whitespace-only Stage-/Resultnamen scheitern bei Registry-Konstruktion. |
| L8 | `verify_system/defaults.py:76`; `verify_system/system.py:245`; `bootstrap/composition_verify.py:111` | Freie `legacy keyword overrides` und Merge-Helfer entfernt; produktive Aufrufer liefern `VerifySystemDefaultOptions`. |
| I1 | `telemetry/projection_accessor.py`; `state_backend/*/_qa_artifact_rows.py` | Drei separat committende QA-Purges entfernt; der gemeinsame Reset-Port loescht Stage-, Finding- und Outcome-Zeilen atomar. |
| I2 | `state_backend/postgres_store/_qa_artifact_rows.py`; `sqlite_store/_qa_artifact_rows.py`; `check_outcome_emitter.py` | Stage-ID-begrenzter Rewrite entfernt; der Batch ersetzt den vollstaendigen Attempt-Snapshot und weist fremde Scopes sowie doppelte Outcome-Identitaeten vor der Mutation ab. |
| I3 | `stage_registry/registry.py`; `adversarial_orchestrator/spawn.py`; `adversarial_orchestrator/challenger.py`; `adversarial_orchestrator/runtime` | Lexikalische Punkt-Aufloesung entfernt; nur der vorherige kanonische Spawn-Envelope mit exaktem Layer-2-Artefakt- und Finding-Bezug liefert Provenienz. Leere Target-Snapshots bleiben explizit und starten den explorativen Worker. |
| I4 | `state_backend/persistence_mappers/_verify.py` | Synthetische `<result>-attempt-<n>`-ID entfernt; Stage und Findings tragen den geprueften kanonischen Envelope-`record_key`. |
| R8 | `verify_system/structural/checker.py`; `structural/checks/meta_checks.py`; `stage_registry/check_origins.py` | Die pro Phase ausgefuehrte Snapshot-Pruefung und ihr Finding verwenden je eine registry-registrierte `phase_snapshots.<phase>`-Identitaet; Outcome-Zeilen und Zaehlung kollabieren nicht mehr. |

## 4. Impact-Sweep

Geprueft und geaendert wurden FK-33 fuer Registry, Outcome-Provenienz und Policy-Engine,
FK-27 fuer QA-Subflow und Policy-Orchestrierung, FK-20 fuer den Recovery-
Artefaktnamen, FK-02 fuer die Artefakt-Ownership, FK-06 fuer die Liste
nicht-kanonischer Materialisierungen, FK-37 fuer den Context-Sufficiency-
Warning-Export sowie FK-71 fuer Artefaktklasse und Producer-Registry. FK-69
ist Konsistenz-Owner der persistierten QA-Zeilen und wurde fuer den
vorvalidierten gemeinsamen Drei-Projektions-Batch nachgezogen: Emitter-
Einzelwrites und Stage-/Finding-Rewrites mit leerer Outcome-Menge sind
ausgeschlossen. Die Abschlussrunde praezisiert denselben Anker fuer
vollstaendige Attempt-Snapshots, atomare Drei-Projektions-Resets, den
existenzgeprueften `artifact_envelopes`-Bezug sowie das Verbot von Legacy-
Importen und Backfills. FK-48 §48.1 und §48.2.2-§48.2.5 wurden als Owner des
Adversarial-Spawn-, Target- und Feedbackvertrags geprueft: Die Aenderung bindet
die vorhandene Target-Ableitung an ihre kanonische Source-Evidenz und behaelt
Schema 3.1 unveraendert. Die bestehende FK-69-Regel, dass `check_proposal_ref` pro
ausgefuehrtem Check `CHK-NNNN | NULL` traegt, bleibt unveraendert und wird durch
die fail-closed Aufloesung praeziser durchgesetzt. FK-10, FK-30 und FK-76
erhalten keine neue Aussage und bleiben unveraendert.

R8 detailliert denselben FK-69-Identitaetsanker fuer die mehrfach ausgefuehrte
Structural-Phasenpruefung: Der bestehende Primaerschluessel bleibt
unveraendert; die Ausfuehrungen erhalten eindeutige registry-registrierte
Check-IDs, und Findings verwenden dieselben Identitaeten.

Die Aenderung detailliert ausschliesslich vorhandene Anker. Sie verschiebt
keine BC-Zustaendigkeit, aendert keine QA-Schwellwerte, eroeffnet keine neue
Konzeptdomaene und fuehrt keinen Migrations- oder Kompatibilitaetspfad ein.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|---|---|---|
| FK-33 §33.2.1 und §33.2.3 | geaendert | Pflichtige per-Check-Provenienz, eine Kennzahlenquelle und das eindeutige Registry-owned Result-Namensfeld werden explizit. |
| FK-33 §33.7 | geaendert | Story-Typ, vollstaendiger Schwellwert-Eintrag und validierte Traversierungsmenge sind Voraussetzung eines Verdicts. |
| FK-02 §2.2.3 | geaendert | Die Artefakt-Ownership fuehrt `decision.json` als einzigen Policy-/Verify-Decision-Export. |
| FK-06 §6.2.2 | geaendert | Der nicht erzeugte Alternativname entfaellt aus der Liste nicht-kanonischer Materialisierungen; der formale Truth-Boundary-Vertrag fuehrt bereits ausschliesslich `decision.json` und bleibt unveraendert. |
| FK-27 VerifySystem-Capability und §27.7 | geaendert | Die Komposition besitzt nur typisierte Defaults; der Orchestrierungsvertrag validiert vor dem Batch-Write und uebergibt Story-Typ sowie exakte Traversierungsmenge ohne Rueckfall. |
| FK-37 Glossar `context-sufficiency` | geaendert | Das Warning wird dem einzigen kanonischen Policy-Decision-Export `decision.json` zugeordnet. |
| FK-20 §20.7.3 | geaendert | Der Recovery-Vertrag benennt den kanonischen Layer-4-Export `decision.json`. |
| FK-71 §71.1.1 und §71.1.2 | geaendert | QA-Artefaktbeispiele und Producer-Zuordnung fuehren ausschliesslich `decision.json`. |
| FK-48 §48.1 und §48.2.2-§48.2.5 | geprueft, nicht geaendert | Der bestehende explorative Harness-Spawn und die Finding-abgeleiteten Mandatory Targets ankern den rundenuebergreifenden Spawn-Envelope. `adversarial.json` Schema 3.1 bleibt unveraendert. |
| FK-69 §69.2, §69.4-§69.7, §69.10-§69.12 und §69.15.5-§69.15.6 | geaendert | FK-69 normiert den existenzgeprueften kanonischen Envelope-Bezug, den vollstaendigen Attempt-Snapshot und den atomaren Drei-Projektions-Reset. Der Emitter baut nur Records; Split-Writes, Split-Purges, stage-begrenzte Rewrite-Reste und Legacy-Import-/Backfill-Pfade sind ausgeschlossen. Wiederholte Checks derselben Stage und desselben Attempts erhalten je Ausfuehrung eine registrierte Identitaet (`phase_snapshots.<phase>`); der Primaerschluessel und der Zeilenvertrag `CHK-NNNN | NULL` bleiben unveraendert. |
| FK-10, FK-30, FK-76 | geprueft, nicht geaendert | Runtime-, Project-Edge- und Observability-Zustaendigkeiten bleiben unberuehrt. |
| `verify_system` Outcome-, Policy- und Coverage-Module | geaendert | Die drei ungenauen bzw. doppelten Urteilswege entfallen. |
| State-Backend QA-Projection-Repository | geaendert | Der bestehende direkte Read bleibt kanonisch; die drei Repository-Protokolle sind read-only. Schreiben und Purgen laufen ausschliesslich ueber den gemeinsamen Batch-Port. |
| Backend-Komposition und Implementation-Aufrufstellen | geaendert | Entfernte Signaturen werden nicht mehr verdrahtet; produktive Aufrufe liefern die praezisen Pflichtinputs. |
| QA-Layer-Produzenten | geaendert | Jeder persistierbare `LayerResult` liefert das vollstaendige `executed_check_ids`-Protokoll; Fehlerpfade benennen ihren ausgefuehrten Fail-closed-Check. |
| QA-Stage-, Finding- und Check-Outcome-Projektionen | geaendert | Alle persistieren die ueber dieselbe Registry-API rueckaufgeloeste kanonische Stage-ID. |
| Betroffene Unit-, Contract- und Integrationstests | geaendert/geprueft | Alte Fallback-Erwartungen werden entfernt; Negativpfade und gemeinsame Registry-Quelle werden belegt. |
