"""Extended unit tests for the architecture-conformance checker.

Covers AC005-AC008, hierarchical component groups, and the tree subcommand.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from concept_compiler import (
    audit_architecture_conformance,
    compile_formal_specs,
    load_architecture_conformance_config,
    render_component_tree,
)
from concept_compiler.architecture_conformance import ArchitectureConformanceError

# ---------------------------------------------------------------------------
# Shared spec-writing helpers
# ---------------------------------------------------------------------------

_BASE_RULE_ID = (
    "architecture-conformance.rule."
    "story_dashboard_must_not_depend_on_transport_or_hook_adapters"
)
_MUTATION_RULE_ID = "architecture-conformance.rule.story_context_write_surface"
_INVARIANT_ID = "architecture-conformance.invariant.story_dashboard_transport_boundary"


def _indent(text: str, spaces: int) -> str:
    """Indent every non-empty line by the given number of spaces."""
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def _write_spec(
    tmp_path: Path,
    *,
    extra_groups: str = "",
    extra_invariants: str = "",
    files: dict[str, str] | None = None,
) -> Path:
    """Write a minimal formal-spec fixture with optional extra groups/invariants.

    Args:
        tmp_path: Base temporary directory.
        extra_groups: Extra YAML fragment (un-indented list items) appended
            inside component_groups. Each item must start with ``- ``.
        extra_invariants: Extra YAML fragment appended as top-level keys to the
            invariants spec body.
        files: Dict of module_name -> source_code.

    Returns:
        Root of the temporary repo.
    """
    root = tmp_path / "repo"
    formal_root = root / "concept" / "formal-spec" / "architecture-conformance"
    source_root = root / "src"
    formal_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    # Build component_groups section: base entries + optional extras.
    # extra_groups items must be indented by 2 spaces to be valid YAML
    # under the component_groups key.
    import textwrap as _textwrap

    extra_groups_stripped = dedent(extra_groups).strip()
    extra_groups_block = "\n" + _textwrap.indent(extra_groups_stripped, "  ") if extra_groups_stripped else ""

    entities_yaml = (
        "---\n"
        "id: formal.architecture-conformance.entities\n"
        "title: Architecture Conformance Entities\n"
        "status: active\n"
        "doc_kind: spec\n"
        "context: architecture-conformance\n"
        "spec_kind: entity-set\n"
        "version: 1\n"
        "prose_refs: []\n"
        "---\n"
        "\n"
        "# Test Entities\n"
        "\n"
        "<!-- FORMAL-SPEC:BEGIN -->\n"
        "```yaml\n"
        "object: formal.architecture-conformance.entities\n"
        "schema_version: 1\n"
        "kind: entity-set\n"
        "context: architecture-conformance\n"
        "bloodgroups:\n"
        "  - id: architecture-conformance.bloodgroup.a_code\n"
        "    code: A\n"
        "    meaning: domain component\n"
        "  - id: architecture-conformance.bloodgroup.r_code\n"
        "    code: R\n"
        "    meaning: adapter\n"
        "  - id: architecture-conformance.bloodgroup.t_code\n"
        "    code: T\n"
        "    meaning: infrastructure driver\n"
        "component_groups:\n"
        "  - id: architecture-conformance.group.story\n"
        "    name: StoryApplication\n"
        "    bloodgroup: A\n"
        "    module_prefixes:\n"
        "      - agentkit.backend.story\n"
        "  - id: architecture-conformance.group.kpi_analytics\n"
        "    name: KpiAnalyticsApplication\n"
        "    bloodgroup: A\n"
        "    module_prefixes:\n"
        "      - agentkit.backend.kpi_analytics\n"
        "  - id: architecture-conformance.group.control_plane\n"
        "    name: ControlPlaneHttp\n"
        "    bloodgroup: R\n"
        "    module_prefixes:\n"
        "      - agentkit.backend.control_plane\n"
        "  - id: architecture-conformance.group.infra_driver\n"
        "    name: InfraDriver\n"
        "    bloodgroup: T\n"
        "    module_prefixes:\n"
        "      - agentkit.infra_driver\n" + extra_groups_block + "\n"
        "```\n"
        "<!-- FORMAL-SPEC:END -->\n"
    )

    extra_invariants_block = dedent(extra_invariants).strip()
    if extra_invariants_block:
        extra_invariants_block = "\n" + extra_invariants_block + "\n"

    invariants_yaml = (
        "---\n"
        "id: formal.architecture-conformance.invariants\n"
        "title: Architecture Conformance Invariants\n"
        "status: active\n"
        "doc_kind: spec\n"
        "context: architecture-conformance\n"
        "spec_kind: invariant-set\n"
        "version: 1\n"
        "prose_refs: []\n"
        "---\n"
        "\n"
        "# Test Invariants\n"
        "\n"
        "<!-- FORMAL-SPEC:BEGIN -->\n"
        "```yaml\n"
        "object: formal.architecture-conformance.invariants\n"
        "schema_version: 1\n"
        "kind: invariant-set\n"
        "context: architecture-conformance\n"
        f"dependency_rules:\n"
        f"  - id: {_BASE_RULE_ID}\n"
        "    source_module_prefixes:\n"
        "      - agentkit.backend.story\n"
        "      - agentkit.backend.kpi_analytics\n"
        "    forbidden_module_prefixes:\n"
        "      - agentkit.backend.control_plane.http\n"
        "    message: story must not depend on control-plane transport\n"
        "acyclic_group_sets:\n"
        "  - id: architecture-conformance.acyclic.application_surface\n"
        "    group_ids:\n"
        "      - architecture-conformance.group.story\n"
        "      - architecture-conformance.group.kpi_analytics\n"
        "mutation_surface_rules:\n"
        f"  - id: {_MUTATION_RULE_ID}\n"
        "    writer_symbols:\n"
        "      - save_story_context\n"
        "    allowed_module_prefixes:\n"
        "      - agentkit.pipeline\n"
        "    message: story context mutation must come from pipeline\n"
        "invariants:\n"
        f"  - id: {_INVARIANT_ID}\n"
        "    scope: static-analysis\n"
        "    rule: story must not import transport adapters\n"
        + extra_invariants_block
        + "```\n"
        "<!-- FORMAL-SPEC:END -->\n"
    )

    (formal_root / "entities.md").write_text(entities_yaml, encoding="utf-8")
    (formal_root / "invariants.md").write_text(invariants_yaml, encoding="utf-8")

    for module_name, source in (files or {}).items():
        module_path = source_root.joinpath(*module_name.split("."))
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.with_suffix(".py").write_text(
            dedent(source).strip() + "\n", encoding="utf-8"
        )

    return root


# ---------------------------------------------------------------------------
# A) Schema extension — hierarchy and exposure
# ---------------------------------------------------------------------------


def test_parent_group_id_resolves_correctly(tmp_path: Path) -> None:
    """parent_group_id pointing to an existing group must load without error."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.story_sub
                name: StorySubComponent
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.sub
                parent_group_id: architecture-conformance.group.story
                exposure: sub_exposed
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    sub = next(
        g
        for g in config.component_groups
        if g.group_id == "architecture-conformance.group.story_sub"
    )
    assert sub.parent_group_id == "architecture-conformance.group.story"
    assert sub.exposure == "sub_exposed"
    assert not sub.is_top()


