# Globale Akzeptanzkriterien (verbindlich fuer ALLE Stories)

Diese Kriterien gelten **zusaetzlich** zu den story-spezifischen Akzeptanzkriterien
fuer jede Story `AG3-*` (Code- wie Doc-only-Stories). **Single Source of Truth:**
die einzelnen Story-DoDs verweisen auf diese Datei, statt den Wortlaut zu duplizieren
(FIX THE MODEL / keine zweite operative Wahrheit).

## GAC-1 — Architektur-Konformitaet: 0 Errors (fail-closed)

Nach Abschluss einer Story MUSS der Architektur-Checker fehlerfrei durchlaufen
(Exit 0):

```
PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py
```

- **ERROR-Severity ist blockierend** (kein Merge). Der Lauf ist fail-closed.
- **Baseline 2026-06-08:** aktuell **GRUEN** (0 Violations, Exit 0). Jede Story
  haelt den Checker gruen — es darf **keine neue ERROR-Violation** (AC001-AC011)
  eingefuehrt werden.
- **WARNING** (z.B. AC012 AT-Touch) ist nicht blockierend, aber gemaess
  SEVERITY-SEMANTIK (CLAUDE.md) aktiv zu spiegeln/begruenden, nicht still
  liegenzulassen.
- Aendert eine Story bewusst die Architektur-Soll-Grenzen, ist die Formal-Spec
  (`concept/formal-spec/architecture-conformance/entities.md` +
  `invariants.md`) mitzuziehen — **FIX THE MODEL, nicht den Check umgehen** und
  keine Regel aufweichen, um gruen zu werden.
- **Doc-only-Stories** (`type: concept`), die keinen `src/`-Python-Code aendern,
  erfuellen GAC-1 vacuously (kein `src/`-Diff -> keine neue Violation); der Lauf
  muss trotzdem gruen bleiben.

## GAC-2 — Architektur-Guardrails (`guardrails/architecture-guardrails.md`)

Die `ARCH-NN`-Leitplanken aus `guardrails/architecture-guardrails.md` gelten
verbindlich fuer jede Story. Implementierung und Loesungsschnitt muessen mit
ihnen vereinbar sein. Konflikt = **hart stoppen und melden** (keine stille
Abweichung), analog zur Konzepttreue.

## Verweis-Konvention

Jede `story.md` traegt am Ende den Block **„Globale Akzeptanzkriterien
(verbindlich)"** mit Verweis auf diese Datei. Die operative Wahrheit (Wortlaut,
Befehl, Severity-Regeln) steht **nur hier**; die Story-Verweise sind Zeiger,
keine Kopien.
