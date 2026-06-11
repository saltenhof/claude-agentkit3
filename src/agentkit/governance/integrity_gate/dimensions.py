"""IntegrityGate dimensions — the nine canonical FK-35 §35.2.4 dimensions.

FK-35 §35.2.3 (mandatory-artifact pre-stage) + §35.2.4 (nine dimensions).
Each dimension verifies the EXACT FK-35 §35.2.4(a) condition against the
canonical QA ``ArtifactEnvelope`` (``artifact_envelopes``) — producer / status /
payload depth / threshold — not merely artifact existence (AG3-034 Remediation
E-A, ZERO DEBT "verifies mandatory fields, not only existence").

| Dim | ID (FK-35 §35.2.4)  | Verified condition (FK-35 §35.2.4)                 |
|-----|---------------------|----------------------------------------------------|
| 1   | NO_QA_ARTIFACTS     | mandatory QA artifact_records for the story exist  |
| 2   | CONTEXT_INVALID     | context record present + valid (status PASS+ids)   |
| 3   | STRUCTURAL_SHALLOW  | structural envelope >500B, >=5 checks, structural producer |
| 4   | DECISION_INVALID    | decision envelope >200B, has ``major_threshold``, policy producer |
| 5   | NO_LLM_REVIEW       | llm(qa)-review + semantic-review envelopes exist, status != skipped/error |
| 6   | NO_ADVERSARIAL      | adversarial envelope exists, >200B, adversarial producer |
| 7   | NO_VERIFY           | latest QA-subflow decision verdict == PASS         |
| 8   | TIMESTAMP_INVERSION | context(record).finished_at < decision(env).finished_at |
| 9   | SONARQUBE_GREEN     | commit-bound Sonar attestation green (FK-35 §35.2.4a) |

**Producer-name reconciliation (no second truth):** FK-35 §35.2.4 names the QA
producers illustratively (``qa-structural-check`` / ``qa-policy-engine`` /
``qa-adversarial``).  The CANONICAL AK3 producer ids the QA layers actually
stamp onto the envelopes are owned by
:mod:`agentkit.core_types.qa_artifact_names` (``STRUCTURAL_PRODUCER`` etc.) — the
cross-cutting SINGLE SOURCE OF TRUTH that ``verify_system`` ALSO imports (R2-H,
no second naming truth).  Dim 3/4/6 verify against those canonical ids.

Dimensions 1, 2, 4 are the hard mandatory-artifact pre-stage (FK-35 §35.2.3):
a missing one aborts with that ``MISSING_*`` failure reason and the remaining
dimensions are reported as blocked.  EVERY mandatory artifact is additionally
field-validated (AG3-034 AK7 / E-F / R2-F): the structural (Dim 1) and decision
(Dim 4) QA envelopes via the FK-71 §71.2 ``EnvelopeValidator``, and the context
record (Dim 2) via its own FK-35 §35.2.4 field check (present + story_id +
run_id — it is NOT a QA envelope).  A violation fails with ``ENVELOPE_VIOLATION``.

Dimension 9 (SONARQUBE_GREEN, FK-35 §35.2.4a) only **verifies** the commit-bound
``sonarqube_gate`` attestation produced by the (out-of-scope) pre-merge scan via
the AG3-052 capability API, and only when the gate point is APPLICABLE.

All reads go through the injected :class:`IntegrityGateStatePort` (AG3-034 AK10)
— no direct state-backend imports.  The Sonar verification runs ONLY through the
``verify_system.sonarqube_gate`` capability API (AK12).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.governance.integrity_gate import _dimension_specs as _specs
from agentkit.governance.integrity_gate._dimension_specs import IntegrityDimension
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system import verify_decision_passed

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.validator import EnvelopeValidator
    from agentkit.governance.integrity_gate import (
        DimensionResult,
        IntegrityGateContext,
    )
    from agentkit.governance.repository import IntegrityGateStatePort
    from agentkit.state_backend.scope import RuntimeStateScope

# Public FK-35 §35.2.4 classification tables / FAIL-codes (SSOT in _specs).
MISSING_PRESTAGE_CODE = _specs.MISSING_PRESTAGE_CODE
MANDATORY_DIMENSIONS = _specs.MANDATORY_DIMENSIONS
CODE_ONLY_DIMENSIONS = _specs.CODE_ONLY_DIMENSIONS

#: Reason emitted when an envelope field validation fails (FK-71 §71.2, AK7).
ENVELOPE_VIOLATION = "ENVELOPE_VIOLATION"
#: Reason emitted when timestamp causality is violated (Dim 8, AK9).  The
#: canonical FK-35 §35.2.4 FAIL-code for the timestamp dimension.
TIMESTAMP_VIOLATION = "TIMESTAMP_INVERSION"

_CODE_TYPES: frozenset[StoryType] = frozenset(
    {StoryType.IMPLEMENTATION, StoryType.BUGFIX}
)


def required_phases_for(story_type: StoryType) -> tuple[str, ...]:
    """Return the mandatory phase snapshots per story type (SSOT, AG3-034 §2.1.4).

    Single source of truth for the Concept/Research drift fix
    (governance-and-guards.C4): one function, not copied tables.

    Args:
        story_type: The story type being evaluated.

    Returns:
        The ordered tuple of required phase names.

    Raises:
        ValueError: For an unknown story type (fail-closed).
    """
    if story_type in _CODE_TYPES:
        return ("setup", "implementation", "closure")
    if story_type in (StoryType.CONCEPT, StoryType.RESEARCH):
        return ("setup", "closure")
    raise ValueError(f"Unknown story_type: {story_type!r}")


def mandatory_dimensions_for(
    story_type: StoryType,
) -> tuple[IntegrityDimension, ...]:
    """Return the mandatory-artifact pre-stage dimensions for a story type.

    NO_QA_ARTIFACTS/DECISION_INVALID are QA artifacts and apply only to code
    stories (implementation/bugfix, FK-24 §24.3.1).  CONTEXT_INVALID is
    universal.

    Args:
        story_type: The story type being evaluated.

    Returns:
        The ordered mandatory dimensions for this type.
    """
    is_code = story_type in _CODE_TYPES
    return tuple(
        dim
        for dim in MANDATORY_DIMENSIONS
        if is_code or dim not in _specs.CODE_ONLY_MANDATORY
    )


def dimensions_for(
    story_type: StoryType,
    *,
    sonar_applicable: bool = False,
) -> tuple[IntegrityDimension, ...]:
    """Return the dimensions evaluated for a story type (AG3-034 §2.1.4).

    Dimensions 5/6 (NO_LLM_REVIEW, NO_ADVERSARIAL) and Dim 9 (SONARQUBE_GREEN)
    are evaluated ONLY for implementation/bugfix; for concept/research they are
    absent from the result (governance-and-guards.C4, AK8).  Dim 9 additionally
    requires the ``sonarqube_gate`` to be APPLICABLE (FK-33 §33.6.5): when
    Sonar is deliberately absent (``available == false``) or the run is fast,
    Dim 9 is not-applicable and is omitted (no ``SONAR_NOT_GREEN`` FAIL — absent
    is not broken, FK-35 §35.2.4a).

    Args:
        story_type: The story type being evaluated.
        sonar_applicable: Whether the ``sonarqube_gate`` resolved APPLICABLE
            for this run (``available == true`` AND ``mode != fast`` AND code
            story).  Only then is Dim 9 evaluated.

    Returns:
        The ordered tuple of dimensions to evaluate (post-mandatory-stage).
    """
    ordered = (
        IntegrityDimension.STRUCTURAL_SHALLOW,
        IntegrityDimension.NO_LLM_REVIEW,
        IntegrityDimension.NO_ADVERSARIAL,
        IntegrityDimension.NO_VERIFY,
        IntegrityDimension.TIMESTAMP_INVERSION,
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
        IntegrityDimension.SONARQUBE_GREEN,
    )
    is_code = story_type in _CODE_TYPES
    selected: list[IntegrityDimension] = []
    for dim in ordered:
        if not is_code and dim in _specs.CODE_ONLY_EVALUATED:
            continue
        if dim is IntegrityDimension.SONARQUBE_GREEN and not sonar_applicable:
            # not-applicable (available==false / fast) -> Dim 9 omitted (skip).
            continue
        selected.append(dim)
    return tuple(selected)


# ---------------------------------------------------------------------------
# Canonical QA-envelope read helpers (FK-35 §35.2.4 verify-against-artefact)
# ---------------------------------------------------------------------------


def _qa_envelope(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
    stage: str,
) -> ArtifactEnvelope | None:
    """Load the latest canonical QA envelope for a stage via the state port."""
    return state_port.find_latest_qa_envelope(gate_ctx.story_dir, runtime_scope, stage)


def _payload_byte_size(envelope: ArtifactEnvelope) -> int:
    """Return the canonical serialized payload byte size (FK-35 depth checks)."""
    payload = envelope.payload or {}
    return len(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _structural_check_count(envelope: ArtifactEnvelope) -> int:
    """Return the structural layer's executed-check count (Dim 3)."""
    payload = envelope.payload or {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        total = metadata.get("total_checks")
        if isinstance(total, int) and total >= 0:
            return total
    findings = payload.get("findings")
    return len(findings) if isinstance(findings, list) else 0


def evaluate_mandatory_artifact(
    dimension: IntegrityDimension,
    gate_ctx: IntegrityGateContext,
    *,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
    envelope_validator: EnvelopeValidator | None,
) -> DimensionResult:
    """Evaluate one mandatory-artifact pre-stage dimension (FK-35 §35.2.3).

    Existence is the hard pre-condition.  For the structural (Dim 1) and the
    decision (Dim 4) mandatory dimensions the envelope field validation (FK-71
    §71.2) additionally runs over the canonical QA envelope when an
    :class:`EnvelopeValidator` is wired; a violation maps to
    ``ENVELOPE_VIOLATION`` (AK7 / E-F).  Each mandatory QA envelope is
    validated — not only the structural one.

    Args:
        dimension: The mandatory dimension to evaluate.
        gate_ctx: Story directory + type context.
        state_port: Read-only state access port.
        runtime_scope: Resolved runtime scope (may be ``None``).
        envelope_validator: Optional envelope field validator (FK-71 §71.2).

    Returns:
        The :class:`DimensionResult` for this mandatory dimension.
    """
    from agentkit.governance.integrity_gate import DimensionResult

    present, detail = _mandatory_present(
        dimension, gate_ctx, state_port, runtime_scope
    )
    if not present:
        return DimensionResult(
            dimension=dimension,
            passed=False,
            failure_reason=MISSING_PRESTAGE_CODE[dimension],
            detail=detail,
        )
    # E-F: validate the canonical QA envelope of every mandatory QA artifact.
    violation = _mandatory_envelope_violation(
        dimension, gate_ctx, state_port, runtime_scope, envelope_validator
    )
    if violation is not None:
        return DimensionResult(
            dimension=dimension,
            passed=False,
            failure_reason=ENVELOPE_VIOLATION,
            detail=violation,
        )
    # FK-35 §35.2.4 Dim 2 (CONTEXT_INVALID, R2-F): the context ArtifactRecord is
    # not a QA envelope, so it carries its OWN field validation (present +
    # story_id + run_id) — story-AC AK7 validates EVERY mandatory artifact, not
    # only the QA envelopes.  A violation fails closed with ``ENVELOPE_VIOLATION``.
    if dimension is IntegrityDimension.CONTEXT_INVALID:
        context_problem = state_port.validate_context_record(
            gate_ctx.story_dir, runtime_scope
        )
        if context_problem is not None:
            return DimensionResult(
                dimension=dimension,
                passed=False,
                failure_reason=ENVELOPE_VIOLATION,
                detail=context_problem,
            )
    # FK-35 §35.2.4 Dim 4 (DECISION_INVALID) depth: the canonical decision
    # envelope must be > 200 bytes, carry ``major_threshold`` and the policy
    # producer — not merely exist.
    if dimension is IntegrityDimension.DECISION_INVALID:
        depth_problem = _decision_depth_problem(
            gate_ctx, state_port, runtime_scope
        )
        if depth_problem is not None:
            return DimensionResult(
                dimension=dimension,
                passed=False,
                failure_reason=dimension.value,
                detail=depth_problem,
            )
    return DimensionResult(dimension=dimension, passed=True, detail=detail)


def _decision_depth_problem(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> str | None:
    """Return a FK-35 §35.2.4 Dim-4 depth problem for the decision envelope.

    Verifies the canonical decision envelope is substantive: payload > 200
    bytes AND carries ``major_threshold`` AND was produced by the policy
    producer.  ``None`` when all conditions hold.
    """
    try:
        envelope = _qa_envelope(
            gate_ctx, state_port, runtime_scope, _specs.VERIFY_DECISION_STAGE
        )
    except CorruptStateError as exc:
        return f"corrupt state reading decision envelope: {exc}"
    if envelope is None:
        return "decision envelope absent for depth verification"
    payload = envelope.payload or {}
    byte_size = _payload_byte_size(envelope)
    problems: list[str] = []
    if byte_size <= _specs.DECISION_MIN_BYTES:
        problems.append(f"payload {byte_size}B <= {_specs.DECISION_MIN_BYTES}B")
    if "major_threshold" not in payload:
        problems.append("missing major_threshold")
    if envelope.producer.name != _specs.VERIFY_DECISION_PRODUCER:
        problems.append(
            f"producer {envelope.producer.name!r} != "
            f"{_specs.VERIFY_DECISION_PRODUCER!r}"
        )
    return "decision shallow: " + "; ".join(problems) if problems else None


def _mandatory_present(
    dimension: IntegrityDimension,
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> tuple[bool, str]:
    """Return (present, detail) for a mandatory artifact via the state port."""
    story_dir = gate_ctx.story_dir
    try:
        if dimension is IntegrityDimension.NO_QA_ARTIFACTS:
            present = _structural_present(story_dir, state_port, runtime_scope)
            return present, "Structural QA artifact"
        if dimension is IntegrityDimension.DECISION_INVALID:
            payload = _decision_payload(story_dir, state_port, runtime_scope)
            return payload is not None, "Verify decision record"
        present = state_port.has_valid_context(story_dir)
        return present, "Story context record"
    except CorruptStateError as exc:
        return False, f"corrupt state: {exc}"


def _mandatory_envelope_violation(
    dimension: IntegrityDimension,
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
    envelope_validator: EnvelopeValidator | None,
) -> str | None:
    """Validate the mandatory QA envelope for a dimension (FK-71 §71.2, E-F).

    The structural (Dim 1) and decision (Dim 4) dimensions own canonical QA
    envelopes; the context dimension (Dim 2) is not a QA envelope so it carries
    no envelope-field validation here.  A missing-but-mandatory QA envelope is
    a fail-closed ``ENVELOPE_VIOLATION`` (the existence pre-check already
    guarantees the record, so absence here is an inconsistency).
    """
    if envelope_validator is None:
        return None
    stage = _specs.MANDATORY_ENVELOPE_STAGE.get(dimension)
    if stage is None:
        return None
    try:
        envelope = _qa_envelope(gate_ctx, state_port, runtime_scope, stage)
    except CorruptStateError as exc:
        return f"corrupt state reading {stage} envelope: {exc}"
    if envelope is None:
        return f"mandatory {stage} envelope missing for field validation"
    return _validate_envelope(envelope_validator, envelope)


def _structural_present(
    story_dir: Path,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> bool:
    """Return True when the structural artifact record is present."""
    if runtime_scope is not None and runtime_scope.run_id is not None:
        return state_port.has_structural_artifact_for_scope(runtime_scope)
    return state_port.has_structural_artifact(story_dir)


def _decision_payload(
    story_dir: Path,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> dict[str, object] | None:
    """Load the latest verify-decision payload via the state port."""
    if runtime_scope is not None and runtime_scope.run_id is not None:
        return state_port.load_latest_verify_decision_for_scope(runtime_scope)
    return state_port.load_latest_verify_decision(story_dir)


def _validate_envelope(
    validator: EnvelopeValidator,
    envelope: ArtifactEnvelope,
) -> str | None:
    """Run the envelope field validation; return a detail string on violation."""
    try:
        validator.validate(envelope)
    except Exception as exc:  # noqa: BLE001 -- any validation error is a violation
        return f"envelope validation failed: {type(exc).__name__}: {exc}"
    return None


def evaluate_dimension(
    dimension: IntegrityDimension,
    gate_ctx: IntegrityGateContext,
    *,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Evaluate one post-mandatory dimension (3,5,6,7,8) (FK-35 §35.2.4).

    Args:
        dimension: The dimension to evaluate.
        gate_ctx: Story directory + type context.
        state_port: Read-only state access port.
        runtime_scope: Resolved runtime scope (may be ``None``).

    Returns:
        The :class:`DimensionResult` for this dimension.
    """
    if dimension is IntegrityDimension.STRUCTURAL_SHALLOW:
        return _check_structural_depth(gate_ctx, state_port, runtime_scope)
    if dimension is IntegrityDimension.NO_LLM_REVIEW:
        return _check_llm_reviews(gate_ctx, state_port, runtime_scope)
    if dimension is IntegrityDimension.NO_ADVERSARIAL:
        return _check_adversarial(gate_ctx, state_port, runtime_scope)
    if dimension is IntegrityDimension.NO_VERIFY:
        return _check_qa_subflow_flow_end(gate_ctx, state_port, runtime_scope)
    if dimension is IntegrityDimension.CONFLICT_FREEZE_PROOF:
        return _check_conflict_freeze_proof(gate_ctx, state_port, runtime_scope)
    return _check_timestamp_causality(gate_ctx, state_port, runtime_scope)


def _check_structural_depth(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Dim 3 — STRUCTURAL_SHALLOW (FK-35 §35.2.4).

    Verifies the canonical structural envelope is substantive: serialized
    payload > 500 bytes AND total executed checks >= 5 AND
    ``producer.name == structural producer``.  A shallow/foreign-producer
    artifact fails closed.
    """
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.STRUCTURAL_SHALLOW
    try:
        envelope = _qa_envelope(
            gate_ctx, state_port, runtime_scope, _specs.STRUCTURAL_STAGE
        )
    except CorruptStateError as exc:
        return _fail(dim, dim.value, f"corrupt state: {exc}")
    if envelope is None:
        return _fail(dim, dim.value, "structural envelope absent")
    byte_size = _payload_byte_size(envelope)
    checks = _structural_check_count(envelope)
    producer = envelope.producer.name
    problems: list[str] = []
    if byte_size <= _specs.STRUCTURAL_MIN_BYTES:
        problems.append(f"payload {byte_size}B <= {_specs.STRUCTURAL_MIN_BYTES}B")
    if checks < _specs.STRUCTURAL_MIN_CHECKS:
        problems.append(f"checks {checks} < {_specs.STRUCTURAL_MIN_CHECKS}")
    if producer != _specs.STRUCTURAL_PRODUCER:
        problems.append(f"producer {producer!r} != {_specs.STRUCTURAL_PRODUCER!r}")
    if problems:
        return _fail(dim, dim.value, "structural shallow: " + "; ".join(problems))
    return DimensionResult(
        dimension=dim,
        passed=True,
        detail=f"structural depth ok ({byte_size}B, {checks} checks)",
    )


def _check_llm_reviews(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Dim 5 — NO_LLM_REVIEW (FK-35 §35.2.4).

    Both the qa-review AND the semantic-review envelopes must exist with a real
    review result (status not ``ERROR`` — AK3's "no LLM result" status, the
    FK-35 "Status != SKIPPED" intent).  A missing or result-less review fails.
    """
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.NO_LLM_REVIEW
    required = (
        (_specs.QA_REVIEW_STAGE, _specs.QA_REVIEW_PRODUCER),
        (_specs.SEMANTIC_REVIEW_STAGE, _specs.SEMANTIC_REVIEW_PRODUCER),
    )
    problems: list[str] = []
    try:
        for stage, expected_producer in required:
            envelope = _qa_envelope(gate_ctx, state_port, runtime_scope, stage)
            problems.extend(_review_problems(stage, expected_producer, envelope))
    except CorruptStateError as exc:
        return _fail(dim, dim.value, f"corrupt state: {exc}")
    if problems:
        return _fail(dim, dim.value, "; ".join(problems))
    return DimensionResult(
        dimension=dim,
        passed=True,
        detail="qa-review + semantic-review present with results",
    )


def _review_problems(
    stage: str,
    expected_producer: str,
    envelope: ArtifactEnvelope | None,
) -> list[str]:
    """Return Dim-5 problems for one review envelope (absent/skipped/foreign)."""
    if envelope is None:
        return [f"{stage} review missing"]
    problems: list[str] = []
    if envelope.status in _specs.NON_REVIEW_STATUSES:
        problems.append(f"{stage} status {envelope.status.value} (no review result)")
    if envelope.producer.name != expected_producer:
        problems.append(
            f"{stage} producer {envelope.producer.name!r} != {expected_producer!r}"
        )
    return problems


def _check_adversarial(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Dim 6 — NO_ADVERSARIAL (FK-35 §35.2.4 + FK-48 §48.1.6/§48.1.8, FK-11 §11.8.2).

    The adversarial envelope must exist, be > 200 bytes and carry the
    adversarial producer (the existing FK-35 §35.2.4 envelope proof).

    AG3-079 (FK-48 §48.1.6/§48.1.8, FK-11 §11.8.2): the SAME envelope additionally
    proves the MANDATORY sparring telemetry — its ``adversarial.json`` payload
    (the single source of truth the gate already reads, no second telemetry-read
    port) mirrors the emitted-event counts. Dim 6 verifies >= 1
    ``adversarial_sparring`` event AND >= 1 ``llm_call role=adversarial_sparring``
    plus the FK-48 §48.1.8 mandatory ``>= 1 executed test``; a missing fact fails
    closed.
    """
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.NO_ADVERSARIAL
    try:
        envelope = _qa_envelope(
            gate_ctx, state_port, runtime_scope, _specs.ADVERSARIAL_STAGE
        )
    except CorruptStateError as exc:
        return _fail(dim, dim.value, f"corrupt state: {exc}")
    if envelope is None:
        return _fail(dim, dim.value, "adversarial envelope absent")
    byte_size = _payload_byte_size(envelope)
    producer = envelope.producer.name
    problems: list[str] = []
    if byte_size <= _specs.ADVERSARIAL_MIN_BYTES:
        problems.append(f"payload {byte_size}B <= {_specs.ADVERSARIAL_MIN_BYTES}B")
    if producer != _specs.ADVERSARIAL_PRODUCER:
        problems.append(f"producer {producer!r} != {_specs.ADVERSARIAL_PRODUCER!r}")
    problems.extend(_adversarial_sparring_problems(envelope))
    if problems:
        return _fail(dim, dim.value, "adversarial: " + "; ".join(problems))
    return DimensionResult(
        dimension=dim,
        passed=True,
        detail=f"adversarial evidence + sparring telemetry ok ({byte_size}B)",
    )


def _adversarial_sparring_problems(envelope: ArtifactEnvelope) -> list[str]:
    """Return Dim-6 sparring-telemetry problems (FK-48 §48.1.6/§48.1.8, FK-11 §11.8.2).

    Verifies the FULL FK-48 §48.1.8 expectation table carried in the
    ``adversarial.json`` payload (the single source of truth the gate already
    reads — no second telemetry-read port):

    * ``adversarial_start`` — EXACTLY 1,
    * ``adversarial_end`` — EXACTLY 1,
    * ``adversarial_sparring`` — >= 1 (AND >= 1 ``llm_call
      role=adversarial_sparring``, FK-11 §11.8.2),
    * ``adversarial_test_created`` — >= 0 (trivially satisfied; verified
      non-negative/consistent),
    * ``adversarial_test_executed`` — >= 1.

    Any violation fails closed (the adversarial run did not really happen as
    specified).
    """
    payload = envelope.payload or {}
    # The canonical adversarial.json (materialised by the Layer-3 runtime) carries
    # the proof at the top level; the LayerResult projection nests it under
    # ``metadata``. Read top-level first, fall back to ``metadata`` (ONE proof
    # shape, two equivalent carriers — no second naming truth).
    metadata = payload.get("metadata")
    metadata_map = metadata if isinstance(metadata, dict) else {}
    problems: list[str] = []
    sparring = payload.get("sparring")
    if not isinstance(sparring, dict):
        sparring = metadata_map.get("sparring")
    if not isinstance(sparring, dict):
        return ["sparring telemetry proof missing (no 'sparring' in payload)"]
    sparring_events = _non_negative_int(sparring.get("adversarial_sparring_events"))
    llm_call_events = _non_negative_int(sparring.get("llm_call_sparring_events"))
    tests_executed = _non_negative_int(
        payload.get("tests_executed", metadata_map.get("tests_executed"))
    )
    if sparring_events < _specs.ADVERSARIAL_MIN_SPARRING_EVENTS:
        problems.append(
            f"adversarial_sparring events {sparring_events} < "
            f"{_specs.ADVERSARIAL_MIN_SPARRING_EVENTS}"
        )
    if llm_call_events < _specs.ADVERSARIAL_MIN_LLM_CALL_SPARRING_EVENTS:
        problems.append(
            f"llm_call role=adversarial_sparring events {llm_call_events} < "
            f"{_specs.ADVERSARIAL_MIN_LLM_CALL_SPARRING_EVENTS}"
        )
    if tests_executed < _specs.ADVERSARIAL_MIN_TESTS_EXECUTED:
        problems.append(
            f"tests_executed {tests_executed} < "
            f"{_specs.ADVERSARIAL_MIN_TESTS_EXECUTED}"
        )
    problems.extend(_adversarial_lifecycle_problems(payload, metadata_map))
    return problems


def _adversarial_lifecycle_problems(
    payload: dict[str, object],
    metadata_map: dict[str, object],
) -> list[str]:
    """Return Dim-6 §48.1.8 lifecycle-count problems (exactly-1 start/end etc.).

    Verifies the EXACT FK-48 §48.1.8 lifecycle counts from the ``telemetry``
    block of ``adversarial.json``: ``adversarial_start`` and ``adversarial_end``
    must be EXACTLY 1, ``adversarial_sparring``/``adversarial_test_executed``
    must be >= their minimums and ``adversarial_test_created`` must be a
    non-negative count (>= 0, trivially satisfied but verified consistent). The
    block is mandatory for a conformant run — its absence fails closed (the run
    did not record its lifecycle telemetry).
    """
    telemetry = payload.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = metadata_map.get("telemetry")
    if not isinstance(telemetry, dict):
        return ["adversarial telemetry counts missing (no 'telemetry' in payload)"]
    problems: list[str] = []
    start = _non_negative_int(telemetry.get("adversarial_start"))
    end = _non_negative_int(telemetry.get("adversarial_end"))
    sparring = _non_negative_int(telemetry.get("adversarial_sparring"))
    created = _non_negative_int(telemetry.get("adversarial_test_created"))
    executed = _non_negative_int(telemetry.get("adversarial_test_executed"))
    if start != _specs.ADVERSARIAL_EXPECTED_START:
        problems.append(
            f"adversarial_start {start} != {_specs.ADVERSARIAL_EXPECTED_START}"
        )
    if end != _specs.ADVERSARIAL_EXPECTED_END:
        problems.append(
            f"adversarial_end {end} != {_specs.ADVERSARIAL_EXPECTED_END}"
        )
    if sparring < _specs.ADVERSARIAL_MIN_SPARRING_EVENTS:
        problems.append(
            f"adversarial_sparring telemetry {sparring} < "
            f"{_specs.ADVERSARIAL_MIN_SPARRING_EVENTS}"
        )
    if executed < _specs.ADVERSARIAL_MIN_TESTS_EXECUTED:
        problems.append(
            f"adversarial_test_executed telemetry {executed} < "
            f"{_specs.ADVERSARIAL_MIN_TESTS_EXECUTED}"
        )
    if created < 0:
        problems.append(f"adversarial_test_created telemetry {created} < 0")
    return problems


def _non_negative_int(value: object) -> int:
    """Return ``value`` as a non-negative int, or ``-1`` when not a valid count."""
    if isinstance(value, bool):
        return -1
    if isinstance(value, int) and value >= 0:
        return value
    return -1


def _check_qa_subflow_flow_end(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Dim 7 — last QA-subflow result is ``PolicyVerdict.PASS`` (FK-35 §35.2.4)."""
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.NO_VERIFY
    try:
        payload = _decision_payload(gate_ctx.story_dir, state_port, runtime_scope)
    except CorruptStateError as exc:
        return _fail(dim, dim.value, f"corrupt state: {exc}")
    if payload is None:
        return _fail(dim, dim.value, "No verify decision record for QA-subflow flow_end")
    if not verify_decision_passed(payload):
        label = payload.get("status", payload.get("decision"))
        return _fail(dim, dim.value, f"QA-subflow verdict is {label!r}, expected PASS")
    return DimensionResult(
        dimension=dim,
        passed=True,
        detail="QA-subflow flow_end is PolicyVerdict.PASS",
    )


def _check_conflict_freeze_proof(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Fail closed when an active conflict-freeze lacks a persisted proof."""
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.CONFLICT_FREEZE_PROOF
    try:
        freeze_reader = getattr(state_port, "has_active_conflict_freeze", None)
        proof_reader = getattr(state_port, "has_conflict_freeze_proof", None)
        if freeze_reader is None or proof_reader is None:
            return DimensionResult(
                dimension=dim,
                passed=True,
                detail="No conflict_freeze reader wired for this state port",
            )
        frozen = freeze_reader(gate_ctx.story_dir, runtime_scope)
        if not frozen:
            return DimensionResult(
                dimension=dim,
                passed=True,
                detail="No conflict_freeze active for this run",
            )
        if proof_reader(gate_ctx.story_dir, runtime_scope):
            return DimensionResult(
                dimension=dim,
                passed=True,
                detail="Conflict-freeze proof record present",
            )
    except CorruptStateError as exc:
        return _fail(dim, dim.value, f"corrupt state: {exc}")
    return _fail(
        dim,
        dim.value,
        "conflict_freeze active but no persisted proof record exists",
    )


def _check_timestamp_causality(
    gate_ctx: IntegrityGateContext,
    state_port: IntegrityGateStatePort,
    runtime_scope: RuntimeStateScope | None,
) -> DimensionResult:
    """Dim 8 — timestamp causality (FK-35 §35.2.4 line 274).

    FK-35 §35.2.4: ``ArtifactRecord(context).finished_at <
    ArtifactRecord(decision).finished_at`` — the CONTEXT record must have been
    finalised strictly before the policy DECISION.  Verified over the canonical
    context record (``story_contexts``, completion timestamp) and the canonical
    decision envelope (``qa-policy-decision``).  A non-strict ordering
    (``decision.finished_at <= context.finished_at``, i.e. the policy decided at
    or before the context existed) is the inversion that fails closed (AK9).
    Record presence is owned by the mandatory pre-stage (Dim 2/4); the inversion
    is asserted only when both the context timestamp and the decision envelope
    are present (concept/research carry no decision -> vacuously satisfied).
    """
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.TIMESTAMP_INVERSION
    try:
        context_finished_at = state_port.load_context_finished_at(
            gate_ctx.story_dir, runtime_scope
        )
        decision_env = _qa_envelope(
            gate_ctx, state_port, runtime_scope, _specs.VERIFY_DECISION_STAGE
        )
    except CorruptStateError as exc:
        return _fail(dim, TIMESTAMP_VIOLATION, f"corrupt state: {exc}")
    violation = _timestamp_violation(context_finished_at, decision_env)
    if violation is not None:
        return _fail(dim, TIMESTAMP_VIOLATION, violation)
    return DimensionResult(
        dimension=dim,
        passed=True,
        detail="Timestamp causality holds (context.finished_at < decision.finished_at)",
    )


def _timestamp_violation(
    context_finished_at: datetime | None,
    decision_env: ArtifactEnvelope | None,
) -> str | None:
    """Return a detail string when context/decision causality is violated (Dim 8).

    FK-35 §35.2.4 line 274 anchors Dim 8 on ``ArtifactRecord(context).finished_at
    < ArtifactRecord(decision).finished_at``: the context (built at setup) must
    pre-date the policy decision (the QA-subflow flow_end).  A decision
    finalised at or before the context's completion is a causality inversion
    (the policy decided before the context existed).

    Presence is owned by the mandatory pre-stage (Dim 2 context / Dim 4
    decision), NOT this dimension: code stories reach Dim 8 only with both
    records present, while concept/research stories carry a context but no
    decision (no QA delivery, FK-24 §24.3.1) — there the causality is vacuously
    satisfied.  The inversion is therefore asserted ONLY when both the context
    timestamp and the decision envelope are present.
    """
    if context_finished_at is None or decision_env is None:
        return None
    if decision_env.finished_at <= context_finished_at:
        return (
            f"decision.finished_at ({decision_env.finished_at.isoformat()}) <= "
            f"context.finished_at ({context_finished_at.isoformat()})"
        )
    return None


def _fail(
    dim: IntegrityDimension,
    failure_reason: str,
    detail: str,
) -> DimensionResult:
    """Build a failing :class:`DimensionResult`."""
    from agentkit.governance.integrity_gate import DimensionResult

    return DimensionResult(
        dimension=dim,
        passed=False,
        failure_reason=failure_reason,
        detail=detail,
    )


__all__ = [
    "CODE_ONLY_DIMENSIONS",
    "ENVELOPE_VIOLATION",
    "MANDATORY_DIMENSIONS",
    "MISSING_PRESTAGE_CODE",
    "TIMESTAMP_VIOLATION",
    "IntegrityDimension",
    "dimensions_for",
    "evaluate_dimension",
    "evaluate_mandatory_artifact",
    "mandatory_dimensions_for",
    "required_phases_for",
]