def test_parent_group_id_unknown_raises(tmp_path: Path) -> None:
    """parent_group_id pointing to a non-existent group must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.dangling
                name: DanglingGroup
                bloodgroup: A
                module_prefixes:
                  - agentkit.dangling
                parent_group_id: architecture-conformance.group.nonexistent
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="unknown parent_group_id"):
        load_architecture_conformance_config(compiled)


def test_parent_group_id_cycle_raises(tmp_path: Path) -> None:
    """Cyclic parent_group_id chains must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.alpha
                name: Alpha
                bloodgroup: A
                module_prefixes:
                  - agentkit.alpha
                parent_group_id: architecture-conformance.group.beta
              - id: architecture-conformance.group.beta
                name: Beta
                bloodgroup: A
                module_prefixes:
                  - agentkit.beta
                parent_group_id: architecture-conformance.group.alpha
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="cycle"):
        load_architecture_conformance_config(compiled)


def test_default_exposure_top_for_root_group(tmp_path: Path) -> None:
    """Groups without parent default to exposure=top."""
    root = _write_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    story = next(
        g
        for g in config.component_groups
        if g.group_id == "architecture-conformance.group.story"
    )
    assert story.exposure == "top"
    assert story.is_top()


def test_default_exposure_internal_for_child_group(tmp_path: Path) -> None:
    """Groups with parent but no explicit exposure default to internal."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.story_inner
                name: StoryInner
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.inner
                parent_group_id: architecture-conformance.group.story
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    inner = next(
        g
        for g in config.component_groups
        if g.group_id == "architecture-conformance.group.story_inner"
    )
    assert inner.exposure == "internal"
    assert not inner.is_top()


def test_sub_exposed_without_parent_raises(tmp_path: Path) -> None:
    """exposure=sub_exposed without parent_group_id must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.orphan_exposed
                name: OrphanExposed
                bloodgroup: A
                module_prefixes:
                  - agentkit.orphan
                exposure: sub_exposed
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(
        ArchitectureConformanceError, match="sub_exposed requires a parent"
    ):
        load_architecture_conformance_config(compiled)


