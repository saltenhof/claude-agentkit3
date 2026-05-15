import agentkit.pipeline_engine as _pe
from agentkit.pipeline_engine.implementation_phase import ImplementationPhaseHandler
from agentkit.pipeline_engine.setup_phase import SetupPhaseHandler


def test_pipeline_engine_namespace_exposes_public_types() -> None:
    # PipelineEngine is lazily loaded; access through module to avoid type narrowing issues.
    engine_cls = _pe.PipelineEngine
    assert getattr(engine_cls, "__name__", None) == "PipelineEngine"
    assert SetupPhaseHandler.__name__ == "SetupPhaseHandler"
    assert ImplementationPhaseHandler.__name__ == "ImplementationPhaseHandler"
