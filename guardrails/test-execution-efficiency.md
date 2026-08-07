# Test-Ausfuehrungs-Effizienz (Inner-Loop-Selektion)

Diese Leitplanke regelt, WIE Tests waehrend der Arbeit ausgefuehrt werden — nicht
WAS getestet wird (das bleibt Sache der `testing-guardrails.md`). Sie existiert,
weil das blinde Fahren der gesamten Suite pro Iteration den mit Abstand groessten
Zeitfresser darstellt.

## Befundlage (statische Import-Graph-Messung, 2026-07-10)

- Suite: ~9.138 Test-Items in 698 Dateien (unit ~7.270 / integration ~780 /
  contract ~1.083 / e2e ~5).
- Eine lokalisierte Aenderung in EINEM Bounded Context (Referenzfall
  `control_plane`) beruehrt verhaltensrelevant nur **~8,4 %** der Test-Items;
  eine sicher gewaehlte Skopierung liegt bei **~15 %**.
- Wer pro Iteration ganze Tiers oder die Gesamtsuite faehrt, macht **7–12x** mehr
  Arbeit als die Aenderung erfordert.
- Nur **~6 %** der Items sind DB-gebunden (Postgres). Der `-n 4`-Cap ist wegen
  dieser ~6 % noetig, wird aber faelschlich auf 100 % der Suite angewandt.

## R0 — Die volle Suite laeuft AUSSCHLIESSLICH auf Jenkins (PO-Anweisung 2026-08-04)

**Kein Agent faehrt die vollstaendige Testsuite lokal. Nie.** Weder zur
Iteration, noch als Pre-Push-Gate, noch „einmal zum Abschluss". Der Ort, an dem
die volle Suite laeuft, ist der Jenkins-Job — und sonst keiner.

Das gilt fuer Orchestrator und Sub-Agents gleichermassen und hat Vorrang vor
allem, was weiter unten steht.

**Was lokal erlaubt bleibt:** die betroffene Teilmenge nach R2, `ruff` und
`mypy` (beide laufen in Sekunden, siehe R6). Was darueber hinausgeht, wird
gepusht und von Jenkins beantwortet.

**Warum:** Ein lokaler Volllauf kostet zwoelf Minuten, blockiert den
Arbeitsbaum, konkurriert mit jedem parallelen Lauf um dieselbe Datenbank — und
beweist am Ende weniger als Jenkins, weil er auf dem falschen Betriebssystem
laeuft. Belegt am 2026-08-03: drei Defekte auf `main` waren lokal auf Windows
gruen und fielen erst im ersten Jenkins-Lauf seit Tagen auf.

## Regel

### R1 — Zweistufiges Modell ist Pflicht
- **Innere Schleife (Iteration):** NUR die von der Aenderung betroffene
  Teilmenge (siehe R2). Ziel: Sekunden bis wenige Minuten Feedback.
- **Vollstaendiger Nachweis:** ausschliesslich Jenkins (R0). Das frueher hier
  beschriebene lokale „Pre-Push-Gate" ist mit R0 **entfallen** — es wird
  gepusht, und Jenkins ist der Nachweis.
- **Jenkins:** finaler und einziger Boden fuer die volle Suite; gegen den
  tatsaechlichen Kandidaten-SHA zu pruefen, nicht gegen einen angenommenen.

Die Regressionssorge „meine Aenderung bricht einen Consumer" ist durch den
Jenkins-Lauf abgedeckt — sie rechtfertigt keinen lokalen Volllauf.

### R2 — Sichere Selektions-Regel fuer die innere Schleife
Fuer eine Aenderung, die auf NICHT-geteilte Module EINES BC beschraenkt ist
(Beispiel `control_plane`):

```
tests/unit/<bc> tests/unit/<bc>_http tests/contract/<bc> tests/integration/<bc> tests/integration/<bc>_http
+ tests/contract/state_backend      # falls ein postgres_store/sqlite_store-Row-Modul beruehrt wird
+ tests/integration/state_backend   # dito (Ownership-Fence-PG-Tests)
+ die per Import-Graph bekannten Cross-BC-Konsumenten des BC
```

