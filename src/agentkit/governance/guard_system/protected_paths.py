"""Protected-Path-Konstanten fuer den QA-Artefakt-Schutz.

Kanonischer Ort: ``agentkit.governance.guard_system.protected_paths``.

Begruendung (FK-31 §31.3 + bc-cut-decisions.md §BC 4 + Refactor-Liste Pkt. 24):
- Die Konstanten konfigurieren den ``qa-artifact-protection``-Hook des
  GuardSystems (FK-31 §31.3, Z. 420-487).
- BC-Cut §BC 4 positioniert das GuardSystem unter ``agentkit.governance.guard_system``.
- Refactor-Pkt. 24: "PROTECTED_ARTIFACTS-Liste gehoert zur Hook-Konfiguration
  in BC 4 (governance.guard_system), nicht zu artifacts oder state_backend".

Truth-Boundary-Disziplin: ``agentkit.governance`` ist
``protected_module_prefix`` laut
``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52.
Die Wire-String-Literale ("structural.json", "decision.json", ...)
duerfen daher nicht **in** diesem Modul stehen. Sie leben als
Cross-Cutting-Konstanten in ``agentkit.core_types.qa_artifact_names``
und werden hier nur zur Tuple-Konfiguration des Hooks importiert.

Quelle:
- FK-31 §31.3 — ``concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md``
  (Z. 420-487)
- ``concept/_meta/bc-cut-decisions.md §BC 4`` — Z. 285-338
- ``concept/_meta/bc-cut-decisions.md §BC 8 Refactor-Liste Pkt. 24`` — Z. 1900
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52
"""

from __future__ import annotations

from agentkit.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)

#: Schutzliste aller QA-Artefakt-Dateinamen (FK-31 §31.3 + FK-27 §27.7).
#: Schreibzugriff durch Sub-Agents auf diese Dateien ist im GuardSystem
#: geblockt, solange der QA-Artifact-Lock aktiv ist (FK-31 §31.3).
#: Enthaelt alle 6 FK-27-Artefakte + das Guardrail-Artefakt.
PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
)

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "PROTECTED_QA_ARTIFACTS",
    "VERIFY_DECISION_FILE",
]
