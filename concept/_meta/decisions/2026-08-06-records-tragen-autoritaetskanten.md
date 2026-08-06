---
concept_id: META-DEC-2026-08-06-RECORDS-TRAGEN-AUTORITAETSKANTEN
title: Concept-Decision-Record — Decision Records tragen Autoritaetskanten
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to:
  - target: META-CONCEPT-CONSISTENCY
    scope: concept-consistency-governance
    reason: Der W4-Owner besitzt Record-Pflicht, Benennung und ab hier auch das Record-Schema
  - target: FK-13
    scope: concept-frontmatter
    reason: FK-13 §13.9.6 besitzt das Korpus-Frontmatter samt Kantenform und Status-Enum
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-consistency, ci, review-gate, AG3-232]
formal_scope: prose-only
---

# Concept-Decision-Record — Decision Records tragen Autoritaetskanten

Datum: 2026-08-06. Record gemaess META-CONCEPT-CONSISTENCY P3.

## 1. Anlass

Jenkins #1248 meldete `MISSING_DECISION_RECORD` fuer
`concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md:346`,
obwohl das zugehoerige Record existierte und schema-konform benannt war.
Ursache war die Frontmatter-Pruefung `validate_decision_record_file`
(`tools/concept_compiler/decision_record_records.py`): Sie verlangte
`authority_over == defers_to == supersedes == []`, `superseded_by is None`
und `status == "active"`.

Damit standen zwei Schemata gegeneinander. Das Korpus-Frontmatter
(FK-13 §13.9.6) kennt `defers_to` als qualifizierte Kante
(`{target, scope, reason}`), `supersedes`/`superseded_by` als
Abloesungspaar und `status` mit dem Enum `active | draft | archived`.
Das Record-Gate erklaerte jeden Record mit einer solchen Kante fuer
schemawidrig. Betroffen waren 5 von 42 Records.

Der Konflikt ist zugunsten des Korpus-Frontmatters aufzuloesen. Die
Belegkette:

- **P2 (§3, normativ)** bindet Prosa an Autoritaet: „Ein Dokument darf
  keine normativen Aussagen ueber Scopes treffen, ueber die es keine
  Authority hat und zu denen keine `defers_to`-Kante existiert." Ein
  Record hat konstruktionsbedingt `authority_over: []`. Die
  `defers_to`-Kante ist damit der **einzige** Weg, auf dem ein Record
  ueber den Scope sprechen darf, dessen Entscheidung er persistiert.
  Ein Schema, das die Kante verbietet, zwingt jeden Record in einen
  P2-Verstoss.
- **FK-13 §13.9.6** ist die Frontmatter-Spezifikation des Korpus und
  fuehrt `defers_to` genau in der Form, die das Gate zurueckwies;
  §13.9.7 prueft Abloesungsketten (`E-REF-003`, `E-CYCLE-002`), setzt
  ihre Existenz also voraus, statt sie zu verbieten.
- **Das Gate hatte fuer die Leerheitsforderung keinen normativen
  Owner.** W4 normierte Ablage, Benennung, Trailer-Syntax und
  Erfuellungswege — nie Frontmatter-Felder. Die Forderung entstand in
  Commit `8b424f56` (AG3-158); dessen eigener Record nennt die zwei
  Records vom 2026-07-02 lediglich als „Frontmatter- und
  Benennungsvorbild". Ein Beispiel wurde zum harten Schema eingefroren.
- **Gegenprobe an einem legitimen Zustand.** `2026-07-14-ccag-central-owner`
  wurde am 2026-08-06 durch `2026-08-06-ccag-matcher-only` abgeloest und
  traegt darum `superseded_by`. Unter dem alten Schema war ein
  abgeloester Record strukturell nie konform. Ein Regelwerk, das einen
  dokumentierten, legitimen Zustand unrepraesentierbar macht, ist
  defekt.

## 2. Entscheidung

Das Record-Schema wird als Auspraegung des Korpus-Frontmatters normiert
und in META-CONCEPT-CONSISTENCY §W4 verankert. `defers_to` und
`supersedes` sind gueltige Kantenlisten; geprueft wird ihre **Form**
(ID oder `{target, scope, reason}`, aufloesbare Ziel-Grammatik,
nichtleere Qualifizierer), nicht ihre Leerheit. `status` folgt dem
Korpus-Enum, eingeschraenkt auf `active | archived` — ein Record haelt
eine bereits getroffene Entscheidung, `draft` ist kein Record-Zustand.
`superseded_by` ist zulaessig und nur zusammen mit `status: archived`
kohaerent. `authority_over` bleibt leer: Ein Record haelt nie eigene
Authority.

