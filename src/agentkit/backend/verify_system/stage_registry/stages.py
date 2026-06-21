"""Typed stage profile model for the QA-subflow stage registry.

Source of truth: FK-33 §33.2.1 (typed stage profile, ``StageDefinition``)
and FK-27 §27.4 (Layer-1 stage catalogue + severities). The
:class:`StageDefinition` here is the AK3 code-level representation of one
QA-subflow stage; the concrete Layer-1 instances live in
:mod:`agentkit.backend.verify_system.stage_registry.data`.

Reuse note (no second truth): ``Severity`` and ``StoryType`` come from the
existing single sources of truth (``agentkit.backend.core_types.Severity`` and
``agentkit.backend.story_context_manager.types.StoryType``); this module does NOT
re-type either of those vocabularies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.backend.core_types import Severity
from agentkit.backend.core_types.qa_artifact_names import STRUCTURAL_PRODUCER
from agentkit.backend.verify_system.protocols import TrustClass

if TYPE_CHECKING:
    from agentkit.backend.story_context_manager.types import StoryType

__all__ = [
    "ExecutionPolicy",
    "StageKind",
    "StageDefinition",
    "StageOverridePolicy",
]


class ExecutionPolicy(StrEnum):
    """DSL policy controlling when a stage is invoked (FK-33 §33.2.1/§33.2.2).

    Deterministic stages default to :attr:`ALWAYS` (FK-33 §33.2.2
    "deterministic Stages: standardmaessig ``execution_policy = ALWAYS``").
    The two conditional policies model the FK-33 §33.8 sequential gate
    semantics where a stage only runs once an earlier gate held.

    Attributes:
        ALWAYS: Always materialised into the stage plan (the Layer-1 default).
        IF_LAYER_PASSES: Only when the surrounding layer has not already hard
            failed (FK-27 §27.4.2: structural checks run after the artifact
            check PASS).
        IF_PREVIOUS_PASS: Only when the previous stage in execution order
            passed (FK-33 §33.8.2 gate sequencing).
    """

    ALWAYS = "ALWAYS"
    IF_LAYER_PASSES = "IF_LAYER_PASSES"
    IF_PREVIOUS_PASS = "IF_PREVIOUS_PASS"


class StageKind(StrEnum):
    """Typed execution kind of a QA stage (FK-33 §33.2.1)."""

    DETERMINISTIC = "deterministic"
    LLM_EVALUATION = "llm_evaluation"
    AGENT = "agent"
    POLICY = "policy"


class StageOverridePolicy(StrEnum):
    """Override scope for stage-level project policy (FK-33 §33.2.4)."""

    BLOCKING_ONLY = "blocking_only"
    NONE = "none"


@dataclass(frozen=True)
class StageDefinition:
    """Typed profile of one QA-subflow stage (FK-33 §33.2.1).

    Immutable value object (ARCH-29). The ``severity`` field carries the
    FK-27 §27.4.2/§27.4.3 classification verbatim; the ``escalated`` flag
    marks the single FK-27 §27.4.5 exception (``impact.violation`` routes to
    ESCALATED rather than a Worker-feedback loop).

    Args:
        stage_id: Canonical check/stage id (e.g. ``"artifact.protocol"``,
            ``"branch.story"``); FK-27 §27.4 Check-ID, also the artefact
            filename base (FK-33 §33.2.3).
        layer: QA-subflow layer (1-4). Layer-1 stages are the deterministic
            structural checks (FK-33 §33.3).
        severity: FK-27 §27.4.2/§27.4.3 severity classification
            (``BLOCKING``/``MAJOR``/``MINOR``). A BLOCKING finding blocks the
            QA-subflow hard (FK-27 §27.4.2).
        applies_to: Story types for which this stage is evaluated
            (FK-33 §33.2.4 ``applies_to``).
        execution_policy: When the stage is invoked (FK-33 §33.2.1).
        escalated: Whether a FAIL of this stage routes DIRECTLY to ESCALATED
            instead of the Worker-feedback loop (FK-27 §27.4.5 exception:
            only ``impact.violation``).
        feature_gated_are: Whether the stage is only active when
            ``features.are == true`` (FK-27 §27.4.4 ARE-Gate). Default
            ``False``.
        origin_check_ref: Originating ``fc_check_proposals.check_id``
            (``CHK-NNNN``) for an FC-derived executed check; ``None`` for
            native checks (FK-33 §33.2.1). verify-system echoes this value
            verbatim into ``qa_check_outcomes.check_proposal_ref`` via the
            :class:`~agentkit.backend.verify_system.check_outcome_emitter.CheckOutcomeEmitter`;
            no FC-semantic interpretation inside verify-system.
    """

    stage_id: str
    layer: int
    severity: Severity
    applies_to: frozenset[StoryType]
    kind: StageKind = StageKind.DETERMINISTIC
    trust_class: TrustClass | None = TrustClass.SYSTEM
    producer: str = STRUCTURAL_PRODUCER
    override_policy: StageOverridePolicy = StageOverridePolicy.BLOCKING_ONLY
    execution_policy: ExecutionPolicy = ExecutionPolicy.ALWAYS
    escalated: bool = False
    feature_gated_are: bool = False
    origin_check_ref: str | None = None
    _blocking_override: bool | None = None

    @property
    def id(self) -> str:
        """FK-33 ``id`` alias for the canonical code field ``stage_id``."""
        return self.stage_id

    @property
    def default_blocking(self) -> bool:
        """Return whether the registry default blocks on failure."""
        return self.severity is Severity.BLOCKING

    @property
    def effective_blocking(self) -> bool:
        """Return the blocking value after a project override, if any."""
        if self._blocking_override is not None:
            return self._blocking_override
        return self.default_blocking
