---
concept_id: META-CONCEPT-CONSISTENCY
title: Konzept-Konsistenz-Governance — Prinzipien und Durchsetzung
module: meta
cross_cutting: true
status: active
doc_kind: policy
authority_over:
  - scope: concept-consistency-governance
defers_to: []
supersedes: []
superseded_by:
tags: [meta, governance, consistency, concept-quality, ci, decision-process]
formal_scope: prose-only
---

# Konzept-Konsistenz-Governance — Prinzipien und Durchsetzung

## 1. Zweck und Anlass

Der Konzeptkorpus hat wiederholt interne Widersprueche entwickelt.
Juengster Fall: FK-56 §56.7a normierte „kein stiller Rueckfall, Mensch
muss explizit neu binden", waehrend FK-10 §10.5/§10.6, FK-02 §2.7,
FK-71 §71.3 und FK-15 gleichzeitig automatische Lock-Freigabe via
PID/TTL/Lease normierten („kein manuelles Loeschen noetig"). Vier
Dokumente hatten denselben Mechanismus nebenbei mitnormiert; als die
Entscheidung sich aenderte, wurde nur das Heimat-Dokument aktualisiert.

Zwei bestehende Massnahmen greifen dagegen nur teilweise:

- Der **BC-Schnitt** lokalisiert Domaenen-Aussagen, verhindert aber
  nicht, dass querschnittliche Mechanismen (Locks, Ownership,
  Lifecycle) von mehreren Dokumenten aus mehreren Blickwinkeln
  **mehrfach behauptet** werden. Mehrfach behauptete Fakten driften.
- Der **Formal-Layer** prueft, was formalisiert ist. Die genannten
  Widersprueche lebten in Prosa (Tabellen-Halbsaetze, Nebenbemerkungen)
  und waren fuer Linter unsichtbar.

Der Geburtsort von Konzept-Widerspruechen ist fast immer derselbe:
Eine Entscheidung aendert sich, das zustaendige Dokument wird
aktualisiert, und niemand weiss, wo die Aussage ueberall noch einmal
steht. Dieses Dokument normiert die Prinzipien und Werkzeuge, die
diesen Mechanismus (a) an der Entstehung hindern und (b) strukturell
detektierbar machen, ohne dass jemand wissen muss, wonach er sucht.

## 2. Geltungsbereich

Der gesamte Konzeptkorpus unter `concept/` (domain-design,
technical-design, formal-spec, guardrails-Referenzen) sowie der
Aenderungsprozess an normativen Aussagen. Massgeblich fuer
Zustaendigkeiten ist die Registry
(`concept/technical-design/_meta/domain-registry.yaml`) mit
`authority_over`-Scopes und `defers_to`-Kanten der Dokumente.

## 3. Grundprinzipien (normativ)

### P1 — Single-Assertion-Prinzip

Eine normative Aussage existiert **genau einmal** im Korpus: im
Dokument mit Authority ueber ihren Scope. Jedes andere Dokument darf
sie **referenzieren** (Dokument-ID + Abschnittsanker bzw. Formal-ID),
aber **nie paraphrasieren**. Paraphrasen sind Kopien, die eigenstaendig
altern — jede ist ein zukuenftiger Widerspruch.

Formulierungs-Test: Wenn ein Satz ausserhalb des Authority-Dokuments
geloescht werden koennte, ohne dass normative Information verloren
geht (weil die Quelle sie traegt), dann gehoert dort ein Verweis hin,
kein Satz.

### P2 — Authority-Bindung von Prosa

Die Frontmatter-Metadaten `authority_over`/`defers_to` binden nicht
nur die Dokumentstruktur, sondern den **Prosa-Inhalt**: Ein Dokument
darf keine normativen Aussagen ueber Scopes treffen, ueber die es
keine Authority hat und zu denen keine `defers_to`-Kante existiert.
„Nebenbei normieren" (eine Retention-Tabelle regelt en passant den
Lock-Lifecycle) ist ein Verstoss — unabhaengig davon, ob die Aussage
inhaltlich richtig ist.

### P3 — Blast-Radius-Pflicht bei normativen Aenderungen

Jede Aenderung an normativen Aussagen erfordert einen
**Impact-Sweep** ueber den Korpus (semantische Suche ueber den
Konzept-Index UND lexikalische Suche nach den Fachbegriffen des
geaenderten Scopes) und eine **Betroffenheitsmatrix** als
Pflicht-Artefakt: jede beruehrte Stelle klassifiziert als
`geaendert` / `referenziert-jetzt` / `nicht-betroffen` (mit
Begruendung). Die Matrix ist Teil eines **Concept-Decision-Records**
(Ablage: `concept/_meta/decisions/`, Benennung
`YYYY-MM-DD-<slug>.md`), das Entscheidung, Anlass, Alternativen und
die Matrix persistiert.

