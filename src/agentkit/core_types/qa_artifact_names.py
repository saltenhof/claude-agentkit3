"""Wire-string constants for QA-artifact filenames (cross-cutting).

This module position holds the canonical wire strings of the QA artifacts
as pure data values without BC responsibility. It is cross-cutting and
NOT part of a protected module-prefix area per
``concept/formal-spec/truth-boundary-checker/invariants.md`` (see
``protected_module_prefixes``: ``agentkit.governance`` / ``agentkit.pipeline``
/ ``agentkit.qa.structural`` may not contain these strings literally).

Callers:
- ``agentkit.state_backend`` (persistence, projection write path) — may
  use the strings productively (state_backend is a T-driver, not
  protected).
- ``agentkit.governance.guard_system.protected_paths`` — imports the
  strings here and bundles them into the hook-configuration tuple. This
  keeps the literals out of the governance namespace
  (truth-boundary conformance).

Concept anchors:
- ``FK-31 §31.3`` — QA-artifact protection (hook configuration in
  governance.guard_system).
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` lines 24-52
  (protected/allowed module prefixes; forbidden_json_truth_filenames).
- ``concept/_meta/bc-cut-decisions.md §BC 8 refactor list item 24``.
- ``FK-27 §27.7`` — canonical filenames for all 6 QA artifacts.
"""

from __future__ import annotations

#: Canonical layer filenames per FK-27 §27.7 (individual constants).
_STRUCTURAL_FILE: str = "structural.json"
_QA_REVIEW_FILE: str = "qa_review.json"
_SEMANTIC_REVIEW_FILE: str = "semantic_review.json"
#: Public alias (SSOT for verify_system._artifact_specs, AG3-034 R2-H).
DOC_FIDELITY_FILE: str = "doc_fidelity.json"
_DOC_FIDELITY_FILE: str = DOC_FIDELITY_FILE
_ADVERSARIAL_FILE: str = "adversarial.json"

#: Layer-artifact filenames per FK-27 §27.7.
#: Contains all data layers (structural, all three Layer-2 reviewers,
#: adversarial). Layer 2 has three standalone artifacts (underscore
#: convention per FK-27 §27.7).
LAYER_ARTIFACT_FILES: dict[str, str] = {
    "structural": _STRUCTURAL_FILE,
    "adversarial": _ADVERSARIAL_FILE,
    # Layer-2 sub-artifacts (FK-27 §27.7, underscore convention).
    "qa_review": _QA_REVIEW_FILE,
    "semantic_review": _SEMANTIC_REVIEW_FILE,
    "doc_fidelity": _DOC_FIDELITY_FILE,
}

#: Layer-2 sub-artifacts (FK-27 §27.7): all three Layer-2 reviewer outputs.
QA_LAYER2_FILES: tuple[str, str, str] = (
    _QA_REVIEW_FILE,
    _SEMANTIC_REVIEW_FILE,
    _DOC_FIDELITY_FILE,
)

#: Filename of the policy-decision artifact (Layer 4, FK-27 §27.7).
#: Canonical name: ``decision.json`` (not ``verify-decision.json``).
VERIFY_DECISION_FILE: str = "decision.json"

#: Stage string for the policy-decision artifact.
#: Canonical: ``qa-policy-decision`` (not ``qa-verify-decision``).
VERIFY_DECISION_STAGE: str = "qa-policy-decision"

#: Canonical QA layer stage IDs (FK-27 §27.7).  This cross-cutting module is the
#: SINGLE SOURCE OF TRUTH for the QA layer stage/producer strings (AG3-034 R2-H):
#: both ``verify_system`` (``_artifact_specs`` / ``artifacts`` / ``register``)
#: and the IntegrityGate (FK-35 §35.2.4) import these constants — neither
#: re-types the literals (no second naming truth).
STRUCTURAL_STAGE: str = "qa-layer-structural"
QA_REVIEW_STAGE: str = "qa-layer-qa-review"
SEMANTIC_REVIEW_STAGE: str = "qa-layer-semantic-review"
DOC_FIDELITY_STAGE: str = "qa-layer-doc-fidelity"
ADVERSARIAL_STAGE: str = "qa-layer-adversarial"

#: Canonical QA layer producer names (FK-27 §27.7).  These are the REAL
#: producer.name values the QA layers stamp onto their envelopes and the SINGLE
#: SOURCE OF TRUTH consumed by ``verify_system`` (``_artifact_specs`` /
#: ``artifacts`` / ``register``) AND the IntegrityGate.  FK-35 §35.2.4 names the
#: producers illustratively (``qa-structural-check`` / ``qa-policy-engine`` /
#: ``qa-adversarial``); the canonical AK3 producer ids below are authoritative
#: (no second naming truth).
STRUCTURAL_PRODUCER: str = "verify-system.layer-1-structural"
QA_REVIEW_PRODUCER: str = "verify-system.layer-2-qa-review"
SEMANTIC_REVIEW_PRODUCER: str = "verify-system.layer-2-semantic-review"
DOC_FIDELITY_PRODUCER: str = "verify-system.layer-2-doc-fidelity"
CONTEXT_SUFFICIENCY_PRODUCER: str = "verify-system.layer-2-context-sufficiency"
ADVERSARIAL_PRODUCER: str = "verify-system.layer-3-adversarial"
SONARQUBE_GATE_PRODUCER: str = "verify-system.layer-1-sonarqube-gate"
CONCEPT_FEEDBACK_PRODUCER: str = "verify-system.layer-2-concept-feedback"
RESEARCH_QUALITY_PRODUCER: str = "verify-system.layer-1-research-quality"
VERIFY_DECISION_PRODUCER: str = "verify-system.layer-4-policy"
POLICY_PRODUCER: str = VERIFY_DECISION_PRODUCER
BUGFIX_REPRODUCER_MANIFEST_PRODUCER: str = STRUCTURAL_PRODUCER
BUGFIX_RED_EVIDENCE_PRODUCER: str = STRUCTURAL_PRODUCER
BUGFIX_GREEN_EVIDENCE_PRODUCER: str = STRUCTURAL_PRODUCER
BUGFIX_SUITE_EVIDENCE_PRODUCER: str = STRUCTURAL_PRODUCER
BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER: str = STRUCTURAL_PRODUCER

