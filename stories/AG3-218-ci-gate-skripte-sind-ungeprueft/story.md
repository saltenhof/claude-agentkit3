# AG3-218 — Die Gate-Skripte unterliegen den Regeln, die sie durchsetzen

- **Typ:** implementation
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** `guardrails/architecture-guardrails.md`, `CLAUDE.md`
  §Code Quality, `Jenkinsfile`
- **Herkunft:** AG3-214 R3 am 2026-08-05.

## Kontext

### Befund — belegt, mit Locator

Ein Sub-Agent-Auftrag verlangte `ruff check src tests scripts` — also
ausdruecklich **mit** `scripts`. Ergebnis:

```
C901 lint_l19_glossary_integrity is too complex (24 > 15)
scripts/ci/check_concept_frontmatter.py:566
Found 1 error.
```

Der Sub-Agent hat den Befund korrekt als mandatsfremd zurueckgemeldet, statt ihn
mit einem `noqa` verschwinden zu lassen. Die Nachpruefung ergab die Ursache:

- **`Jenkinsfile:103`** fuehrt `python -m ruff check src tests` aus — **ohne
  `scripts`**.
- **`pyproject.toml [tool.mypy]`** setzt `packages = ["agentkit"]`, prueft also
  nur `src/agentkit`. `mypy_path` enthaelt `tools`, aber `scripts` ist kein
  geprueftes Paket.

Damit gilt: **`scripts/ci/` ist der einzige produktive Codebestand dieses
Repos, der Regeln durchsetzt, denen er selbst nicht unterliegt.**

### Warum das mehr ist als ein uebersehener Pfad

Die Skripte unter `scripts/ci/` sind keine Hilfsdateien. Sie sind der
ausfuehrende Arm der Guardrails: `check_interpreter_entrypoints.py`,
`check_architecture_conformance.py`, die sechs Konzept-Gates und
`compile_formal_specs.py` entscheiden, ob eine Aenderung durchkommt. Ein Defekt
dort ist teurer als ein Defekt im Fachcode, weil er nicht auffaellt — ein Gate,
das faelschlich passieren laesst, meldet nichts.

`CLAUDE.md` verlangt fuer Produktionscode `mypy` strict ohne unerklaerte
`type: ignore` und `ruff` ohne unerklaerte `noqa`. Fuer die Instanz, die genau
das durchsetzt, gilt das bisher nicht. Das ist kein Formfehler, sondern eine
Luecke im Selbstbezug des Systems.

Der C901-Befund ist nicht der Kern dieser Story, sondern ihr **Anlassfall**: er
lag unbemerkt da, weil niemand hinsah. Wie viele weitere Befunde `scripts/`
traegt, weiss aktuell niemand. Das herauszufinden ist Teil der Umsetzung.

## Scope

### In Scope

- `scripts/` faellt unter `ruff` — im `Jenkinsfile`, im pre-commit-Hook und in
  der in `CLAUDE.md` §Operations dokumentierten Standardpruefung.
- `scripts/` faellt unter `mypy --strict`, mit derselben Plattformmatrix
  (`win32`, `linux`, `darwin`), die der Rest des Repos bereits fuehrt.
- **Alle** dadurch sichtbar werdenden Befunde werden **behoben**, nicht
  unterdrueckt. `lint_l19_glossary_integrity`
  (`scripts/ci/check_concept_frontmatter.py:566`, Cognitive Complexity 24 > 15)
  wird refaktoriert; die Zerlegung muss die Lint-Semantik unveraendert lassen
  und das durch Tests belegen.
- Falls Typannotationen in `scripts/` fehlen: ergaenzen, nicht ausklammern.

### Out of Scope

- Keine funktionale Aenderung an irgendeinem Gate. Was heute einen Befund
  erzeugt, erzeugt ihn danach ebenso; was heute passiert, passiert danach
  ebenso. Diese Story macht die Skripte pruefbar, nicht anders.
- Kein Anheben von `max-complexity` und keine Ausnahmeliste fuer `scripts/`.
  Beides waere die Umgehung statt der Behebung (`CLAUDE.md` NO ERROR
  BYPASSING).
- `tools/` und `.githooks/` bleiben ausserhalb, sofern sich nicht bei der
  Umsetzung zeigt, dass dieselbe Luecke dort ebenfalls besteht. Zeigt sie sich:
  benennen, nicht stillschweigend mitziehen — das ist eine Mandatsanfrage.

## Akzeptanzkriterien

1. **`ruff check src tests scripts` ist gruen** — und `scripts` steht in
   `Jenkinsfile`, im pre-commit-Hook und in `CLAUDE.md` §Operations, damit die
   Pruefung nicht wieder nur bei dem stattfindet, der zufaellig daran denkt.
2. **`mypy --strict` deckt `scripts/` ab** und ist fuer alle drei Plattformen
   gruen. Belegt durch die drei Kommandos mit ihrer Ausgabe.
3. **`lint_l19_glossary_integrity` ist unter der Komplexitaetsschwelle**, ohne
   dass sich sein Verhalten aendert. Nachgewiesen durch Tests, die die
   L19-Lint-Semantik vor und nach der Zerlegung an denselben Eingaben pruefen.
4. **Kein Befund wurde unterdrueckt.** Ein `noqa` oder `type: ignore` in
   `scripts/` ist nur zulaessig mit einer Begruendung an Ort und Stelle, die
   sagt, warum die Regel dort fachlich nicht greift — nie, weil die Behebung
   aufwendig war. Die Liste aller verbliebenen Unterdrueckungen gehoert in den
   Abschlussbericht.
5. **Die Gate-Skripte verhalten sich unveraendert.** Nachgewiesen durch einen
   Lauf jedes Gates vor und nach der Aenderung mit identischem Urteil und
   identischen Zaehlwerten.
6. Volle Suite gruen auf Jenkins gegen den Kandidaten-SHA.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §Code Quality — `mypy` strict, `ruff` ohne unerklaerte `noqa`
- `CLAUDE.md` §NO ERROR BYPASSING — Ursache beheben, nicht die Regel weichspuelen
- `CLAUDE.md` §ZERO DEBT RULE — „Ein Fehler wird gefunden. Ein Entwurf wird
  erweitert."
