---
title: Verfahrensentwurf — agentische Konzeptpruefung (Delta zu FK-78)
status: draft
doc_kind: workspace-proposal
date: 2026-08-02
authority_over: []
note: >
  Nicht-normativ. Dieser Entwurf beschreibt ein Delta zu DK-16/FK-78 und
  ersetzt keinen Satz dieser Dokumente. Wo FK-78 etwas bereits normiert,
  wird referenziert, nicht wiederholt.
---

# Verfahrensentwurf — agentische Konzeptpruefung

## 0. Was dieser Entwurf ist und was er nicht ist

Der PO hat die Konzeptpruefung neu ausgerichtet: weg von Hub-Gates, an
die Konzeptanteile geschickt werden, hin zu **nativen Agenten mit
Leitplanken, Zielen und Nachweispflichten**, die ihre Strategie selbst
waehlen. Dieser Entwurf beschreibt genau die Differenz zum heutigen
normativen Bestand. Er ist **kein Parallelverfahren**.

Drei Saetze, die den Zuschnitt tragen:

1. **FK-78 traegt bereits fast die gesamte Mechanik.** Lauf-Lifecycle,
   Register, Digest-Pins, Receipts mit Reviewer-Unabhaengigkeit,
   Diff-Hunk-Reverse-Trace, Scope-Locks, Promotion-Closure — alles
   normiert und implementiert. Was fehlt, ist eine **leichte Bahn** durch
   dieselbe Mechanik und ein **Vertrag fuer den agentischen Pruefer**.
2. **Was sich aendert, ist der Ausfuehrende, nicht der Beleg.** FK-78
   §78.14 definiert Semantik-Gates als Request-Pack -> Ausfuehrung ->
   **Semantik-Receipt** -> deterministische Verrechnung. Der
   Receipt-Vertrag ist ausfuehrerneutral. Der Wechsel Hub -> Bridge ist
   damit ein Adaptertausch, kein Verfahrenswechsel (siehe Befund C-9).
