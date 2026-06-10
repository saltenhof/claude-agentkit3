"""HandoverPackager — the worker -> QA-subflow handover (FK-26 §26.7).

Produces ``handover.json``, the structured worker-to-QA handover. The schema is
the FULL FK-26 §26.7.3 contract (seven mandatory fields) — exactly the field-set
the AG3-042 Layer-1 ``artifact.handover`` check validates
(``agentkit.verify_system.structural.checks.artifact_checks``): ONE consistent
schema, no producer/validator drift (CLAUDE.md SINGLE SOURCE OF TRUTH).

``package`` writes the handover TWICE, deliberately and consistently:

1. the plain ``handover.json`` file under the story dir — the Layer-1
   ``artifact.handover`` check reads ``story_dir/handover.json`` directly; and
2. a typed ``ArtifactClass.HANDOVER`` envelope via the :class:`ArtifactManager`
   (AG3-023 producer-bound write path) — the durable, ownership-clear record.

``acceptance_criteria_status`` values follow FK-26 §26.7.3 (``ADDRESSED`` /
``ACStatus.NOT_APPLICABLE`` / ``BLOCKED``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.artifacts import ArtifactEnvelope, ProducerType
from agentkit.artifacts.envelope import ENVELOPE_SCHEMA_VERSION
from agentkit.artifacts.producer import Producer, ProducerId
from agentkit.core_types import HANDOVER_FILE, ArtifactClass, EnvelopeStatus
from agentkit.implementation.register import (
    IMPLEMENTATION_HANDOVER_PRODUCER,
    IMPLEMENTATION_HANDOVER_STAGE,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager, ArtifactReference
    from agentkit.implementation.worker_loop.loop import IncrementResult
    from agentkit.implementation.worker_session.session import WorkerSession

#: Canonical handover filename read by the Layer-1 ``artifact.handover`` check.
HANDOVER_FILENAME = HANDOVER_FILE


class ACStatus(StrEnum):
    """Per-AC status in the handover (FK-26 §26.7.3).

    Attributes:
        ADDRESSED: The AC was addressed by the worker.
        ACStatus.NOT_APPLICABLE: The AC does not apply to the delivered increment.
        BLOCKED: The AC could not be addressed (blocker documented).
    """

    ADDRESSED = "ADDRESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


class HandoverIncrement(BaseModel):
    """One increment entry in the handover (FK-26 §26.7.2 ``increments``).

    Attributes:
        description: Description of the vertical increment.
        commit_sha: The increment's commit SHA.
        tests_added: Test locators added in the increment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    commit_sha: str
    tests_added: list[str] = Field(default_factory=list)


class DriftLogEntry(BaseModel):
    """One drift entry in the handover (FK-26 §26.7.2 ``drift_log``).

    Attributes:
        increment: 1-based increment index the drift belongs to.
        drift: What deviated from the design.
        justification: Why the deviation was made.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    increment: int
    drift: str
    justification: str


class HandoverData(BaseModel):
    """The typed ``handover.json`` payload (FK-26 §26.7.3, seven mandatory fields).

    The seven required keys are exactly the AG3-042 ``artifact.handover``
    validator's required set, so a packaged handover always passes Layer 1.
    ``assumptions`` and ``drift_log`` may be empty lists but the keys are always
    present (FK-26 §26.7.3).

    Attributes:
        changes_summary: What changed and why (free text).
        increments: Vertical increments with commit SHA and tests.
        assumptions: Assumptions made (may be empty).
        existing_tests: Test locators that exist.
        risks_for_qa: Risks the QA agent should target.
        drift_log: Documented deviations from the design (may be empty).
        acceptance_criteria_status: Per-AC status (FK-26 §26.7.3 values).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    changes_summary: str
    increments: list[HandoverIncrement]
    assumptions: list[str] = Field(default_factory=list)
    existing_tests: list[str] = Field(default_factory=list)
    risks_for_qa: list[str] = Field(default_factory=list)
    drift_log: list[DriftLogEntry] = Field(default_factory=list)
    acceptance_criteria_status: dict[str, ACStatus] = Field(default_factory=dict)