#: Filename of the guardrail artifact (see FK-31 §31.3).
GUARDRAIL_FILE: str = "guardrail.json"

#: Filename of the exploration change-frame artifact per FK-23 §23.4.3 -- stored
#: under ``_temp/qa/{story_id}/``. Cross-cutting SSOT for the wire string: the
#: exploration worker (AG3-055, BC ``agent-skills``) writes the file, the QA
#: artifact protection (``governance.guard_system.protected_paths``) registers
#: the path. Not a QA-layer artifact -- deliberately NOT part of
#: ``ALL_QA_ARTIFACT_FILES``; only co-located under ``_temp/qa/{story_id}/``
#: (shared protection mechanism, FK-23 §23.4.3 / FK-31 §31.3).
CHANGE_FRAME_FILE: str = "change_frame.json"

#: Filename of the RAW worker change-frame draft (FK-23 §23.3.2 step 6 output),
#: under ``_temp/qa/{story_id}/``. The exploration worker (AG3-055) emits its
#: seven-part draft here; the productive ``ExplorationWorkerRunner`` adapter reads
#: it back across the LLM/worker boundary, and the ``ExplorationDrafting`` core
#: validates it and writes the canonical ``change_frame.json`` (above). Kept
#: SEPARATE from the canonical file so the worker's raw, pre-validation output is
#: never confused with the protected, validated change-frame the AG3-045 handler
#: consumes. Cross-cutting SSOT for the wire string.
CHANGE_FRAME_DRAFT_FILE: str = "change_frame.draft.json"

#: Canonical worker handover filenames (FK-27 §27.4.1). These are cross-cutting
#: wire strings used by implementation handover production, structural artifact
#: checks, and terminality gates. FK-27 remains the semantic owner; this module
#: owns only the filename SSOT.
PROTOCOL_FILE: str = "protocol.md"
WORKER_MANIFEST_FILE: str = "worker-manifest.json"
HANDOVER_FILE: str = "handover.json"

#: POSIX-relative root segment of the Layer-3 adversarial sandbox (AG3-044,
#: FK-48 §48.1): adversarial spawns write tests under
#: ``_temp/adversarial/{story_id}/{epoch}/``. Cross-cutting SSOT for the wire
#: string: the AdversarialSpawner uses it, the QA-artifact protection
#: (``governance.guard_system.protected_paths``) registers the prefix as a
#: Protected-Path. The literal must NOT live in the protected governance
#: namespace (truth boundary), so it lives here and is re-exported there.
ADVERSARIAL_SANDBOX_PREFIX: str = "_temp/adversarial/"

#: All 6 FK-27 §27.7 artifact filenames as a protection set (FK-31 §31.3).
ALL_QA_ARTIFACT_FILES: tuple[str, ...] = (
    _STRUCTURAL_FILE,
    _QA_REVIEW_FILE,
    _SEMANTIC_REVIEW_FILE,
    _DOC_FIDELITY_FILE,
    _ADVERSARIAL_FILE,
    VERIFY_DECISION_FILE,
)

__all__ = [
    "ADVERSARIAL_PRODUCER", "ADVERSARIAL_SANDBOX_PREFIX", "ADVERSARIAL_STAGE", "ALL_QA_ARTIFACT_FILES",
    "BUGFIX_GREEN_EVIDENCE_PRODUCER", "BUGFIX_RED_EVIDENCE_PRODUCER", "BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER",
    "BUGFIX_REPRODUCER_MANIFEST_PRODUCER", "BUGFIX_SUITE_EVIDENCE_PRODUCER",
    "CHANGE_FRAME_DRAFT_FILE", "CHANGE_FRAME_FILE", "CONCEPT_FEEDBACK_PRODUCER", "CONTEXT_SUFFICIENCY_PRODUCER",
    "DOC_FIDELITY_FILE", "DOC_FIDELITY_PRODUCER", "DOC_FIDELITY_STAGE", "GUARDRAIL_FILE", "HANDOVER_FILE",
    "LAYER_ARTIFACT_FILES", "POLICY_PRODUCER", "PROTOCOL_FILE", "QA_LAYER2_FILES",
    "QA_REVIEW_PRODUCER", "QA_REVIEW_STAGE", "RESEARCH_QUALITY_PRODUCER",
    "SEMANTIC_REVIEW_PRODUCER", "SEMANTIC_REVIEW_STAGE", "SONARQUBE_GATE_PRODUCER",
    "STRUCTURAL_PRODUCER", "STRUCTURAL_STAGE", "VERIFY_DECISION_FILE",
    "VERIFY_DECISION_PRODUCER", "VERIFY_DECISION_STAGE", "WORKER_MANIFEST_FILE",
]
