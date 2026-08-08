---
concept_id: META-DEC-2026-08-08-VERIFY-SYSTEM-EDGE-ENDPOINTS
title: Concept-Decision-Record — die Bewertungsstrecke von verify-system verlaesst den Edge-Prozess
module: meta
cross_cutting: true
status: active
authority_over: []
doc_kind: decision-record
defers_to:
  - target: FK-91
    scope: api-catalog
    reason: FK-91 owns the /v1 operation catalog this record adds two operations to
  - target: FK-28
    scope: evidence-assembly
    reason: FK-28 owns the evidence assembly and its operator-recovery surface
  - target: FK-21
    scope: story-creation
    reason: FK-21 owns the create-time conflict assessment this record relocates
  - target: FK-10
    scope: distribution-boundary
    reason: FK-10 owns the edge/core cut that makes the operations necessary
supersedes: []
superseded_by:
tags: [meta, decision-record, api-catalog, distribution, verify-system, AG3-241]
formal_scope: prose-only
---

# Concept-Decision-Record — die Bewertungsstrecke von verify-system verlaesst den Edge-Prozess

Datum: 2026-08-08. Record fuer AG3-241.

## 1. Anlass

AK3 soll auf zwei Maschinen laufen: **Project Edge** auf dem Entwicklerrechner,
**Kern** auf einem zentralen Server. `/v1` ist die einzige vorgesehene Bruecke.
Gemessen am 2026-08-08 hielt der Bounded Context `verify-system` **20**
Grenzverletzungspaare, 19 davon Edge→Kern.

Die 19 zerfallen in genau zwei fachliche Vorgaenge — und beide sind mehr als ein
Distributionsproblem:

- **17 Paare**: Der Edge hielt `HubLlmClient`, den geteilten
  `StructuredEvaluator` und einen Prompt-Materializer als Python-Symbole und
  fuehrte damit die FK-21 §21.4.1-Schritt-3-Bewertung **der Story aus, die er
  gerade anlegt**. `CLAUDE.md` §WORKFLOW- UND STATE-DISZIPLIN: „Worker duerfen
  ihre eigenen QA-Ergebnisse nicht manipulieren."
- **2 Paare**: Der Operator-Recovery-Command `agentkit evidence assemble` rief
  den `EvidenceAssembler` lokal auf. Die Assemblierung entscheidet, welche
  Evidenz ein Reviewer sieht, und praegt den `manifest_hash`, an dem die Reviewer
  gemessen werden — ein QA-Artefakt-Erzeuger im Prozess des Beurteilten.

## 2. Entscheidung

**Zwei neue `/v1`-Operationen, beide nicht-mutierend, beide projekt-skopiert.**

| Operation | ersetzt |
|---|---|
| `POST /v1/projects/{project_key}/story-conflict-assessments` | 17 Ueberquerungspaare aus 5 Edge-Modulen |
| `POST /v1/projects/{project_key}/verify-evidence-assemblies` | 2 Ueberquerungspaare aus `cli.evidence_commands` |

Beide stehen mit Pfad, Verb, Schema und Fehlerfaellen in FK-91 §91.1a.

### 2.1 Kein `op_id`