def test_component_kind_shared_validation_all_fields_required(tmp_path: Path) -> None:
    """shared component_kind without required fields must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.bad_shared
                name: BadShared
                bloodgroup: A
                module_prefixes:
                  - agentkit.bad_shared
                component_kind: shared
                owner_group_id: architecture-conformance.group.story
            """
            # missing allowed_importers, exported_symbols, allowed_imported_symbols
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(
        ArchitectureConformanceError, match="requires non-empty 'allowed_importers'"
    ):
        load_architecture_conformance_config(compiled)


def test_component_kind_shared_valid(tmp_path: Path) -> None:
    """Fully specified shared component must load without error."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.good_shared
                name: GoodShared
                bloodgroup: A
                module_prefixes:
                  - agentkit.good_shared
                component_kind: shared
                owner_group_id: architecture-conformance.group.story
                allowed_importers:
                  - architecture-conformance.group.story
                exported_symbols:
                  - agentkit.good_shared.SomeClass
                allowed_imported_symbols:
                  - agentkit.good_shared.SomeClass
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    shared = next(
        g
        for g in config.component_groups
        if g.group_id == "architecture-conformance.group.good_shared"
    )
    assert shared.is_shared()
    assert shared.owner_group_id == "architecture-conformance.group.story"


def test_shared_allowed_importer_must_be_top_level(tmp_path: Path) -> None:
    """allowed_importers containing non-top-level group must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.story_sub
                name: StorySub
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.sub
                parent_group_id: architecture-conformance.group.story
              - id: architecture-conformance.group.shared_x
                name: SharedX
                bloodgroup: A
                module_prefixes:
                  - agentkit.shared_x
                component_kind: shared
                owner_group_id: architecture-conformance.group.story
                allowed_importers:
                  - architecture-conformance.group.story_sub
                exported_symbols:
                  - agentkit.shared_x.Foo
                allowed_imported_symbols:
                  - agentkit.shared_x.Foo
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="not a top-level group"):
        load_architecture_conformance_config(compiled)


