"""QA artifact persistence and reads.

Schreibpfad (AG3-023 ReCut 3.4.0):
  write_layer_artifacts / write_verify_decision_artifacts:
    1. ArtifactEnvelope bauen und via ArtifactManager in artifact_envelopes
       persistieren (fail-closed; CorruptStateError und ProducerNotRegisteredError
       propagieren).
    2. state_backend.store.record_layer_artifacts / record_verify_decision
       fuer FK-69-Materialisierung und Projektionsdatei rufen.
  Kein Legacy-Fallback auf Projektionspfad mehr; kein synthetic run_id;
  keine Exception-Suppression.

Lesepfad:
  load_verify_decision_artifact -- liest aus decision_records ueber den
  state_backend; bei korruptem Scope nur dann auf die Projektionsdatei
  zurueckfallen, wenn die kanonische Quelle nicht erreichbar ist (graceful
  read-degrade, kein Schreib-Bypass).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    EnvelopeStatus,
    EnvelopeValidator,
    Producer,
    ProducerId,
    ProducerRegistry,
    ProducerType,
)
from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)
from agentkit.exceptions import CorruptStateError
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.state_backend.store import (
    load_latest_verify_decision,
    load_latest_verify_decision_for_scope,
    record_layer_artifacts,
    record_verify_decision,
    resolve_runtime_scope,
)
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.verify_system.policy_engine.projections import (
    build_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
)
from agentkit.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.state_backend.scope import RuntimeStateScope
    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult


_LAYER_TO_PRODUCER: dict[str, tuple[str, ProducerType]] = {
    "structural": ("verify-system.layer-1-structural", ProducerType.DETERMINISTIC),
    "semantic": ("verify-system.layer-2-llm", ProducerType.LLM_REVIEWER),
    "adversarial": ("verify-system.layer-3-adversarial", ProducerType.LLM_REVIEWER),
}
_LAYER_TO_STAGE: dict[str, str] = {
    "structural": "qa-layer-structural",
    "semantic": "qa-layer-semantic",
    "adversarial": "qa-layer-adversarial",
}
_VERIFY_DECISION_PRODUCER: tuple[str, ProducerType] = (
    "verify-system.layer-4-policy",
    ProducerType.DETERMINISTIC,
)
_VERIFY_DECISION_STAGE = "qa-verify-decision"


def load_verify_decision_artifact(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the canonical verify decision (graceful degrade on corrupt scope)."""

    try:
        scope = resolve_runtime_scope(story_dir)
    except CorruptStateError:
        scope = None
    if scope is not None and scope.run_id is not None:
        payload = load_latest_verify_decision_for_scope(scope)
        if payload is not None:
            return VERIFY_DECISION_FILE, payload

    payload = load_latest_verify_decision(story_dir)
    if payload is not None:
        return VERIFY_DECISION_FILE, payload

    return _load_verify_decision_projection(_qa_projection_dir(story_dir))


