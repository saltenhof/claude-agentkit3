"""verify-system contract models.

Defines the public input bundle (``VerifyContextBundle``) and the internal
wrapper model (``VerifyTarget`` + ``VerifyTargetType``).

Architecture rules:
- ``VerifyContextBundle`` is exported from ``agentkit.backend.verify_system`` (public surface).
- ``VerifyTarget``, ``VerifyTargetType``, ``QaSubflowExecutionResult`` are
  INTERNAL. They are NEVER exported from ``agentkit.backend.verify_system.__init__``
  and are never used as method parameters in the public API (AK11).
- ``PhaseEnvelopeView`` is a BC-boundary DTO: it carries only the four
  QA-cycle identity fields from ``PhaseEnvelope.state.payload`` without
  importing the ``pipeline_engine`` BC (W2 / BC-Topology-Fix).

Source:
  - AG3-026 §2.1.1 -- VerifyContextBundle, VerifyTarget
  - AG3-026 §2.1.3 -- QaSubflowExecutionResult (optional internal detail)
  - ``concept/_meta/bc-cut-decisions.md §BC 2 verify-system``
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.backend.core_types import PolicyVerdict, SpawnRequest
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import LayerResult
from agentkit.backend.verify_system.remediation.feedback import RemediationFeedback

#: 12-char lowercase hex UUID-fragment (FK-27 §27.2.1 qa_cycle_id).
_QA_CYCLE_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
#: 64-char lowercase hex SHA-256 digest.
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PhaseEnvelopeView(BaseModel):
    """BC-boundary read-only DTO for QA-cycle identity fields.

    Carries exactly the four QA-cycle identity fields from
    ``PhaseEnvelope.state.payload`` (FK-27 §27.2.1). This DTO is the
    only representation of ``pipeline_engine`` phase-state that crosses
    into the ``verify-system`` BC, preventing a direct ``pipeline_engine``
    import in ``verify_system/contract.py`` (W2 BC-topology fix).

    Callers (e.g. ``ImplementationPhaseHandler``) build this view from
    ``PhaseEnvelope.state.payload`` and pass it into
    ``VerifyContextBundle.phase_envelope``.

    Attributes:
        qa_cycle_id: 12-char lowercase hex UUID-fragment; ``None`` before
            the first cycle. When set, ``qa_cycle_round`` must be >= 1.
        qa_cycle_round: Monotonic counter >= 1 once ``qa_cycle_id`` is set.
            Default ``0`` marks the idle state before the first cycle.
        evidence_epoch: UTC-aware ISO-8601 timestamp of the last
            artefact mutation. ``None`` before any cycle has run.
        evidence_fingerprint: SHA-256 hex digest (64 lowercase chars)
            over relevant artefacts. ``None`` before any cycle has run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    qa_cycle_id: str | None = None
    qa_cycle_round: int | None = None
    evidence_epoch: datetime | None = None
    evidence_fingerprint: str | None = None

    @field_validator("qa_cycle_id")
    @classmethod
    def _validate_qa_cycle_id(cls, value: str | None) -> str | None:
        """FK-27 §27.2.1: qa_cycle_id is a 12-char lowercase hex UUID-fragment."""
        if value is None:
            return value
        if not _QA_CYCLE_ID_PATTERN.fullmatch(value):
            msg = (
                "qa_cycle_id must be a 12-char lowercase hex UUID-fragment "
                f"(FK-27 §27.2.1); got {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("evidence_epoch")
    @classmethod
    def _validate_evidence_epoch(cls, value: datetime | None) -> datetime | None:
        """FK-27 §27.2.1: evidence_epoch must be UTC-aware (offset == 0)."""
        if value is None:
            return value
        if value.tzinfo is None:
            msg = (
                "evidence_epoch must be tz-aware (UTC); naive datetime not "
                f"allowed (FK-27 §27.2.1): {value!r}"
            )
            raise ValueError(msg)
        if value.utcoffset() != timedelta(0):
            msg = (
                "evidence_epoch must be UTC (offset=0); non-UTC tz-aware "
                f"not allowed (FK-27 §27.2.1): {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("evidence_fingerprint")
    @classmethod
    def _validate_evidence_fingerprint(cls, value: str | None) -> str | None:
        """FK-27 §27.2.1: evidence_fingerprint is a 64-char lowercase SHA-256 hex."""
        if value is None:
            return value
        if not _SHA256_HEX_PATTERN.fullmatch(value):
            msg = (
                "evidence_fingerprint must be a 64-char lowercase hex SHA-256 "
                f"digest (FK-27 §27.2.1); got {value!r}"
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_round_when_id_set(self) -> PhaseEnvelopeView:
        """FK-27 §27.2.1: qa_cycle_round >= 1 when qa_cycle_id is set."""
        if (
            self.qa_cycle_id is not None
            and (self.qa_cycle_round is None or self.qa_cycle_round < 1)
        ):
            msg = (
                "qa_cycle_round must be >= 1 when qa_cycle_id is set; "
                f"got qa_cycle_round={self.qa_cycle_round!r} with "
                f"qa_cycle_id={self.qa_cycle_id!r}"
            )
            raise ValueError(msg)
        return self


class VerifyContextBundle(BaseModel):
    """Public input bundle for ``VerifySystem.run_qa_subflow``.

    Carries the run-time context that the VerifySystem needs to write
    QA artefacts and wire QA-cycle metadata into the produced envelopes.

    Attributes:
        run_id: Correlation ID of the current pipeline run.
        story_dir: Root directory of the story being verified.
        phase_envelope: Read-only BC-boundary view of the current phase's
            QA-cycle identity fields (or ``None`` if the caller has no
            envelope yet). The QA-cycle fields (``qa_cycle_id``,
            ``qa_cycle_round``, ``evidence_epoch``,
            ``evidence_fingerprint``) are read directly from the view
            when present (AG3-026 §AK8; populated by AG3-041 / THEME-009).
            Callers build a ``PhaseEnvelopeView`` from
            ``PhaseEnvelope.state.payload`` to avoid a BC import of
            ``pipeline_engine`` into ``verify_system``.
        attempt: QA-subflow attempt counter (>= 1).
        project_root: Optional project root for canonical QA-artefact path
            resolution (FK-27 §27.2.3 invalidation; AG3-041 E4). When set, the
            cycle-bound artefacts resolve under ``{project_root}/_temp/qa/
            {story_id}`` via ``installer.paths.resolve_qa_story_dir`` — the SAME
            resolver the phase handler uses for its QA projections (one path
            truth). ``None`` => the resolver derives the root from
            ``story_dir``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    story_dir: Path
    phase_envelope: PhaseEnvelopeView | None = None
    attempt: int
    project_root: Path | None = None


class VerifyTargetType(StrEnum):
    """Classification of the artefact under review.

    Determines which QA-layer configuration is selected (routing.py).

    Attributes:
        IMPLEMENTATION: Normal implementation story output.
        EXPLORATION: Exploration/design-phase output.
        BUGFIX: Bugfix story output (treated identically to IMPLEMENTATION).
    """

    IMPLEMENTATION = "IMPLEMENTATION"
    EXPLORATION = "EXPLORATION"
    BUGFIX = "BUGFIX"


class VerifyTarget(BaseModel):
    """Internal wrapper resolved from ``ArtifactReference + VerifyContextBundle``.

    **NOT exported from ``agentkit.backend.verify_system``** (AK11). Never used as
    a method parameter in the public API.

    Attributes:
        artifact_ref_record_key: Record key from the ``ArtifactReference``.
        target_type: Classification of the artefact under review.
        branch_ref: Optional git branch name relevant to this target.
        commit_sha: Optional git commit SHA relevant to this target.
        paths_in_scope: Tuple of paths that the QA-layers should evaluate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_ref_record_key: str
    target_type: VerifyTargetType
    branch_ref: str | None = None
    commit_sha: str | None = None
    paths_in_scope: tuple[str, ...] = ()


class _QaSubflowExecutionResult(BaseModel):
    """Internal detail model for a completed QA-subflow run.

    **NOT exported from ``agentkit.backend.verify_system``** (AK11). Callers see
    only the top-level ``PolicyVerdict`` return from ``run_qa_subflow``.

    Attributes:
        verdict: Overall PASS/FAIL decision.
        stage_results: Tuple of LayerResults from each executed layer.
        artifact_refs_written: Record keys of QA artefacts written.
        blocking_failures: Number of blocking findings.
        major_failures: Number of major findings.
        minor_failures: Number of minor findings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: PolicyVerdict
    stage_results: tuple[LayerResult, ...]
    artifact_refs_written: tuple[str, ...]
    blocking_failures: int
    major_failures: int
    minor_failures: int


class PolicyVerdictResult(BaseModel):
    """Internal QA-subflow verdict carrier with escalation/closure flags.

    **NOT exported from ``agentkit.backend.verify_system``** (AK11; pinned by
    ``tests/contract/verify_system/test_top_surface.py``). It is the internal
    aggregation of the policy verdict with the two AG3-041 control flags that
    the remediation loop and the closure gate consume:

    * ``escalated`` -- set when the remediation loop exhausted
      ``max_feedback_rounds`` on a FAIL (FK-27 §27.2.2 ``max_rounds_exceeded``
      -> ``escalated``). When escalated, ``verdict`` is forced to ``FAIL``.
    * ``closure_blocked`` -- set when, in a remediation context, at least one
      previous-round finding remains open -- ``NOT_RESOLVED`` or
      ``PARTIALLY_RESOLVED`` (FK-34 §34.9.4 / DK-04 §4.6,
      AG3-041 §2.1.6). The closure-phase handler consumes this flag in a
      follow-up story; it is computed here, not wired into closure yet.

    Attributes:
        verdict: PASS/FAIL summary verdict.
        escalated: Whether the remediation loop escalated (hard FAIL).
        closure_blocked: Whether open (NOT_RESOLVED or PARTIALLY_RESOLVED)
            previous findings block closure in a remediation context.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: PolicyVerdict
    escalated: bool = False
    closure_blocked: bool = False

    @model_validator(mode="after")
    def _escalated_implies_fail(self) -> PolicyVerdictResult:
        """FK-27 §27.2.2: an escalated cycle is a hard FAIL (no PASS escalation)."""
        if self.escalated and self.verdict is not PolicyVerdict.FAIL:
            msg = (
                "escalated=True requires verdict=FAIL "
                f"(FK-27 §27.2.2 max_rounds_exceeded); got verdict={self.verdict!r}"
            )
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Public outcome DTO (Befund A / AG3-026 Pass-2)
# ---------------------------------------------------------------------------


class QaSubflowOutcome(BaseModel):
    """Public outcome DTO returned by ``VerifySystem.run_qa_subflow``.

    Carries the full result of one QA-subflow run so that cross-BC
    callers (e.g. ``agentkit.backend.implementation``) can:

    * read the PASS/FAIL verdict without parsing the decision details,
    * feed ``decision.layer_results`` into FK-69
      (``record_layer_artifacts``, ``record_verify_decision``) without
      re-running any layers,
    * log or surface structured remediation feedback.

    ``_QaSubflowExecutionResult`` remains internal. This model is the
    **only** exported carrier of QA-subflow results (AK11).

    Normative references:
    - AG3-026 Pass-2 §Befund-A (Outcome-Modell).
    - FK-27 §27.3 / §27.7 (QA-Subflow-Top, Artefakt-Filenamen).
    - FK-69 (record_layer_artifacts / record_verify_decision).
    - ``concept/_meta/bc-cut-decisions.md §BC 2 verify-system``.

    Attributes:
        verdict: PASS or FAIL summary verdict (``PolicyVerdict``).
        decision: Full ``VerifyDecision`` from the policy engine,
            containing ``layer_results``, ``all_findings``,
            ``blocking_findings``, ``summary`` and ``passed``.
        artifact_refs: Tuple of artifact filenames written during
            this subflow run (FK-27 §27.7; 6 entries for
            IMPLEMENTATION, 4 for EXPLORATION).
        attempt_nr: QA-subflow attempt counter (>= 1).
        qa_cycle_round: Monotonic QA-cycle counter from the context
            bundle; mirrors ``VerifyContextBundle.attempt``.
        feedback: Structured remediation feedback when
            ``verdict == FAIL``; ``None`` when ``verdict == PASS``.
        qa_cycle_id: 12-char lowercase hex UUID-fragment of the QA cycle this
            run executed under (FK-27 §27.2.1). The QA-subflow always resolves
            a cycle (idle -> ``start_cycle``), so this is always set; the state
            owner (phase handler) persists it into ``ImplementationPayload``.
        evidence_epoch: UTC-aware timestamp of the cycle's last artefact
            mutation (FK-27 §27.2.1). Always set; persisted by the state owner.
        evidence_fingerprint: SHA-256 hex of the cycle's evidence
            (FK-27 §27.2.1), surfaced from the resolved QA-cycle state. Always
            set; persisted by the state owner.
        escalated: Whether the subflow-internal remediation loop escalated
            (``max_rounds_exceeded`` -> hard FAIL; FK-27 §27.2.2 / AG3-041
            §2.1.7). Always ``False`` on PASS.
        closure_blocked: Whether open (NOT_RESOLVED or PARTIALLY_RESOLVED)
            previous-round findings block closure in a remediation context
            (FK-34 §34.9.4 / DK-04 §4.6, AG3-041 §2.1.6). Consumed by the
            closure phase in a follow-up story.
        adversarial_spawn: Typed Layer-3 adversarial spawn orders derived from
            this round's BLOCKING Layer-2 findings (FK-27 §27.6 / FK-48 §48.2).
            Each :class:`SpawnRequest` is an ``ADVERSARIAL`` worker order the
            state owner (``ImplementationPhaseHandler``) writes into
            ``PhaseState.agents_to_spawn`` so the orchestrator spawns the
            adversarial worker on phase re-entry. Empty when Layer 3 was not
            routed (e.g. Exploration / fast) or Layer 2 produced no BLOCKING
            finding. The protected sandbox + ``ADVERSARIAL_TEST_SANDBOX``
            envelope are materialised by ``run_qa_subflow`` as a side effect of
            building these orders (the spawn is non-dead on the real QA path).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    verdict: PolicyVerdict
    decision: VerifyDecision
    artifact_refs: tuple[str, ...]
    attempt_nr: int
    qa_cycle_round: int
    feedback: RemediationFeedback | None = None
    qa_cycle_id: str | None = None
    evidence_epoch: datetime | None = None
    evidence_fingerprint: str | None = None
    escalated: bool = False
    closure_blocked: bool = False
    adversarial_spawn: tuple[SpawnRequest, ...] = ()


__all__ = [
    # Public
    "PhaseEnvelopeView",
    "QaSubflowOutcome",
    "VerifyContextBundle",
    # Internal (listed for intra-BC imports only)
    "_QaSubflowExecutionResult",
    "PolicyVerdictResult",
    "VerifyTarget",
    "VerifyTargetType",
]
