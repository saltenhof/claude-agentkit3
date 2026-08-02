# AG3-197 — `tools/` unter `ruff` und `mypy` stellen

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** `CLAUDE.md` §Operations (Pflichtkommandos), FK-78 §78.14
  (deploybare Concept-Toolchain)
- **Herkunft:** Befund vom 2026-08-02, dokumentiert in
  `stories/AG3-179-run-mutex-intent-liveness/status.yaml`
  („NACHWEIS-LUECKEN RUNDE 3", zwei Bestandsbefunde). Ausgezogen aus AG3-184
  am 2026-08-02 nach unabhaengigem Codex-Review (Auflage ERROR-12).

## Kontext

### Befund — belegt, mit Locator

Die verbindlichen Kommandos aus `CLAUDE.md` §Operations sind
`ruff check src tests` und `mypy src`. **`tools/` liegt damit ausserhalb jeder
Pruefung** — und genau dort leben Konzept-Compiler, Governance-Werkzeuge und
Ingester, also die Werkzeuge, die unsere Konzeptqualitaet sichern sollen.

**Gemessen am 2026-08-02** (`find tools -name "*.py" -not -path "*__pycache__*"
| xargs wc -l`): 66 Dateien, **10 670 Zeilen**. Dazu die gebundelte
Zielprojekt-Toolchain unter `src/agentkit/bundles/target_project/tools/`:
weitere **11 888 Zeilen**, die zwar unter `src/` liegen, aber als deploybares
Asset eine eigene Betrachtung brauchen.

> **Korrektur gegenueber der Reviewvorlage:** dort stand „rund 40 000 Zeilen".
> Die gemessene Zahl ist kleiner. Der Befund selbst ist davon unberuehrt: die
> Flaeche ist ungeprueft, und beide bekannten Defekte sind reproduzierbar.

**Zwei Defekte, am 2026-08-02 nachgemessen und heute erneut reproduziert:**

- `.venv/Scripts/python -m ruff check tools` → **1 error**: C901 in
  `tools/concept_compiler/architecture_conformance.py:1409` (Komplexitaet
  20 > 15).
- `.venv/Scripts/python -m mypy tools` → **1 error, „errors prevented further
  checking"**: `tools/concept_ingester/config.py` scheitert an der
  Modulpfad-Aufloesung (fehlendes `__init__.py` bzw. fehlende
  `--explicit-package-bases`/`MYPYPATH`-Konfiguration). Der zuvor berichtete
  Fehler in `tools/concept_ingester/discovery.py:243` liegt **hinter** dieser
  Blockade — er wird erst sichtbar, wenn die Paketaufloesung steht.

Der zweite Befund ist der interessantere: `mypy` kommt heute gar nicht bis zu
den Typen. Die Story muss deshalb zuerst die Paketstruktur/Konfiguration von
`tools/` in Ordnung bringen, sonst prueft das neue Gate wieder nichts.

## Scope

### In Scope

- `tools/` vollstaendig unter `ruff` und `mypy --strict` stellen, in den
  verbindlichen Kommandos und im `Jenkinsfile`.
- Die Paketstruktur/Konfiguration so herrichten, dass `mypy` die Module
  tatsaechlich aufloest.
- Beide bekannten Befunde an der Wurzel beheben.
- Eine Entscheidung, wie die gebundelte Zielprojekt-Toolchain unter
  `src/agentkit/bundles/target_project/tools/` behandelt wird.

### Out of Scope

- Die Referenz-Baseline — **AG3-184**.
- Die FK-93-Eigentumsfrage — **AG3-198** / **AG3-199**.
- Gate-Outcome-Semantik — **AG3-195**.
- Keine funktionale Aenderung an den Werkzeugen ueber das hinaus, was die
  Befunde erfordern.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `pyproject.toml` | geaendert | `ruff`- und `mypy`-Konfiguration deckt `tools/` ab; Paketaufloesung |
| `tools/**/__init__.py` | neu/geaendert | Modulpfad-Aufloesung fuer `mypy` |
| `tools/concept_compiler/architecture_conformance.py` | geaendert | C901 an der Wurzel, per Zerlegung — nicht per `noqa` |
| `tools/concept_ingester/config.py`, `tools/concept_ingester/discovery.py` | geaendert | Typfehler nach hergestellter Aufloesung |
| `tools/**` (uebrige) | geaendert | die Befunde, die erst nach Aktivierung sichtbar werden |
| `CLAUDE.md` §Operations, §Weitere Qualitaetschecks | geaendert | Pflichtkommandos nennen `tools` |
| `AGENTS.md` | geaendert | Pflicht-Gates-Liste |
| `Jenkinsfile` | geaendert | Ruff-/Mypy-Stages decken `tools/` ab |
| `concept/_meta/decisions/2026-XX-XX-tools-unter-den-gates.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **`ruff` und `mypy --strict` decken `tools/` ab**, in den verbindlichen
   Kommandos aus `CLAUDE.md`, im `Jenkinsfile` und im lokalen Pre-Commit-Hook.
   Nachgewiesen daran, dass ein konstruierter Verstoss in einer beliebigen
   `tools/`-Datei den Pflichtlauf rot macht.
2. **`mypy` loest die Module tatsaechlich auf.** Der heutige Abbruch
   („errors prevented further checking") tritt nicht mehr auf; die Ausgabe
   nennt die Zahl der geprueften Quelldateien, und sie deckt alle 66
   `tools/`-Module ab. Ein Lauf, der mit 0 Fehlern endet, weil er nichts
   geprueft hat, erfuellt dieses Kriterium **nicht**.
3. **Beide bekannten Befunde sind an der Wurzel behoben** — C901 in
   `architecture_conformance.py:1409` per Zerlegung, der Ingester-Typfehler per
   korrekter Typisierung. **Nicht per `noqa`, nicht per `type: ignore`, nicht
   per Exclude.**
4. **Jede bewusste Ausnahme steht in der Konfiguration, nicht im Kopf des
   Naechsten.** Bleibt ein Teil von `tools/` ausgenommen, traegt der
   Konfigurationseintrag die fachliche Begruendung.
5. **Die gebundelte Zielprojekt-Toolchain ist entschieden.** Fuer
   `src/agentkit/bundles/target_project/tools/` (11 888 Zeilen) ist
   ausgeschrieben, ob und wie sie geprueft wird — sie ist ein deploybares
   Asset, das in fremden Projekten laeuft. Eine Nichtbehandlung ist zu
   **begruenden**, nicht zu uebergehen.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` gruen fuer `win32`,
   `linux` und `darwin` — **inklusive der neu abgedeckten Flaeche**. Alle
   deterministischen Konzept-Gates gruen.
7. **Konzept/Regelwerk nachgezogen:** `CLAUDE.md` und `AGENTS.md` nennen die
   erweiterten Pflichtkommandos; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe).
- Die Zahl der von `mypy` geprueften `tools/`-Dateien liegt im Story-Record.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/78_concept_incubation_process.md` §78.14 —
  deploybare Concept-Toolchain
- `PROJECT_STRUCTURE.md` — Modulgrenzen und Ablage von `tools/`
- `concept/_meta/konzept-konsistenz-governance.md` §5 — die Werkzeuge, die hier
  geprueft werden

## Guardrail-Referenzen

- `CLAUDE.md` §Operations — die Pflichtkommandos, die heute `tools/` auslassen.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 3: kein `noqa`, kein Exclude.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 5.
- `CLAUDE.md` „SEVERITY-SEMANTIK" — AC 2: ein Lauf, der nichts geprueft hat,
  ist nicht bestanden (siehe auch AG3-195).