3. **Determinismus wandert, er verschwindet nicht.** Frei wird die
   *Untersuchung*; deterministisch bleibt die *Verrechnung*. Ein Agent
   darf selbst entscheiden, wie er einen Befund findet; ob ein Befund
   blockiert, entscheidet weiterhin eine Policy gegen typisierte
   Belege. Ohne diese Trennung waere der Umbau ein Verstoss gegen
   CLAUDE.md ("nur dort LLMs, wo kreative oder bewertende Arbeit noetig
   ist") und gegen META-CONCEPT-CONSISTENCY §5 — siehe Befund C-1, dort
   liegt die einzige echte Doktrinfrage dieses Umbaus.

## 1. Die Stufen: heissen sie in FK-78 schon so?

**Nein — und zwar in beide Richtungen unterschiedlich.**

### 1.1 Was FK-78 heute hat

FK-78 §78.3 modelliert den Inkubator **lauf-orientiert**:
`concept-incubator/runs/<run_id>/` mit `workers/<pid>/outbox/`,
`rounds/r<N>/`, `synthesis/`, `promotion/`. Die Stufung entsteht ueber
die `run_status`-Achse (formal.concept-incubation.state-machine), nicht
ueber Verzeichnisse. Ein Verzeichnis `workspace/` existiert nicht; ein
Verzeichnis `interface/` existiert nicht.

### 1.2 Was der Blueprint hat — und warum der Name traegt und trotzdem taeuscht

Das Nachbarprojekt schneidet **themen-orientiert**:
`concept-inkubator/<space>/werkstatt/` und
`concept-inkubator/<space>/schnittstelle/`, genau zwei Kategorien je
Space, keine dritte (`ablage-und-zielorte` §3, Substruktur der
Inkubator-Spaces).

Der Punkt, der beim Uebernehmen leicht verlorengeht: `schnittstelle/`
ist dort **keine Reviewstufe**, sondern eine **Sichtbarkeitsgrenze** —
`werkstatt/` ist Rohstoff und nie versioniert, `schnittstelle/` ist das
abgeleitete Ergebnis und versioniert. Wer den Namen fuer ein Reviewgate
uebernimmt, importiert einen falschen Freund (Befund C-3).

### 1.3 Vorschlag: Zuordnung statt Umbenennung

Keine Umbenennung in FK-78. Die PO-Begriffe werden **zugeordnet** und
der Inkubatorwurzel ein Themenschnitt vorgelagert:

```text
concept-incubator/
  <space>/                      # Themenstrang (neu, additiv)
    workspace/
      runs/<run_id>/            # FK-78 §78.3 unveraendert, nur re-rooted
    interface/
      <slug>-freigabestand.md   # Vorlage-Dokument (neu)
      <slug>-einfuegeplan.tsv   # Freigabebasis (neu, §3.2)
      <slug>-review-<n>.json    # Review-Receipts (neu, §2.4)
```

Warum so und nicht anders:

- **`incubator_root` ist bereits projektkonfigurierbar** (FK-78 §78.2,
  `concept-governance.json`). Ein Themen-Zwischenverzeichnis ist damit
  eine Konfigurations-/Layoutfrage, keine Schemaaenderung.
- **Der Lauf bleibt die Einheit von Nachvollziehbarkeit, Locking und
  Closure** (FK-78-Glossar `incubation-run`). Ein rein themenbasiertes
  Layout ohne `run_id` wuerde diese Einheit aufloesen und waere eine
  zweite Wahrheit ueber den Ort der Inkubation.
- **`interface/` ist die einzige echte neue Stufe.** Zwischen DECIDING
  und PROMOTING gibt es heute keinen Ort, an dem ein Stand
  "vorlagefaehig, aber noch nicht promotet" liegt. Genau diesen Ort
  verlangt der PO.

Zustandszuordnung (keine neuen Zustaende — die Achse bleibt formal
normiert):

| PO-Begriff | FK-78-Entsprechung |
|---|---|
| `workspace` | `runs/<run_id>/` in FRAMING, STAFFING, CONVERGING, SYNTHESIZING, DECIDING |
| "wir sind fertig" | Austritt aus DECIDING; Dispositions-Closure als Eintrittsbedingung bleibt (§78.4-Gate-Mapping) |
| `interface` | **neu**: Vorlagestand vor PROMOTING; kein neuer `run_status`, sondern eine Pflicht-Station innerhalb von DECIDING |
| "Freigabe" | Eintritt in PROMOTING; Scope-Locks werden hier erworben (§78.11) |
| normativ | PROMOTING -> CLOSED, Promotion-Closure unveraendert (§78.11) |
| Migrationstreue-Pruefung | **neu benannter Nachweis** auf der vorhandenen Mechanik §78.10/§78.11 (siehe §3) |

**Konsequenz fuer FK-78, wenn der PO zustimmt:** eine Ergaenzung in
§78.3 (Layout), eine in §78.16 (Profil-Pflichten: `interface`-Station),
eine in §78.14 (Ausfuehrer der Semantik-Gates). Nicht mehr. Alles
Uebrige ist Referenz.

## 2. Die Reviewdimensionen als Nachweispflichten

Vorgegeben werden **Ziel und Beleg**, nicht Vorgehen. Jede Pflicht hat
dieselbe Gestalt: *Ziel* (was wahr sein muss), *Beleg* (welches typisierte
Artefakt es beweist), *Fail-closed* (was gilt, wenn der Beleg nicht
erbringbar ist). Der Agent waehlt Werkzeuge, Reihenfolge und Tiefe selbst.

**Gemeinsame Leitplanken fuer jeden Pruefauftrag:**

- Der Pruefer ist **read-only** auf `concept/` und auf `workspace/`; er
  schreibt ausschliesslich sein eigenes Receipt in `interface/`.
- Der Pruefer ist **unabhaengig**: anderer `principal_id`, andere
  `session_ref` als der Verfasser (FK-78 §78.10-Regel, unveraendert
  uebernommen).
- Fremder Entwurfstext ist **untrusted data**, nie Instruktion (FK-78
  §78.5, unveraendert).
- Ein Befund ohne **Locator** (Pfad + Anker/Zeilen) und ohne
  **woertlichen Beleg** aus dem geprueften Text ist kein Befund.
- "Konnte ich nicht pruefen" ist ein **zulaessiges und pflichtiges**
  Ergebnis. Es ist niemals PASS.

### R0 — Vorlagefaehigkeit (Eintrittspruefung, deterministisch)

- **Ziel:** Der Stand in `interface/` ist ueberhaupt pruefbar: er traegt
  einen vollstaendigen Einfuegeplan (§3.2), jede Zeile nennt Zielort und
  Aenderungsart, und der Entwurfsdigest ist gepinnt.
- **Beleg:** deterministischer Check (Toolchain), kein Agent.
- **Fail-closed:** fehlt der Plan oder ist er unvollstaendig, geht der
  Stand ohne Review nach `workspace/` zurueck. Ein Agent wird gar nicht
  erst beauftragt.

R0 ist der Hebel gegen Handarbeit: der Einfuegeplan ist die einzige
Zusatzarbeit des Verfassers, und er ist zugleich Reviewgrundlage,
Freigabebasis und Migrationsbaseline.

### R1 — Ankertreue (Zielortbindung)

- **Ziel:** Jede Zeile des Einfuegeplans zeigt auf eine **existierende**
  normative Stelle, die den Gehalt **besitzen darf**. Besitz heisst:
  `authority_over` des Zieldokuments deckt den Scope der Aussage, oder
  es existiert eine `defers_to`-Kante. Die naechstgelegene Textstelle ist
  nicht automatisch der richtige Eigner (Blueprint `ATOM-01` Invariante 8).
- **Beleg:** je Planzeile ein Urteil `passt | falscher-eigner |
  ziel-fehlt` mit Locator im Zieldokument und der Frontmatter-Zeile, aus
  der der Besitz folgt.
- **Fail-closed:** `falscher-eigner` und `ziel-fehlt` sind ERROR. Wo kein
  Dokument den Scope eindeutig besitzt, ist **das selbst der Befund** —
  der Gehalt wird nicht opportunistisch beim Nachbardokument abgelegt.
- **Abgrenzung:** Die reine *Aufloesbarkeit* von Ankern prueft W1
  deterministisch und bleibt Pflichtgate. R1 prueft die **Zustaendigkeit**,
  die W1 nicht kennt.

### R2 — Interne Konsistenz

- **Ziel:** Der Entwurf widerspricht (a) sich selbst nicht, (b) dem
  normativen Bestand im beruehrten Scope nicht, und (c) fuehrt keine
  Aussage ein, die anderswo bereits normiert ist (Single-Assertion,
  META-CONCEPT-CONSISTENCY P1).
- **Beleg:** je Widerspruch ein Paar aus zwei woertlichen Zitaten mit
  Locatoren und die Angabe, welche Seite nach der Autoritaetsordnung
  gewinnen muesste. Fuer (c) zusaetzlich der Fundort der bestehenden
  Aussage.
- **Fail-closed:** Ein Widerspruch, dessen Vorrangfrage der Pruefer nicht
  entscheiden kann, ist `CONFLICT` und geht als Entscheidungsvorlage an
  den PO — nicht in einen Kompromisstext.
- **Was hier stirbt:** genau das, was W3 leisten sollte. W3 hat den
  Scope-Set-Sweep ueber den Gesamtkorpus gefahren; R2 prueft den
  **Entwurf gegen seinen Scope**. Das ist der eigentliche Grund, warum
  das neue Verfahren billiger ist: der Sweep folgt der Aenderung, nicht
  dem Bestand.

### R3 — Fachliche Korrektheit und Problemraum

- **Ziel:** Der Entwurf trifft das Problem, das er zu loesen behauptet,
  und ist **kalt implementierbar**: ein unbeteiligter Umsetzer kann aus
  dem Entwurf plus den referenzierten Normen bauen, ohne eigene Annahmen
  einzufuegen.
- **Beleg (drei Teile, alle drei Pflicht):**
  1. **Divergenztest** (Blueprint `ATOM-01` Invariante 13): benannte
     Stellen, an denen zwei gewissenhafte Implementierer wesentlich
     verschiedenes Verhalten bauen koennten — mit dem konkreten
     Beispielpaar, nicht als Behauptung.
  2. **Kalter Implementierbarkeitstest** (`ATOM-01` §9.5): jede Stelle,
     an der der Pruefer eine eigene Annahme einfuegen muesste, wird als
     Luecke registriert — als Befund, nicht als Rueckfrage.
  3. **Luecken-Klassifikation** je Luecke: `extension | calibration |
     contract | decision` (`ATOM-01` §8.2a). AK3 kennt diese Achse heute
     nicht (Befund C-5); sie ist der Grund, warum "benannte Luecke"
     ueberhaupt entscheidbar wird.
- **Fail-closed:** `contract` und `decision` blockieren die Freigabe.
  `extension` und vollstaendig interimsgedeckte `calibration` duerfen
  benannt offen bleiben.
- **Warum dieser Test der wichtigste ist:** er ist das einzige Werkzeug
  im gesamten Verfahren, das **Abwesenheit** findet. Alle uebrigen
  Pruefungen pruefen Behauptungen; eine fehlende Sache behauptet nichts
  und erzeugt von sich aus keine Pruefung.

### 2.4 Das Review-Receipt

Ergebnis jedes Pruefauftrags ist **ein** Artefakt in `interface/`, nach
dem Muster des Semantik-Receipts aus FK-78 §78.14 (dieselbe Gestalt,
damit die Verrechnung dieselbe bleibt):

`{schema_version, review_kind: release|migration, subject_digest,
plan_digest, base_revision, agent: {harness, model, principal_id,
session_ref}, dimensions[]: {id: R0..R3|M1..M4, verdict:
passed|failed|not_assessable, reason}, findings[]: {finding_id,
severity: P0|P1|P2, dimension, path, locator, quote, statement,
gap_class?}, completed_at}`

Deterministisch verrechnet wird daraus: **Freigabe genau dann, wenn
jede Dimension `passed` ist und kein Befund `P0`/`P1` offen ist.**
`not_assessable` ist niemals `passed`. Kein Agent erklaert seine eigene
Arbeit fuer freigegeben; er liefert Belege, die Policy entscheidet.

## 3. Migrationstreue — der schaerfste Teil

### 3.1 Korrektur der Auftragsannahme

Der Auftrag sagt, die Migrationstreue-Pruefung fehle in AK3
**vollstaendig**. Das ist nicht richtig, und die Korrektur veraendert den
Zuschnitt erheblich (Befund C-2):

- **Fachlich normiert** ist sie in DK-16 §6 mit vier Ansprüchen: nichts
  verloren, nichts verfaelscht, nichts eingeschmuggelt, der Bestand hat
  sich nicht unbemerkt bewegt.
- **Technisch normiert** ist sie in FK-78 §78.10 (Projection-Receipts,
  Diff-Hunk-Reverse-Trace) und §78.11 (Promotion-Closure, Regeln 1–3).
- **Implementiert** ist sie in
  `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py`
  (`_check_atom_closure`, `_check_receipt_independence`,
  `_check_reverse_trace`, `_check_targets`).

Was **wirklich** fehlt, ist enger und benennbar:

1. Diese Mechanik haengt am **Atom-Register**, das nur ein
   `FULL_ATOM`-Lauf erzeugt. Fuer den vom PO verlangten sofort
   anwendbaren Pfad existiert sie nicht.
2. Es gibt **keinen Auftragsvertrag fuer den pruefenden Agenten** — nur
   fuer den Reviewer eines einzelnen Projektions-Receipts.
3. Es gibt **keine Freigabebasis** ausserhalb des Atom-Registers, gegen
   die "genau das Freigegebene" ueberhaupt gemessen werden koennte.

Die Aufgabe ist also nicht "Verfahren erfinden", sondern **die
vorhandene Mechanik auf eine leichte Basis stellen**.

### 3.2 Die Freigabebasis: der Einfuegeplan

Der PO verlangt ohnehin, dass der Entwurf schon korrekt auf die Stellen
referenziert, an denen er eingefuegt wird. Genau daraus wird die
Freigabebasis — das Atom-Register des leichten Pfades:

`interface/<slug>-einfuegeplan.tsv`, eine Zeile je materieller Aussage:

| Spalte | Inhalt |
|---|---|
| `assertion_id` | stabil, lauf-praefixiert; keine Wiederverwendung |
| `statement` | qualifikatorentreu — Bedingung, Ausnahme, Modalitaet, Owner, Failure reisen mit (`ATOM-01` §7.3) |
| `target_path` | Zieldokument |
| `target_anchor` | Abschnittsanker; mehrere bei Aufteilung |
| `change_kind` | `add \| replace \| delete` |
| `source_locator` | Fundstelle im Entwurf |
| `scope_id` | beanspruchter AssertionScope |

Der Plan wird beim Uebergang nach `interface/` **digest-gepinnt**. Er ist
zugleich R0-Gegenstand, R1-Gegenstand und M-Baseline. Das ist der
gesamte Zusatzaufwand des Verfassers — und es ist Arbeit, die er ohne
den Plan spaeter beim Einfuegen ohnehin taete, nur unaufgeschrieben.

### 3.3 Die vier Nachweispflichten der Migrationstreue

Sie sind bewusst **wortgleich zu den vier Ansprüchen aus DK-16 §6**
geschnitten. Keine neue Doktrin, nur ihre Nachweisform fuer den leichten
Pfad.

**M1 — Nichts fehlt ("nicht weniger").**
- *Ziel:* Jede `assertion_id` des gepinnten Plans ist im normativen Diff
  angekommen, an ihrem deklarierten Zielort, mit ihren Qualifikatoren.
- *Beleg:* je Planzeile Zielpassage-Locator plus Urteil
  `aequivalent | verkuerzt | fehlt`, bei `verkuerzt` der amputierte
  Qualifikator woertlich.
- *Deterministischer Anteil:* Mengengleichheit Plan <-> abgedeckte
  Anker. Maschine.
- *Agentischer Anteil:* semantische Aequivalenz. `verkuerzt` und `fehlt`
  sind ERROR.

**M2 — Nichts kam dazu ("nicht mehr").**
- *Ziel:* Jeder nicht-formale Diff-Hunk unter den Konzept-Wurzeln loest
  auf eine Planzeile oder auf ein benanntes Decision Record auf.
- *Beleg:* **hier ist nichts Neues zu bauen.** Der Diff-Hunk-Reverse-
  Trace aus FK-78 §78.10 leistet das bereits deterministisch; er braucht
  statt `atom_register.target_refs` die `target_anchor`-Spalte des Plans.
- *Fail-closed:* ungedeckter Hunk ist ERROR — unveraendert.

**M3 — Nichts wurde verfaelscht.**
- *Ziel:* Die Zielpassage traegt dieselbe Semantik wie die freigegebene
  Aussage, nicht nur dieselben Woerter.
- *Beleg:* Receipt mit `writer_principal_id != reviewer_principal_id`
  **und** verschiedenen Sessions (FK-78 §78.10, unveraendert). Verglichen
  wird ueber den semantischen Vektor, nicht ueber Wortlaut: Subjekt,
  Modalitaet, Praedikat, Objekt, Scope, Vorbedingungen, Ausnahmen, Owner,
  Failure-Semantik (`ATOM-01` §9.1). Typische Scheindeckungen — gleicher
  Fachbegriff bei anderem Owner, gleiche Aktion ohne Negativguard,
  gleicher Default mit gewechseltem Geltungsstatus — sind ausdruecklich
  Pruefgegenstand.
- *Fail-closed:* `disagrees` blockiert den Scope; ein Override durch den
  Verfasser ist verboten.

**M4 — Der Bestand hat sich nicht unbemerkt bewegt.**
- *Ziel:* Die Normwelt steht noch auf der `base_revision`, gegen die
  freigegeben wurde.
- *Beleg:* Digestvergleich. Reine Maschine.
- *Fail-closed:* Drift fuehrt nach RECHECK mit Adjudikationspflicht
  (FK-78 §78.4) — unveraendert.

### 3.4 Warum das nicht in Handarbeit ausartet

Die Frage des Auftrags war genau das. Die Antwort hat drei Teile:

1. **M2 und M4 sind vollstaendig deterministisch** und laufen heute
   schon. Sie sind die Haelfte des Nachweises und kosten nichts.
2. **M1 ist eine Mengenpruefung mit semantischem Rest.** Die Menge
   prueft die Maschine; der Agent urteilt nur ueber die Zeilen, die die
   Maschine als abgedeckt meldet.
3. **Der Plan wird nicht zusaetzlich geschrieben, sondern vorgezogen.**
   Ohne Plan macht der Verfasser dieselbe Zuordnung beim Einfuegen —
   nur unsichtbar und unpruefbar. Das ist der Unterschied zwischen
   Aufwand und Umschichtung.

Der ehrliche Restaufwand: bei einem Entwurf mit 30 Aussagen sind 30
Planzeilen zu schreiben und 30 Aequivalenzurteile zu faellen. Das ist
nicht nichts. Es ist der Preis dafuer, dass "verlustfrei uebernommen"
eine belegte Aussage wird statt einer Behauptung.

## 4. Einzelagent oder Council — wer entscheidet, und woran

**Wer:** Der Council-Orchestrator schlaegt vor, der PO entscheidet. FK-78
§78.15 verbietet bereits die stille Default-Besetzung; diese Regel wird
nicht angetastet, sondern nur mit Kriterien unterlegt.

**Woran:** Der PO nennt Groesse, Umfang, Impact. Operationalisiert — und
bewusst an die **bestehenden drei Profile** aus FK-78 §78.16 gebunden,
nicht an eine vierte Achse:

| Signal | Frage | Gewicht |
|---|---|---|
| Autoritaetsbreite | Wie viele `authority_over`-Scopes traegt der Entwurf? | 1 Scope -> leicht; >= 3 -> schwer |
| Ebenenbreite | Prosa allein, oder Prosa + Formal + Registry gemeinsam? | mehrere Ebenen -> schwer |
| Aenderungsart | Additiv, oder Ersetzung/Supersession/Ownership-Verschiebung? | Ersetzung -> schwer |
| Entscheidungsgehalt | Liefert der Divergenztest ein Ja? Gibt es eine echte Weiche? | Ja -> Council, unabhaengig von der Groesse |
| Anspruch | Wird "verlustfrei" oder "vollstaendig" behauptet? | Ja -> `FULL_ATOM` |

Zuordnung:

- **kein Signal** -> `DIRECT_GOVERNED_CHANGE`: kein Lauf, kein Council,
  aber Decision Record, Betroffenheitsmatrix und alle deterministischen
  Gates. Unveraendert.
- **ein bis zwei Signale** -> `LIGHT_INCUBATION`: Einzelagent im
  `workspace`, danach **zwingend ein fremder Agent** im `interface`.
  Ein Vier-Augen-Prinzip ueber Modell- und Anbietergrenzen hinweg, kein
  Gremium.
- **drei oder mehr Signale, oder Entscheidungsgehalt, oder
  Vollstaendigkeitsanspruch** -> `FULL_ATOM`: Council mit unabhaengigen
  Proposals und Runden. Unveraendert.

**Das Kriterium mit dem groessten Hebel ist der Entscheidungsgehalt.**
Ein kleiner Entwurf, der eine echte Weiche im Systemverhalten stellt,
gehoert ins Gremium; ein grosser Entwurf, der nur ausbuchstabiert, was
entschieden ist, nicht. Groesse allein ist das schwaechste der fuenf
Signale und steht deshalb nicht an erster Stelle.

## 5. Nicht-Freigabe: Rueckweg, Runden, Abbruch

**Der Rueckweg.** Ein nicht freigegebener Stand wandert als Ganzes nach
`workspace/` zurueck. Der `interface/`-Stand wird **nicht editiert** —
er ist mit seinem Digest die Referenz, gegen die der naechste Stand
gemessen wird, und bleibt als superseded liegen. Die Befunde werden in
das Befundregister des Laufs uebernommen (`findings.tsv`, FK-78 §78.9),
nicht in eine Nebendatei.

**Was am Rueckweg gemessen wird.** Ein Folgestand muss zu jedem Befund
eine von genau drei Antworten tragen: behoben (mit Locator), begruendet
zurueckgewiesen (mit Gegenbeleg), oder an den PO eskaliert. Ein Befund
ohne Antwort blockiert die erneute Vorlage. Das ist die Stelle, an der
das Verfahren gegen "5 Majors behoben, fertig" gesichert ist.

**Runden.** Keine feste Obergrenze durch Zaehlen allein — die
Abbruchkriterien sind dieselben zwei wie in der PO-Grundregel
(CLAUDE.md, Definition of Done):

1. Der Pruefer findet nichts Substanzielles mehr und sagt das
   ausdruecklich, nachdem er alle Dimensionen geprueft hat, **oder**
2. die verbleibenden Befunde sind nachweislich formale Kleinigkeiten;
   diese Feststellung ist zu begruenden und die Befunde sind zu
   benennen.

**Ergaenzend — und das ist neu:** Kommt es **ab der dritten Runde** nicht
zu einer Verengung (die Befunde werden nicht weniger und nicht
schwaecher), ist das **kein Qualitaetsproblem, sondern ein Signal**. Der
Stand geht dann nicht in eine vierte Runde, sondern als
Entscheidungsvorlage an den PO: entweder liegt ein strukturelles
Spannungsfeld vor (dann entscheidet er es), oder der Scope ist falsch
geschnitten (dann wird neu gerahmt). Eine Reviewschleife, die sich nicht
verengt, verengt sich auch in Runde sieben nicht — das ist die Anti-Loop-
Regel, angewandt auf das Reviewverfahren selbst.

**Abbruch.** Ein Lauf, dessen Entwurf verworfen wird, endet regulaer
(ABORTED nach FK-78, Locks werden als Bestandteil von `abort-run`
freigegeben). Die Befunde bleiben; der Rohstoff bleibt liegen. "Verworfen"
ist ein zulaessiges und dokumentiertes Ergebnis, kein Fehlschlag.

## 6. Die Harness-Bridge

Die Bridge ist **ausschliesslich Adapter**. Sie transportiert Auftrag und
Ergebnis; sie traegt keine Verfahrenssemantik.

- Der Auftrag enthaelt: Leitplanken (§2, gemeinsame), die Nachweispflicht
  (R0–R3 oder M1–M4), den Zugriffsumfang, das Receipt-Schema und die
  Fail-closed-Regel. Er enthaelt **kein Vorgehen**.
- `participants[].spawn_mode` kennt `harness-bridge` bereits (FK-78
  §78.4). Es ist kein neuer Wert noetig.
- Der Pruefagent laeuft in einem physisch separaten Arbeitsverzeichnis,
  wenn der Harness nicht guard-faehig ist (FK-78 §78.5, unveraendert).
- Ausfall der Bridge ist **niemals PASS**: fehlender Agentenzugang fuehrt
  zu `blocked_projection` fuer die betroffenen Scopes, exakt wie heute
  bei fehlendem LLM-Zugang (FK-78 §78.14, `check.py semantic-status`).

Was damit **nicht** geregelt ist und auch nicht hierhin gehoert:
Spawn-Mechanik, Session-Wiederaufnahme und Settings-Materialisierung
bleiben FK-76.

## 7. Was ersetzt wird, was bleibt

**Ersetzt:**

- W2 (`concept-authority-prose`) als korpusweiter Hub-Sweep -> geht in
  **R1** auf, aber aenderungsgetrieben statt korpusgetrieben.
- W3 (`concept-scope-consistency`) als Scope-Set-Sweep ueber den Bestand
  -> geht in **R2** auf, mit demselben Wechsel.
- Der Hub als Ausfuehrer der Semantik-Gates -> Bridge-Agent. Das
  Request-Pack/Receipt-Modell aus FK-78 §78.14 **bleibt**.

**Bleibt unveraendert verbindlich:**

- W1 `concept-reference-integrity` — Aufloesbarkeit aller Querverweise.
- `check_concept_frontmatter`, `compile_formal_specs`,
  `check_concept_code_contracts`, `check_architecture_conformance`.
- W4 `concept-decision-record-gate` — Record-Pflicht und
  Betroffenheitsmatrix (META-CONCEPT-CONSISTENCY P3).
- `check.py projection` gegen das Projektionsmanifest.
- Die gesamte Promotion-Closure aus FK-78 §78.11.

**Bleibt offen** (siehe `D-offene-entscheidungen.md`): ob die
Nightly-Laeufe von W2/W3 als Bestandsdetektor weiterlaufen. Sie leisten
etwas, das das neue Verfahren strukturell **nicht** leistet — sie finden
Widersprueche in Passagen, die gerade **niemand** anfasst. Das neue
Verfahren ist aenderungsgetrieben und sieht den ruhenden Bestand nie
wieder an.

## 8. Abgrenzung — was dieser Entwurf ausdruecklich nicht behandelt

- **Die Komponenten- und Schnittstellenschicht** zwischen Prosa und
  Formal-Layer (Befund C-4). Sie ist benannt, nicht konzipiert. Sie
  beruehrt FK-07, FK-17/FK-18, den Formal-Layer-Vertrag und die
  Registry-Landschaft gleichzeitig und traegt mindestens zwei echte
  Weichen. Sie waere der erste ernsthafte Anwendungsfall des hier
  entworfenen Verfahrens — nicht seine Vorbedingung.
- **Spawn-Mechanik, Session-Wiederaufnahme, Settings-Materialisierung.**
  Bleibt FK-76.
- **Guard-Definition und -Enforcement** der Inkubator-Pfadklassen.
  Bleibt FK-30; FK-78 §78.5 definiert die Regeln, dieser Entwurf
  aendert sie nicht.
- **Storylokale Designarbeit** (Exploration, Change-Frame, Feindesign).
  Bleibt FK-23/FK-25; DK-16 §9 grenzt das bereits ab.
- **Die Feindefinition des Einfuegeplans** ueber den Mindestbestand aus
  §3.2 hinaus. Sie gehoert in den ersten echten Lauf, nicht in einen
  unerprobten Entwurf.
