from agentkit.pipeline_engine import PipelineEngine
from agentkit.pipeline_engine.implementation_phase import ImplementationPhaseHandler
from agentkit.pipeline_engine.setup_phase import SetupPhaseHandler


def test_pipeline_engine_namespace_exposes_public_types() -> None:
    assert PipelineEngine.__name__ == "PipelineEngine"
    assert SetupPhaseHandler.__name__ == "SetupPhaseHandler"
    assert ImplementationPhaseHandler.__name__ == "ImplementationPhaseHandler"
