---
concept_id: DK-16
title: Konzeption und Konzeptinkubation
module: concept-incubation
domain: concept-incubation
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: conception-process
  - scope: concept-incubation-domain
  - scope: council-roles
defers_to:
  - target: FK-78
    scope: concept-incubation-technical
    reason: Blueprint-Topologie, Artefakt-Schemata, Lifecycle, Toolchain und Skill-Auslieferung werden technisch in FK-78 normiert
  - target: DK-10
    scope: story-lifecycle
    reason: Die Konzeption liegt VOR dem Story-Lifecycle; Story-Erstellung und -Abarbeitung bleiben bei story-lifecycle
  - target: DK-03
    scope: governance
    reason: Guard-Enforcement der Inkubator-Rollengrenzen ist Governance-Sache; DK-16 definiert nur die fachlichen Rollenregeln
  - target: DK-12
    scope: skills
    reason: Skill-Format, Bundles und Bindung liegen beim Skill-System; DK-16 definiert nur den fachlichen Skill-Inhalt der Konzeption
supersedes: []
superseded_by:
tags: [concept-incubation, conception, council, promotion, blueprint]
formal_scope: prose-only
---

# 16 — Konzeption und Konzeptinkubation

> **Normative Abgrenzung:** Dieses Dokument beschreibt die fachliche
> Gestalt der Konzeptionssaeule — Motivation, Rollenbild, Prozessidee und
> Anspruch. Die verbindlichen Ablaeufe, Zustaende, Artefakt-Schemata,
> Gates und Invarianten normieren ausschliesslich FK-78 und der formale
> Kontext `concept-incubation`; bei Abweichungen gelten diese. Kein Satz
> dieses Dokuments begruendet eine eigene pruefbare Regel.

## 1. Zweck

Der Softwareentwicklungsprozess beginnt vor der ersten Story: In der
**Konzeptionsphase** wird der Problemraum in den Loesungsraum ueberfuehrt.
Die AK3-Best-Practice dafuer ist ein Zusammenspiel aus menschlichen
Solution-Architects und KI-Agenten unterschiedlicher Hersteller, bei dem
die Agenten schwerpunktmaessig die Dokumentationsarbeit uebernehmen —
Konzepte als Markdown und andere textbasierte Artefakte.

DK-16 ist der fachliche Owner dieses Prozesses. Er beantwortet drei Fragen:

1. **Wie ist eine gute Konzeptwelt strukturiert?** (Blueprint: Domain-Layer,
   Fachkonzept-Layer — der in Wahrheit Fach- UND IT-Konzepte traegt —,
   Formal-Layer, Meta-Governance.)
2. **Wie bleiben die Ebenen konsistent**, statt auseinanderzudriften?
3. **Wie wird eine grosse Konzeptwelt weiterentwickelt**, ohne dass der
   normative Bestand zum Arbeitsordner verkommt und ohne dass bei der
   Uebernahme grosser Arbeitsstaende Inhalte verloren gehen oder subtile
   Fehler entstehen?

AK3 operationalisiert die Antworten **nicht durch die Backend-Applikation**,
sondern durch mitgelieferte Skills und eine deploybare, deterministische
Toolchain (FK-78). AK3 wendet das Verfahren auf seine eigene Konzeptwelt an;
die AK3-Konzeptwelt ist die Referenzimplementierung des Blueprints.

## 2. Kernproblem

Konzeptionsarbeit mit Agenten skaliert an zwei Stellen schlecht:

- **Der normative Layer als Arbeitsordner.** Wer Entwuerfe direkt in die
  autoritative Konzeptwelt schreibt, macht jeden Zwischenstand zur
  scheinbaren Wahrheit. Halbfertige Gedanken, konkurrierende Varianten und
  finale Normen werden ununterscheidbar.
- **Verlust und Verfaelschung bei der Uebernahme.** Wenn ein grosser
  Arbeitsstand (Beispiel: 1000 Seiten Zuwachs auf 2000 Seiten Bestand) in
  die normative Welt ueberfuehrt wird, sind die typischen Fehlerbilder:
  die Haelfte wird vergessen, Minderheitspositionen verschwinden
  unadjudiziert, Qualifikatoren werden beim Umformulieren amputiert, und
  ein einzelner synthetisierender Agent baut subtile Abweichungen ein, die
  niemand mehr gegen die Quellen prueft.

