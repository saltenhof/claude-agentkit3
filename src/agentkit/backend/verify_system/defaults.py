"""Default construction options for the verify-system facade."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, cast

from agentkit.backend.verify_system.errors import VerifySystemError

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
    from agentkit.backend.verify_system.qa_cycle.invalidation import ArtifactInvalidationSink
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

    max_major_findings: int = 0
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


def resolve_default_options(
    defaults: VerifySystemDefaultOptions | None,
    overrides: dict[str, object],
) -> VerifySystemDefaultOptions:
    """Merge the typed options object with legacy keyword overrides."""
    config = defaults or VerifySystemDefaultOptions()
    if not overrides:
        return config
    option_names = {option.name for option in fields(VerifySystemDefaultOptions)}
    unknown = sorted(set(overrides) - option_names)
    if unknown:
        msg = f"unknown VerifySystem.create_default option(s): {unknown}"
        raise VerifySystemError(msg)
    return VerifySystemDefaultOptions(
        max_major_findings=cast(
            "int", overrides.get("max_major_findings", config.max_major_findings)
        ),
        max_feedback_rounds=cast(
            "int | None",
            overrides.get("max_feedback_rounds", config.max_feedback_rounds),
        ),
        story_context_port=cast(
            "StoryContextQueryPort | None",
            overrides.get("story_context_port", config.story_context_port),
        ),
        sonar_gate_port=cast(
            "SonarGateInputPort | None",
            overrides.get("sonar_gate_port", config.sonar_gate_port),
        ),
        invalidation_sink=cast(
            "ArtifactInvalidationSink | None",
            overrides.get("invalidation_sink", config.invalidation_sink),
        ),
        review_completion_sink=cast(
            "ReviewCompletionSink | None",
            overrides.get("review_completion_sink", config.review_completion_sink),
        ),
        conformance_emitter=cast(
            "EventEmitter | None",
            overrides.get("conformance_emitter", config.conformance_emitter),
        ),
        conformance_config=cast(
            "ConformanceConfig | None",
            overrides.get("conformance_config", config.conformance_config),
        ),
        layer2_bundle_token_limit=cast(
            "int",
            overrides.get(
                "layer2_bundle_token_limit",
                config.layer2_bundle_token_limit,
            ),
        ),
        layer2_llm_client=cast(
            "LlmClient | None",
            overrides.get("layer2_llm_client", config.layer2_llm_client),
        ),
        adversarial_sparring_client=cast(
            "LlmClient | None",
            overrides.get(
                "adversarial_sparring_client", config.adversarial_sparring_client
            ),
        ),
        adversarial_telemetry_emitter=cast(
            "EventEmitter | None",
            overrides.get(
                "adversarial_telemetry_emitter",
                config.adversarial_telemetry_emitter,
            ),
        ),
        adversarial_sparring_resolver=cast(
            "RolePoolResolver | None",
            overrides.get(
                "adversarial_sparring_resolver",
                config.adversarial_sparring_resolver,
            ),
        ),
        fast_test_runner=cast(
            "Callable[[Path], tuple[bool, str | None]] | None",
            overrides.get("fast_test_runner", config.fast_test_runner),
        ),
        stage_registry=cast(
            "StageRegistry | None",
            overrides.get("stage_registry", config.stage_registry),
        ),
        structural_telemetry_port=cast(
            "TelemetryEventQueryPort | None",
            overrides.get(
                "structural_telemetry_port", config.structural_telemetry_port
            ),
        ),
        structural_build_test_port=cast(
            "BuildTestEvidencePort | None",
            overrides.get(
                "structural_build_test_port", config.structural_build_test_port
            ),
        ),
        structural_are_provider=cast(
            "AreGateProvider | None",
            overrides.get("structural_are_provider", config.structural_are_provider),
        ),
        structural_change_evidence_port=cast(
            "ChangeEvidencePort | None",
            overrides.get(
                "structural_change_evidence_port",
                config.structural_change_evidence_port,
            ),
        ),
    )
