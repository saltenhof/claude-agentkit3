"""QA artifact persistence via ArtifactManager (AG3-023 §AK12).

Diese Top-Surface ist ausschliesslich Konsumer der ``ArtifactManager``-API
aus dem ``agentkit.artifacts``-BC. Sie importiert **keine**
``agentkit.state_backend.store``-Funktionen — der Aufrufer
(``implementation/phase.py`` oder ein Test) muss die Manager-Instanz und
die Scope-Felder explizit liefern. Damit ist der von der Story (Z. 287
+ Z. 316) geforderte BC-Schnitt eingehalten: verify_system nutzt
ausschliesslich ``ArtifactManager.write/read`` als Persistenz-Facade.

Funktionen:
  - ``write_layer_artifacts``: pro bekanntem QA-Layer einen Envelope via
    ``manager.write`` schreiben (UPSERT in artifact_envelopes).
  - ``write_verify_decision_artifacts``: einen Verify-Decision-Envelope
    via ``manager.write`` schreiben.
  - ``load_verify_decision_artifact``: liest den hoechsten-attempt
    Envelope per ``manager.read_latest`` und gibt
    ``(VERIFY_DECISION_FILE, payload)`` zurueck.

Die FK-69-Materialisierung (qa_stage_results, qa_findings,
decision_records) und das Projektionsfile sind **nicht** Aufgabe dieses
Moduls; sie laufen im Orchestrator (implementation/phase.py) via
``state_backend.record_layer_artifacts`` / ``record_verify_decision``.
Beide Pfade sind idempotent (UPSERT in artifact_envelopes; UPSERT in
den FK-69-Tabellen), so dass ein Re-Run keine divergente Wahrheit
erzeugt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactNotFoundError,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import (
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
from agentkit.verify_system.policy_engine.projections import (
    build_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult


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
    """Schreibt pro bekanntem QA-Layer einen ArtifactEnvelope via Manager.

    Args:
        manager: Injizierte ArtifactManager-Instanz.
        story_id: Story-Display-ID (z.B. ``AG3-901``).
        run_id: Run-Korrelations-ID.
        layer_results: Layer-Ergebnisse aus dem QA-Subflow.
        attempt_nr: Versuchszaehler (>= 1).

    Returns:
        Tuple der Projektions-Filenamen je geschriebenem Layer
        (analog zur bisherigen Signatur).

    Raises:
        ProducerNotRegisteredError / EnvelopeFieldError: aus
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
    """Schreibt einen Verify-Decision-Envelope via ArtifactManager.

    Raises:
        ProducerNotRegisteredError / EnvelopeFieldError: aus
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
    """Liest den letzten Verify-Decision-Envelope via ``manager.read_latest``.

    Args:
        manager: Injizierte ArtifactManager-Instanz.
        story_id: Story-Display-ID.
        run_id: Run-Korrelations-ID; ``None`` matched ueber alle runs.

    Returns:
        ``(VERIFY_DECISION_FILE, payload)`` oder ``None`` wenn kein
        Envelope existiert.
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

    Beibehalten fuer Tests, die das Projektions-Verhalten direkt pruefen.
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