Beide Probleme sind Prozessprobleme, keine Werkzeugprobleme. Sie werden
durch einen definierten Arbeitsraum (Inkubator), ein Gremienverfahren mit
unabhaengigen Perspektiven und eine mechanisch geprüfte Uebernahme geloest.

## 3. Die drei Welten

Eine AK3-konforme Konzeptlandschaft trennt strikt:

| Welt | Ort | Charakter |
|---|---|---|
| **Normative Welt** | `concept/` (+ `guardrails/`) | Einzige Quelle fachlicher Wahrheit; jede Aussage hat genau einen Autoritaets-Owner |
| **Backlogs** | Backlog-Dokumente, offene-Punkte-Sektionen | Sichtbare Arbeitsvorraete mit Soll/Ist |
| **Werkstatt** | `concept-incubator/` | Entstehungsraum: Laeufe, Proposals, Synthesen, Promotionsakten; niemals Normquelle |

Die normative Welt ist ohne die Werkstatt vollstaendig lesbar. Jedes
Werkstatt-Artefakt hat manifestierten Zweck, Status und Verbleib. Offene
Werkstatt-Substanz muss von der normativen Welt oder einem Backlog aus
sichtbar sein — nichts haengt still in der Werkstatt.

## 4. Der Konzeptinkubator (fachliche Idee)

Konzeptionelle Arbeit oberhalb einer Bagatellgrenze laeuft als
**Inkubationslauf** in `concept-incubator/`:

1. **Rahmung**: Auftrag, Scope und Datenklassifikation werden mit dem
   Auftraggeber geklaert und eingefroren; der relevante normative Bestand
   wird inventarisiert (Baseline).
2. **Besetzung**: Der Orchestrator fragt den Auftraggeber, welche Modelle
   bzw. Agenten als Gremiums-Worker teilnehmen. Es gibt keine stille
   Standardbesetzung. (Referenzbesetzung aus der Praxis: vier Modelle
   unterschiedlicher Hersteller parallel, moderiert von einem fuenften.)
3. **Unabhaengige Proposals**: Jeder Gremiums-Worker analysiert die
   normative Welt selbst — Volllektuere seines zugeteilten Pakets, keine
   vorgekauten Zusammenfassungen — und schreibt ein eigenstaendiges
   Proposal mit expliziten Referenzen auf normative Anker. In der ersten
   Runde sieht kein Worker die Proposals der anderen.
4. **Konvergenzrunden**: Bei wesentlicher Differenz erhalten die Worker die
   versiegelten Proposals der jeweils anderen, lernen daraus und
   ueberarbeiten ihr eigenes. Der Orchestrator bewertet je Runde:
   konvergierend, divergierend, stabil-kontrovers oder strukturelles
   Spannungsfeld. Konvergenz wird nicht erzwungen — ein Spannungsfeld geht
   als Entscheidungsvorlage an den Auftraggeber, nicht in einen faulen
   Kompromiss.
5. **Synthese**: Der Orchestrator synthetisiert — erst nachdem alle
   Quell-Claims inventarisiert sind — und fuehrt Konsens, Dissens und
   offene Fragen getrennt aus. Die Synthese bleibt Werkstatt-Artefakt.
6. **Entscheidung**: Der Auftraggeber entscheidet offene Fragen; die
   Entscheidungen werden als Concept-Decision-Records festgehalten.
7. **Promotion**: Die Uebernahme in die normative Welt laeuft als
   mechanisch gepruefter Vorgang (§6).

## 5. Rollen

Die Konzeption kennt zwei exklusive Rollen — und ergaenzt damit die beiden
AK3-Work-Modes um einen dritten, klar abgegrenzten Modus:

- **Council-Orchestrator** (typischerweise der Main-Agent der
  User-Session): moderiert, steuert Runden, bewertet Konvergenz,
  synthetisiert und fuehrt die Promotion. Er schreibt **kein eigenes
  konkurrierendes Proposal** und bezieht in Moderationsphasen keine
  inhaltliche Partei-Position. Seine Facharbeit ist ausschliesslich
  Integrationsarbeit nach vollstaendiger Claim-Inventur — das
  unterscheidet ihn vom klassischen Orchestrator-Modus (der gar keine
  Facharbeit tut) und vom Worker-Modus (der Partei ist).
- **Gremiums-Worker**: gespawnte Agenten (fremde Harnesses, fremde
  Modelle, Sub-Agenten), die Proposals verfassen und dafuer selbst
  analysieren. Sie schreiben niemals in die normative Welt und niemals in
  fremde Arbeitsbereiche; ihre Grenzen werden technisch durchgesetzt, wo
  ein Guard-faehiger Harness vorhanden ist, und durch physische
  Arbeitsverzeichnis-Trennung, wo nicht.

