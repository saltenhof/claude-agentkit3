"""Compiler and linting helpers for formal concept specifications."""

from __future__ import annotations

from .architecture_conformance import (
    ArchitectureConformanceConfig,
    ArchitectureConformanceError,
    ArchitectureViolation,
    BloodtypeDependencyRule,
    BoundaryModule,
    BoundaryModuleKind,
    ComponentGroup,
    EffectSurface,
    TypeTaintRule,
    audit_architecture_conformance,
    load_architecture_conformance_config,
    raise_on_architecture_violations,
    render_component_tree,
    split_violations_by_severity,
)
from .compiler import (
    CompiledFormalSpec,
    FormalReference,
    compile_formal_specs,
)
from .drift import DriftLink, audit_formal_prose_links
from .loader import (
    FormalSpecDocument,
    discover_formal_spec_files,
    load_formal_spec,
)
from .scenario_runner import (
    FormalScenarioError,
    ScenarioValidation,
    validate_scenarios,
)
from .truth_boundary import (
    ContractViolation,
    TruthBoundaryConfig,
    TruthBoundaryError,
    audit_truth_boundary,
    load_truth_boundary_config,
    raise_on_truth_boundary_violations,
)

__all__ = [
    "ArchitectureConformanceConfig",
    "ArchitectureConformanceError",
    "ArchitectureViolation",
    "BloodtypeDependencyRule",
    "BoundaryModule",
    "BoundaryModuleKind",
    "ComponentGroup",
    "CompiledFormalSpec",
    "DriftLink",
    "EffectSurface",
    "FormalReference",
    "FormalScenarioError",
    "FormalSpecDocument",
    "ScenarioValidation",
    "ContractViolation",
    "TruthBoundaryConfig",
    "TruthBoundaryError",
    "TypeTaintRule",
    "audit_architecture_conformance",
    "audit_formal_prose_links",
    "audit_truth_boundary",
    "compile_formal_specs",
    "discover_formal_spec_files",
    "load_architecture_conformance_config",
    "load_truth_boundary_config",
    "load_formal_spec",
    "raise_on_architecture_violations",
    "raise_on_truth_boundary_violations",
    "render_component_tree",
    "split_violations_by_severity",
    "validate_scenarios",
]