Referenzprozess (erprobt am Session-Ownership-Strang 2026-07):
Entwurf in `_temp/` als zusammenhaengende Prosa mit
Verankerungs-Matrix → adversariale Review-Schleifen (Machbarkeit
gegen Codebase UND konzeptionelle Edge-Cases, bis Freigabe) →
Ueberfuehrung in die normativen Dokumente → Re-Review des normativen
Diffs. Fuer kleine Aenderungen darf der Prozess proportional
verschlankt werden; die Matrix-Pflicht entfaellt nie.

### P4 — Widersprueche sind Formalisierungs-Signale

Jeder gefundene Prosa-Widerspruch erzeugt die Pruefpflicht: „Gehoert
dieser Scope in den Formal-Layer?" Scopes, die sich als
widerspruchsanfaellig erweisen (typisch: Lifecycle-, Ownership-,
Zustandsuebergangs-Regeln), werden als formale Objekte modelliert
(State-Machines, Invarianten, Command-Sets); die Prosa referenziert
danach Formal-IDs statt Regeln auszuformulieren. Beispiel: Waere der
Lock-Lifecycle als State-Machine modelliert gewesen
(`active → ended_by {closure, exit, reset, split, transfer}`), waere
„TTL-Ablauf" ein nicht existierender Uebergang gewesen — maschinell
pruefbar statt Prosa-Drift.

### P5 — Referenz-Integritaet

Alle Querverweise im Korpus (FK-/DK-/META-Dokument-IDs,
§-Abschnittsanker, formal.*-IDs, Dateipfade) muessen aufloesen. Tote
Anker sind keine Kosmetik, sondern das Fruehsymptom
auseinandergelaufener Dokumente (Beispiel: FK-02 verwies auf
<!-- REF-INTEGRITY:IGNORE-BEGIN deliberate historical negative anchor example -->
„FK-71 §67.x" — die Abschnitte heissen seit der Umnummerierung
§71.x). Befund-Schwere: ERROR.
<!-- REF-INTEGRITY:IGNORE-END -->

## 4. Severity-Zuordnung

Gemaess der projektweiten Severity-Semantik (PASS/WARNING/ERROR,
CLAUDE.md):

| Befund | Severity |
|---|---|
| Normative Aussage ausserhalb der eigenen Authority (P2) | ERROR |
| Paraphrase einer fremden normativen Aussage, semantisch (noch) deckungsgleich (P1) | WARNING — Umbau zu Referenz ist Pflicht, nicht Option |
| Semantischer Widerspruch zwischen Aussagen desselben Scopes | ERROR |
| Toter Anker / nicht aufloesende Referenz (P5) | ERROR |
| Normative Aenderung ohne Decision-Record/Betroffenheitsmatrix (P3) | ERROR (Review-Gate) |
| Widerspruchsanfaelliger Scope ohne Formalisierungs-Pruefung (P4) | WARNING |

WARNINGs unterliegen der Spiegelpflicht: aktiv an den Auftraggeber
melden, nicht liegen lassen (ZERO DEBT).

## 5. Durchsetzungswerkzeuge (Soll — Umsetzung ueber Stories)

Alle Werkzeuge folgen dem AK3-eigenen Muster: **LLM nur als
Bewertungsfunktion, Entscheidung deterministisch** (analog
Verify-Layer 2, FK-27). Kein Werkzeug entscheidet frei; jedes liefert
reproduzierbar referenzierte Befunde (Dokument, Anker, Aussagetext),
die eine deterministische Policy gegen eine gepflegte Baseline
auswertet.

### W1 — `concept-reference-integrity` (deterministisch, CI-Pflichtgate)

Prueft die Aufloesbarkeit aller Querverweise: Dokument-IDs gegen den
Bestand, §-Anker gegen die realen Ueberschriften des Zieldokuments,
formal.*-IDs gegen die kompilierte Spec-Landschaft, Dateipfade gegen
das Repo. Erweitert die bestehende Prose-Link-Pruefung von
`compile_formal_specs.py` um FK-Querverweise und §-Anker. Rein
statisch, kein LLM, blocking in CI (`scripts/ci/`-Muster).

Zusatzauftrag (Befund 2026-07-02): Der dokumentweite `defers_to`-Graph
des Bestands ist heute stark zyklisch (u. a. FK-63↔FK-70,
FK-02↔FK-71, lange transitive Schleifen ueber FK-20/27/29/54). Da
`defers_to`-Kanten scope-qualifiziert sind, sind Zyklen auf
Dokumentebene nicht per se Fehler — azyklisch sein muss die
Zustaendigkeit **pro Scope** (kein Scope darf im Kreis delegiert
werden). W1 muss diese Semantik festschreiben und pruefen:
Scope-Delegationsketten azyklisch (ERROR bei Verstoss),
Dokumentebenen-Zyklen zunaechst nur reporten (Baseline).

### W2 — `concept-authority-prose` (LLM-Bewertung + deterministische Policy)

