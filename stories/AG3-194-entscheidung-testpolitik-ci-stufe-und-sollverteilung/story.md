# AG3-194 — Entscheidungs-Story: CI-Stufe der Realitaetsnachweise und Sollverteilung der Pyramide

- **Typ:** concept (Entscheidungs-Story)
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-183, AG3-196
- **Quell-Konzept:** `PROJECT_STRUCTURE.md` §tests, `CLAUDE.md` §Tests,
  `guardrails/testing-guardrails.md`
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-10 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

> **Diese Story entscheidet nichts.** Sie legt zwei Fragen entscheidungsreif
> vor und haelt das Ergebnis normativ fest. Das Agentenmandat aus `AGENTS.md`
> untersagt ausdruecklich, eine fehlende Grundentscheidung durch eine gut
> formulierte Detailaussage zu ersetzen.

## Kontext

### Der Konflikt — belegt, mit Locator

Am 2026-08-02 hat der PO die Grundregel **„REALITAETSNACHWEIS AN
FREMDSYSTEM-GRENZEN"** in `CLAUDE.md` verankert (Commit `3b53989a`). Sie sagt:

> „Der Live-Lauf des Checkpoints gegen das echte Gegenueber ist
> **Abnahmekriterium**, nicht Opt-in. Ohne ihn ist die Story nicht fertig."

Im selben Dokument steht unter „Testebenen" weiterhin:

> „`tests/e2e/` nur opt-in, nie Standard-CI"

Und `PROJECT_STRUCTURE.md:307` (Regel 4) sagt:

> „**E2E-Tests sind IMMER opt-in.** Marker: `@pytest.mark.e2e`. Nie in
> Standard-CI. Brauchen echte Credentials."

Dazu `PROJECT_STRUCTURE.md:298`: E2E laeuft „Manuell/Nightly".

**Der heutige `Jenkinsfile` faehrt konsequenterweise keine E2E-Stage.** Die
Stages sind: Ruff, Mypy, Unit Tests + Coverage, Postgres Contract + Integration,
vier Konzept-Gates, Contract Checks, LOC, SonarQube, Quality Gate.

Die beiden Aussagen sind nicht durch Auslegung vereinbar. Entweder ist der
Live-Lauf blockierendes Abnahmekriterium in einem Pflichtlauf, oder E2E bleibt
opt-in. Der Schnitt vom 2026-08-02 hat schlicht das eine gefordert, ohne das
andere zu benennen.

### Warum die Frage nicht nebenbei fallen darf

Beide Seiten haben ein reales Kostenprofil:

- **Blockierend in der CI**: jede Aenderung braucht laufende Fremdsysteme
  (Weaviate, Postgres, Harness, GitHub, Jenkins, Sonar). Faellt eines aus, steht
  die Entwicklung. Der Anlassfall vom 2026-08-02 zeigt aber, dass genau diese
  Laeufe die Fehler finden, die keine Testsuite finden kann.
- **Opt-in/Nightly**: die Entwicklung bleibt schnell, und der Nachweis wird
  wieder das, was er am 2026-08-02 war — nicht gefahren. Sechs VektorDB-Storys
  sind abgenommen worden, ohne dass der Installer je gegen ein laufendes
  Weaviate lief.

Ein Mittelweg ist denkbar (Pflichtlauf je Fremdsystem-Vertrag statt fuer alle;
Pflicht beim Story-Abschluss statt bei jedem Commit; Pflicht mit benannter,
sichtbarer Luecke bei Dienstausfall) — aber welcher es ist, ist eine
PO-Entscheidung.

### Zweiter Gegenstand: die Sollverteilung

Der Schnitt vom 2026-08-02 forderte „eine benannte Sollverteilung der Pyramide
— PO-Entscheidung, kein erfundener Wert". Diese Entscheidung ist nie eingeholt
worden und hatte danach keinen Owner. Gemessener Ist-Stand am 2026-08-02:

| Ebene | Dateien | Testfunktionen |
|---|---:|---:|
| unit | 599 | 4457 |
| integration | 109 | 696 |
| contract | 97 | 595 |
| **e2e** | **3** | **5** |

Ohne Zielbild ist „zu wenig E2E" eine Meinung.

## Scope

### In Scope

