from agentkit.pipeline import PipelineEngine as LegacyPipelineEngine
from agentkit.pipeline_engine import PipelineEngine
from agentkit.pipeline_engine.setup_phase import SetupPhaseHandler
from agentkit.pipeline_engine.verify_phase import VerifyPhaseHandler


def test_pipeline_engine_namespace_reexports_legacy_api() -> None:
    assert PipelineEngine is LegacyPipelineEngine
    assert SetupPhaseHandler.__name__ == "SetupPhaseHandler"
    assert VerifyPhaseHandler.__name__ == "VerifyPhaseHandler"
