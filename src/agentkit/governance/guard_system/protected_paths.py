"""Protected-Path-Konstanten fuer den QA-Artefakt-Schutz.

Kanonischer Ort: ``agentkit.governance.guard_system.protected_paths``.

Begruendung (FK-31 §31.3 + bc-cut-decisions.md §BC 4 + Refactor-Liste Pkt. 24):
- Die Konstanten konfigurieren den ``qa-artifact-protection``-Hook des
  GuardSystems (FK-31 §31.3, Z. 420-487).
- BC-Cut §BC 4 positioniert das GuardSystem unter ``agentkit.governance.guard_system``.
- Refactor-Pkt. 24: "PROTECTED_ARTIFACTS-Liste gehoert zur Hook-Konfiguration
  in BC 4 (governance.guard_system), nicht zu artifacts oder state_backend".

Migrationspfad: Die Konstanten waren zuvor in ``agentkit.state_backend.paths``.
  Kein Re-Export-Shim dort; keine Re-Exports aus ``agentkit.governance``-Top-Level.
  Einziger kanonischer Importpfad: dieses Modul.

Quelle:
- FK-31 §31.3 — ``concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md``
  (Z. 420-487)
- ``concept/_meta/bc-cut-decisions.md §BC 4`` — Z. 285-338
- ``concept/_meta/bc-cut-decisions.md §BC 8 Refactor-Liste Pkt. 24`` — Z. 1900
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Layer-Artefakt-Dateinamen pro QA-Layer (FK-31 §31.3)
# ---------------------------------------------------------------------------

#: Kanonische Dateinamen pro QA-Layer-Name.
LAYER_ARTIFACT_FILES: dict[str, str] = {
    "structural": "structural.json",
    "semantic": "semantic-review.json",
    "adversarial": "adversarial.json",
}

#: Dateiname des Verify-Decision-Artefakts.
VERIFY_DECISION_FILE: str = "verify-decision.json"

#: Dateiname des Guardrail-Artefakts.
GUARDRAIL_FILE: str = "guardrail.json"

#: Schutzliste aller QA-Artefakt-Dateinamen.
#: Schreibzugriff durch Sub-Agents auf diese Dateien ist im GuardSystem
#: geblockt, solange der QA-Artifact-Lock aktiv ist (FK-31 §31.3).
PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *LAYER_ARTIFACT_FILES.values(),
    GUARDRAIL_FILE,
    VERIFY_DECISION_FILE,
)

__all__ = [
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "PROTECTED_QA_ARTIFACTS",
    "VERIFY_DECISION_FILE",
]
