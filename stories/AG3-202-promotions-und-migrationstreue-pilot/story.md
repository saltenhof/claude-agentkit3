# AG3-202 — Erster vollstaendiger Promotions- und Migrationstreue-Pilot

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-201"]`; entblockt AG3-186
- **Quell-Konzept:** DK-16 §6, FK-78 §78.10, §78.11
- **Herkunft:** Ausgezogen aus AG3-185 am 2026-08-02 nach unabhaengigem
  Codex-Review (Auflage ERROR-15).

## Kontext

### Befund — belegt, mit Locator

`C-befundbericht.md` C-2 korrigiert die urspruengliche Annahme, die
Migrationstreue-Pruefung fehle. Sie fehlt nicht:

| Ebene | Fundstelle |
|---|---|
| fachlicher Anspruch | DK-16 §6, vier Ansprueche: nichts verloren, nichts verfaelscht, nichts eingeschmuggelt, Bestand nicht unbemerkt bewegt |
| technische Norm | FK-78 §78.10 (Projection-Receipts, Diff-Hunk-Reverse-Trace), §78.11 (Promotion-Closure Regeln 1–3) |
| Implementierung | `promotion_check.py`: `_check_atom_closure`, `_check_receipt_independence`, `_check_reverse_trace`, `_check_targets` |

**Und der ehrliche Zusatzbefund:**

> „Die Mechanik ist normiert und implementiert, aber im AK3-eigenen Korpus
> **noch nie durchlaufen**. Der Gruendungslauf
> `2026-07-19-conception-support-b4a7d375` traegt einen
> ‚Bootstrap-Sonderstatus' mit sichtbaren Blockern; das Werkstatt-Manifest
> weist keinen abgeschlossenen Promotionslauf nach den eigenen Regeln aus. Eine
> normierte, implementierte und nie gefahrene Mechanik ist kein Beweis fuer
> Praxistauglichkeit."

Das ist dieselbe Klasse Befund wie die PO-Grundregel „REALITAETSNACHWEIS AN
FREMDSYSTEM-GRENZEN": gruene Unit-Tests belegen den **Mechanismus**, nicht
seine Uebereinstimmung mit der Wirklichkeit.

### Warum der Pilot am Ende der Kette steht

Die PO-Empfehlung aus `D-offene-entscheidungen.md` E8 bindet die volle
Normierung an ein **Ereignis** statt an ein Datum: sie tritt in Kraft, „sobald
der erste Lauf des neuen Verfahrens vollstaendig durchgelaufen ist,
einschliesslich Migrationstreue-Pruefung. Damit ist die Norm an einem echten
Lauf gemessen, bevor sie andere bindet."

Diese Story ist genau dieses Ereignis.

## Scope

### In Scope

- Ein vollstaendiger Lauf des in AG3-185 normierten und in AG3-201
  implementierten Verfahrens auf einem **echten** Aenderungssatz dieses Korpus.
- Die Migrationstreue-Pruefung als Teil dieses Laufs.
- Die Feststellung, dass die Norm damit in Kraft tritt (E8), oder die benannten
  Befunde, die dem entgegenstehen.

### Out of Scope

- **Keine Normaenderung.** Ergibt der Pilot, dass die Norm nicht traegt, ist
  das ein Befund fuer AG3-185, kein Freibrief, sie hier anzupassen.
- **Kein Mechanikbau** — AG3-201.
- Die Komponenten-/Schnittstellenschicht als erster fachlicher Anwendungsfall —
  **AG3-186**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept-incubator/<space>/…` (je nach E1-Entscheidung) | neu | der Pilotlauf mit seinen Artefakten |
| `concept-incubator/INDEX.md` | geaendert | Werkstatt-Manifest weist den abgeschlossenen Promotionslauf aus |
| `AGENTS.md` | geaendert | Interimspflicht wird durch die in Kraft getretene Norm abgeloest (E8) |
| `concept/_meta/decisions/2026-XX-XX-verfahren-in-kraft.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Der Lauf ist vollstaendig durchlaufen**, alle Stufen, auf einem echten
   Aenderungssatz dieses Korpus. Ein konstruiertes Spielzeug-Delta erfuellt das
   nicht: der Aenderungssatz ist einer, der ohnehin gebraucht wird.
2. **Die Migrationstreue-Pruefung ist Teil des Laufs und hat ein Ergebnis** —
   alle vier Ansprueche aus DK-16 §6 einzeln: nichts verloren, nichts
   verfaelscht, nichts eingeschmuggelt, Bestand nicht unbemerkt bewegt.
3. **Die Unabhaengigkeitsregel ist eingehalten und belegt:**
   `reviewer_principal_id != writer_principal_id` **und** verschiedene
   Sessions (FK-78 §78.10), plus der in AG3-185/E6 beschlossene Grad
   (Modellhaus). Der Beleg nennt beide Principals.
4. **Der Lauf hat mindestens einen echten Befund erzeugt oder das Gegenteil ist
   begruendet.** Ein erster Lauf eines neuen Verfahrens, der nichts findet, ist
   ein Anlass zur Nachfrage, nicht zur Zufriedenheit — die Feststellung ist zu
   **begruenden**, nicht zu behaupten.
5. **Was der Pilot ueber die Norm gelernt hat, ist festgehalten** — auch die
   Irrwege. Der Blueprint ist AK3 an dieser Stelle methodisch voraus (C-12): er
   protokolliert, welcher reale Lauf welchen Befund erzeugt hat und was eine
   Ruecknahme gekostet hat. Ein Agent mit kurzem Horizont leitet eine
   zurueckgenommene Regel korrekt neu ab, wenn ihre Herleitung stehenbleibt.
6. **Die Norm tritt in Kraft, oder es ist benannt, was dem entgegensteht**
   (E8). `AGENTS.md` ist entsprechend nachgezogen: die Interimspflicht wird
   abgeloest, nicht doppelt gefuehrt.
7. **Alle deterministischen Konzept-Gates gruen**; Decision Record mit
   Betroffenheitsmatrix. Ein nicht gefahrener Sweep wird nicht als gruen
   berichtet.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommandos, Ausgaben, Receipts).
- Der Lauf ist im Werkstatt-Manifest als abgeschlossener Promotionslauf nach
  den eigenen Regeln ausgewiesen.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/domain-design/16-konzeption-und-konzeptinkubation.md` §6 —
  verlustfreie Promotion, vier Ansprueche
- `concept/technical-design/78_concept_incubation_process.md` §78.10, §78.11
- `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-2, C-12
- `concept-incubator/konzeptpruefung-verfahren/workspace/D-offene-entscheidungen.md`
  E6, E8

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — sinngemaess auf die
  eigene Mechanik angewandt: gruene Tests sind Voraussetzung, nie Nachweis.
- `CLAUDE.md` „Definition of Done: Codex-Review bis zum Abbruchkriterium".
- `CLAUDE.md` „ZERO DEBT RULE" — AC 5 und AC 6.
