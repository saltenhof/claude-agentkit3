# AG3-009: Multi-Repo-Closure-Saga

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-007 (ClosureProgress), AG3-008 (MultiRepoClosureState)
**Quell-Konzept:** FK-29 §29.1.6, AK2-Vorlage `agentkit/worktree/merge.py`

---

## Kontext

FK-29 §29.1.6 normiert Multi-Repo-Closure als atomare 5-stufige Saga:

1. **Pre-Merge-Check (Stufe 0)** — alle Repos ff-mergebar?
2. **Push-Stufe (Stufe 1)** — alle Story-Branches gepusht
3. **Merge-Stufe (Stufe 2)** — lokal-atomar mit `pre_merge_sha`-Rollback
4. **Push-zu-main-Stufe (Stufe 3)** — alle Hauptbranches gepusht
5. **Teardown-Stufe (Stufe 4)** — Worktrees aufraeumen

AK2 hat das in `T:/codebase/claude-agentkit/agentkit/worktree/merge.py`
(`merge_story_multi_repo`) als Saga-Pattern implementiert. Diese Story
zieht die Implementation nach AK3 mit AK3-konformen Strukturen.

## Scope

### In Scope

- Neues Modul (z. B. `src/agentkit/closure/multi_repo_saga.py`):
  - `pre_merge_check(repos, story_id) -> list[str] (failed_repos)`
  - `push_story_branches(repos, story_id) -> SagaStageResult`
  - `local_ff_merge_with_rollback(repos, story_id, base="main") -> SagaStageResult`
    - Pre-merge-SHA pro Repo erfassen
    - Rollback via `git reset --hard <pre_merge_sha>` bei Fehler
  - `push_main(repos) -> SagaStageResult` (Partial-Push-State-aware)
  - `teardown_worktrees(repos, story_id) -> None` (idempotent)
- `MultiRepoClosureState`-Updates pro Stufe (pushed_repos,
  merged_repos, rolled_back_repos, failed_repo)
- ClosureProgress-Setzpunkte:
  - `story_branch_pushed = true` nach Stufe 1
  - `merge_done = true` nach Stufe 4 (alle Repos gepusht UND Stufen
    1-4 PASS)
- Single-Repo-Fall: das Modul muss auch fuer |N|=1 funktionieren
  (Single-Repo ist Multi-Repo-Saga mit |N|=1; keine Sonder-API)
- Tests:
  - Happy-Path 2 Repos
  - Pre-Merge-Check FAIL in einem Repo (kein Push, kein Merge)
  - Push-Stufe-FAIL in Repo k (Repos 1..k-1 bleiben gepusht,
    explizite Eskalation)
  - Merge-Stufe-FAIL in Repo k (Repos 1..k-1 lokal zurueckgesetzt
    via pre_merge_sha)
  - Push-zu-main-FAIL in Repo k (Partial-Push-State, k+1..N lokal
    zurueckgesetzt, ESCALATED)
  - Teardown idempotent (kein Fehler bei wiederholtem Aufruf)

### Out of Scope

- Force-revert-Recovery-Pfad (FK-29 §29.1.6.3 a) — manueller Operator-Pfad
- Closure-Retry-Logik fuer verbleibende Repos (FK-29 §29.1.6.3 b)
- Phase-Runner-Integration (separate Story falls noetig)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/closure/multi_repo_saga.py` | Neu | Saga-Implementierung |
| `src/agentkit/closure/__init__.py` | Modifiziert | Re-Export |
| `tests/unit/closure/test_multi_repo_saga.py` | Neu | Saga-Tests |
| `tests/integration/closure/test_multi_repo_saga_integration.py` | Optional | E2E mit Test-Worktrees |

## Akzeptanzkriterien

1. Saga laeuft 5-stufig wie in FK-29 §29.1.6.1.
2. Bei Pre-Merge-Check-FAIL: kein Push, kein Merge, ESCALATED.
3. Bei Merge-FAIL in Repo k: alle bereits lokal gemergten Repos via
   `pre_merge_sha` zurueckgesetzt.
4. Bei Push-zu-main-FAIL in Repo k: Repos 1..k-1 bleiben gepusht
   (Partial-Push-State), Repos k+1..N lokal zurueckgesetzt,
   `MultiRepoClosureState.failed_repo = r_k`,
   `MultiRepoClosureState.pushed_repos = [r_1, ..., r_{k-1}]`.
5. ClosureProgress-Substates werden korrekt gesetzt
   (`story_branch_pushed`, `merge_done`).
6. Single-Repo-Fall funktioniert ohne Sonderpfad.
7. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Tests gruen, inkl. Failure-Pfade (Stufe-FAIL in jeder Stufe)
- mypy strict ohne neue Ignores
- AK2-Vorlage als Querverweis im Modul-Docstring

## Konzept-Referenzen

- FK-29 §29.1.6 — Multi-Repo-Closure (5 Stufen, Pre-Merge-Check, Saga)
- FK-29 §29.1.6.3 — Partial-Push-State
- FK-29 §29.1.6.4 — Implementations-Anker AK2
- AK2: `T:/codebase/claude-agentkit/agentkit/worktree/merge.py`

## Guardrail-Referenzen

- FAIL CLOSED: jede Stufe, die FAIL meldet, blockiert sofort die
  naechste Stufe — keine partial-merged Stories
- ZERO DEBT: kein "Rollback machen wir spaeter"
- FIX THE MODEL: pre_merge_sha als praeziser Rollback-Anker
