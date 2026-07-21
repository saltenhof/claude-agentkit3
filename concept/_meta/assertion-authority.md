---
concept_id: META-ASSERTION-AUTHORITY
title: Assertion-Authority- und Projektions-Vertrag
module: meta
cross_cutting: true
status: active
doc_kind: policy
authority_over:
  - scope: assertion-authority
  - scope: projection-status-semantics
defers_to:
  - target: META-CONCEPT-CONSISTENCY
    scope: concept-consistency-governance
    reason: Single-Assertion, Authority-Bindung, Blast-Radius und Referenz-Integritaet bleiben dort normiert; dieser Vertrag ergaenzt die Status- und Vorrangsemantik
supersedes: []
superseded_by:
tags: [meta, governance, authority, assertion, projection, precedence]
formal_scope: prose-only
---

# Assertion-Authority- und Projektions-Vertrag

## 1. Zweck und Anlass

Der Konzeptkorpus traegt dieselbe Semantik auf mehreren Ebenen: als
angenommene Entscheidung (Decision Record), als Prosa (DK/FK), als formale
Projektion (`formal-spec/`) und als Registry-Kante. Ohne definierte
Statussemantik entstehen zwei symmetrische Fehler: Eine frisch entschiedene
Aenderung gilt als "fertig", obwohl die formale Projektion noch Altsemantik
traegt — oder eine veraltete formale Projektion "ueberstimmt" still die
frisch entschiedene Prosa, weil pauschal "formal gewinnt" gilt.

Dieser Vertrag schliesst beide Luecken. Er ist Teil des Blueprint-Exports
(FK-78): Zielprojekte erhalten ihn als materialisierte Meta-Governance.

## 2. Kernobjekte

### 2.1 AssertionScope

Jede maschinenadressierbare normative Aussage gehoert zu genau einem
Scope mit stabilem `scope_id` (Grammatik: projektkonfiguriert, Default
`^[a-z0-9]+([.-][a-z0-9]+)*$`; deterministische Normalisierung: lowercase,
Kollaps von `[._-]`-Wiederholungen). Zwei Owner duerfen denselben Scope
nicht aktiv besitzen (META-CONCEPT-CONSISTENCY P2). Eine gewollte
Komposition braucht disjunkte Teil-Scopes und einen benannten Composer;
eine blosse `defers_to`-Kante heilt keine Doppel-Ownership.

### 2.2 Projektion und Receipt

Eine **Projektion** ist die Abbildung einer Assertion in eine andere
Ebene (Prosa → Formal, Decision → Prosa, Prosa → Registry-Kante). Ein
**Projection-Receipt** belegt die semantische Aequivalenz einer konkreten
Projektion: Quelle und Ziel je mit SHA-256-Digest, Reviewer-Principal,
Verdict, Zeitpunkt. Receipts werden im Promotion-Manifest des erzeugenden
Inkubationslaufs gefuehrt (FK-78).

## 3. Statussemantik (kanonisch)

Vier getrennte Achsen mit jeweils genau einem Owner:

| Achse | Werte | Owner |
|---|---|---|
| Decision-Lifecycle (je Decision Record) | `proposed \| accepted \| rejected \| superseded` | Decision Record selbst |
| `promotion_disposition` (je Atom/Scope innerhalb eines Inkubationslaufs) | `promoted \| rejected \| deferred` | Promotion-Manifest des Laufs (FK-78) |
| `assertion_status` (je Scope, korpusweit) | `draft \| active \| blocked_projection \| deprecated \| superseded` | dieser Vertrag |
| `equivalence_status` (je Projektion) | `unreviewed \| equivalent \| disagrees \| stale \| blocked_missing_target` | dieser Vertrag |

Bedeutungen der `assertion_status`-Werte:

- `draft`: reviewbarer Kandidat; nicht implementations- oder codegen-treibend.
- `active`: einzige ausfuehrbare Assertion im Scope; alle Pflichtprojektionen
  sind nachweislich `equivalent`.
- `blocked_projection`: das Ziel ist entschieden, aber mindestens eine
  Pflichtprojektion fehlt, ist `stale` oder `disagrees`. Implementierung und
  Codegen fuer diesen Scope stoppen; weder alte noch erfundene Semantik darf
  verwendet werden. `blocked_projection` ist ein ehrlicher Stopp, keine
  schwaechere Form von `active`.
- `deprecated`: lesbar fuer bestehende Consumer; keine neuen Consumer;
  Removal-Bedingung ist Pflicht.
- `superseded`: historisch; nicht als Current referenzierbar.

## 4. Ableitungsregeln (eindeutig)

