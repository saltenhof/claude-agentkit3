"""Flow-structure + CP-order tests for the installer checkpoint flow (AG3-088).

Covers story AC1/AC2/AC3/AC9: the installer is a
``FlowDefinition(level=COMPONENT, owner="Installer")``; every §2.1.1 node id is
present; branch nodes exist per feature; and the normative CP-order edges are
enforced structurally (CP 10 before CP 10a/CP 10c; CP 10b after CP 11).
"""

from __future__ import annotations

from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.flow import (
    BRANCH_VECTORDB_ENABLED_STAGE2,
    build_installer_flow,
)
from agentkit.backend.process.language.model import FlowLevel, NodeKind

_EXPECTED_STEP_IDS = (
    nid.CP_01_PACKAGE_CHECK,
    nid.CP_02_REPO_CHECK,
    nid.CP_03_RESERVED,
    nid.CP_04_RESERVED,
    nid.CP_05_PIPELINE_CONFIG,
    nid.CP_06_PROFILE_RESOLUTION,
    nid.CP_07_BACKEND_REGISTRATION,
    nid.CP_08_SKILL_BINDINGS,
    nid.CP_09_HOOK_REGISTRATION,
    nid.CP_10_MCP_REGISTRATION,
    nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
    nid.CP_10B_CONCEPT_VALIDATION_HOOK,
    nid.CP_10C_ARE_SCOPE_VALIDATION,
    nid.CP_10D_SONARQUBE,
    nid.CP_11_GIT_HOOKS_AND_CLAUDE,
    nid.CP_12_VERIFY_REGISTRATION,
)


def test_installer_flow_is_component_level_owned_by_installer() -> None:
    """AC1: the installer is a level=COMPONENT, owner="Installer" FlowDefinition."""
    flow = build_installer_flow()
    assert flow.level is FlowLevel.COMPONENT
    assert flow.owner == "Installer"


def test_all_normative_node_ids_present_as_nodes() -> None:
    """AC3: every §2.1.1 checkpoint node id exists as a node in the flow."""
    flow = build_installer_flow()
    names = set(flow.node_names)
    for node_id in _EXPECTED_STEP_IDS:
        assert node_id in names, f"missing checkpoint node {node_id}"
    # Each expected checkpoint id is a STEP node.
    for node_id in _EXPECTED_STEP_IDS:
        node = flow.get_node(node_id)
        assert node is not None
        assert node.kind is NodeKind.STEP


def test_branch_nodes_present_per_feature() -> None:
    """AC2/AC3: vectordb/are/sonarqube branch nodes exist (vectordb two-stage)."""
    flow = build_installer_flow()
    for branch_id in (
        nid.BRANCH_VECTORDB_ENABLED,
        nid.BRANCH_ARE_ENABLED,
        nid.BRANCH_SONARQUBE_ENABLED,
        BRANCH_VECTORDB_ENABLED_STAGE2,  # second vectordb stage (CP 10b gate)
    ):
        node = flow.get_node(branch_id)
        assert node is not None, f"missing branch node {branch_id}"
        assert node.kind is NodeKind.BRANCH


def _node_index(flow_node_names: tuple[str, ...], node_id: str) -> int:
    return flow_node_names.index(node_id)


def test_cp10_precedes_cp10a_and_cp10c() -> None:
    """AC9a: cp_10_mcp_registration is ordered BEFORE cp_10a and cp_10c."""
    flow = build_installer_flow()
    names = flow.node_names
    cp10 = _node_index(names, nid.CP_10_MCP_REGISTRATION)
    assert cp10 < _node_index(names, nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES)
    assert cp10 < _node_index(names, nid.CP_10C_ARE_SCOPE_VALIDATION)
    # And the branch edges flow CP10 -> vectordb-branch -> cp10a and the are
    # branch sits after CP10 on the spine (so the ARE-MCP is registered first).
    vectordb_branch_targets = {
        e.target for e in flow.get_edges_from(nid.CP_10_MCP_REGISTRATION)
    }
    assert nid.BRANCH_VECTORDB_ENABLED in vectordb_branch_targets


def test_cp10b_follows_cp11() -> None:
    """AC9b: cp_10b_concept_validation_hook is ordered AFTER cp_11."""
    flow = build_installer_flow()
    names = flow.node_names
    assert _node_index(names, nid.CP_11_GIT_HOOKS_AND_CLAUDE) < _node_index(
        names, nid.CP_10B_CONCEPT_VALIDATION_HOOK
    )
    # The stage-2 vectordb branch (CP 10b gate) is the successor of CP 11.
    cp11_targets = {e.target for e in flow.get_edges_from(nid.CP_11_GIT_HOOKS_AND_CLAUDE)}
    assert BRANCH_VECTORDB_ENABLED_STAGE2 in cp11_targets


def test_each_branch_has_guarded_and_skip_edge() -> None:
    """Each branch node has exactly two ordered outgoing edges (guarded+skip)."""
    flow = build_installer_flow()
    for branch_id in (
        nid.BRANCH_VECTORDB_ENABLED,
        nid.BRANCH_ARE_ENABLED,
        nid.BRANCH_SONARQUBE_ENABLED,
        BRANCH_VECTORDB_ENABLED_STAGE2,
    ):
        edges = flow.get_edges_from(branch_id)
        assert len(edges) == 2
        # Descending priority: the guarded sub-checkpoint first, skip second.
        assert edges[0].priority > edges[1].priority


def test_vectordb_branch_stage1_guards_cp10a_stage2_guards_cp10b() -> None:
    """AC2: vectordb branch is two-stage — stage1 -> cp_10a, stage2 -> cp_10b."""
    flow = build_installer_flow()
    stage1 = flow.get_edges_from(nid.BRANCH_VECTORDB_ENABLED)
    assert stage1[0].target == nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES
    stage2 = flow.get_edges_from(BRANCH_VECTORDB_ENABLED_STAGE2)
    assert stage2[0].target == nid.CP_10B_CONCEPT_VALIDATION_HOOK