Die **Contract-Tests des beruehrten BC gehoeren IMMER in die innere Schleife** —
sie pinnen die Wire-Contracts, auf die die Nachbar-BCs sich verlassen; genau das
macht das Auslassen der Nachbar-Tests sicher.

### R3 — Widening-Blocklist: sofort volle Suite (Pre-Push-Gate = Iteration)
Beruehrt `git diff --name-only` irgendeinen dieser geteilten/kernnahen Pfade,
ist die innere Schleife NICHT sicher — dann ist die volle Suite die Iteration:
- `backend/core_types/`, `backend/exceptions.py`, `backend/schemas/`
- `state_backend/config.py`, `state_backend_connection_manager.py`,
  `persistence_test_support.py`, `persistence_mappers/`
- `story_context_manager/{types,models,story_model}.py`,
  `verify_system/protocols.py`, `verify_system/stage_registry/`
- `bootstrap/` (composition_root), `backend/config/`
- jede `*.sql` / `_schema.py` / Migration (es gibt KEINE Import-Kante zu
  SQL-Dateien; nur PG-gebundene Tests beweisen sie)
- alles dynamisch Dispatchte (Producer-Registries, Prompt-/Skill-Bundles,
  `pyproject.toml`-Entry-Points) — der Import-Graph sieht das nicht
- jede `conftest.py`, `tests/fixtures/`

### R4 — Coverage in EINEM Durchlauf
Niemals „plain pytest, dann nochmal mit Coverage". `pytest-cov` ist xdist-faehig;
das Pre-Push-Gate misst Coverage in einem einzigen Lauf:

```
.venv\Scripts\python -m pytest --cov=agentkit --cov-report=term-missing:skip-covered
```

### R5 — Tier-Split-Parallelitaet (optional, fuer das volle Gate)
Die Unit-Tier (~80 %) ist per autouse-sqlite-Pin DB-frei und darf hoeher
parallelisieren als die DB-gebundenen Tiers:

```
.venv\Scripts\python -m pytest tests/unit -n 8 --dist loadfile
.venv\Scripts\python -m pytest tests/integration tests/contract tests/e2e -n 4 --dist loadfile
```

Achtung: getrennte Laeufe brechen die Single-Pass-Coverage (R4). Fuer das
Coverage-Gate entweder die Ein-Pass-Form nutzen oder `--cov-append` +
`coverage combine`.

### R6 — mypy/ruff nicht skopieren fuer das Gate
`mypy` laeuft warm in ~7 s — immer voll. `ruff check src tests scripts tools` ist ohnehin
sub-Sekunde. In der inneren Schleife darf `ruff` auf die beruehrten Pfade
beschraenkt werden; `mypy` bleibt voll.

## Warum NICHT pytest-testmon
Trotz inzwischen vorhandener xdist-Unterstuetzung (v1.4) ungeeignet fuer dieses
Repo: Worker laufen in frischen Worktrees (jeder zahlt einen vollen Seed-Lauf,
bevor er spart); `.testmondata` ist pro-rootdir/env und darf nicht zwischen
parallelen Workern geteilt werden; testmon sieht KEINE statischen Dateien
(`*.sql`, Bundles) und keine Live-DB — genau die riskantesten Aenderungsklassen
hier; und es erzwingt das Deaktivieren von `pytest-randomly`. Die Pfad-Selektion
(R2/R3) holt ~90 % des Nutzens mit null zu pflegendem State.

## Verwandte Architektur-Schuld (getrennt getrackt)
- `backend/exceptions.py` ist ein Cross-BC-God-Modul (132 direkte Importer;
  fremde BC-Fehler ausserhalb ihres Owners → CRP-Verstoss). Aufspalten in
  per-BC-Exception-Module verkleinert die R3-Blocklist.
- `postgres_store`/`sqlite_store`-`__init__.py` re-exportieren eager alle
  Row-Module (Import-Zeit-Reichweite ~94 %). Lazy `__getattr__` (wie
  `telemetry/__init__.py` / `story_context_manager/__init__.py`) beheben.
