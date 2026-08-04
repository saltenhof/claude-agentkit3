# AG3-215 — Der atomare Schreibvorgang hat keinen Eigentuemer

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-10 (Persistenz), betroffen sind alle Bounded Contexts
  mit atomaren Dateischreibvorgaengen
- **Herkunft:** Nebenbefund bei der Reparatur des VectorDB-Recovery-Journals am
  2026-08-04 (Commit `858ef1fe`). Der Umsetzer hat ihn mandatstreu **gemeldet
  statt eigenmaechtig behoben** — `backend/utils/io.py` war ausdruecklich
  ausgeschlossen, weil die Funktion breit genutzt wird.

## Befund — belegt, mit Realdaten-Nachweis

**Locator:** `src/agentkit/backend/utils/io.py:48`

```python
tmp = path.with_suffix(path.suffix + ".tmp")
```

`atomic_write_text` benutzt einen **festen** Temp-Namen, abgeleitet allein vom
Zielpfad. Zwei Schreiber auf dieselbe Zieldatei teilen sich damit dieselbe
Zwischendatei. Der Cleanup-Pfad im `except` entfernt sie unbedingt — also
gegebenenfalls die Zwischendatei eines **fremden** Schreibers.

Die Funktion verspricht Atomizitaet. Unter Nebenlaeufigkeit auf denselben
Zielpfad haelt sie das nicht: Der Schutz endet an der eigenen Prozess- bzw.
Thread-Grenze, und genau dort faengt das Problem an.

### Gemessen, nicht vermutet

Zwei Schreiber auf denselben Zielpfad, 200 Iterationen:

| Messgroesse | Wert |
|---|---|
| fehlerhafte Iterationen | 200 von 200 |
| Write-Fehler | 201 |
| **ungueltiger Zielinhalt** | **1** |

Die letzte Zeile ist die teure: Nicht nur schlagen Schreibvorgaenge fehl — in
einem Fall stand am Ende eine Zieldatei mit ungueltigem Inhalt da. Ein
fehlgeschlagener Schreibvorgang ist sichtbar; eine korrupte Zieldatei nicht.

### Erreichbare ungeschuetzte Aufrufer (nicht abschliessend)

- `src/agentkit/harness_client/projectedge/client.py:497` (`LocalEdgePublisher`)
- `src/agentkit/harness_client/projectedge/permission_projection.py:43`
- `src/agentkit/backend/state_backend/store/freeze_repository.py:451`

Insgesamt 35 produktive Aufrufer (34 `atomic_write_text`, 1
`atomic_write_yaml`). Welche davon real nebenlaeufig auf denselben Zielpfad
schreiben koennen, ist Teil dieser Story — die drei oben sind die bereits
belegten.

## Warum das eine eigene Story ist

`atomic_write_text` ist eine der meistgenutzten Hilfsfunktionen des Repos. Eine
Aenderung dort beruehrt jeden Bounded Context, der Dateien schreibt. Sie
nebenbei in einer VectorDB-Reparatur mitzunehmen waere genau die Art
Mandatsueberschreitung, die `CLAUDE.md` §Sub-Agent Rules beschreibt — und die
am 2026-08-03 schon einmal 76 Dateien gekostet hat.

## Scope

### In Scope

- Pro Schreiber eine **exklusiv erzeugte** Temp-Datei im Zielverzeichnis.
- Cleanup entfernt ausschliesslich die **eigene** Temp-Datei.
- Temp-Namensvertrag und die Erkennung einer Temp-Datei liegen **gemeinsam beim
  I/O-Owner**. Das VectorDB-Journal kennt das Schema heute lokal (noetige
  Sofortmassnahme aus `858ef1fe`); mit dieser Story wird daraus die eine
  Wahrheit, und das Journal bezieht sie von dort.
- Inventur der 35 Aufrufer: welche koennen real nebenlaeufig auf denselben
  Zielpfad schreiben?

### Out of Scope

- Kein Umbau der Aufrufer ueber das hinaus, was der neue Vertrag erzwingt.
- Keine Aenderung an der Semantik von `newline`/`errors` (FK-44 §44.6
  Byte-Reproduzierbarkeit bleibt unberuehrt).

## Akzeptanzkriterien

1. **Zwei Schreiber auf denselben Zielpfad stoeren sich nicht mehr.**
   Nachgewiesen durch die Wiederholung derselben Messung: 200 Iterationen, 0
   fehlerhafte, 0 ungueltige Zieldateien. Die Vorher-Zahlen stehen oben; der
   Beleg ist der Vergleich, nicht ein gruener Einzellauf.
2. **Cleanup ist eigentumsbeschraenkt.** Ein Schreiber entfernt niemals die
   Zwischendatei eines anderen. Negativpfad-Test.
3. **Es gibt genau eine Wahrheit ueber das Temp-Schema.** Der I/O-Owner
   definiert Erzeugung UND Erkennung; das VectorDB-Journal benutzt sie, statt
   das Schema ein zweites Mal zu kennen. Nachgewiesen durch einen Test, der
   beide Seiten gegen dieselbe Quelle fuehrt.
4. **Die Aufrufer-Inventur liegt vor.** Jeder der 35 Aufrufer ist bewertet:
   nebenlaeufig moeglich oder nicht, mit Begruendung. Wo eine echte
   Nebenlaeufigkeit besteht, ist sie durch einen Test gedeckt.
5. **Kein Aufrufer verliert Garantien.** Insbesondere bleibt die
   Byte-Reproduzierbarkeit der Prompt-Audit-Pfade (FK-44 §44.6) unveraendert.
6. **Volle Suite gruen** (Jenkins), `ruff`, `mypy --strict`, alle
   deterministischen Konzept-Gates.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — der Vertrag ist falsch, nicht
  die Aufrufer
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — AC 3
- `CLAUDE.md` „FAIL-CLOSED" — eine korrupte Zieldatei ist der schlechteste
  aller Ausgaenge, weil sie nicht auffaellt
- `guardrails/testing-guardrails.md` — Lastnachweis statt Einzellauf
