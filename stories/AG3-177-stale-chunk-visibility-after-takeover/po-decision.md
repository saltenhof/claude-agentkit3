# PO-Entscheidung — AG3-177 Phase 1 (Ratifizierung)

- **Datum:** 2026-07-26
- **Entscheider:** PO (Stefan Altenhof)
- **Grundlage:** `design.md` (Phase-1-Entwurf mit gemessenen Kosten), Story-AC 1
  („Phase-1-Entwurf liegt vor und ist PO-ratifiziert … Kein Code vor der
  Ratifizierung")

## Entscheidung: **Variante (c)** — Rest vertraglich fassen, erkennbar machen, Aufraeumen zur Betriebspflicht

Der Restbefund wird **nicht** durch einen Retrieval-Filter geschlossen. Statt
dessen wird er ehrlich vertraglich gefasst, **beobachtbar** gemacht und sein
Aufraeumen als Betriebspflicht verankert.

## Begruendung

Der entscheidende Befund der Phase-1-Analyse: **der Aufraeumweg existiert bereits
und ist deterministisch** — ein Sync der betroffenen Quelle entfernt die
veralteten Zeilen zuverlaessig ueber die Generationsordnung. Es fehlt nicht das
Mittel, sondern der **Ausloeser**.

Die Kostenasymmetrie entscheidet: **Ausschliessen kostet +1 Lesezugriff bei
JEDER Suchanfrage** (gemessen; ein Cache hilft nicht, weil Suche und Sync
verschiedene Prozesse sind) **plus einen mit der Quellenzahl wachsenden Filter**
(3,7 KiB / 11,9 KiB / 49 KiB bei 75 / 242 / 1000 Quellen) **plus ein ungemessenes
Risiko fuer Trefferqualitaet und Antwortzeit der Vektorsuche**. **Erkennen kostet
nichts** — `list_sources` liest die betroffenen Zeilen und die Abschluss-Records
ohnehin.

Eine Dauersteuer auf dem meistgenutzten Pfad des Systems zu zahlen, um eine
**Vier-fach-Koinzidenz** abzudecken (haengender Sync **und** bewusste
Admin-Uebernahme **und** wiederauferstandener Altprozess **und** kein
nachfolgender Sync), ist wirtschaftlich nicht vertretbar — **solange der Rest
erkennbar ist.**

## Die tragende Bedingung

**Beobachtbarkeit ist nicht Beiwerk, sondern der Gegenstand der Lieferung.**
Ohne sie wird (c) zu „hoffen, dass es niemandem auffaellt" — genau das, was
FAIL-CLOSED und ZERO DEBT verbieten. Ein dokumentierter Rest, den niemand
bemerken kann, ist im Effekt ein verschwiegener Rest (SEVERITY-SEMANTIK).

Die Beobachtbarkeit ist gratis; deshalb traegt die Bedingung.

## Verbindliche Auflagen

1. **Erkennbarkeit als Kernlieferung.** Ein veralteter Rest muss im Betrieb
   auffindbar sein, nicht nur beschrieben. Ein Test beweist die Meldung am realen
   Produktionspfad.
2. **Ort der Meldung — entschieden:** in den `story_list_sources`-Envelope. D1
   fixierte eine **minimale** Shape („Mindestens …"); eine zusaetzliche Kennzahl
   ist damit eine vertragskonforme Erweiterung, kein Bruch. Begruendung: Der Zweck
   ist Erkennbarkeit **an der Stelle, an der ein Agent oder Operator hinsieht** —
   Telemetrie, die niemand liest, waere derselbe Fehlermodus wie ein
   undokumentierter Rest. FK-13 §13.4.1 ist entsprechend nachzuziehen.
3. **Betriebspflicht.** „Nach einer administrativen Uebernahme einen Sync der
   betroffenen Quelle fahren" wird als Betriebsschritt verankert (Runbook-Ebene).
   Der Operator hat die Uebernahme ohnehin bewusst ausgeloest; ein weiterer
   Schritt in demselben Ablauf ist zumutbar.
4. **FK-13 §13.9.9 wahr halten.** Der dort verankerte offene, nicht ratifizierte
   Rest wird durch den **ratifizierten Vertrag** ersetzt. Keine Grenze behaupten,
   die nicht gehalten wird; **keine Atomizitaet**. Begleitender Decision Record
   unter `concept/_meta/decisions/` (P3-Pflicht).
5. **Keine Regression der AG3-174-Zusicherungen:** kein Loeschen der Daten einer
   neueren Generation, keine Umkehrung der gemeldeten Freshness, Receipt-last,
   Legacy-Konvergenz — je durch die bestehenden Tests belegt.
6. **Der Post-Completion-Sweep bleibt.** Er deckt den haeufigen Fall; (c) ergaenzt
   ihn, ersetzt ihn nicht.

## Was ausdruecklich offen gehalten wird

**Variante (b) bleibt als spaeter entscheidbarer Schritt verfuegbar**, in der in
`design.md` gemessenen **billigsten** Form (ein abgeleiteter Autoritaetsschluessel
`source_file|generation` → **eine** Mengenbedingung statt 2N Bedingungen, halbe
Wire-Groesse). Die Messungen bleiben in `design.md` erhalten, damit eine spaetere
Entscheidung sie nicht neu erheben muss.

**Ausloesende Bedingung fuer eine Neubewertung:** wenn „die Suche darf nie eine
ueberholte Fassung zeigen" zu einer harten Zusage wird (z. B. durch eine
Zielprojekt-Anforderung), oder wenn die gemeldete Kennzahl im Betrieb zeigt, dass
der Fall haeufiger auftritt als die Vier-fach-Koinzidenz erwarten laesst.

## Nicht gemessen, bewusst nicht nachgeholt

Der Einfluss eines Retrieval-Filters auf Trefferqualitaet und Antwortzeit der
Vektorsuche bleibt **ungemessen**. Die Messung waere moeglich (Weaviate laeuft
lokal auf dem FK-13-Port mit `text2vec-transformers`), ist fuer (c) aber ohne
Entscheidungsrelevanz. Sie ist **nachzuholen, falls (b) reaktiviert wird** — als
Vorbedingung jener Entscheidung, nicht dieser.