def test_top_surface_modules_must_be_subprefix(tmp_path: Path) -> None:
    """top_surface_modules entries not under module_prefixes must raise."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.bad_surface
                name: BadSurface
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story
                top_surface_modules:
                  - agentkit.other.module
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="not a subprefix"):
        load_architecture_conformance_config(compiled)


# ---------------------------------------------------------------------------
# B) AC008 — Module completeness check
# ---------------------------------------------------------------------------


_AC008_OPT_IN = "module_completeness_check: true"


def test_ac008_unassigned_module_raises_violation(tmp_path: Path) -> None:
    """A module without a matching component_group raises AC008 when enabled."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_AC008_OPT_IN,
        files={
            "agentkit.unknown_module.service": "def noop():\n    return None\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(v.code == "AC008" for v in violations)
    assert any(
        v.module == "agentkit.unknown_module.service" and v.code == "AC008"
        for v in violations
    )


def test_ac008_assigned_module_no_violation(tmp_path: Path) -> None:
    """A module with a matching component_group must not produce AC008."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_AC008_OPT_IN,
        files={
            "agentkit.backend.story.service": "def noop():\n    return None\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac008 = [v for v in violations if v.code == "AC008"]
    assert ac008 == []


def test_ac008_non_agentkit_module_not_flagged(tmp_path: Path) -> None:
    """Modules outside agentkit.* never produce AC008 even when enabled."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_AC008_OPT_IN,
        files={
            "other_package.service": "def noop():\n    return None\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac008 = [v for v in violations if v.code == "AC008"]
    assert ac008 == []


def test_ac008_disabled_by_default_no_violations(tmp_path: Path) -> None:
    """Without module_completeness_check: true, AC008 must not fire (safe default)."""
    root = _write_spec(
        tmp_path,
        files={
            # Unassigned module — but AC008 is disabled by default
            "agentkit.unknown_module.service": "def noop():\n    return None\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac008 = [v for v in violations if v.code == "AC008"]
    assert ac008 == []


# ---------------------------------------------------------------------------
# C) Asymmetric inheritance: target-side exposure (AC001-target-not-exposed)
# ---------------------------------------------------------------------------


def test_cross_bc_import_to_internal_subcomponent_raises_ac001(tmp_path: Path) -> None:
    """Cross-BC import targeting an internal subcomponent must produce AC001."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.kpi_analytics_inner
                name: KpiAnalyticsInner
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.kpi_analytics.inner
                parent_group_id: architecture-conformance.group.kpi_analytics
                exposure: internal
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.backend.kpi_analytics.inner import something

                def use() -> None:
                    pass
                """
            ),
            "agentkit.backend.kpi_analytics.inner": "def something() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    target_not_exposed = [
        v
        for v in violations
        if v.code == "AC001" and "non-exposed subcomponent" in v.message
    ]
    assert target_not_exposed, f"Expected AC001 target-not-exposed, got: {violations}"


def test_cross_bc_import_to_sub_exposed_subcomponent_no_violation(
    tmp_path: Path,
) -> None:
    """Cross-BC import to a sub_exposed subcomponent must NOT raise AC001."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.kpi_analytics_api
                name: KpiAnalyticsApi
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.kpi_analytics.api
                parent_group_id: architecture-conformance.group.kpi_analytics
                exposure: sub_exposed
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.backend.kpi_analytics.api import something

                def use() -> None:
                    pass
                """
            ),
            "agentkit.backend.kpi_analytics.api": "def something() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    target_not_exposed = [
        v
        for v in violations
        if v.code == "AC001" and "non-exposed subcomponent" in v.message
    ]
    assert target_not_exposed == []


# ---------------------------------------------------------------------------
# D) Intra-BC layer order (AC002)
# ---------------------------------------------------------------------------


_INTRA_BC_GROUPS = dedent(
    """
      - id: architecture-conformance.group.layered_bc
        name: LayeredBc
        bloodgroup: A
        module_prefixes:
          - agentkit.layered
        intra_bc_layer_order:
          - architecture-conformance.group.layered_layer0
          - architecture-conformance.group.layered_layer1
      - id: architecture-conformance.group.layered_layer0
        name: LayeredLayer0
        bloodgroup: A
        module_prefixes:
          - agentkit.layered.layer0
        parent_group_id: architecture-conformance.group.layered_bc
        exposure: internal
      - id: architecture-conformance.group.layered_layer1
        name: LayeredLayer1
        bloodgroup: A
        module_prefixes:
          - agentkit.layered.layer1
        parent_group_id: architecture-conformance.group.layered_bc
        exposure: internal
    """
)


