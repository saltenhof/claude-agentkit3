"""Unit tests for the architecture-conformance checker."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from concept_compiler import (
    ArchitectureViolation,
    audit_architecture_conformance,
    compile_formal_specs,
    load_architecture_conformance_config,
    raise_on_architecture_violations,
    split_violations_by_severity,
)
from concept_compiler.architecture_conformance import ArchitectureConformanceError

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
TELEMETRY_PROJECT_READ_RULE_ID = (
    "architecture-conformance.rule.telemetry_project_read_surface"
)
TELEMETRY_PROJECT_READ_INVARIANT_ID = (
    "architecture-conformance.invariant.telemetry_project_read_surface_is_bounded"
)


def test_architecture_conformance_loads_formal_policy(tmp_path: Path) -> None:
    root = _write_fixture(tmp_path, module_name="agentkit.backend.story.service")

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    assert any(group.name == "StoryApplication" for group in config.component_groups)
    assert any(rule.rule_id == RULE_ID for rule in config.dependency_rules)


def test_architecture_conformance_rejects_forbidden_import(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.backend.story.service",
        source="""
            from agentkit.backend.control_plane.http import ControlPlaneApplication

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
            "agentkit.backend.story.service": """
                from agentkit.backend.kpi_analytics.dashboard.service import DashboardService

                def build() -> type[DashboardService]:
                    return DashboardService
            """,
            "agentkit.backend.kpi_analytics.dashboard.service": """
                from agentkit.backend.story.service import build

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
        module_name="agentkit.backend.story.service",
        source="""
            from agentkit.backend.state_backend import save_story_context

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
        module_name="agentkit.backend.kpi_analytics.service",
        source="""
            from agentkit.backend.state_backend import load_execution_events_global

            def expose() -> object:
                return load_execution_events_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {STORY_READ_RULE_ID}
                reader_symbols:
                  - load_execution_events_global
                allowed_module_prefixes:
                  - agentkit.backend.state_backend
                  - agentkit.backend.story.repository
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
        module_name="agentkit.backend.control_plane.runtime",
        source="""
            from agentkit.backend.state_backend import load_session_run_binding_global

            def expose() -> object:
                return load_session_run_binding_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {CONTROL_PLANE_READ_RULE_ID}
                reader_symbols:
                  - load_session_run_binding_global
                allowed_module_prefixes:
                  - agentkit.backend.state_backend
                  - agentkit.backend.control_plane.repository
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


def test_architecture_conformance_rejects_unauthorized_telemetry_project_read_import(
    tmp_path: Path,
) -> None:
    """AG3-128: A-code importing the project telemetry loader off-surface is AC004."""
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.backend.kpi_analytics.service",
        source="""
            from agentkit.backend.state_backend.store.facade import (
                load_execution_events_for_project_global,
            )

            def expose() -> object:
                return load_execution_events_for_project_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {TELEMETRY_PROJECT_READ_RULE_ID}
                reader_symbols:
                  - load_execution_events_for_project_global
                allowed_module_prefixes:
                  - agentkit.backend.state_backend
                  - agentkit.backend.bootstrap.composition_root
                message: >
                  project-scoped telemetry execution-event read loaders may
                  only be imported from the state-backend telemetry read
                  surface or the composition-root wiring seam
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(violation.code == "AC004" for violation in violations)
    assert any(
        violation.rule_id == TELEMETRY_PROJECT_READ_RULE_ID for violation in violations
    )


def test_architecture_conformance_allows_telemetry_project_read_on_surface(
    tmp_path: Path,
) -> None:
    """AG3-128: the composition-root wiring seam may import the pinned loader."""
    root = _write_fixture(
        tmp_path,
        module_name="agentkit.backend.bootstrap.composition_root",
        source="""
            from agentkit.backend.state_backend.store.facade import (
                load_execution_events_for_project_global,
            )

            def wire() -> object:
                return load_execution_events_for_project_global
        """,
        read_surface_rules=f"""
            read_surface_rules:
              - id: {TELEMETRY_PROJECT_READ_RULE_ID}
                reader_symbols:
                  - load_execution_events_for_project_global
                allowed_module_prefixes:
                  - agentkit.backend.state_backend
                  - agentkit.backend.bootstrap.composition_root
                message: >
                  project-scoped telemetry execution-event read loaders may
                  only be imported from the state-backend telemetry read
                  surface or the composition-root wiring seam
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert not any(
        violation.rule_id == TELEMETRY_PROJECT_READ_RULE_ID for violation in violations
    )