Fremde Proposals sind fuer Worker Daten, keine Instruktionen. Der
Auftraggeber (PO) ist keine dritte Agentenrolle, sondern die
Entscheidungsinstanz, an die Spannungsfelder, Verwerfungen und offene
Fragen eskaliert werden.

## 6. Verlustfreie Promotion (fachlicher Anspruch)

Die Uebernahme eines Inkubationsergebnisses in die normative Welt gilt erst
dann als vollzogen, wenn mechanisch belegt ist:

- **Nichts ist verloren.** Jeder materielle Claim jeder Quelle — auch
  Minderheits- und Zwischenpositionen, die es nicht in die Synthese
  geschafft haben — ist inventarisiert und hat genau eine begruendete
  Disposition (uebernommen, verworfen, offen, vertagt mit sichtbarem
  Anker).
- **Nichts ist verfaelscht.** Die Uebernahme erfolgt atomisiert:
  qualifikatorentreue Einzelaussagen werden auf ihre Autoritaetsziele
  gemappt; semantische Aequivalenz wird durch einen unabhaengigen Reviewer
  bestaetigt, nicht vom Uebernehmenden selbst attestiert.
- **Nichts ist eingeschmuggelt.** Jede Aenderung im normativen Diff ist
  auf ein Atom oder eine Entscheidung rueckfuehrbar; Aenderungen ohne
  Herkunft blockieren.
- **Der Bestand hat sich nicht unbemerkt bewegt.** Die Baseline ist
  digest-gebunden; Parallel-Drift fuehrt zu Recheck, nicht zu stiller
  Uebernahme.

Ein Lauf kann administrativ geschlossen sein, waehrend einzelne fachliche
Scopes blockiert bleiben; Blockaden sind sichtbar und haben einen Owner.
Die technische Mechanik (Register, Digests, Receipts, Checks, Zustaende)
normiert FK-78.

## 7. Proportionalitaet

Nicht jede Aenderung braucht das volle Gremium. Es gibt drei
Prozessprofile — direkte governete Aenderung (kleiner, eindeutiger Scope;
Decision-Record- und Gate-Pflicht, kein Gremium), leichte Inkubation
(echte Unsicherheit, begrenzter Scope, ein bis zwei Worker) und volle
atomare Inkubation (grosse Migrationen, Dokumentfamilien-Umbauten,
Ownership-Verschiebungen, Vollstaendigkeitsansprueche). Die Profilwahl ist
deklariert und kriteriengebunden, kein stilles Ermessen. Bagatellen ohne
normativen Gehalt sind inkubator- und record-frei, bleiben aber durch die
deterministischen Konzept-Gates geprueft.

## 8. Konsistenzhaltung der Ebenen

Fuer die Konzeptwelt gelten die Konsistenzprinzipien der
Konzept-Governance (Single-Assertion, Authority-Bindung, Blast-Radius-
Pflicht, Widersprueche als Formalisierungssignal, Referenz-Integritaet —
META-CONCEPT-CONSISTENCY) sowie der Assertion-/Projection-Vertrag
(META-ASSERTION-AUTHORITY): Eine angenommene Entscheidung setzt das Ziel;
ausfuehrbar ist ein Scope erst mit nachweislich aequivalenter Projektion;
Widerspruch oder Fehlen blockiert den Scope, statt dass eine Ebene still
"gewinnt". Beide Vertraege gehoeren zum Blueprint-Export: Zielprojekte
erhalten sie als Teil der materialisierten Meta-Governance.

## 9. Abgrenzung

- **Kein Ersatz fuer storylokale Designarbeit.** Exploration, Change-Frame
  und Feindesign innerhalb einer Story bleiben beim BC
  exploration-and-design. DK-16 besitzt die corpus-weite, vor-storyliche
  Evolution der normativen Konzeptwelt.
- **Kein Backend-Feature.** Der Inkubator laeuft ueber Skills, Dateisystem
  und deterministische Checks; er hat in v1 keine Persistenz im
  State-Backend, keine Control-Plane-API und keine Telemetrie-Pflichten.
- **Kein Story-Traeger.** Ergebnisse der Konzeption speisen die
  Story-Ableitung (DK-10), ersetzen sie aber nicht.
