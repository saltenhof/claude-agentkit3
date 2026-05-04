# AG3-010: Multi-Repo Worktree-Setup

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-22 §22.6.2

---

## Kontext

FK-22 §22.6.2 normiert die Multi-Repo-Worktree-Erstellung pro
teilnehmendem Repo. Pseudo-Code:

```python
def setup_worktrees(story_id: str, context: StoryContext,
                    project: Project,
                    base_ref: str = "main") -> list[WorktreeResult]:
    repo_lookup = {r.name: r for r in project.repositories}
    for repo_name in context.participating_repos:
        repo = repo_lookup[repo_name]  # KeyError -> Setup FAIL
        result = setup_worktree(story_id, repo, base_ref)
        results.append(result)
    return results
```

Identifikator ist Repo-`name` aus `project.repositories[].name`. Alle
teilnehmenden Repos sind gleichberechtigt — kein Primary-Repo.
Branch-Name `story/{story_id}` identisch in allen Worktrees.

## Scope

### In Scope

- `setup_worktrees()` in `src/agentkit/pipeline/phases/setup/...` (oder
  passendes Modul):
  - Iteriert ueber `context.participating_repos`
  - Loest Repo-Name -> `RepoEntry` aus `project.yaml`
    (`project.repositories[]`) auf
  - Ruft `setup_worktree(story_id, repo_entry, base_ref)` pro Repo
  - Bei Fehler in Repo k: best-effort Cleanup der bereits angelegten
    Worktrees 1..k-1
- `setup_worktree()` Single-Repo bleibt; nimmt `RepoEntry` (nicht
  `RepoRef` — siehe Konzept-Cleanup)
- `WorktreeResult` enthaelt `repo_name` (nicht `repo` als generischer Begriff)
- Single-Repo-Fall: `participating_repos` = `[repo_name]` -> 1 Worktree
- Tests:
  - 1, 2, 3 Repos parallel
  - Repo-Name nicht in `project.repositories` -> Setup FAIL mit
    aussagekraeftigem Fehler
  - Bestehender Branch in einem Repo -> Setup FAIL (Preflight-Check)
  - Fehlschlag in Repo k -> Worktrees 1..k-1 abgeraeumt

### Out of Scope

- Worker-Spawn mit Worktree-Map (AG3-011)
- Lock-Aktivierung (FK-22 §22.7)
- Mode-Routing (FK-22 §22.8)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/pipeline/phases/setup/worktree.py` (oder analog) | Neu/Modifiziert | setup_worktrees() Multi-Repo |
| `src/agentkit/story_context_manager/models.py` | Pruefen | participating_repos: list[str] |
| `src/agentkit/project_management/entities.py` | Pruefen | RepoEntry-Schema (name, path, language, test_command, build_command) |
| `tests/unit/pipeline/phases/setup/test_worktree.py` | Neu/Erweitert | Multi-Repo-Tests |

## Akzeptanzkriterien

1. `setup_worktrees()` legt einen Worktree pro `participating_repos`-
   Eintrag an, alle mit Branch `story/{story_id}`.
2. Repo-Name nicht in `project.repositories` -> Fehler `RepoNotFoundError`
   o.ae. mit klarer Meldung.
3. Bei Fehler in Repo k werden bereits angelegte Worktrees 1..k-1
   wieder abgeraeumt (best-effort Cleanup).
4. Single-Repo-Fall (|N|=1) funktioniert ohne Sonderpfad.
5. Tests gruen, Lints clean.

## Definition of Done

- Tests gruen
- mypy strict
- Doc-String mit Querverweis FK-22 §22.6.2

## Konzept-Referenzen

- FK-22 §22.6.1 — Gleichberechtigte Teilnehmer, kein Primary-Repo
- FK-22 §22.6.2 — setup_worktrees() Pseudo-Code
- FK-22 §22.6.3 — Worktree-Pfad-Konvention
- FK-12 §12.6.1 — Repo-Identifikation via Name

## Guardrail-Referenzen

- FAIL CLOSED: Setup-FAIL bei nicht-existierendem Repo-Namen
- ZERO DEBT: best-effort Cleanup bei partial-failure