def test_real_spec_pins_telemetry_project_read_surface() -> None:
    """AG3-128: the productive invariants spec loads the new read-surface rule.

    Guards the FIX-THE-MODEL contract: the executable ``read_surface_rule`` and
    its declarative ``invariants:`` twin both exist (no second source of truth).
    """
    compiled = compile_formal_specs(Path("concept/formal-spec"))
    config = load_architecture_conformance_config(compiled)

    rule = next(
        (
            r
            for r in config.read_surface_rules
            if r.rule_id == TELEMETRY_PROJECT_READ_RULE_ID
        ),
        None,
    )
    assert rule is not None, "telemetry_project_read_surface rule missing"
    assert rule.reader_symbols == (
        "load_execution_events_for_project_global",
        "load_execution_event_rows_for_project_global",
    )
    assert rule.allowed_module_prefixes == (
        "agentkit.backend.state_backend",
        "agentkit.backend.bootstrap.composition_root",
    )

    invariants_doc = next(
        doc
        for doc in compiled.documents
        if doc.doc_id == "formal.architecture-conformance.invariants"
    )
    declared_ids = {
        entry["id"] for entry in invariants_doc.spec.get("invariants", [])
    }
    assert TELEMETRY_PROJECT_READ_INVARIANT_ID in declared_ids, (
        "declarative invariant twin missing (second source of truth risk)"
    )


_NEWLY_PINNED_STORY_READ_LOADERS = (
    "load_story_context_by_story_number_global",
    "load_story_context_by_uuid_global",
    "load_story_context_rows_global",
    "load_execution_event_rows_global",
)


def test_real_spec_pins_extended_story_and_telemetry_read_loaders() -> None:
    """AG3-128 review FUND1: every newly pinned global read loader is on-surface."""
    compiled = compile_formal_specs(Path("concept/formal-spec"))
    config = load_architecture_conformance_config(compiled)

    story_rule = next(
        r for r in config.read_surface_rules if r.rule_id == STORY_READ_RULE_ID
    )
    for symbol in _NEWLY_PINNED_STORY_READ_LOADERS:
        assert symbol in story_rule.reader_symbols, symbol

    telemetry_rule = next(
        r
        for r in config.read_surface_rules
        if r.rule_id == TELEMETRY_PROJECT_READ_RULE_ID
    )
    assert (
        "load_execution_event_rows_for_project_global"
        in telemetry_rule.reader_symbols
    )


@pytest.mark.parametrize(
    "loader_symbol",
    [
        "load_story_context_by_uuid_global",
        "load_execution_event_rows_global",
        "load_execution_event_rows_for_project_global",
        "load_project",
        "load_projects",
        "load_project_by_story_id_prefix",
    ],
)
def test_real_spec_rejects_offsurface_global_read_loader(
    tmp_path: Path, loader_symbol: str
) -> None:
    """AG3-128 review FUND2: real-spec audit flags off-surface pinned loaders.

    Uses the productive ``concept/formal-spec`` rules (not a synthetic fixture)
    against a synthetic A-code module to prove fail-closed AC004 coverage of the
    newly pinned story-context and execution-event-rows loaders.
    """
    code_root = tmp_path / "src"
    module_dir = code_root / "agentkit" / "backend" / "kpi_analytics"
    module_dir.mkdir(parents=True)
    (module_dir / "read_model_leak.py").write_text(
        "from __future__ import annotations\n"
        "from agentkit.backend.state_backend.store.facade import (\n"
        f"    {loader_symbol},\n"
        ")\n\n\n"
        "def leak() -> object:\n"
        f"    return {loader_symbol}\n",
        encoding="utf-8",
    )

    compiled = compile_formal_specs(Path("concept/formal-spec"))
    violations = audit_architecture_conformance(compiled, code_root)

    ac004 = [v for v in violations if v.code == "AC004"]
    assert ac004, f"expected AC004 for {loader_symbol}, got {violations}"
    assert any(loader_symbol in v.message for v in ac004)