def write_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist canonical layer records (fail-closed).

    Schritt 1: ArtifactEnvelope pro bekanntem Layer via ArtifactManager
        in artifact_envelopes schreiben.
    Schritt 2: FK-69-Materialisierung + Projektionsfile via state_backend.

    Raises:
        CorruptStateError: Wenn keine bindbare Runtime-Scope (Story-Context
            oder FlowExecution) aufloesbar ist, oder wenn die Scope keinen
            ``run_id`` traegt.
        Errors aus ``ArtifactManager.write`` propagieren unveraendert
        (``ProducerNotRegisteredError``, ``EnvelopeFieldError``, ...).
    """

    normalized = tuple(layer_results)
    scope = resolve_runtime_scope(story_dir)
    _require_run_scope(scope)

    manager = _build_artifact_manager(story_dir)
    started_at = _utc_now()
    for layer_result in normalized:
        if layer_result.layer not in _LAYER_TO_STAGE:
            continue
        producer_name, producer_type = _LAYER_TO_PRODUCER[layer_result.layer]
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=scope.story_id,
            run_id=_run_id(scope),
            stage=_LAYER_TO_STAGE[layer_result.layer],
            attempt=attempt_nr,
            producer=Producer(
                type=producer_type,
                name=producer_name,
                id=ProducerId(f"{producer_name}-{_run_id(scope)}-{attempt_nr}"),
            ),
            started_at=started_at,
            finished_at=started_at,
            status=EnvelopeStatus.PASS if layer_result.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=serialize_layer_result(layer_result, attempt_nr=attempt_nr),
        )
        manager.write(envelope)

    return record_layer_artifacts(
        story_dir,
        layer_results=normalized,
        attempt_nr=attempt_nr,
        projection_dir=projection_dir or _qa_projection_dir(story_dir),
    )


def write_verify_decision_artifacts(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist canonical decision records (fail-closed).

    Schritt 1: ArtifactEnvelope fuer die Verify-Decision via
        ArtifactManager schreiben.
    Schritt 2: decision_records + Projektionsfile via state_backend.

    Raises:
        CorruptStateError: Wenn keine bindbare Runtime-Scope mit ``run_id``
            existiert.
        Errors aus ``ArtifactManager.write`` propagieren unveraendert.
    """

    scope = resolve_runtime_scope(story_dir)
    _require_run_scope(scope)

    manager = _build_artifact_manager(story_dir)
    started_at = _utc_now()
    producer_name, producer_type = _VERIFY_DECISION_PRODUCER
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=scope.story_id,
        run_id=_run_id(scope),
        stage=_VERIFY_DECISION_STAGE,
        attempt=attempt_nr,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId(f"{producer_name}-{_run_id(scope)}-{attempt_nr}"),
        ),
        started_at=started_at,
        finished_at=started_at,
        status=EnvelopeStatus.PASS if decision.passed else EnvelopeStatus.FAIL,
        artifact_class=ArtifactClass.QA,
        payload=build_verify_decision_artifact(decision, attempt_nr=attempt_nr),
    )
    manager.write(envelope)

    return record_verify_decision(
        story_dir,
        decision=decision,
        attempt_nr=attempt_nr,
        projection_dir=projection_dir or _qa_projection_dir(story_dir),
    )


def _build_artifact_manager(story_dir: Path) -> ArtifactManager:
    """Construct an ArtifactManager bound to the current story-dir backend."""

    registry = ProducerRegistry()
    register_verify_producers(registry)
    validator = EnvelopeValidator(registry)
    repository = StateBackendArtifactRepository(story_dir)
    return ArtifactManager(repository, validator)


def _require_run_scope(scope: RuntimeStateScope) -> None:
    """Fail-closed: ArtifactEnvelope-Writes verlangen einen gebundenen run_id."""

    if scope.run_id is None:
        raise CorruptStateError(
            "ArtifactEnvelope write requires a runtime scope with run_id; "
            "no FlowExecution is bound to this story-dir.",
            detail={
                "story_id": scope.story_id,
                "story_dir": str(scope.story_dir),
            },
        )


def _run_id(scope: RuntimeStateScope) -> str:
    """Type-narrowing helper used after ``_require_run_scope``."""

    assert scope.run_id is not None  # noqa: S101 -- guarded by _require_run_scope
    return scope.run_id


def _utc_now() -> datetime:
    """UTC-aware ``datetime`` used as Envelope started_at/finished_at."""

    from datetime import datetime

    return datetime.fromisoformat(now_iso())


def _load_verify_decision_projection(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the verify-decision projection file if present."""

    canonical = load_json_object(story_dir / VERIFY_DECISION_FILE)
    if canonical is not None:
        return VERIFY_DECISION_FILE, canonical
    return None


def _write_projection(path: Path, payload: dict[str, object]) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _qa_projection_dir(story_dir: Path) -> Path:
    return resolve_qa_story_dir(story_dir, story_id=story_dir.name)


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
