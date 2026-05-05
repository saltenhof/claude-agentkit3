# AG3-016: Verify-System Modul-Migration

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** keine
**Quell-Konzept:** _meta/bc-cut-decisions.md Z. 1880, FK-29 §29.1.2, FK-33 §33.1, FK-34 §34.1, FK-41 §41.x, formal-spec/architecture-conformance/entities.md

---

## Kontext

Die Konzepte verweisen durchgaengig auf den Modul-Pfad
`agentkit.verify_system.*` fuer alle Komponenten des BC verify-system:

- `agentkit.verify_system.policy_engine` (FK-33 §33.1, _meta Z. 202)
- `agentkit.verify_system.llm_evaluator` (FK-34 §34.x, FK-29 §29.1.2,
  FK-41 §41.x, formal-spec/architecture-conformance Z. 230)
- `agentkit.verify_system.adversarial_orchestrator` (_meta Z. 201,
  formal-spec Z. 257)
- `agentkit.verify_system.stage_registry` (FK-33 §33.1)

Im Code lebt das aber unter `agentkit.qa.*`:
- `src/agentkit/qa/policy_engine/`
- `src/agentkit/qa/evaluators/reviewer.py`
- `src/agentkit/qa/adversarial/challenger.py`
- `src/agentkit/qa/structural/`
- `src/agentkit/qa/remediation/`
- `src/agentkit/qa/evidence/`
- `src/agentkit/qa/reports/`
- `src/agentkit/qa/artifacts.py`
- `src/agentkit/qa/prompt_audit.py`

`src/agentkit/verify_system/` existiert, enthaelt aber nur
`stage_registry/` und `qa_read_models.py`.

Das ist ein klassisches Code-vs-Konzept-Drift: `_meta/bc-cut-decisions.md`
Z. 1880 listet "agentkit.llm_evaluator -> agentkit.verify_system.llm_evaluator"
explizit als ausstehende Refactor-Aufgabe; Z. 229 erwaehnt die Migration
ebenso.

## Scope

### In Scope

- Modul-Verschiebung von `src/agentkit/qa/*` nach
  `src/agentkit/verify_system/*`:
  - `qa/policy_engine/` -> `verify_system/policy_engine/`
  - `qa/evaluators/` -> `verify_system/llm_evaluator/`
  - `qa/adversarial/` -> `verify_system/adversarial_orchestrator/`
  - `qa/structural/` -> `verify_system/structural/`
  - `qa/remediation/` -> `verify_system/remediation/`
  - `qa/evidence/` -> `verify_system/evidence/`
  - `qa/reports/` -> `verify_system/reports/`
  - `qa/artifacts.py` -> `verify_system/artifacts.py`
  - `qa/prompt_audit.py` -> `verify_system/prompt_audit.py`
- Alle Imports im Code anpassen (`from agentkit.qa.*` -> `from agentkit.verify_system.*`)
- Tests gleich strukturieren: `tests/unit/qa/*` -> `tests/unit/verify_system/*`
- Architektur-Conformance-Check (`scripts/ci/check_architecture_conformance.py`)
  laeuft gruen — formal-spec/architecture-conformance erwartet bereits
  die neuen Pfade
- `agentkit.qa`-Top-Package entfernen (vollstaendig leer nach Migration)
- pyproject.toml und alle Test-Imports konsistent

### Out of Scope

- Funktionale Aenderungen — reines Modul-Rename
- Schema-Versionierung (kein DB-Schema betroffen)
- Konzept-Updates (Konzepte sind bereits auf neuen Pfad)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/qa/**` | Verschoben | komplett nach `src/agentkit/verify_system/**` |
| `src/agentkit/qa/__init__.py` | Geloescht | Top-Package entfaellt |
| `tests/unit/qa/**` | Verschoben | komplett nach `tests/unit/verify_system/**` |
| `src/agentkit/**/*.py` | Modifiziert | Import-Anpassung (`from agentkit.qa` -> `from agentkit.verify_system`) |
| `tests/**/*.py` | Modifiziert | Import-Anpassung |

## Akzeptanzkriterien

1. `from agentkit.qa` existiert nicht mehr im Code (`grep` liefert 0 Treffer).
2. Alle Module liegen unter `agentkit.verify_system.*` mit Naming
   gemaess Konzept (`policy_engine`, `llm_evaluator`,
   `adversarial_orchestrator`, `structural`, `remediation`, `evidence`,
   `reports`, `artifacts`, `prompt_audit`, `stage_registry`).
3. Alle Tests gruen.
4. `mypy src` clean.
5. `ruff check src tests` clean.
6. `scripts/ci/check_architecture_conformance.py` gruen.

## Definition of Done

- Build kompiliert
- Tests gruen — vor und nach der Migration identisch
- mypy strict
- Architektur-Conformance-Check gruen
- Imports alphabetisch sortiert (ruff isort)

## Konzept-Referenzen

- _meta/bc-cut-decisions.md Z. 1880 (Refactor-Liste Punkt 4)
- _meta/bc-cut-decisions.md Z. 198-202 (BC-7-Top-Surface-Tabelle)
- FK-29 §29.1.2 (Mermaid-Verweise auf agentkit.verify_system.llm_evaluator)
- FK-33 §33.1 (Architekturzuordnung StageRegistry/PolicyEngine)
- FK-34 §34.1 (Sub-Pfade)
- FK-41 §41.x (LlmEvaluator-Referenzen)
- formal-spec/architecture-conformance/entities.md Z. 230, 257, 266

## Guardrail-Referenzen

- FIX THE MODEL, NOT THE SYMPTOM: BC-Schnitt im Code muss zum BC-Schnitt
  im Konzept passen
- ZERO DEBT: kein paralleler `qa.*`/`verify_system.*`-Zustand
- SINGLE SOURCE OF TRUTH: ein Modul-Heimatpfad pro Komponente
