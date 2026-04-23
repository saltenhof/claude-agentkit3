"""Unit tests for the architecture-conformance checker."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from concept_compiler import (
    audit_architecture_conformance,
    compile_formal_specs,
    load_architecture_conformance_config,
)

RULE_ID = (
    "architecture-conformance.rule."
    "story_dashboard_must_not_depend_on_transport_or_hook_adapters"
)
INVARIANT_ID = (
    "architecture-conformance.invariant."
    "story_dashboard_transport_boundary"
)
MUTATION_RULE_ID = "architecture-conformance.rule.story_context_write_surface"
STORY_READ_RULE_ID = "architecture-conformance.rule.story_read_surface"
CONTROL_PLANE_READ_RULE_ID = (
    "architecture-conformance.rule.control_plane_runtime_read_surface"
)


def test_architecture_conformance_loads_formal_policy(tmp_path: Path) -> None:
    root = _write_fixture(tmp_path, module_name="agentkit.story.service")

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    assert any(group.name == "StoryApplication" for group in config.component_groups)
    assert any(rule.rule_id == RULE_ID for rule in config.dependency_rules)


def test_architecture_conformance_rejects_forbidden_import(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.story.service",
        source="""
            from agentkit.control_plane.http import ControlPlaneApplication

            def build() -> type[ControlPlaneApplication]:
                return ControlPlaneApplication
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC001" for violation in violations)
    assert any(
        "control-plane transport" in violation.message
        for violation in violations
    )


def test_architecture_conformance_rejects_component_cycle(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        files={
            "agentkit.story.service": """
                from agentkit.dashboard.service import DashboardService

                def build() -> type[DashboardService]:
                    return DashboardService
            """,
            "agentkit.dashboard.service": """
                from agentkit.story.service import build

                def call() -> object:
                    return build()
            """,
        },
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC002" for violation in violations)


def test_architecture_conformance_rejects_unauthorized_writer_surface_import(
    tmp_path: Path,
) -> None:
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.story.service",
        source="""
            from agentkit.state_backend import save_story_context

            def expose() -> object:
                return save_story_context
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC003" for violation in violations)
    assert any(violation.rule_id == MUTATION_RULE_ID for violation in violations)


def test_architecture_conformance_rejects_unauthorized_read_surface_import(
    tmp_path: Path,
) -> None:
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.dashboard.service",
        source="""
            from agentkit.state_backend import load_execution_events_global

            def expose() -> object:
                return load_execution_events_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {STORY_READ_RULE_ID}
                reader_symbols:
                  - load_execution_events_global
                allowed_module_prefixes:
                  - agentkit.state_backend
                  - agentkit.story.repository
                message: >
                  story read loaders may only be imported from the
                  explicit story repository surface
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC004" for violation in violations)
    assert any(violation.rule_id == STORY_READ_RULE_ID for violation in violations)


def test_architecture_conformance_rejects_unauthorized_control_plane_read_import(
    tmp_path: Path,
) -> None:
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.control_plane.runtime",
        source="""
            from agentkit.state_backend import load_session_run_binding_global

            def expose() -> object:
                return load_session_run_binding_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {CONTROL_PLANE_READ_RULE_ID}
                reader_symbols:
                  - load_session_run_binding_global
                allowed_module_prefixes:
                  - agentkit.state_backend
                  - agentkit.control_plane.repository
                message: >
                  control-plane runtime read loaders may only be imported
                  from the explicit control-plane repository surface
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC004" for violation in violations)
    assert any(
        violation.rule_id == CONTROL_PLANE_READ_RULE_ID
        for violation in violations
    )


def test_architecture_conformance_accepts_current_repo() -> None:
    compiled = compile_formal_specs(Path("concept/formal-spec"))

    violations = audit_architecture_conformance(compiled, Path("src"))

    assert violations == ()


def _write_fixture(
    tmp_path: Path,
    *,
    module_name: str | None = None,
    source: str | None = None,
    files: dict[str, str] | None = None,
    read_surface_rules: str = "",
) -> Path:
    root = tmp_path / "repo"
    formal_root = root / "concept" / "formal-spec" / "architecture-conformance"
    source_root = root / "src"
    formal_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    (formal_root / "entities.md").write_text(
        dedent(
            """
            ---
            id: formal.architecture-conformance.entities
            title: Architecture Conformance Entities
            status: active
            doc_kind: spec
            context: architecture-conformance
            spec_kind: entity-set
            version: 1
            prose_refs: []
            ---

            # Test Entities

            <!-- FORMAL-SPEC:BEGIN -->
            ```yaml
            object: formal.architecture-conformance.entities
            schema_version: 1
            kind: entity-set
            context: architecture-conformance
            bloodgroups:
              - id: architecture-conformance.bloodgroup.a_code
                code: A
                meaning: domain component
            component_groups:
              - id: architecture-conformance.group.story
                name: StoryApplication
                bloodgroup: A
                module_prefixes:
                  - agentkit.story
              - id: architecture-conformance.group.dashboard
                name: DashboardApplication
                bloodgroup: A
                module_prefixes:
                  - agentkit.dashboard
              - id: architecture-conformance.group.control_plane
                name: ControlPlaneHttp
                bloodgroup: R
                module_prefixes:
                  - agentkit.control_plane
              - id: architecture-conformance.group.projectedge
                name: ProjectEdgeClient
                bloodgroup: R
                module_prefixes:
                  - agentkit.projectedge
            ```
            <!-- FORMAL-SPEC:END -->
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    (formal_root / "invariants.md").write_text(
        dedent(
            f"""
            ---
            id: formal.architecture-conformance.invariants
            title: Architecture Conformance Invariants
            status: active
            doc_kind: spec
            context: architecture-conformance
            spec_kind: invariant-set
            version: 1
            prose_refs: []
            ---

            # Test Invariants

            <!-- FORMAL-SPEC:BEGIN -->
            ```yaml
            object: formal.architecture-conformance.invariants
            schema_version: 1
            kind: invariant-set
            context: architecture-conformance
            dependency_rules:
              - id: {RULE_ID}
                source_module_prefixes:
                  - agentkit.story
                  - agentkit.dashboard
                forbidden_module_prefixes:
                  - agentkit.control_plane.http
                  - agentkit.projectedge.client
                message: >
                  story and dashboard application code may not depend on
                  control-plane transport or project-edge transport
            acyclic_group_sets:
              - id: architecture-conformance.acyclic.application_surface
                group_ids:
                  - architecture-conformance.group.story
                  - architecture-conformance.group.dashboard
            mutation_surface_rules:
              - id: {MUTATION_RULE_ID}
                writer_symbols:
                  - save_story_context
                allowed_module_prefixes:
                  - agentkit.pipeline
                message: >
                  story context mutation may only be imported from
                  pipeline surfaces
            {read_surface_rules}
            invariants:
              - id: {INVARIANT_ID}
                scope: static-analysis
                rule: >
                  story and dashboard modules may not import transport
                  adapters
            ```
            <!-- FORMAL-SPEC:END -->
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    if files is None and module_name is not None:
        files = {module_name: source or "def noop():\n    return None\n"}
    for item_name, item_source in (files or {}).items():
        module_path = source_root.joinpath(*item_name.split("."))
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.with_suffix(".py").write_text(
            dedent(item_source).strip() + "\n",
            encoding="utf-8",
        )
    return root
