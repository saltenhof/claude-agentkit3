# AG3-232 — Das Gate misst einen anderen Zustand als der Entwickler

- **Typ:** bugfix
- **Groesse:** S
- **Abhaengigkeiten:** keine
- **Herkunft:** Jenkins #1248 gegen `a32dc6d6`, 2026-08-06

## Befund

Ein Decision Record nannte eine soeben geloeschte Datei. Das Gate meldete

```
lokal:    [PASS]  concept-reference-integrity: 0 error(s), 54 report(s)
Jenkins:  [ERROR] concept-reference-integrity: 1 error(s), 54 report(s)
```

— bei identischen 54 Reports, auf demselben Stand.

**Ursache:** `_tracked_repo_paths`
(`tools/concept_compiler/reference_integrity.py:418-447`) ruft in Zeile 424
`git ls-files -z`. Das Ergebnis geht als `tracked_paths` in `_scan_document`
und wird in Zeile 245 gegen den Backtick-Token geprueft
(`candidate not in tracked_paths`). **`Path.exists()` kommt im gesamten Modul
nicht vor.**

Die Fehlermeldung lautet `repo-relative path does not exist` und beschreibt
damit etwas, das das Gate gar nicht prueft.

## Zwei Experimente, die es beweisen

| Aufbau | Ergebnis |
|---|---|
| Datei im **Arbeitsbaum** vorhanden, nicht im Index | **ROT** |
| Datei im **Index** vorhanden, nicht auf der Platte | **GRUEN** |

Der zweite Fall ergab byte-identisch die Meldung, die den Fehler ueberhaupt
erst verdeckt hat.

## Beide Richtungen sind kaputt

- Eine **geloeschte, noch nicht gestagte** Datei: lokal gruen, auf CI rot.
- Eine **neu angelegte, noch nicht gestagte** Datei, die ein Konzeptdokument
  nennt: lokal rot, auf CI gruen.

Die zweite Richtung ist die gefaehrlichere: Sie laesst einen echten Fehler
durch die CI, weil dort die Datei im Tree steht — waehrend lokal ein
Fehlalarm entsteht, den jemand irgendwann durch Gewoehnung ignoriert.

## Warum das schwerer wiegt als ein einzelner Fehlschlag

Jeder Auftrag in diesem Projekt verlangt vom Umsetzer, die deterministischen
Gates **vor der Uebergabe** lokal auszufuehren. Ein Gate, das einen anderen
Zustand misst als den, den der Umsetzer vor sich hat, macht diese Vorabpruefung
wertlos — und der Fehler faellt erst zwoelf Minuten spaeter auf Jenkins auf,
in einem Lauf, der dann die Stufen danach gar nicht mehr erreicht.

Genau das ist am 2026-08-06 passiert: Die Reference-Integrity-Stufe brach die
Pipeline ab, und die Stufe „Concept Decision Record" — die aus einem **anderen**
Grund rot war — wurde nie erreicht. Ein falsch messendes Gate verdeckt die
Befunde der Gates dahinter.

## Scope

### In Scope

- Die Existenzpruefung folgt dem **Dateisystem**: `(repo_root / candidate).exists()`.
- `git ls-files` bleibt allenfalls als **Ignore-Filter** fuer untrackte
  Artefakte erhalten — dann mit ausdruecklicher Begruendung, was damit
  ausgeschlossen wird und warum.
- Die Fehlermeldung sagt, was tatsaechlich geprueft wurde.
- Beide Richtungen sind getestet: geloescht-aber-gestaged, neu-aber-ungestaged.

### Out of Scope

- Der Umfang der `reference-integrity-baseline.yaml` (54 Eintraege). Wenn die
  korrigierte Pruefung Eintraege gegenstandslos macht, ist das zu **melden**,
  nicht nebenbei zu bereinigen.
- Andere Gates. Ob dieselbe Konstruktion anderswo vorkommt, ist zu pruefen und
  zu melden — die Behebung dort ist eine eigene Entscheidung.

## Akzeptanzkriterien

1. **Das Gate misst den Zustand, den der Entwickler vor sich hat.** Ein Test je
   Richtung: eine geloeschte Datei, deren Loeschung noch nicht gestaged ist,
   und eine neue Datei, die noch nicht gestaged ist. Beide muessen dasselbe
   Ergebnis liefern wie nach dem Stagen.
2. **Die Meldung beschreibt die Pruefung.** Kein Text, der Existenz behauptet,
   wo Tracking geprueft wird — oder umgekehrt.
3. **Das Gate weist weiterhin ab, was es abweisen soll.** Ein kuenstlich
   eingefuegter, echter unaufgeloester Repo-Pfad wird gefunden. Ohne diesen
   Nachweis ist die Aenderung nur eine Lockerung.
4. **Der Bestand bleibt stabil:** Nach der Korrektur weiterhin 0 Fehler und
   dieselben 54 Reports — oder, falls sich etwas aendert, je Abweichung eine
   Begruendung.
5. **Dieselbe Konstruktion anderswo ist geprueft und gemeldet**, mit Locator.
6. `ruff` clean bis auf den AG3-218-`C901`; `mypy --strict` fuer `win32`,
   `linux`, `darwin`; alle deterministischen Gates gruen;
   `tests/unit/tools/concept_compiler` ohne `-k` gruen.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — die Pruefung folgt dem
  Gegenstand, nicht einem Nebenprodukt
- `CLAUDE.md` §FAIL-CLOSED — AC 3; ein Gate, das falsch gruen meldet, entwertet
  jede Aussage, die es je gemacht hat
