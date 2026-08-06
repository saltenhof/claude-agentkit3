# AG3-234 — Vier Werkzeuge messen Git und sprechen über den Arbeitsbaum

- **Typ:** bugfix
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: [AG3-232]` — dort ist die Loesungsform
  erarbeitet
- **Herkunft:** Zusatzfrage aus AG3-232, 2026-08-06

## Anlass

AG3-232 hat `reference_integrity.py` als index-messend entlarvt, waehrend seine
Meldung von Existenz sprach. Die Anschlussfrage lautete, ob es dabei bleibt.

**Es bleibt nicht.** Vier weitere Fundstellen, eine davon gravierend.

## Die Befunde

### F2 — der schwerste: falsch grün für die eigene Aufgabe

`concept_toolchain/decision_gate.py`

```
Docstring Z. 67-68:  "against `base` and the current working tree"
gemessen Z. 292-293: git diff --name-only -z <base>
```

**Untrackte Dateien tauchen in keinem Diff auf.** Ein brandneues, nie
`git add`-tes normatives Konzeptdokument ist damit unsichtbar, und das Gate
kurzschliesst bei Z. 88-90 mit „no concept documents changed" — **falsch grün
für genau die Aenderungsklasse, für die es existiert.**

Gegenrichtung im selben File: Z. 147-149 entscheidet die Trailer-Erfuellung per
blossem `is_file()`. Ein nie committeter Decision Record erfuellt damit den
Trailer eines echten Commits.

Beide Richtungen zusammen heissen: Das Gate kann eine Konzeptaenderung
uebersehen **und** ihre Rechtfertigung fuer erbracht halten.

### F1 — derselbe Defekt, ausgeliefert an Zielprojekte, und schlimmer

`src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/reference_check.py`
ist ein Klon des Originals: `git ls-files -z` (Z. 314-322, **ohne** `--others`),
Meldung `repo-relative path does not exist` (Z. 268), Praedikat heisst
`path_exists` (Z. 69-73).

**Schlimmer als das Original:** Z. 314-325 macht das git-Ergebnis **optional**.
Schlaegt der Aufruf fehl, faellt es auf `Path.exists()` zurueck. Derselbe
Meldungstext bedeutet damit **zwei verschiedene Praedikate je nach Umgebung** —
ein Determinismusdefekt obendrauf.

Und dieser Klon liegt in der **Auslieferung an Zielprojekte**. Er misst dort,
wo AK3 keine Kontrolle ueber den Git-Zustand hat.

### F3 — neue Konzeptdokumente fallen aus dem Pre-Merge-Scope

`tools/concept_governance/git_scope.py:18-19`. `changed_concept_docs` verspricht
„committed and working-tree Markdown changes", misst zwei
`git diff --name-status` (Z. 26-45). Untrackte `.md` erscheinen nie
(`--diff-filter=A` heisst „staged added"). Neu verfasste Konzeptdokumente
fallen aus dem W2-Pre-Merge-Scope.

### F4 — Propagation

`tools/concept_governance/chunks.py:20-26`. `load_chunks` docstringt
„working-tree chunks without an external index dependency"; im Pre-Merge-Pfad
**ist** die Auswahl index-abgeleitet (F3 → `runner.py:41` → hier). Kein
eigenstaendiger Defekt, aber der Docstring ist unabhaengig falsch.

## Was sauber ist — das Negativergebnis gehört dazu

Geprüft und in Ordnung: alle neun `scripts/ci/*`-Einstiege;
`decision_record_git*.py`; `incubator_check.py` (**vorbildlich** — die Meldungen
nennen ausdruecklich „committed blob of base_revision"); `promotion_check.py`;
`check_concept_frontmatter.py`; `check_interpreter_entrypoints.py`;
`concept_ingester`, `concept_mcp`, `diagram_export`.

`incubator_check.py` ist der Beleg, dass es geht: Wer misst, was er sagt, sagt
es auch.

## Scope

### In Scope

- **F1–F3 behoben**, F4 als Docstring korrigiert.
- **Die Meldung sagt in jedem Fall, was gemessen wurde** — Git-Zustand,
  Arbeitsbaum, oder beides konjunktiv.
- **F1 erbt die Loesungsform aus AG3-232**, statt eine zweite zu erfinden. Falls
  Original und Klon dieselbe Logik tragen sollten: Das ist eine
  Doppelwahrheit und gehoert benannt — mit Vorschlag, aber **nicht** nebenbei
  zusammengezogen, denn das Zielprojekt-Bundle hat eigene Randbedingungen.
- **Der Fallback in F1 verschwindet.** Ein Praedikat, das je nach Umgebung
  etwas anderes bedeutet, ist mit `CLAUDE.md` §FAIL-CLOSED unvereinbar:
  „Fehlende externe Systeme werden nicht wegerklaert."

### Out of Scope

- `reference_integrity.py` — in AG3-232 erledigt.
- Der fachliche Zuschnitt der betroffenen Gates. Dies ist eine Korrektur
  dessen, **was** sie messen, nicht **ob** sie das Richtige pruefen.

## Akzeptanzkriterien

1. **Je Befund ein Richtungstest**: Eine neu angelegte, ungestagte Datei und
   eine geloeschte, ungestagte Datei liefern dasselbe Ergebnis wie nach dem
   Stagen. Gegen ein echtes Repository, nicht gegen Mocks.
2. **F2 ist an seiner eigenen Aufgabe belegt**: Ein neues, nie gestagtes
   normatives Konzeptdokument wird gesehen, und das Gate kurzschliesst **nicht**
   mit „no concept documents changed".
3. **Die Gegenrichtung von F2 ist geschlossen**: Ein nie committeter Decision
   Record erfuellt den Trailer eines Commits **nicht**.
4. **F1 hat kein umgebungsabhaengiges Praedikat mehr.** Belegt an einem Lauf,
   in dem der git-Aufruf scheitert: Das Werkzeug bricht benannt ab, statt
   stillschweigend etwas anderes zu messen.
5. **Jedes Gate weist weiterhin ab, was es abweisen soll.** Je Befund ein
   kuenstlich eingefuegter echter Verstoss, der gefunden wird. Ohne diese
   Haelfte sind die Aenderungen nur Lockerungen.
6. **Kein neuer Fundort.** Der Sweep aus AG3-232 wird auf dem geaenderten Stand
   wiederholt; kommt eine fuenfte Stelle dazu, wird sie gemeldet, nicht
   stillschweigend mitgenommen.
7. `ruff` clean bis auf den AG3-218-`C901`; `mypy --strict` fuer `win32`,
   `linux`, `darwin`; alle sieben deterministischen Gates gruen.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FAIL-CLOSED — AC 4; ein Fallback auf ein anderes Praedikat ist
  „Wegerklaeren" eines fehlenden Systems
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — die Meldung folgt der Messung
- `CLAUDE.md` §SINGLE SOURCE OF TRUTH — F1 ist ein Klon; die Doppelwahrheit
  gehoert benannt
