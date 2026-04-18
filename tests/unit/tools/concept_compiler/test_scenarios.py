"""Unit tests for formal scenario validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from concept_compiler.compiler import compile_formal_specs
from concept_compiler.scenario_runner import FormalScenarioError

FIXTURES = Path("tests/fixtures/concept_compiler")


def test_compile_formal_specs_validates_scenarios() -> None:
    result = compile_formal_specs(FIXTURES / "scenario_ok")

    assert len(result.validated_scenarios) == 1
    assert result.validated_scenarios[0].scenario_id == "example.scenario.happy_path"


def test_compile_formal_specs_rejects_non_terminal_scenario_end() -> None:
    with pytest.raises(FormalScenarioError, match="terminal status"):
        compile_formal_specs(FIXTURES / "scenario_invalid")