Ziel einer `defers_to`-Kante ist ein autoritaetshaltendes Dokument
(`FK-NN`, `DK-NN`, `META-<POLICY>`), nicht ein anderer Record — Records
halten keine Authority, auf die verwiesen werden koennte. Ziel einer
`supersedes`-Kante und eines `superseded_by` ist ausschliesslich ein
Record (`META-DEC-…`).

Das Gate weist danach unveraendert ab: nichtleeres `authority_over`,
Kanten ohne `target`, Kanten auf nicht existente ID-Grammatiken, leere
`scope`/`reason`-Qualifizierer, Nicht-Listen in Kantenfeldern,
`supersedes` auf ein FK-Dokument, ein gesetztes `superseded_by` bei
`status: active`, `superseded_by` auf ein Nicht-Record, `status`
ausserhalb des Enums, abweichende `module`/`cross_cutting`/`doc_kind`/
`formal_scope`, fehlendes `decision-record`-Tag, `concept_id` in
falscher Grammatik oder mit vom Dateinamen abweichendem Datum, leerer
Titel und fehlende Pflichtfelder.

## 3. Alternativen

- **`defers_to` in den fuenf Records leeren.** Verworfen: Das haette
  inhaltliche Autoritaetskanten geloescht, um ein Werkzeug zu bedienen,
  und den P2-Verstoss erst erzeugt. Die Reparatur waere am falschen Ende
  erfolgt.
- **Das Leerheitsgebot normativ nachtragen.** Verworfen: Es
  widerspricht P2 und FK-13 §13.9.6 und macht Abloesung
  unrepraesentierbar. Ein Widerspruch verschwindet nicht dadurch, dass
  man die schwaechere Seite zur Regel erklaert.
- **Frontmatter der Records gar nicht mehr pruefen.** Verworfen: Das
  Gate wuerde jedes beliebig strukturierte Dokument im Records-Ordner
  als Erfuellung akzeptieren; die Pflicht waere durch eine leere Datei
  erfuellbar.
- **Ein eigenes Status-Wort `superseded` einfuehren.** Verworfen: FK-13
  §13.9.6 fuehrt das Korpus-Enum, und der Record vom 2026-07-25 haelt
  ausdruecklich fest, dass ausschliesslich `active`, `draft`, `archived`
  zulaessig sind. `archived` deckt den Zustand ab. Die ausfuehrliche
  Begruendung steht in §4a, weil es sich um denselben Fehlermechanismus
  handelt wie bei der Leerheitsforderung.

## 4a. `status: superseded` war nie zulaessig — Achsenverwechslung

Dieser Abschnitt steht hier nicht als Fussnote. Er dokumentiert
denselben Mechanismus, der auch die Leerheitsforderung erzeugt hat:
**Etwas stand im Baum und galt darum als Regel, ohne dass es je jemand
entschieden haette.** Bei der Leerheitsforderung war es ein eingefrorenes
Beispiel, hier ein einmal geschriebener Wert.

`concept/_meta/decisions/2026-07-14-ccag-central-owner.md` trug
`status: superseded`. Dieser Wert war zu keinem Zeitpunkt zulaessig:
FK-13 §13.9.6 fuehrt das Korpus-Enum `active | draft | archived`, und
`2026-07-25-concept-search-mixed-status-result-sets.md` haelt fest, dass
ausschliesslich diese drei Werte gelten. Es gab nie einen Beschluss, das
Enum zu erweitern.

Der Fehler ist praeziser als ein Tippfehler: Er ist eine
**Achsenverwechslung**. `assertion-authority.md` §3 normiert vier
getrennte Statusachsen mit je eigenem Owner. `superseded` ist auf zwei
davon ein gueltiger Wert — auf dem Decision-Lifecycle
(`proposed | accepted | rejected | superseded`, Owner: das Record selbst)
und auf `assertion_status`. Auf der Frontmatter-Achse `status`, die FK-13
§13.9.6 besitzt, ist er es nie. Der Record hat einen
Lifecycle-Wert in das Korpus-Statusfeld geschrieben.

Dass die Achsen getrennte Felder sind, ist im Korpus belegt:
`2026-07-19-concept-incubation-support.md` fuehrt den Lifecycle korrekt
als eigenes Feld `decision_status: accepted` **neben** `status: active`.
Genau diese Trennung fehlte im betroffenen Record.

