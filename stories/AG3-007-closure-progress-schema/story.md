# AG3-007: ClosureProgress-Schema synchronisieren

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-29 §29.1.0, FK-39 §39.x

---

## Kontext

Der Konzept-Cleanup `ddd9976` hat in FK-29 das `ClosureProgress`-Boolean
`issue_closed` zu `story_closed` umbenannt (analog zur GitHub-Issues-
Entfernung). Plus FK-29 §29.1.0 listet **6 Booleans**:
`integrity_passed, story_branch_pushed, merge_done, story_closed,
metrics_written, postflight_done`.

Der Code unter `src/agentkit/story_context_manager/models.py:89-96`
hat aber:
- nur 5 Booleans (`story_branch_pushed` fehlt)
- noch `issue_closed` statt `story_closed`

Das ist Code-vs-Konzept-Drift und blockiert die Multi-Repo-Closure
(AG3-008/009).

## Scope

### In Scope

- `ClosureProgress` in `src/agentkit/story_context_manager/models.py`:
  - `issue_closed: bool = False` -> `story_closed: bool = False`
  - Neues Feld `story_branch_pushed: bool = False` (zwischen
    `integrity_passed` und `merge_done`)
- Schema-Versionierung beachten (FK-18 §18.9a Side-by-Side):
  - schema_version Bump (z. B. 3.1.0)
  - falls Persistierungs-Stores betroffen, neue DB anlegen
- ClosurePayload bleibt Pydantic-Wrapper; nur progress-Inhalt aendert sich
- Tests: bestehende ClosureProgress-Tests anpassen, neue Tests fuer
  Reihenfolge (story_branch_pushed setzbar erst wenn integrity_passed
  true)

### Out of Scope

- `MultiRepoClosureState`-Block (AG3-008)
- Multi-Repo-Saga-Logik (AG3-009)
- Postflight-Check `story_closed` (FK-29 §29.3.1) — Folge-Story falls
  noch nicht abgedeckt

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/story_context_manager/models.py` | Modifiziert | ClosureProgress: issue_closed -> story_closed; story_branch_pushed neu |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/story_context_manager/test_models.py` | Pruefen | Closure-Progress-Tests anpassen |
| `tests/unit/state_backend/test_schema_versioning.py` | Pruefen | Schema-Versionierung |

## Akzeptanzkriterien

1. `ClosureProgress` hat exakt 6 Booleans in der konzept-konformen
   Reihenfolge: `integrity_passed, story_branch_pushed, merge_done,
   story_closed, metrics_written, postflight_done`.
2. Kein Vorkommen von `issue_closed` mehr in `src/`.
3. Schema-Versionierung mitgezogen (Side-by-Side, nicht in-place).
4. Tests gruen: `pytest tests/unit`.
5. Lints clean: `ruff check src tests`, `mypy src`.

## Definition of Done

- Build kompiliert
- Unit-Tests gruen (insbesondere ClosureProgress-Konstruktion)
- Schema-Migration funktioniert (alte DB bleibt unangetastet, neue
  schema_version-Tabellen werden parallel angelegt)

## Konzept-Referenzen

- FK-29 §29.1.0 — ClosurePayload + ClosureProgress (6 Felder)
- FK-39 §39.x — PhaseState ClosurePayload-Definition
- FK-18 §18.9a — Schema-Versionierung Side-by-Side

## Guardrail-Referenzen

- FIX THE MODEL, NOT THE SYMPTOM: nicht zwei Felder parallel; sauberer
  Schema-Wechsel
- ZERO DEBT: kein Mix-State zwischen alt und neu
