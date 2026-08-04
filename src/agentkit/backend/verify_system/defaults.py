"""Default construction options for the verify-system facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.config.models import ConformanceConfig
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.verify_system.llm_evaluator import LlmClient
    from agentkit.backend.verify_system.llm_evaluator.llm_client import RolePoolResolver
    from agentkit.backend.verify_system.protocols import (
        StoryContextQueryPort,
        TelemetryEventQueryPort,
    )
    from agentkit.backend.verify_system.qa_cycle.fingerprint import (
        QaCycleFingerprintSource,
    )
    from agentkit.backend.verify_system.qa_cycle.invalidation import ArtifactInvalidationSink
    from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCyclePushBarrierGate
    from agentkit.backend.verify_system.review_completion import ReviewCompletionSink
    from agentkit.backend.verify_system.sonarqube_gate.port import SonarGateInputPort
    from agentkit.backend.verify_system.stage_registry.registry import StageRegistry
    from agentkit.backend.verify_system.structural.checker import AreGateProvider
    from agentkit.backend.verify_system.structural.checks import (
        BuildTestEvidencePort,
        ChangeEvidencePort,
    )


@dataclass(frozen=True)
class VerifySystemDefaultOptions:
    """Optional collaborator bundle for ``VerifySystem.create_default``."""

    max_feedback_rounds: int | None = None
    story_context_port: StoryContextQueryPort | None = None
    sonar_gate_port: SonarGateInputPort | None = None
    invalidation_sink: ArtifactInvalidationSink | None = None
    review_completion_sink: ReviewCompletionSink | None = None
    conformance_emitter: EventEmitter | None = None
    conformance_config: ConformanceConfig | None = None
    layer2_bundle_token_limit: int = 32_000
    layer2_llm_client: LlmClient | None = None
    #: AG3-079 (FK-48 §48.1.6 / FK-11 §11.8): the verify-LLM-transport the Layer-3
    #: runtime drives for the MANDATORY ``adversarial_sparring`` call. ``None`` =>
    #: the Layer-3 runtime is unwired and fails closed (no PASS without sparring).
    adversarial_sparring_client: LlmClient | None = None
    #: AG3-079 (FK-48 §48.1.8): the emitter the Layer-3 runtime writes its five
    #: adversarial telemetry events to. ``None`` => unwired -> fail-closed.
    adversarial_telemetry_emitter: EventEmitter | None = None
    #: AG3-079: optional role->pool resolver to record the concrete sparring pool
    #: label in the telemetry / ``adversarial.json`` (FK-48 §48.1.6 ``pool``).
    adversarial_sparring_resolver: RolePoolResolver | None = None
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None
    stage_registry: StageRegistry | None = None
    structural_telemetry_port: TelemetryEventQueryPort | None = None
    structural_build_test_port: BuildTestEvidencePort | None = None
    structural_are_provider: AreGateProvider | None = None
    structural_change_evidence_port: ChangeEvidencePort | None = None
    #: AG3-147 (FK-10 §10.2.4b boundary type 2): the QA-cycle-boundary push-barrier
    #: gate the ``QaCycleLifecycle`` enforces before advancing a cycle round.
    #: ``None`` => the no-op gate (test / unwired path); the composition root wires
    #: the productive control-plane-delegating gate.
    qa_cycle_push_barrier_gate: QaCyclePushBarrierGate | None = None
    #: AG3-147 AC11: source of reported pushed heads / compare evidence used for
    #: QA-cycle fingerprints. ``None`` leaves the lifecycle fail-closed unless a
    #: caller injects an explicit source.
    qa_cycle_fingerprint_source: QaCycleFingerprintSource | None = None
