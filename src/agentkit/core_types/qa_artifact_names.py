"""Wire-String-Konstanten fuer QA-Artefakt-Dateinamen (Cross-Cutting).

Diese Modulposition haelt die kanonischen Wire-Strings der QA-Artefakte
als reine Datenwerte ohne BC-Verantwortung. Sie ist Cross-Cutting und
NICHT Teil eines geschuetzten Modul-Prefix-Bereichs nach
``concept/formal-spec/truth-boundary-checker/invariants.md`` (siehe
``protected_module_prefixes``: ``agentkit.governance`` / ``agentkit.pipeline``
/ ``agentkit.qa.structural`` duerfen diese Strings literal nicht
enthalten).

Aufrufer:
- ``agentkit.state_backend`` (Persistenz, Projection-Schreibpfad) — darf
  die Strings produktiv nutzen (state_backend ist T-Treiber, nicht
  protected).
- ``agentkit.governance.guard_system.protected_paths`` — importiert die
  Strings hier und buendelt sie zur Hook-Konfigurations-Tuple. Damit
  bleiben die Literale aus dem governance-Namespace draussen
  (Truth-Boundary-Conformance).

Konzept-Anker:
- ``FK-31 §31.3`` — QA-Artefakt-Schutz (Hook-Konfiguration in
  governance.guard_system).
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52
  (protected/allowed module prefixes; forbidden_json_truth_filenames).
- ``concept/_meta/bc-cut-decisions.md §BC 8 Refactor-Liste Pkt. 24``.
- ``FK-27 §27.7`` — kanonische Dateinamen fuer alle 6 QA-Artefakte.
"""

from __future__ import annotations

#: Kanonische Layer-Dateinamen nach FK-27 §27.7 (Einzelkonstanten).
_STRUCTURAL_FILE: str = "structural.json"
_QA_REVIEW_FILE: str = "qa_review.json"
_SEMANTIC_REVIEW_FILE: str = "semantic_review.json"
_DOC_FIDELITY_FILE: str = "doc_fidelity.json"
_ADVERSARIAL_FILE: str = "adversarial.json"

#: Layer-Artefakt-Dateinamen nach FK-27 §27.7.
#: Enthaelt alle Datenschichten (strukturell, alle drei Layer-2-Reviewer,
#: adversarial). Layer-2 hat drei eigenstaendige Artefakte (Underscore-
#: Konvention gemaess FK-27 §27.7).
LAYER_ARTIFACT_FILES: dict[str, str] = {
    "structural": _STRUCTURAL_FILE,
    "adversarial": _ADVERSARIAL_FILE,
    # Layer-2 Sub-Artefakte (FK-27 §27.7, Underscore-Konvention).
    "qa_review": _QA_REVIEW_FILE,
    "semantic_review": _SEMANTIC_REVIEW_FILE,
    "doc_fidelity": _DOC_FIDELITY_FILE,
}

#: Layer-2 Sub-Artefakte (FK-27 §27.7): alle drei Layer-2-Reviewer-Outputs.
QA_LAYER2_FILES: tuple[str, str, str] = (
    _QA_REVIEW_FILE,
    _SEMANTIC_REVIEW_FILE,
    _DOC_FIDELITY_FILE,
)

#: Dateiname des Policy-Decision-Artefakts (Layer 4, FK-27 §27.7).
#: Kanonischer Name: ``decision.json`` (nicht ``verify-decision.json``).
VERIFY_DECISION_FILE: str = "decision.json"

#: Stage-String fuer das Policy-Decision-Artefakt.
#: Kanonisch: ``qa-policy-decision`` (nicht ``qa-verify-decision``).
VERIFY_DECISION_STAGE: str = "qa-policy-decision"

#: Dateiname des Guardrail-Artefakts (siehe FK-31 §31.3).
GUARDRAIL_FILE: str = "guardrail.json"

#: Alle 6 FK-27 §27.7-Artefakt-Dateinamen als Schutzmenge (FK-31 §31.3).
ALL_QA_ARTIFACT_FILES: tuple[str, ...] = (
    _STRUCTURAL_FILE,
    _QA_REVIEW_FILE,
    _SEMANTIC_REVIEW_FILE,
    _DOC_FIDELITY_FILE,
    _ADVERSARIAL_FILE,
    VERIFY_DECISION_FILE,
)

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "QA_LAYER2_FILES",
    "VERIFY_DECISION_FILE",
    "VERIFY_DECISION_STAGE",
]
