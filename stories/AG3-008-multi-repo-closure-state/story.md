# AG3-008: MultiRepoClosureState im ClosurePayload

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** AG3-007 (ClosureProgress-Schema muss konsolidiert sein)
**Quell-Konzept:** FK-29 §29.1.6.2, FK-39 §39.x

---

## Kontext

FK-29 §29.1.6.2 modelliert `MultiRepoClosureState` als optionales Feld
auf `ClosurePayload` fuer Multi-Repo-Stories. Die sechs
ClosureProgress-Booleans bleiben pro-Story; per-Repo-Granularitaet
liegt in `multi_repo: MultiRepoClosureState | None`.

```python
class MultiRepoClosureState(BaseModel):
    pre_merge_check_passed: list[str] = Field(default_factory=list)
    pushed_repos: list[str] = Field(default_factory=list)
    merged_repos: list[str] = Field(default_factory=list)
    rolled_back_repos: list[str] = Field(default_factory=list)
    failed_repo: str | None = None
```

`MultiRepoClosureState` ist im Code heute nicht modelliert. AG3-009
(Saga-Implementierung) braucht das Modell als Datenanker.

## Scope

### In Scope

- Neue Klasse `MultiRepoClosureState` in
  `src/agentkit/story_context_manager/models.py` (oder einem
  passenden Modul fuer Closure-Modelle)
- `ClosurePayload`-Erweiterung um `multi_repo: MultiRepoClosureState | None = None`
- Pydantic v2 Validierung: bei Multi-Repo-Stories
  (`participating_repos` |N| >= 2) ist das Feld zwingend gesetzt; bei
  Single-Repo bleibt es None
- Tests:
  - Konstruktion und Default-Werte
  - Frozen/immutable Verhalten konsistent zu ClosureProgress
  - JSON-Serialisierung deterministisch

### Out of Scope

- Saga-Logik selbst (AG3-009)
- ClosureProgress-Setzung bei Multi-Repo (Logik in AG3-009)
- ClosurePayload-Persistierung (lebt in PhaseState — AG3-007 hat das
  Schema schon vorgezogen)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/story_context_manager/models.py` | Modifiziert | MultiRepoClosureState neu; ClosurePayload erweitert |
| `tests/unit/story_context_manager/test_models.py` | Erweitert | Tests fuer MultiRepoClosureState |

## Akzeptanzkriterien

1. `MultiRepoClosureState` existiert mit 5 Feldern wie in FK-29 §29.1.6.2.
2. `ClosurePayload.multi_repo` ist optional (`None` fuer Single-Repo).
3. Alle bestehenden Tests fuer ClosurePayload gruen.
4. Lints clean.

## Definition of Done

- Tests gruen (bestehende und neue)
- mypy strict ohne neue Ignores
- Konzept-Referenz (FK-29 §29.1.6.2 + FK-39 §39.x) im Modul-Docstring

## Konzept-Referenzen

- FK-29 §29.1.6.2 — MultiRepoClosureState Schema
- FK-39 §39.x — PhaseState multi_repo-Feld

## Guardrail-Referenzen

- ZERO DEBT: keine Platzhalter-Felder
- SINGLE SOURCE OF TRUTH: Modell-Definition genau einmal in Pydantic
