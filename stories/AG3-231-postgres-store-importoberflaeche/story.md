# AG3-231 — Was von `postgres_store` öffentlich ist, entscheidet niemand

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** keine
- **Herkunft:** Codex-Abschlussreview zu AG3-229, 2026-08-06

## Befund

`src/agentkit/backend/state_backend/postgres_store/__init__.py` sagt im
Docstring über sich selbst:

> „Compatibility import surface for the PostgreSQL state backend."

Das faellt woertlich unter `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN.
Re-Export-Fassaden sind dort ausnahmslos verboten, und wer eine findet,
entfernt sie **mitsamt allem, was nur ihretwegen existiert**.

Der Fall ist der Zwilling von `control_plane/http.py`, den AG3-229 entfernt hat
— nur eine Groessenordnung darueber.

## Gemessener Umfang

```
272 Namen in __all__, dynamisch per import_module + vars()-Reflexion
     ueber 14 private Submodule (_sql_script … _purge_rows; 17 .py im Paket),
     gefiltert ueber __module__-Herkunft
 +   eine handgepflegte 18-elementige _EXPORTED_CONSTANTS-Liste fuer
     Konstanten, welche die Herkunftspruefung nicht erfasst

 49 Importstellen in 42 Dateien ziehen ueber die Fassade statt ueber die
     Submodule:  20 in src/   22 in tests/   0 in scripts/
 64 Dateien nennen postgres_store insgesamt
```

## Die eigentliche Aufgabe ist nicht das Umziehen der Importe

**Die Fassade ist nicht bloss ein Umleitungsschild, sondern die einzige
oeffentliche Oberflaeche des Pakets.** Alle 14 Zielmodule sind mit `_` privat
benannt. Wer die Fassade entfernt, ohne vorher zu entscheiden, was oeffentlich
sein soll, hat kein Paket mehr, sondern 14 private Module und 49 Aufrufer, die
in Privates greifen.

**Die Reihenfolge ist deshalb:**

1. Entscheiden, welche der 272 Namen zur oeffentlichen Oberflaeche gehoeren.
2. Die Submodule entsprechend oeffentlich schneiden — entlang fachlicher
   Verantwortung, nicht entlang der heutigen Dateigrenzen.
3. Erst dann die 49 Importzeilen umziehen.

Wer bei 3 anfaengt, verschiebt das Problem.

## Warum das mehr ist als eine Stilfrage

Eine **dynamisch reflektierte** Exportliste ist das Gegenteil dessen, was AK3 v3
will. `CLAUDE.md` §Zielbild nennt „definierte State-Owner statt JSON-Wildwuchs"
und „klare fachliche Schnitte statt God-Files". Hier entsteht die Liste zur
**Laufzeit**: Niemand kann lesen, welches Modul welchen Namen besitzt, und
niemand bemerkt, wenn ein Modul einen Namen dazubekommt oder verliert. Die
handgepflegte Konstantenliste daneben belegt, dass die Reflexion die Sache
schon heute nicht vollstaendig erfasst.

Die Zahl „272 unveraendert" aus der AG3-229-Review belegt genau das: Sie zeigt,
dass die Fassade weiterhin alles verdeckt exportiert — nicht, dass Ownership
und oeffentliche Oberflaeche sauber geschnitten sind.

## Scope

### In Scope

- Die Entscheidung, welche Namen oeffentlich sind — **begruendet**, nicht als
  Liste behauptet.
- Der oeffentliche Schnitt der Submodule entlang fachlicher Verantwortung.
- Umzug aller 49 Importstellen auf die kanonischen Pfade.
- Entfernung der Fassade und der handgepflegten `_EXPORTED_CONSTANTS`-Liste.
- Decision Record; normative Nachfuehrung dort, wo das Konzept die Oberflaeche
  beschreibt.

### Out of Scope

- Das Verhalten der Persistenz. Dies ist ein Schnitt, keine Fachaenderung.
- Der SQLite-Zwilling, falls er dieselbe Konstruktion traegt — **pruefen und
  melden**, nicht mitnehmen. Erst wenn der Umfang bekannt ist, laesst sich
  entscheiden, ob er in dieselbe Story gehoert.

## Akzeptanzkriterien

1. **Kein Modul im Paket traegt mehr eine Re-Export-Fassade**, und kein
   `__all__` entsteht durch Reflexion. Die oeffentliche Oberflaeche ist
   **lesbar** — man sieht an der Quelle, welches Modul welchen Namen besitzt.
2. **Jeder oeffentliche Name hat einen benannten Eigentuemer.** Für die
   Auswahl gilt: Was nur ein einziger Aufrufer braucht und nicht zur fachlichen
   Oberflaeche gehoert, wird **nicht** oeffentlich, sondern der Aufrufer zieht
   um.
3. **Alle 49 Importstellen sind umgezogen**, nachgewiesen durch eine Suche, die
   belegt, dass niemand mehr ueber die Fassade importiert.
4. **Der Schnitt ist begruendet.** Je Submodul: welche fachliche Verantwortung
   es traegt und warum die zugeordneten Namen dorthin gehoeren. Eine Aufteilung,
   die nur die heutigen Dateigrenzen oeffentlich macht, erfuellt das nicht.
5. **Keine Verhaltensaenderung**, belegt durch die volle Suite auf Jenkins.
6. **Der SQLite-Zwilling ist geprueft und der Befund benannt** — mit Umfang,
   damit er entscheidungsreif ist.
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle
   deterministischen Gates gruen; Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — der Anlass, woertlich
- `CLAUDE.md` §SINGLE SOURCE OF TRUTH / §Zielbild — Ownership sichtbar machen
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — AC 4