def test_intra_bc_layer_order_violation_detected(tmp_path: Path) -> None:
    """Lower layer importing from higher layer must produce AC002 intra-BC violation.

    LayeredLayer0 (index 0) imports from LayeredLayer1 (index 1): violation.
    """
    root = _write_spec(
        tmp_path,
        extra_groups=_INTRA_BC_GROUPS,
        files={
            # layer0 (index 0) imports from layer1 (index 1)
            # violation: lower index imports higher
            "agentkit.layered.layer0.service": dedent(
                """
                from agentkit.layered.layer1.impl import something

                def use() -> None:
                    pass
                """
            ),
            "agentkit.layered.layer1.impl": "def something() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    layer_violations = [
        v
        for v in violations
        if v.code == "AC002" and "intra-BC layer violation" in v.message
    ]
    assert layer_violations, f"Expected AC002 intra-BC, got: {violations}"


def test_intra_bc_layer_order_no_violation_higher_imports_lower(tmp_path: Path) -> None:
    """Higher layer importing from lower layer must NOT violate intra-BC order.

    LayeredLayer1 (index 1) imports from LayeredLayer0 (index 0): allowed.
    """
    root = _write_spec(
        tmp_path,
        extra_groups=_INTRA_BC_GROUPS,
        files={
            # layer1 (index 1) imports from layer0 (index 0)
            # allowed: higher index imports lower
            "agentkit.layered.layer1.impl": dedent(
                """
                from agentkit.layered.layer0.service import helper

                def something() -> None:
                    pass
                """
            ),
            "agentkit.layered.layer0.service": "def helper() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    layer_violations = [
        v
        for v in violations
        if v.code == "AC002" and "intra-BC layer violation" in v.message
    ]
    assert layer_violations == []


def test_intra_bc_layer_order_absent_no_check(tmp_path: Path) -> None:
    """Without intra_bc_layer_order no intra-BC check runs (default preserved)."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.story_a
                name: StoryA
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.amod
                parent_group_id: architecture-conformance.group.story
              - id: architecture-conformance.group.story_b
                name: StoryB
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.bmod
                parent_group_id: architecture-conformance.group.story
            """
        ),
        files={
            "agentkit.backend.story.amod.service": dedent(
                """
                from agentkit.backend.story.bmod.impl import something

                def use() -> None:
                    pass
                """
            ),
            "agentkit.backend.story.bmod.impl": "def something() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    layer_violations = [
        v
        for v in violations
        if v.code == "AC002" and "intra-BC layer violation" in v.message
    ]
    assert layer_violations == []


# ---------------------------------------------------------------------------
# E) AC005 — Bloodtype-Dependency-Rules
# ---------------------------------------------------------------------------


def test_ac005_a_imports_t_raises_violation(tmp_path: Path) -> None:
    """A-bloodgroup importing T-bloodgroup must produce AC005."""
    root = _write_spec(
        tmp_path,
        extra_invariants=dedent(
            """
            bloodtype_dependency_rules:
              - id: architecture-conformance.ac005.a_must_not_import_t
                source_bloodgroup: A
                forbidden_target_bloodgroups:
                  - T
                message: A-code must not directly import T-code
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.store import run_query

                def execute() -> None:
                    pass
                """
            ),
            "agentkit.infra_driver.store": "def run_query() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac005 = [v for v in violations if v.code == "AC005"]
    assert ac005, f"Expected AC005, got: {violations}"
    assert any("A-code must not directly import T-code" in v.message for v in ac005)


def test_ac005_no_violation_allowed_bloodgroup(tmp_path: Path) -> None:
    """A importing R (not forbidden) must not produce AC005."""
    root = _write_spec(
        tmp_path,
        extra_invariants=dedent(
            """
            bloodtype_dependency_rules:
              - id: architecture-conformance.ac005.a_must_not_import_t
                source_bloodgroup: A
                forbidden_target_bloodgroups:
                  - T
                message: A-code must not directly import T-code
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.backend.control_plane.gateway import call

                def execute() -> None:
                    pass
                """
            ),
            "agentkit.backend.control_plane.gateway": "def call() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac005 = [v for v in violations if v.code == "AC005"]
    assert ac005 == []


def test_ac005_empty_rules_no_violations(tmp_path: Path) -> None:
    """Empty bloodtype_dependency_rules list must produce no AC005 violations."""
    root = _write_spec(
        tmp_path,
        extra_invariants="bloodtype_dependency_rules: []",
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.store import run_query

                def execute() -> None:
                    pass
                """
            ),
            "agentkit.infra_driver.store": "def run_query() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac005 = [v for v in violations if v.code == "AC005"]
    assert ac005 == []


def test_ac005_anti_laundering_r_re_exports_t(tmp_path: Path) -> None:
    """When R re-exports T symbols, A->R must still be a violation (anti-laundering)."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.middleware
                name: MiddlewareR
                bloodgroup: R
                module_prefixes:
                  - agentkit.middleware
                exported_symbols:
                  - agentkit.infra_driver.store.run_query
            """
        ),
        extra_invariants=dedent(
            """
            bloodtype_dependency_rules:
              - id: architecture-conformance.ac005.a_laundering
                source_bloodgroup: A
                forbidden_target_bloodgroups:
                  - T
                allow_through_bloodgroup: R
                message: A-code must not import T-code even through R
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.middleware.facade import run_query

                def execute() -> None:
                    pass
                """
            ),
            "agentkit.middleware.facade": dedent(
                """
                from agentkit.infra_driver.store import run_query

                __all__ = ['run_query']
                """
            ),
            "agentkit.infra_driver.store": "def run_query() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    # middleware is R but re-exports T symbol -> A->R is still a violation
    ac005 = [v for v in violations if v.code == "AC005"]
    assert ac005, f"Expected AC005 anti-laundering violation, got: {violations}"


# ---------------------------------------------------------------------------
# F) AC006 — Effect-Surfaces
# ---------------------------------------------------------------------------


def test_ac006_persistence_surface_violation(tmp_path: Path) -> None:
    """A-code importing a persistence-surface symbol must produce AC006."""
    root = _write_spec(
        tmp_path,
        extra_invariants=dedent(
            """
            effect_surfaces:
              - id: architecture-conformance.ac006.persistence
                name: persistence
                forbidden_for_bloodgroups:
                  - A
                symbols:
                  - sqlalchemy.orm.Session
                message: A-code must not directly import persistence primitives
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                from sqlalchemy.orm import Session

                def get_session() -> Session:
                    raise NotImplementedError
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac006 = [v for v in violations if v.code == "AC006"]
    assert ac006, f"Expected AC006 persistence violation, got: {violations}"


def test_ac006_filesystem_surface_wildcard_violation(tmp_path: Path) -> None:
    """A-code importing from a wildcard filesystem surface symbol must produce AC006."""
    root = _write_spec(
        tmp_path,
        extra_invariants=dedent(
            """
            effect_surfaces:
              - id: architecture-conformance.ac006.filesystem
                name: filesystem
                forbidden_for_bloodgroups:
                  - A
                symbols:
                  - os.path.*
                message: A-code must not directly use os.path filesystem calls
            """
        ),
        files={
            "agentkit.backend.story.service": dedent(
                """
                import os.path

                def exists(p: str) -> bool:
                    return os.path.exists(p)
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac006 = [v for v in violations if v.code == "AC006"]
    assert ac006, f"Expected AC006 filesystem violation, got: {violations}"


def test_ac006_network_surface_not_forbidden_for_r_no_violation(tmp_path: Path) -> None:
    """R-code importing a network surface symbol (A-only forbidden) is allowed."""
    root = _write_spec(
        tmp_path,
        extra_invariants=dedent(
            """
            effect_surfaces:
              - id: architecture-conformance.ac006.network
                name: network
                forbidden_for_bloodgroups:
                  - A
                symbols:
                  - httpx.Client
                message: A-code must not directly use HTTP client primitives
            """
        ),
        files={
            # control_plane is bloodgroup R — should not be flagged
            "agentkit.backend.control_plane.client": dedent(
                """
                import httpx

                def fetch(url: str) -> str:
                    return httpx.get(url).text
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac006 = [v for v in violations if v.code == "AC006"]
    assert ac006 == []


def test_ac006_empty_surfaces_no_violations(tmp_path: Path) -> None:
    """Empty effect_surfaces list must produce no AC006 violations."""
    root = _write_spec(
        tmp_path,
        extra_invariants="effect_surfaces: []",
        files={
            "agentkit.backend.story.service": "import os\ndef noop() -> None:\n    pass\n",
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac006 = [v for v in violations if v.code == "AC006"]
    assert ac006 == []


# ---------------------------------------------------------------------------
# G) AC007 — Type-Taint AST-Walker
# ---------------------------------------------------------------------------

_TYPE_TAINT_INVARIANTS = dedent(
    """
    type_taint_rules:
      - id: architecture-conformance.ac007.a_no_t_in_signatures
        source_bloodgroup: A
        forbidden_typed_bloodgroups:
          - T
        forbid_instantiation_of_bloodgroups:
          - T
        message: A-code must not expose T-types in public signatures
    """
)


def test_ac007_type_taint_simple_import_annotation(tmp_path: Path) -> None:
    """T-type in public function return annotation of A-module must produce AC007."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_TYPE_TAINT_INVARIANTS,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": dedent(
                """
                class DbRecord:
                    pass
                """
            ),
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.models import DbRecord

                def get_record() -> DbRecord:
                    raise NotImplementedError
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007 = [v for v in violations if v.code == "AC007" and "type_taint" in v.rule_id]
    assert ac007, f"Expected AC007 type-taint, got: {violations}"


def test_ac007_type_taint_subscript_list_annotation(tmp_path: Path) -> None:
    """T-type inside list[T] in public signature of A-module must produce AC007."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_TYPE_TAINT_INVARIANTS,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": dedent(
                """
                class DbRecord:
                    pass
                """
            ),
            "agentkit.backend.story.service": dedent(
                """
                from __future__ import annotations
                from agentkit.infra_driver.models import DbRecord

                def get_records() -> list[DbRecord]:
                    return []
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007 = [v for v in violations if v.code == "AC007" and "type_taint" in v.rule_id]
    assert ac007, f"Expected AC007 subscript type-taint, got: {violations}"


def test_ac007_type_taint_forward_ref_string_annotation(tmp_path: Path) -> None:
    """T-type inside a string forward-ref annotation must produce AC007."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_TYPE_TAINT_INVARIANTS,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": dedent(
                """
                class DbRecord:
                    pass
                """
            ),
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.models import DbRecord

                def get_record() -> 'DbRecord':
                    raise NotImplementedError
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007 = [v for v in violations if v.code == "AC007" and "type_taint" in v.rule_id]
    assert ac007, f"Expected AC007 forward-ref type-taint, got: {violations}"


def test_ac007_forbidden_instantiation(tmp_path: Path) -> None:
    """Instantiation of T-class inside public A-function must produce AC007."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_TYPE_TAINT_INVARIANTS,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": dedent(
                """
                class DbRecord:
                    pass
                """
            ),
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.models import DbRecord

                def create_record() -> object:
                    return DbRecord()
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007_inst = [
        v
        for v in violations
        if v.code == "AC007" and "forbidden_instantiation" in v.rule_id
    ]
    assert ac007_inst, f"Expected AC007 forbidden-instantiation, got: {violations}"


def test_ac007_private_function_not_checked(tmp_path: Path) -> None:
    """Private functions (name starts with _) must not trigger AC007."""
    root = _write_spec(
        tmp_path,
        extra_invariants=_TYPE_TAINT_INVARIANTS,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": dedent(
                """
                class DbRecord:
                    pass
                """
            ),
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.models import DbRecord

                def _private_get() -> DbRecord:
                    raise NotImplementedError
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007 = [v for v in violations if v.code == "AC007"]
    assert ac007 == [], f"Expected no AC007 for private function, got: {violations}"


def test_ac007_empty_rules_no_violations(tmp_path: Path) -> None:
    """Empty type_taint_rules list must produce no AC007 violations."""
    root = _write_spec(
        tmp_path,
        extra_invariants="type_taint_rules: []",
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.infra_driver_sub
                name: InfraDriverSub
                bloodgroup: T
                module_prefixes:
                  - agentkit.infra_driver.models
            """
        ),
        files={
            "agentkit.infra_driver.models": "class DbRecord:\n    pass\n",
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.infra_driver.models import DbRecord

                def get_record() -> DbRecord:
                    raise NotImplementedError
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac007 = [v for v in violations if v.code == "AC007"]
    assert ac007 == []


# ---------------------------------------------------------------------------
# H) Tree render
# ---------------------------------------------------------------------------


def test_render_component_tree_basic(tmp_path: Path) -> None:
    """render_component_tree must include all top-level groups in output."""
    root = _write_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    tree = render_component_tree(config)

    assert "StoryApplication" in tree
    assert "KpiAnalyticsApplication" in tree
    assert "ControlPlaneHttp" in tree
    # box-drawing characters
    assert any(c in tree for c in ("├─", "└─"))


def test_render_component_tree_with_children(tmp_path: Path) -> None:
    """Tree must nest children under their parent group."""
    root = _write_spec(
        tmp_path,
        extra_groups=dedent(
            """
              - id: architecture-conformance.group.story_sub
                name: StorySubComponent
                bloodgroup: A
                module_prefixes:
                  - agentkit.backend.story.sub
                parent_group_id: architecture-conformance.group.story
                exposure: sub_exposed
            """
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    tree = render_component_tree(config)

    assert "StorySubComponent" in tree
    assert "[A, sub_exposed]" in tree


def test_render_component_tree_bloodgroup_and_exposure_shown(tmp_path: Path) -> None:
    """Each node must show bloodgroup and exposure in brackets."""
    root = _write_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    tree = render_component_tree(config)

    assert "[A, top]" in tree
    assert "[R, top]" in tree


# ---------------------------------------------------------------------------
# I) New invariant categories default to empty (no-op) when absent
# ---------------------------------------------------------------------------


def test_new_invariant_keys_default_empty(tmp_path: Path) -> None:
    """Specs without new invariant keys must load cleanly with empty tuples."""
    root = _write_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    assert config.bloodtype_dependency_rules == ()
    assert config.effect_surfaces == ()
    assert config.type_taint_rules == ()


# ---------------------------------------------------------------------------
# J) Existing behavior preserved end-to-end (regression guard)
# ---------------------------------------------------------------------------


def test_existing_ac001_still_works_after_refactor(tmp_path: Path) -> None:
    """AC001 dependency rule must still trigger correctly after refactor."""
    root = _write_spec(
        tmp_path,
        files={
            "agentkit.backend.story.service": dedent(
                """
                from agentkit.backend.control_plane.http import App

                def build() -> object:
                    return App
                """
            ),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    assert any(v.code == "AC001" for v in violations)


def test_existing_checks_ac001_ac004_still_green_on_real_repo() -> None:
    """The real AK3 codebase must produce no AC001–AC004 violations after refactor.

    AC008 may fire on modules not yet mapped in entities.md; that is expected and
    will be resolved in the downstream content-migration step.
    """
    compiled = compile_formal_specs(Path("concept/formal-spec"))
    violations = audit_architecture_conformance(compiled, Path("src"))

    pre_existing_codes = {"AC001", "AC002", "AC003", "AC004"}
    legacy_violations = [v for v in violations if v.code in pre_existing_codes]
    assert legacy_violations == []