class HandoverPackager:
    """Builds + persists the worker->QA handover (FK-26 §26.7)."""

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        """Initialise with the producer-bound artifact manager.

        Args:
            artifact_manager: The AG3-023 manager (the only authorised
                envelope write path).
        """
        self._artifact_manager = artifact_manager

    def package(
        self,
        session: WorkerSession,
        increments: list[IncrementResult],
        *,
        story_dir: Path,
        changes_summary: str,
        risks_for_qa: list[str],
        acceptance_criteria_status: dict[str, ACStatus],
        assumptions: list[str] | None = None,
        existing_tests: list[str] | None = None,
        commit_sha: str | None = None,
        branch_ref: str | None = None,
    ) -> ArtifactReference:
        """Build ``handover.json`` and persist it as file + HANDOVER envelope.

        Derives the ``increments``, ``drift_log`` and (default)
        ``existing_tests`` from the recorded :class:`IncrementResult` list, then
        writes the plain ``story_dir/handover.json`` (Layer-1 read path) and the
        typed ``ArtifactClass.HANDOVER`` envelope (durable record).

        Args:
            session: The active worker session (story/run binding).
            increments: The recorded increment results.
            story_dir: Story working directory (where ``handover.json`` lives).
            changes_summary: What changed and why.
            risks_for_qa: Risks for the QA agent (Layer-3 anchors).
            acceptance_criteria_status: Per-AC status (FK-26 §26.7.3 values).
            assumptions: Assumptions made (defaults to empty list).
            existing_tests: Test locators; defaults to the union of the
                increments' added tests.
            commit_sha: HEAD commit of the worker's work (envelope payload).
            branch_ref: Story branch ref (envelope payload).

        Returns:
            The :class:`ArtifactReference` of the persisted HANDOVER envelope.
        """
        handover = self._build_handover(
            increments,
            changes_summary=changes_summary,
            risks_for_qa=risks_for_qa,
            acceptance_criteria_status=acceptance_criteria_status,
            assumptions=assumptions,
            existing_tests=existing_tests,
        )
        # 1. Plain file — the Layer-1 artifact.handover check reads this path.
        payload = handover.model_dump(mode="json")
        atomic_write_text(
            story_dir / HANDOVER_FILENAME,
            _to_json(payload),
        )
        # 2. Typed HANDOVER envelope (AG3-023 producer-bound write path).
        envelope_payload = dict(payload)
        if commit_sha is not None:
            envelope_payload["commit_sha"] = commit_sha
        if branch_ref is not None:
            envelope_payload["branch_ref"] = branch_ref
        now = datetime.now(tz=UTC)
        envelope = ArtifactEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            story_id=session.story_id,
            run_id=session.run_id,
            stage=IMPLEMENTATION_HANDOVER_STAGE,
            attempt=1,
            producer=Producer(
                type=ProducerType.WORKER,
                name=IMPLEMENTATION_HANDOVER_PRODUCER,
                id=ProducerId(f"{IMPLEMENTATION_HANDOVER_PRODUCER}-{session.run_id}"),
            ),
            started_at=now,
            finished_at=now,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.HANDOVER,
            payload=envelope_payload,
        )
        return self._artifact_manager.write(envelope)

    @staticmethod
    def _build_handover(
        increments: list[IncrementResult],
        *,
        changes_summary: str,
        risks_for_qa: list[str],
        acceptance_criteria_status: dict[str, ACStatus],
        assumptions: list[str] | None,
        existing_tests: list[str] | None,
    ) -> HandoverData:
        """Assemble the typed handover from the recorded increments."""
        handover_increments = [
            HandoverIncrement(
                description=result.summary.description,
                commit_sha=result.summary.commit_sha,
                tests_added=list(result.summary.tests_added),
            )
            for result in increments
        ]
        drift_log = [
            DriftLogEntry(
                increment=result.drift.increment,
                drift=result.drift.reason or "drift detected",
                justification=result.drift.reason or "drift detected",
            )
            for result in increments
            if result.drift.drift_detected and not result.drift.skipped
        ]
        derived_tests: list[str] = []
        for result in increments:
            derived_tests.extend(result.summary.tests_added)
        return HandoverData(
            changes_summary=changes_summary,
            increments=handover_increments,
            assumptions=list(assumptions or []),
            existing_tests=list(existing_tests if existing_tests is not None
                                else dict.fromkeys(derived_tests)),
            risks_for_qa=list(risks_for_qa),
            drift_log=drift_log,
            acceptance_criteria_status=dict(acceptance_criteria_status),
        )


def _to_json(payload: dict[str, object]) -> str:
    """Serialise a handover payload to stable, human-readable JSON."""
    import json

    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "HANDOVER_FILENAME",
    "ACStatus",
    "DriftLogEntry",
    "HandoverData",
    "HandoverIncrement",
    "HandoverPackager",
]
