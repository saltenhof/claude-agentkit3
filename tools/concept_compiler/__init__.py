"""Compiler and linting helpers for formal concept specifications."""

from __future__ import annotations

from concept_compiler.compiler import (
    CompiledFormalSpec,
    FormalReference,
    compile_formal_specs,
)
from concept_compiler.drift import DriftLink, audit_formal_prose_links
from concept_compiler.loader import (
    FormalSpecDocument,
    discover_formal_spec_files,
    load_formal_spec,
)
from concept_compiler.scenario_runner import (
    FormalScenarioError,
    ScenarioValidation,
    validate_scenarios,
)
from concept_compiler.truth_boundary import (
    ContractViolation,
    TruthBoundaryConfig,
    TruthBoundaryError,
    audit_truth_boundary,
    load_truth_boundary_config,
    raise_on_truth_boundary_violations,
)

__all__ = [
    "CompiledFormalSpec",
    "DriftLink",
    "FormalReference",
    "FormalScenarioError",
    "FormalSpecDocument",
    "ScenarioValidation",
    "ContractViolation",
    "TruthBoundaryConfig",
    "TruthBoundaryError",
    "audit_formal_prose_links",
    "audit_truth_boundary",
    "compile_formal_specs",
    "discover_formal_spec_files",
    "load_truth_boundary_config",
    "load_formal_spec",
    "raise_on_truth_boundary_violations",
    "validate_scenarios",
]
