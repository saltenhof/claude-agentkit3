"""QA artifact persistence via ArtifactManager (AG3-023 §AK12).

This top-surface is exclusively a consumer of the ``ArtifactManager`` API
from the ``agentkit.backend.artifacts`` BC. It imports **no**
``agentkit.backend.state_backend.store`` functions — the caller
(``implementation/phase.py`` or a test) must supply the manager instance and
the scope fields explicitly. This keeps the BC cut required by the story
(line 287 + line 316): verify_system uses
``ArtifactManager.write/read`` exclusively as the persistence facade.

Functions:
  - ``write_layer_artifacts``: write one envelope per known QA layer via
    ``manager.write`` (UPSERT into artifact_envelopes).
  - ``write_verify_decision_artifacts``: write one verify-decision envelope
    via ``manager.write``.
  - ``load_verify_decision_artifact``: read the highest-attempt
    envelope via ``manager.read_latest`` and return
    ``(VERIFY_DECISION_FILE, payload)``.

The FK-69 materialization (qa_stage_results, qa_findings,
decision_records) and the projection file are **not** the task of this
module; they run in the orchestrator (implementation/phase.py) via
``state_backend.record_layer_artifacts`` / ``record_verify_decision``.
Both paths are idempotent (UPSERT into artifact_envelopes; UPSERT into
the FK-69 tables), so that a re-run produces no divergent truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactNotFoundError,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.backend.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
    DOC_FIDELITY_PRODUCER,
    DOC_FIDELITY_STAGE,
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
    STRUCTURAL_PRODUCER,
    STRUCTURAL_STAGE,
    VERIFY_DECISION_FILE,
    VERIFY_DECISION_PRODUCER,
    VERIFY_DECISION_STAGE,
)
from agentkit.backend.verify_system.policy_engine.projections import (
    build_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import LayerResult


# Producer/stage strings reference the cross-cutting SSOT
# ``core_types.qa_artifact_names`` (FK-27 §27.7; no second naming truth, R2-H).
_LAYER_TO_PRODUCER: dict[str, tuple[str, ProducerType]] = {
    "structural": (STRUCTURAL_PRODUCER, ProducerType.DETERMINISTIC),
    "qa_review": (QA_REVIEW_PRODUCER, ProducerType.LLM_REVIEWER),
    "semantic_review": (SEMANTIC_REVIEW_PRODUCER, ProducerType.LLM_REVIEWER),
    "doc_fidelity": (DOC_FIDELITY_PRODUCER, ProducerType.LLM_REVIEWER),
    "adversarial": (ADVERSARIAL_PRODUCER, ProducerType.LLM_REVIEWER),
}
_LAYER_TO_STAGE: dict[str, str] = {
    "structural": STRUCTURAL_STAGE,
    "qa_review": QA_REVIEW_STAGE,
    "semantic_review": SEMANTIC_REVIEW_STAGE,
    "doc_fidelity": DOC_FIDELITY_STAGE,
    "adversarial": ADVERSARIAL_STAGE,
}
_VERIFY_DECISION_PRODUCER: tuple[str, ProducerType] = (
    VERIFY_DECISION_PRODUCER,
    ProducerType.DETERMINISTIC,
)


def write_layer_artifacts(
    *,
    manager: ArtifactManager,
    story_id: str,
    run_id: str,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
) -> tuple[str, ...]:
    """Write one ArtifactEnvelope per known QA layer via the manager.

    Args:
        manager: Injected ArtifactManager instance.
        story_id: Story display ID (e.g. ``AG3-901``).
        run_id: Run correlation ID.
        layer_results: Layer results from the QA subflow.
        attempt_nr: Attempt counter (>= 1).

    Returns:
        Tuple of the projection file names per written layer
        (analogous to the previous signature).

    Raises:
        ProducerNotRegisteredError / EnvelopeFieldError: from
            ``ArtifactManager.write`` (fail-closed).
    """

    started_at = _utc_now()
    produced: list[str] = []
    for layer_result in layer_results:
        if layer_result.layer not in _LAYER_TO_STAGE:
            continue
        producer_name, producer_type = _LAYER_TO_PRODUCER[layer_result.layer]
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=run_id,
            stage=_LAYER_TO_STAGE[layer_result.layer],
            attempt=attempt_nr,
            producer=Producer(
                type=producer_type,
                name=producer_name,
                id=ProducerId(f"{producer_name}-{run_id}-{attempt_nr}"),
            ),
            started_at=started_at,
            finished_at=started_at,
            status=EnvelopeStatus.PASS if layer_result.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=serialize_layer_result(layer_result, attempt_nr=attempt_nr),
        )
        manager.write(envelope)
        produced.append(LAYER_ARTIFACT_FILES[layer_result.layer])
    return tuple(produced)


def write_verify_decision_artifacts(
    *,
    manager: ArtifactManager,
    story_id: str,
    run_id: str,
    decision: VerifyDecision,
    attempt_nr: int,
) -> tuple[str, ...]:
    """Write one verify-decision envelope via the ArtifactManager.

    Raises:
        ProducerNotRegisteredError / EnvelopeFieldError: from
            ``ArtifactManager.write`` (fail-closed).
    """

    started_at = _utc_now()
    producer_name, producer_type = _VERIFY_DECISION_PRODUCER
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=VERIFY_DECISION_STAGE,
        attempt=attempt_nr,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId(f"{producer_name}-{run_id}-{attempt_nr}"),
        ),
        started_at=started_at,
        finished_at=started_at,
        status=EnvelopeStatus.PASS if decision.passed else EnvelopeStatus.FAIL,
        artifact_class=ArtifactClass.QA,
        payload=build_verify_decision_artifact(decision, attempt_nr=attempt_nr),
    )
    manager.write(envelope)
    return (VERIFY_DECISION_FILE,)


def load_verify_decision_artifact(
    *,
    manager: ArtifactManager,
    story_id: str,
    run_id: str | None = None,
) -> tuple[str, dict[str, object]] | None:
    """Read the latest verify-decision envelope via ``manager.read_latest``.

    Args:
        manager: Injected ArtifactManager instance.
        story_id: Story display ID.
        run_id: Run correlation ID; ``None`` matches across all runs.

    Returns:
        ``(VERIFY_DECISION_FILE, payload)`` or ``None`` if no
        envelope exists.
    """
    try:
        envelope = manager.read_latest(
            story_id=story_id,
            run_id=run_id,
            artifact_class=ArtifactClass.QA,
            stage=VERIFY_DECISION_STAGE,
        )
    except ArtifactNotFoundError:
        return None
    return VERIFY_DECISION_FILE, dict(envelope.payload or {})


def _utc_now() -> datetime:
    """UTC-aware ``datetime`` used as Envelope started_at/finished_at."""

    from datetime import datetime

    return datetime.fromisoformat(now_iso())


def _write_projection(path: Path, payload: dict[str, object]) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed.

    Kept for tests that check the projection behavior directly.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


__all__ = [
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "VERIFY_DECISION_FILE",
    "build_verify_decision_artifact",
    "load_json_object",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
