"""Materialise ``adversarial.json`` from the sandbox result (FK-48 §48.1.7 / §48.2.4).

AG3-079 AC5: a deterministic Zone-2 pipeline script reads the sandbox
``result.json`` (``_temp/adversarial/{story_id}/{epoch}/result.json``), validates
it against the Pydantic schema and materialises
``_temp/qa/{story_id}/adversarial.json`` via the ``ArtifactManager`` with:

* Producer == :data:`~agentkit.backend.core_types.qa_artifact_names.ADVERSARIAL_PRODUCER`
  (``verify-system.layer-3-adversarial``), NEVER a string literal,
* Stage == :data:`~agentkit.backend.core_types.qa_artifact_names.ADVERSARIAL_STAGE`
  (``qa-layer-adversarial``), and
* ``schema_version`` ``"3.1"`` with ``mandatory_target_results`` (FK-48 §48.2.4).

The producer/stage come from the cross-cutting SSOT constants
(``core_types.qa_artifact_names``), not from a literal — the integrity gate
(Dim 6) verifies against the SAME constants (no second naming truth). Sub-agents
never write ``_temp/qa/`` (FK-31 §31.3); the producer stamp is applied here via
the ``ArtifactManager`` (the only authorised QA-artefact write path).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ArtifactEnvelope, ProducerType
from agentkit.backend.artifacts.envelope import ENVELOPE_SCHEMA_VERSION
from agentkit.backend.artifacts.producer import Producer, ProducerId
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus
from agentkit.backend.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
    ADVERSARIAL_SANDBOX_RESULT_FILENAME,
    AdversarialResultArtifact,
    AdversarialTelemetryCounts,
    SandboxResult,
    SparringProof,
)
from agentkit.backend.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager, ArtifactReference
    from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
        PromotionSummary,
    )

#: Envelope status of a derived-PASS Layer-3 result.
_STATUS_PASS: str = "PASS"


class AdversarialResultReadError(VerifySystemError):
    """Raised when the sandbox ``result.json`` is missing or invalid (fail-closed).

    FK-48 §48.1.7: the sub-agent's result is the only evidence of the adversarial
    run. A missing or schema-invalid result is a hard error (no PASS without real
    evidence, FK-48 §48.1.8) — never a silent empty result.
    """


def read_sandbox_result(sandbox_dir: Path) -> SandboxResult:
    """Read + validate the Harness-Sub-Agent's sandbox ``result.json`` (FK-48 §48.1.7).

    Args:
        sandbox_dir: The protected sandbox dir
            (``_temp/adversarial/{story_id}/{epoch}/``).

    Returns:
        The validated :class:`SandboxResult`.

    Raises:
        AdversarialResultReadError: When the file is absent, unreadable, not JSON,
            or fails schema validation (fail-closed, FK-48 §48.1.8).
    """
    result_path = sandbox_dir / ADVERSARIAL_SANDBOX_RESULT_FILENAME
    if not result_path.is_file():
        raise AdversarialResultReadError(
            f"adversarial sandbox result {result_path} is absent — the "
            "Harness-Sub-Agent produced no evidence (FAIL-CLOSED, FK-48 §48.1.7)."
        )
    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdversarialResultReadError(
            f"adversarial sandbox result {result_path} is unreadable/invalid JSON: "
            f"{type(exc).__name__}: {exc} (FAIL-CLOSED, FK-48 §48.1.7)."
        ) from exc
    try:
        return SandboxResult.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 -- pydantic ValidationError -> fail-closed
        raise AdversarialResultReadError(
            f"adversarial sandbox result {result_path} failed schema validation: "
            f"{type(exc).__name__}: {exc} (FAIL-CLOSED, FK-48 §48.1.7)."
        ) from exc


def build_result_artifact(
    *,
    sandbox_result: SandboxResult,
    run_id: str,
    sparring: SparringProof,
    promotion: PromotionSummary,
    telemetry: AdversarialTelemetryCounts,
) -> AdversarialResultArtifact:
    """Build the ``adversarial.json`` payload (schema 3.1) from the run evidence.

    The Layer-3 verdict is DERIVED from real evidence (FK-48 §48.1.8), not copied
    from the sub-agent's self-report: PASS only when at least one test executed
    AND no executed test failed; otherwise FAIL.

    Args:
        sandbox_result: The validated sandbox result.
        run_id: Run-correlation id.
        sparring: The mandatory-sparring proof (FK-48 §48.1.6).
        promotion: The deterministic promotion outcome (FK-48 §48.1.5).
        telemetry: The emitted §48.1.8 adversarial-lifecycle event counts
            (FK-48 §48.1.8) the integrity gate (Dim 6) verifies against.

    Returns:
        The :class:`AdversarialResultArtifact` (schema_version ``3.1``).
    """
    tests_failed = sum(
        1 for t in sandbox_result.tests if t.outcome.upper() != _STATUS_PASS
    )
    tests_passed = sum(
        1 for t in sandbox_result.tests if t.outcome.upper() == _STATUS_PASS
    )
    has_evidence = sandbox_result.tests_executed >= 1
    derived_status = _STATUS_PASS if (has_evidence and tests_failed == 0) else "FAIL"
    return AdversarialResultArtifact(
        story_id=sandbox_result.story_id,
        run_id=run_id,
        status=derived_status,
        tests_created=len(sandbox_result.tests),
        tests_executed=sandbox_result.tests_executed,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        sparring=sparring,
        promotion=promotion,
        telemetry=telemetry,
        tests=sandbox_result.tests,
        mandatory_target_results=sandbox_result.mandatory_target_results,
        findings=sandbox_result.findings,
    )


def materialize_adversarial_artifact(
    *,
    artifact_manager: ArtifactManager,
    artifact: AdversarialResultArtifact,
    attempt: int,
) -> ArtifactReference:
    """Stamp ``adversarial.json`` via the ArtifactManager (canonical producer/stage).

    FK-48 §48.1.7 / story §2.1.5: the producer/stage come from the SSOT constants
    (:data:`ADVERSARIAL_PRODUCER` / :data:`ADVERSARIAL_STAGE`), NOT a literal. The
    envelope ``status`` mirrors the derived Layer-3 verdict.

    Args:
        artifact_manager: The producer-bound ArtifactManager (the only authorised
            QA-artefact write path; sub-agents cannot write ``_temp/qa/``).
        artifact: The validated ``adversarial.json`` payload (schema 3.1).
        attempt: The QA-subflow attempt counter (>= 1) the envelope is scoped to.

    Returns:
        The :class:`ArtifactReference` of the persisted envelope.
    """
    now = datetime.now(tz=UTC)
    envelope_status = (
        EnvelopeStatus.PASS if artifact.status == _STATUS_PASS else EnvelopeStatus.FAIL
    )
    envelope = ArtifactEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        story_id=artifact.story_id,
        run_id=artifact.run_id,
        stage=ADVERSARIAL_STAGE,
        attempt=attempt,
        producer=Producer(
            type=ProducerType.LLM_REVIEWER,
            name=ADVERSARIAL_PRODUCER,
            id=ProducerId(f"{ADVERSARIAL_PRODUCER}-{artifact.run_id}-{attempt:03d}"),
        ),
        started_at=now,
        finished_at=now,
        status=envelope_status,
        artifact_class=ArtifactClass.QA,
        payload=artifact.model_dump(mode="json"),
    )
    return artifact_manager.write(envelope)


__all__ = [
    "AdversarialResultReadError",
    "build_result_artifact",
    "materialize_adversarial_artifact",
    "read_sandbox_result",
]