Der Detektor fuer „ich weiss nicht, wonach ich suche": Geht
chunk-weise (H2-Ebene, wie der Konzept-Index) ueber den Korpus und
beantwortet pro Chunk zwei Fragen: *Enthaelt der Abschnitt normative
Aussagen?* *Ueber welche Scopes?* Deterministischer Abgleich gegen
die Registry: normative Aussage ueber Scope X in einem Dokument ohne
Authority ueber X und ohne defers_to-Kante → Befund (ERROR).
Erkennt damit die **unzustaendige Behauptung** — der Widerspruch
selbst muss nicht semantisch gefunden werden. Betrieb: nightly +
vor Konzept-Merges; Befund-Baseline mit begruendeten Eintraegen
(keine stillen Baselines).

### W3 — `concept-scope-consistency` (LLM-Sweep pro Scope)

Widerspruchssuche, kollabiert auf kleine Mengen: Pro
`authority_over`-Scope werden alle Aussagen-Chunks des Scopes
gesammelt (via Konzept-Index) und als geschlossenes Set auf
Widersprueche geprueft („lies diese ~20 Aussagen zu Lock-Lifecycle —
widersprechen sich welche?"). Setzt W2/P1 voraus, um klein zu
bleiben; ohne sie degeneriert die Pruefung zu O(n²) ueber den
Gesamtkorpus. Betrieb: nightly, Baseline wie W2.

### W4 — `concept-decision-record-gate` (Prozess-Gate)

Erzwingt P3: Ein Diff, der normative Konzeptdokumente aendert, muss
ein Concept-Decision-Record unter `concept/_meta/decisions/`
referenzieren (Commit-Konvention + Review-Checkliste; technisch
pruefbar: Konzeptdiff ohne gleichzeitigen decisions/-Eintrag oder
Record-Referenz in der Commit-Message → Befund). Reine
Tippfehler-/Format-Fixes sind ausgenommen (Abgrenzung: keine
Aenderung an normativen Saetzen).

## 6. Betriebsmodell

- **W1 ist Pflichtgate** in derselben CI-Stufe wie die bestehenden
  vier Konzept-Gates (`check_concept_frontmatter`,
  `check_concept_code_contracts`, `compile_formal_specs`,
  `check_architecture_conformance`). Die bestehenden Gates bleiben
  unveraendert bestehen; die neuen Werkzeuge ergaenzen sie.
- **W2/W3 laufen nightly** und zusaetzlich vor der Landung normativer
  Konzeptaenderungen. Neue Befunde sind ERROR, bis sie triagiert
  sind; Triage-Ergebnis ist entweder Fix oder begruendeter
  Baseline-Eintrag. Baselines ohne Begruendung sind unzulaessig.
- **W4 wirkt im Review** (Checkliste + deterministischer Check) und
  gilt ab Inkrafttreten dieses Dokuments auch manuell — unabhaengig
  vom Implementierungsstand des Checks.
- LLM-gestuetzte Werkzeuge (W2/W3) muessen ihre Prompts/Modelle
  versionieren und Befunde idempotent referenzieren, damit Baselines
  stabil bleiben.

## 7. Umsetzungsfahrplan (Story-Kandidaten)

Empfohlene Reihenfolge, jeweils als eigene Story ueber den regulaeren
Prozess:

<!-- REF-INTEGRITY:IGNORE-BEGIN deliberate historical negative anchor example -->
1. **W1** `concept-reference-integrity` — deterministisch, billig,
   sofortiger Nutzen; Anker-Klasse von Fehlern (FK-02 §67.x) stirbt
   aus. Keine Abhaengigkeiten.
<!-- REF-INTEGRITY:IGNORE-END -->
2. **W4** `concept-decision-record-gate` — Prozess + leichter Check;
   etabliert `concept/_meta/decisions/` und die Matrix-Pflicht.
   Keine technischen Abhaengigkeiten.
3. **W2** `concept-authority-prose` — braucht Zugriff auf
   Registry-Projektion + Chunking (vorhanden via Konzept-Index) und
   einen LLM-Aufrufpfad im CI-/Nightly-Kontext.
4. **W3** `concept-scope-consistency` — setzt W2-Infrastruktur
   voraus (Chunk-Klassifikation, Baseline-Mechanik).

Flankierend, ohne eigene Story: P1/P2 gelten ab Inkrafttreten fuer
alle neuen und geaenderten Konzeptpassagen; Bestandsverstoesse werden
nicht big-bang saniert, sondern (a) durch W2-Befunde sichtbar gemacht
und (b) beim naechsten fachlichen Anfassen der Stelle mitbereinigt.

## 8. Abgrenzung

- Dieses Dokument normiert die **Konsistenz-Governance des
  Konzeptkorpus**, nicht die fachlichen Inhalte der Konzepte selbst.
- Es ersetzt keine bestehenden Gates und keine Review-Pflichten aus
  CLAUDE.md/guardrails; es ergaenzt sie.
- Die Werkzeug-Spezifikationen (W1–W4) sind Soll-Beschreibungen auf
  Konzeptniveau; die exakten Schnittstellen, Baselines-Formate und
  Prompt-Vertraege werden in den jeweiligen Stories designt.