Korrigiert auf `status: archived`. Die Tatsache der Abloesung geht dabei
nicht verloren — sie wird von `superseded_by` getragen, und die in §2
festgelegte Kohaerenzregel bindet beide Felder aneinander.

**Korpus-Sweep (Vollstaendigkeit).** Gesucht wurde repo-weit nach
`status:`-Werten `superseded` sowie nach `superseded` als Enum-Wert.
Ergebnis: Im Konzeptkorpus **genau eine** Fundstelle, die korrigierte.
Die Frontmatter-Statusverteilung ueber `concept/` lautet 367x `active`,
2x `draft`, sonst nichts. Alle weiteren Repo-Treffer liegen in
`stories/**/status.yaml` und gehoeren zur **Story-Status-Achse** mit
eigenem Owner und eigenem Enum — kein Defekt, keine Korrektur; der
Record vom 2026-07-25 stellt diese Trennung bereits ausdruecklich fest.
Treffer unter `var/` und `.claude/worktrees/` sind ephemere Kopien
ebendieser Story-Dateien.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `tools/concept_compiler/`,
`scripts/ci/`, `tests/` und die 42 bestehenden Records nach
`defers_to`, `superseded_by`, `decision-record` und `doc_kind`.
Ergebnis: Genau ein normativer Owner der W4-Regel
(`concept/_meta/konzept-konsistenz-governance.md`); genau ein Owner des
Korpus-Frontmatters (FK-13 §13.9.6), der unveraendert bleibt und hier
nur referenziert wird. Die technische Durchsetzung liegt allein in
`tools/concept_compiler/decision_record_records.py`;
`check_concept_frontmatter.py` liest ausschliesslich
`technical-design/` und `domain-design/` und sieht Records nicht.
`reference_integrity.py` ist nicht beruehrt. K5 ist nicht betroffen:
Das Gate besitzt weder Laufzeitdaten noch ein Datenbankschema.

Nach der Aenderung sind alle 43 Records schema-konform. Der einzige
Fall, der zunaechst offen blieb (`2026-07-14-ccag-central-owner.md`,
`status: superseded`), ist gemaess §4a am Record behoben worden — nicht
durch eine Aufweichung des Enums. Der zugehoerige Korpus-Sweep in §4a
belegt, dass es bei dieser einen Fundstelle bleibt.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| `concept/_meta/konzept-konsistenz-governance.md` §W4 | geaendert | Normativer Owner erhaelt das Record-Frontmatter-Schema und die P2-Begruendung der Kantenpflicht. |
| `concept/_meta/decisions/2026-08-06-records-tragen-autoritaetskanten.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| `tools/concept_compiler/decision_record_records.py` | geaendert | Formpruefung der Kanten und des Abloesungszustands statt Leerheitsforderung. |
| `tests/unit/tools/concept_compiler/test_decision_record.py` | geaendert | Belegt Kanten, Abloesung und die weiterhin abgewiesenen Schemaverstoesse. |
| `concept/_meta/decisions/2026-07-14-ccag-central-owner.md` | geaendert | `status: superseded` war ein Lifecycle-Wert im Korpus-Statusfeld (§4a); korrigiert auf `archived`. Keine Prosa beruehrt. |
| `concept/_meta/assertion-authority.md` §3 | referenziert-jetzt | Owner der vier getrennten Statusachsen; belegt, dass `superseded` auf der Frontmatter-Achse nie zulaessig war. |
| `stories/**/status.yaml` | nicht-betroffen | Eigene Story-Status-Achse mit eigenem Owner und Enum; der dortige Wert `superseded` ist kein Korpus-Frontmatter. |
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.9.6/§13.9.7 | referenziert-jetzt | Bleibt Owner des Korpus-Frontmatters; das Record-Schema ist seine Auspraegung. |
| `concept/_meta/decisions/2026-07-13-concept-decision-record-gate.md` | nicht-betroffen | Ablage, Benennung, Trailer-Syntax und Erfuellungswege von W4 bleiben unveraendert. |
| `scripts/ci/check_concept_decision_record.py`, `Jenkinsfile` | nicht-betroffen | Aufruf, Exit-Code-Vertrag und Stage-Verdrahtung bleiben unveraendert. |
| `scripts/ci/check_concept_frontmatter.py` | nicht-betroffen | Liest `technical-design/` und `domain-design/`; Records liegen ausserhalb seines Korpus. |
| Uebrige Konzeptdokumente | nicht-betroffen | Keine fachliche Aussage und keine Authority wird geaendert. |
