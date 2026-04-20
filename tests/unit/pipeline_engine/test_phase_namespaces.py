"""Unit tests for pipeline_engine phase namespace exports."""

import agentkit.pipeline_engine.closure_phase as closure_phase
import agentkit.pipeline_engine.exploration_phase as exploration_phase
import agentkit.pipeline_engine.implementation_phase as implementation_phase
from agentkit.pipeline.phases.closure.execution_report import (
    ExecutionReport as CanonicalExecutionReport,
)
from agentkit.pipeline.phases.closure.execution_report import (
    write_execution_report as canonical_write_execution_report,
)
from agentkit.pipeline.phases.closure.phase import (
    ClosureConfig as CanonicalClosureConfig,
)
from agentkit.pipeline.phases.closure.phase import (
    ClosurePhaseHandler as CanonicalClosurePhaseHandler,
)


def test_closure_phase_namespace_reexports_canonical_symbols() -> None:
    assert closure_phase.ExecutionReport is CanonicalExecutionReport
    assert closure_phase.write_execution_report is canonical_write_execution_report
    assert closure_phase.ClosureConfig is CanonicalClosureConfig
    assert closure_phase.ClosurePhaseHandler is CanonicalClosurePhaseHandler


def test_empty_phase_namespaces_are_explicitly_empty() -> None:
    assert exploration_phase.__all__ == []
    assert implementation_phase.__all__ == []