def test_architecture_conformance_accepts_current_repo() -> None:
    """Component-group checks (AC001-AC008) produce no violations on the current repo.

    AC010-AC012 (boundary-module checks) may produce violations because the
    existing src/ pre-dates the code refactor that will align modules with
    boundary_modules. The tool must return violations without aborting.
    """
    compiled = compile_formal_specs(Path("concept/formal-spec"))

    violations = audit_architecture_conformance(compiled, Path("src"))

    # Component-group checks must remain clean.
    component_violations = [
        v for v in violations if v.code in {"AC001", "AC002", "AC003", "AC004",
                                             "AC005", "AC006", "AC007", "AC008"}
    ]
    assert not component_violations, (
        f"Unexpected component-group violations: {component_violations}"
    )
    # Boundary violations (AC010-AC012) are expected during the code-refactor
    # phase; the audit must run without raising.
    assert isinstance(violations, tuple)


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
                  - agentkit.backend.story
              - id: architecture-conformance.group.kpi_analytics
                name: KpiAnalyticsApplication
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.kpi_analytics
              - id: architecture-conformance.group.control_plane
                name: ControlPlaneHttp
                bloodgroup: R
                module_prefixes:
                  - agentkit.backend.control_plane
              - id: architecture-conformance.group.projectedge
                name: ProjectEdgeClient
                bloodgroup: R
                module_prefixes:
                  - agentkit.harness_client.projectedge
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
                  - agentkit.backend.story
                  - agentkit.backend.kpi_analytics
                forbidden_module_prefixes:
                  - agentkit.backend.control_plane.http
                  - agentkit.harness_client.projectedge.client
                message: >
                  story and kpi_analytics application code may not depend on
                  control-plane transport or project-edge transport
                transition_exceptions:
                  - agentkit.backend.kpi_analytics.dashboard.service
            acyclic_group_sets:
              - id: architecture-conformance.acyclic.application_surface
                group_ids:
                  - architecture-conformance.group.story
                  - architecture-conformance.group.kpi_analytics
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


# ---------------------------------------------------------------------------
# Severity-Mechanismus
# ---------------------------------------------------------------------------


def _make_violation(
    code: str, severity: str = "error"
) -> ArchitectureViolation:
    return ArchitectureViolation(
        code=code,
        path=None,
        module="test.module",
        line=1,
        column=0,
        message=f"synthetic {code}",
        rule_id=f"test.{code}",
        severity=severity,  # type: ignore[arg-type]
    )


def test_violation_default_severity_is_error() -> None:
    """Backward-compat: severity defaultet auf error."""
    v = ArchitectureViolation(
        code="ACX",
        path=None,
        module="m",
        line=1,
        column=0,
        message="x",
        rule_id="r",
    )
    assert v.severity == "error"


def test_split_violations_by_severity_separates_correctly() -> None:
    """split_violations_by_severity trennt errors und warnings sauber."""
    err1 = _make_violation("AC001", severity="error")
    warn1 = _make_violation("AC012", severity="warning")
    err2 = _make_violation("AC002", severity="error")
    warn2 = _make_violation("AC012", severity="warning")

    errors, warnings = split_violations_by_severity((err1, warn1, err2, warn2))

    assert errors == (err1, err2)
    assert warnings == (warn1, warn2)


def test_raise_on_architecture_violations_ignores_warnings() -> None:
    """Bei nur Warnings darf raise_on_architecture_violations nicht raisen."""
    warn = _make_violation("AC012", severity="warning")

    raise_on_architecture_violations((warn,))


def test_raise_on_architecture_violations_raises_on_errors() -> None:
    """Bei mindestens einem Error muss raise_on_architecture_violations raisen."""
    err = _make_violation("AC001", severity="error")
    warn = _make_violation("AC012", severity="warning")

    with pytest.raises(ArchitectureConformanceError):
        raise_on_architecture_violations((err, warn))


def test_raise_on_architecture_violations_passes_on_empty() -> None:
    """Leere Liste raised nicht."""
    raise_on_architecture_violations(())


# ---------------------------------------------------------------------------
# Bluttyp 0
# ---------------------------------------------------------------------------


def test_bloodgroup_zero_accepted_in_entities(tmp_path: Path) -> None:
    """Bluttyp 0 (Null-Software) wird in entities.md als component_groups-Wert akzeptiert."""
    root = tmp_path / "repo"
    formal_root = root / "concept" / "formal-spec" / "architecture-conformance"
    formal_root.mkdir(parents=True)
    (root / "src").mkdir()

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
            component_groups:
              - id: architecture-conformance.group.shared_utils
                name: SharedUtils
                bloodgroup: "0"
                module_prefixes:
                  - agentkit.shared
            ```
            <!-- FORMAL-SPEC:END -->
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    (formal_root / "invariants.md").write_text(
        dedent(
            """
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
            dependency_rules: []
            acyclic_group_sets: []
            mutation_surface_rules: []
            invariants: []
            ```
            <!-- FORMAL-SPEC:END -->
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    compiled = compile_formal_specs(formal_root.parent)
    config = load_architecture_conformance_config(compiled)

    shared = next(
        group for group in config.component_groups if group.name == "SharedUtils"
    )
    assert shared.bloodgroup == "0"
