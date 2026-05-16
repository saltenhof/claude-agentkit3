"""Pipeline-engine top-level namespace exposes only orchestration types."""

from __future__ import annotations

import agentkit.pipeline_engine as _pe


def test_pipeline_engine_namespace_exposes_orchestrator_surface() -> None:
    """``agentkit.pipeline_engine.*`` must expose orchestration symbols only.

    Phase handler classes live in their owning bounded contexts and must
    not be re-exported by the engine namespace.
    """

    assert _pe.PipelineEngine.__name__ == "PipelineEngine"
    assert _pe.PhaseHandlerRegistry.__name__ == "PhaseHandlerRegistry"
    assert _pe.PhaseHandler.__name__ == "PhaseHandler"
    assert _pe.HandlerResult.__name__ == "HandlerResult"
    assert _pe.NoOpHandler.__name__ == "NoOpHandler"
    assert _pe.AttemptRecord.__name__ == "AttemptRecord"
    assert _pe.EngineResult.__name__ == "EngineResult"
    assert _pe.PipelineRunResult.__name__ == "PipelineRunResult"
    assert _pe.EngineRuntimeState.__name__ == "EngineRuntimeState"
    assert callable(_pe.run_pipeline)


def test_pipeline_engine_does_not_reexport_phase_handlers() -> None:
    """Phase handlers belong to their BCs, not to ``pipeline_engine``."""

    for forbidden in (
        "SetupPhaseHandler",
        "ImplementationPhaseHandler",
        "ClosurePhaseHandler",
    ):
        assert not hasattr(_pe, forbidden), (
            f"pipeline_engine must not re-export {forbidden!r}"
        )