Keine der beiden Operationen mutiert kanonischen Zustand. FK-91 §91.1a Regel 5
verlangt das Operation-Ledger-`op_id` fuer kanonische Projektmutationen; die
bestehende Ausnahme ist woertlich bei `POST /v1/auth/login` dokumentiert („keine
kanonische Projektmutation; deshalb kein Operation-Ledger-`op_id`"). Diese beiden
folgen derselben Regel — sie ist nicht neu, sie wird angewandt.

### 2.2 Der Anker ist der Kern nicht neu

Rolle, Check-ID-Whitelist und Prompt-Template der create-time-Bewertung liegen
seit jeher in `verify-system`: `roles.ROLE_TEMPLATE[STORY_CREATION_REVIEW]`
(`vectordb-conflict`) und `stage_registry.check_origins.STORY_CREATION_REVIEW_CHECK_IDS`.
Nur die *ausfuehrende* Maschinerie lag auf der falschen Seite. Sie zieht dorthin,
wo ihr Vokabular schon steht; ein neuer Bounded Context entsteht nicht.

### 2.3 Das Verdikt an der Grenze ist **binaer**

FK-21 §21.4.1 Schritt 3 spezifiziert `PASS` (kein Konflikt) oder `FAIL`
(Duplikat / Ueberschneidung). Die geteilte Layer-2-Aggregation kennt zusaetzlich
`PASS_WITH_CONCERNS`; der einzige Konsument der create-time-Antwort behandelt
ausschliesslich `FAIL` als Konflikt, ein `PASS_WITH_CONCERNS` waere dort still
ein „kein Konflikt".

Das Wire-Vokabular fuehrt deshalb `ConflictVerdict` mit **zwei** Werten, und der
Kern kollabiert Ambiguitaet vor dem Senden zu `FAIL`. Der ternaere `LlmVerdict`
bleibt unveraendert das Vokabular der ausfuehrungs-skopierten QA-Aggregation.

**Wirkung auf einen bestehenden Vertrag, ausdruecklich benannt:** Das Feld
`reconciliation.verdict` im Request von `POST /v1/projects/{project_key}/stories`
traegt ab jetzt `PASS`/`FAIL` statt `PASS`/`FAIL`/`PASS_WITH_CONCERNS`. Das ist
eine **Verengung auf die tatsaechlich erzeugte Wertemenge**: Der einzige Produzent
kollabierte schon vorher zu binaer, `PASS_WITH_CONCERNS` war an dieser Stelle nie
sendbar. Die Verengung entfernt einen fail-open-Zustand, sie entfernt keine
gelebte Faehigkeit.

### 2.4 Der Dateisystem-Anker wird kernseitig aufgeloest

Der Evidence-Request traegt **keinen** Pfad. Der Kern loest das
Story-Arbeitsverzeichnis aus dem `project_registry` auf (FK-10 §10.2.3 / I3:
„nie aus einem Feld des Dev-Prozesses"). Ein `project_root` im Body waere auf der
Kern-Maschine bedeutungslos und wuerde die kern-eigenen Story-Artefakte von
aussen adressierbar machen.

## 3. Was **nicht** entschieden wurde

- Die 4-Schichten-QA, Stage-Registry, Policy Engine und Trust-Klassen sind
  unveraendert. Diese Story verlegt den Aufrufweg, sie aendert keine
  Bewertungsregel.
- Der verbleibende Kern→Edge-Uebergang
  `verify_system.qa_cycle.invalidation -> installer.paths` (`QA_DIR`,
  `resolve_qa_story_dir`) ist **nicht** geschlossen. Er ist kein Endpunkt-Fall:
  ein Netzaufruf fuer eine Pfad-Konstante bezahlt Latenz und einen Ausfallpfad
  fuer Code, den beide Seiten lokal ausfuehren muessen — `installer.paths` wird
  auch von Edge-Modulen genutzt (`governance.guard_evaluation:23`). Er gehoert in
  dieselbe Klasse wie `utils`/`config`/`boundary`: geteilte Foundation, die der
  Edge als **eigene Kopie** bekommt. **Owner: AG3-209.**

## 4. Betroffenheitsmatrix

| Dokument | Aenderung | Grund |
|---|---|---|
| FK-91 §91.1a | zwei additive Tabellenzeilen | Katalog-Owner der `/v1`-Operationen |
| FK-91 §91.1 | CLI-Zeile `agentkit evidence assemble` praezisiert | die CLI ist jetzt Adapter, nicht Implementierung |
| FK-28 §28.7.1 | Signatur, Parameter, Handler-Ablauf nachgezogen | FK-28 besitzt den Operator-Recovery-Command, dessen Ablauf sich geaendert hat |
| FK-21 §21.4 | unveraendert | Ablauf, Schwellen und Zaehler sind dieselben; nur der Ausfuehrungsort der Stufe 2 wechselt, und den legt FK-21 nicht fest |
| FK-10 | unveraendert | der Distributionsschnitt wird angewandt, nicht geaendert |
| formal-spec `architecture-conformance.entities` | unveraendert | `wire_target_modules` katalogisiert **Symbolwanderungen** aus bestehenden Modulen; `agentkit_wire.verify_system` ist neues Vertragsvokabular, aus dem nichts wandert. Ein Eintrag dort wuerde eine Migration behaupten, die nicht stattfindet. Der Praefix `agentkit_wire` ist seit AG3-239 beansprucht, die Messung greift. |