- Die beiden Fragen entscheidungsreif aufbereiten: Kontext, Konsequenzen je
  Richtung, ehrliche Kosten, Empfehlung — als **offener Loesungsraum**, nicht
  als Multiple-Choice-Verengung.
- Das Einholen der PO-Entscheidung.
- Das Festhalten des Ergebnisses als Decision Record mit Betroffenheitsmatrix.
- Der normative Nachzug der beruehrten Dokumente **genau so weit**, wie die
  Entscheidung reicht.

### Out of Scope

- **Kein Bau von Tests, Gates oder CI-Stages.** Das ist AG3-183 (Matrix und
  E2E-Spitzen), AG3-195 (Gate-Ehrlichkeit) und AG3-196 (Fixtures/Messung).
- Keine Vorwegnahme des Ergebnisses in Detailtext.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/_meta/decisions/2026-XX-XX-testpolitik-ci-stufe.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `CLAUDE.md` §Tests/Testebenen | geaendert | nur falls die Entscheidung es verlangt — PO-Grundregel, kein Agenten-Alleingang |
| `PROJECT_STRUCTURE.md` §tests Regel 4 und die Ebenen-Tabelle (`:298`, `:307`) | geaendert | dito |
| `guardrails/testing-guardrails.md` | geaendert | dito |
| `Jenkinsfile` | unveraendert | die Umsetzung gehoert nach AG3-183 |

## Akzeptanzkriterien

1. **Die Vorlage benennt den Widerspruch woertlich**, mit beiden Locatoren
   (`CLAUDE.md` §Tests „nur opt-in, nie Standard-CI" gegen `CLAUDE.md`
   „REALITAETSNACHWEIS …"; `PROJECT_STRUCTURE.md:298` und `:307`) und mit dem
   Befund, dass der heutige `Jenkinsfile` keine E2E-Stage faehrt.
2. **Beide Richtungen sind mit ehrlichen Kosten dargestellt.** Keine der beiden
   ist als offensichtlich richtig dargestellt; wo eine Empfehlung ausgesprochen
   wird, ist sie als solche markiert und begruendet.
3. **Der Loesungsraum ist offen formuliert.** Genannte Varianten sind Beispiele
   im Raum, keine Auswahlliste. Ein Mittelweg ist ausdruecklich moeglich.
4. **Die Sollverteilung ist als zweite Frage getrennt vorgelegt**, mit dem
   gemessenen Ist-Stand als Ausgangslage. Es wird **kein** Zielwert erfunden.
5. **Die PO-Entscheidung liegt vor** und ist mit Datum und Urheber im Decision
   Record festgehalten. Eine Entscheidung, die der Umsetzer selbst getroffen
   hat, erfuellt dieses Kriterium nicht.
6. **Der normative Nachzug reicht genau so weit wie die Entscheidung.** Jede
   geaenderte normative Aussage ist in der Betroffenheitsmatrix aufgefuehrt und
   auf die Entscheidung zurueckgefuehrt. Kein Satz aendert sich „nebenbei".
7. **Alle deterministischen Konzept-Gates gruen**; `check_concept_decision_record.py`
   bestaetigt Record und Matrix.

## Definition of Done

- AC 1–7 erfuellt.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `CLAUDE.md` §Tests („Testebenen", „REALITAETSNACHWEIS AN
  FREMDSYSTEM-GRENZEN")
- `PROJECT_STRUCTURE.md` §tests, Ebenen-Tabelle (`:298`) und Regel 4 (`:307`)
- `guardrails/testing-guardrails.md`
- `concept/_meta/konzept-konsistenz-governance.md` §4 (Severity-Zuordnung)

## Guardrail-Referenzen

- `AGENTS.md` (Agentenmandat, PO-Ratifikation 2026-08-02) — „eine fehlende
  Grundentscheidung wird nicht durch eine gut formulierte Detailaussage
  ersetzt". Diese Story existiert genau deshalb.
- `CLAUDE.md` „Konzepttreue ist Pflicht" — bei Konzeptkonflikt hart stoppen und
  den Konflikt benennen, keine implizite Abweichung implementieren.
- `stories/README.md` §5 — Konzept-/Architekturkonflikt: anhalten, melden,
  Entscheidung abwarten.