0. **Lifecycle zuerst.** Jeder Scope traegt einen Lifecycle-Stand
   (`current | draft | deprecated | superseded`), der ausschliesslich aus
   Decision-/Supersession-Lage bestimmt wird. `draft`, `deprecated` und
   `superseded` werden von der Statusableitung NIEMALS ueberschrieben —
   die Ableitung nach Regel 2 und 5 gilt nur fuer die aktuelle
   akzeptierte Assertion (`lifecycle = current`).
1. Ein `accepted` Decision Record setzt die **Sollwahrheit** seines Scopes.
   Es bedeutet NICHT, dass jede Projektion bereits `active` ist.
2. `promotion_disposition = promoted` fuer einen Scope ⇒
   `assertion_status = active` genau dann, wenn alle Pflichtprojektionen des
   Scopes `equivalent` sind und keine Blocker offen sind; andernfalls
   `blocked_projection` mit sichtbarem Blocker-Eintrag (Owner + Anker).
3. `promotion_disposition = deferred` ⇒ der Scope behaelt seinen bisherigen
   `assertion_status`; der vertagte Gehalt braucht Owner, Trigger und einen
   von der normativen Welt oder einem Backlog aus sichtbaren Anker.
4. `promotion_disposition = rejected` aendert den `assertion_status` nicht;
   die verworfene Alternative bleibt im Lauf dokumentiert.
5. **Disagreement blocks.** Widerspricht eine Projektion ihrer Quelle
   (`disagrees`), ist sie `stale` oder fehlt sie
   (`blocked_missing_target`), wird der Scope `blocked_projection`. Es gibt
   keine pauschale Vorrangregel "formal gewinnt" und keine stille
   Prosa-Dominanz. Der Konflikt wird adjudiziert (Decision Record oder
   Korrektur der Projektion), nie wegpriorisiert.
6. Implementierung, Tests und Prototypen sind Conformance-Objekte und
   Gegenbelege, keine Normquelle. Ein gruener Test kann stale Semantik
   konservieren.
7. Engere Scopes gewinnen nur bei disjunkter, expliziter Scope-Hierarchie.
   Textnaehe, Dateidatum und Detailgrad erzeugen keinen Vorrang.

## 4a. Fuehrendes Artefakt

Der korpusweite Traeger von `assertion_status` und `equivalence_status` ist
`concept/_meta/projection-manifest.json`: je Scope die Assertion-Quelle
(Pfad + Digest), die vollstaendige Pflichtprojektionsmenge (Art, Ziel,
Ziel-Digest, Receipt-Referenz), der je Projektion deterministisch
abgeleitete `equivalence_status` (Receipt fehlt → `unreviewed`;
Digest-Abweichung → `stale`; Ziel fehlt → `blocked_missing_target`) und der
daraus abgeleitete `assertion_status` (alle Pflichtprojektionen
`equivalent` und keine offenen Blocker → `active`, sonst
`blocked_projection`). Die Ableitung ist ausschliesslich dort maschinell
verankert; dieses Dokument traegt ihre Semantik. Das Format normiert FK-78;
die Toolchain prueft das Manifest gegen den Ist-Korpus.

## 5. Aktivierung und atomare Closure

Eine Projektion darf nur `equivalent` und ihr Scope nur `active` werden,
wenn im selben atomaren Aenderungssatz:

1. alle deklarierten Pflichtmengen (`required_decision_ids`,
   `required_concept_ids`, `required_formal_ids`,
   `required_registry_edges`, `required_support_paths`,
   `required_test_oracles`) physisch vorhanden und aufloesbar sind;
2. Quell- und Ziel-Digests den Receipts entsprechen;
3. Prosa/Formal- und Supersession-Reziprozitaet geschlossen ist;
4. der Receipt-Reviewer vom Verfasser der Zielpassage unabhaengig ist
   (anderer Principal, andere Session; `disagrees` eskaliert an den
   Auftraggeber und darf vom Verfasser nicht ueberschrieben werden);
5. die deterministischen Konzept-Gates fehlerfrei gelaufen sind.

Teilaktivierung innerhalb eines Scopes ist verboten. Unabhaengige Scopes
derselben Entscheidung duerfen nur getrennt aktiviert werden, wenn sie als
getrennte Assertions mit stabilen Scope-IDs deklariert sind.

## 6. Supersession und Referenzen

- Breaking Semantik erzeugt eine neue Assertion (neuer Scope-Stand), keine
  stille Mutation.
- `supersedes`/`superseded_by` sind reziprok; Historisches bleibt
  auffindbar, wird aber nie als Current konsumiert.
- Evidenz darf per Pfad/ID referenziert werden; normative Semantik steht
  immer restated im Korpus selbst (Werkstatt ist keine Nebenautoritaet).

## 7. Merksatz

**Eine angenommene Entscheidung setzt das Ziel; ausfuehrbar ist nur eine
aktive, nachweislich aequivalente Projektion; jeder Widerspruch und jede
fehlende Projektion blockiert den Scope — sichtbar, mit Owner, ohne
stillen Gewinner.**
