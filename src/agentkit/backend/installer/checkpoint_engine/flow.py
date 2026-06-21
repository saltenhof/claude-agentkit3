"""The installer checkpoint flow as a process-DSL ``FlowDefinition`` (FK-50 §50.3.1).

Builds the NORMATIVE installer flow (story §2.1.1) as a
``FlowDefinition(level=COMPONENT, owner="Installer")`` — a structural reuse of
the existing process-DSL (`agentkit.backend.process.language`), NOT a new flow engine.

Spine + branches (FK-50 §50.3.1, story §2.1.1):

    cp_01 -> cp_02 -> cp_03 -> cp_04 -> cp_05 -> cp_06 -> cp_07 -> cp_08
          -> cp_09 -> cp_10 -> branch_vectordb_enabled
                                 (true)-> cp_10a -> branch_are_enabled
                                 (false)----------> branch_are_enabled
          branch_are_enabled (true)-> cp_10c -> branch_sonarqube_enabled
                             (false)---------> branch_sonarqube_enabled
          branch_sonarqube_enabled (true)-> cp_10d -> cp_11
                                   (false)---------> cp_11
          cp_11 -> branch_vectordb_enabled_stage2
                       (true)-> cp_10b -> cp_12
                       (false)---------> cp_12

CP-order invariants enforced structurally (story §2.1.1, AC9):
- ``cp_10_mcp_registration`` precedes ``cp_10a`` and ``cp_10c`` (it is the
  common MCP precondition — story-knowledge-base MCP at ``features.vectordb``,
  ARE-MCP at ``features.are``, FK-03 §3.1).
- ``cp_10b_concept_validation_hook`` follows ``cp_11_git_hooks_and_claude``
  (CP 10b depends on the configured git hooks).

The vectordb branch is two-stage (one logical feature decision evaluated at two
flow positions): ``branch_vectordb_enabled`` guards CP 10a BEFORE CP 11, and the
identical-predicate stage-2 branch guards CP 10b AFTER CP 11. Both stages route
only when ``features.vectordb: true``. A distinct node id for the stage-2 branch
is mandatory because a flow node id is unique; both bind the SAME vectordb
predicate, so they are one feature decision in two positions (story §2.1.1).
"""

from __future__ import annotations

from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.process.language.model import (
    EdgeRule,
    FlowDefinition,
    FlowLevel,
    NodeDefinition,
    NodeKind,
)

#: Flow id of the installer checkpoint flow.
INSTALLER_FLOW_ID = "installer_checkpoint_flow"
#: Logical component owner of the installer flow (FK-50 §50.3.1).
INSTALLER_FLOW_OWNER = "Installer"

#: Stage-2 vectordb branch node (post-CP11 CP 10b gate). Distinct id because a
#: flow node id is unique; bound to the SAME vectordb predicate as
#: ``branch_vectordb_enabled`` so the two-stage vectordb decision routes
#: consistently (story §2.1.1 / AC2).
BRANCH_VECTORDB_ENABLED_STAGE2 = "branch_vectordb_enabled_stage2"


def _step(node_id: str) -> NodeDefinition:
    """Build a ``step`` checkpoint node."""
    return NodeDefinition(name=node_id, kind=NodeKind.STEP, handler_ref=node_id)


def _branch(node_id: str) -> NodeDefinition:
    """Build a ``branch`` feature-decision node."""
    return NodeDefinition(name=node_id, kind=NodeKind.BRANCH)


def build_installer_flow() -> FlowDefinition:
    """Build the installer checkpoint :class:`FlowDefinition` (FK-50 §50.3.1).

    Returns:
        The frozen ``level=COMPONENT, owner="Installer"`` flow with every CP
        node from story §2.1.1 and the CP-order/branch edges (AC9). Branch nodes
        carry exactly two outgoing edges: the guarded sub-checkpoint at priority
        1 and the skip edge (rejoining the spine) at priority 0, so the engine
        resolves the branch deterministically.
    """
    nodes: tuple[NodeDefinition, ...] = (
        _step(nid.CP_01_PACKAGE_CHECK),
        _step(nid.CP_02_REPO_CHECK),
        _step(nid.CP_03_RESERVED),
        _step(nid.CP_04_RESERVED),
        _step(nid.CP_05_PIPELINE_CONFIG),
        _step(nid.CP_06_PROFILE_RESOLUTION),
        _step(nid.CP_07_BACKEND_REGISTRATION),
        _step(nid.CP_08_SKILL_BINDINGS),
        _step(nid.CP_09_HOOK_REGISTRATION),
        _step(nid.CP_10_MCP_REGISTRATION),
        _branch(nid.BRANCH_VECTORDB_ENABLED),
        _step(nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES),
        _branch(nid.BRANCH_ARE_ENABLED),
        _step(nid.CP_10C_ARE_SCOPE_VALIDATION),
        _branch(nid.BRANCH_SONARQUBE_ENABLED),
        _step(nid.CP_10D_SONARQUBE),
        _step(nid.CP_11_GIT_HOOKS_AND_CLAUDE),
        _branch(BRANCH_VECTORDB_ENABLED_STAGE2),
        _step(nid.CP_10B_CONCEPT_VALIDATION_HOOK),
        _step(nid.CP_12_VERIFY_REGISTRATION),
    )

    edges: tuple[EdgeRule, ...] = (
        # Spine CP1..CP10.
        EdgeRule(source=nid.CP_01_PACKAGE_CHECK, target=nid.CP_02_REPO_CHECK),
        EdgeRule(source=nid.CP_02_REPO_CHECK, target=nid.CP_03_RESERVED),
        EdgeRule(source=nid.CP_03_RESERVED, target=nid.CP_04_RESERVED),
        EdgeRule(source=nid.CP_04_RESERVED, target=nid.CP_05_PIPELINE_CONFIG),
        EdgeRule(source=nid.CP_05_PIPELINE_CONFIG, target=nid.CP_06_PROFILE_RESOLUTION),
        EdgeRule(
            source=nid.CP_06_PROFILE_RESOLUTION,
            target=nid.CP_07_BACKEND_REGISTRATION,
        ),
        EdgeRule(
            source=nid.CP_07_BACKEND_REGISTRATION,
            target=nid.CP_08_SKILL_BINDINGS,
        ),
        EdgeRule(source=nid.CP_08_SKILL_BINDINGS, target=nid.CP_09_HOOK_REGISTRATION),
        EdgeRule(source=nid.CP_09_HOOK_REGISTRATION, target=nid.CP_10_MCP_REGISTRATION),
        # CP10 -> vectordb branch (stage 1): CP10 precedes CP10a (AC9a).
        EdgeRule(
            source=nid.CP_10_MCP_REGISTRATION,
            target=nid.BRANCH_VECTORDB_ENABLED,
        ),
        # branch_vectordb_enabled: guarded -> cp_10a (prio 1); skip -> are branch.
        EdgeRule(
            source=nid.BRANCH_VECTORDB_ENABLED,
            target=nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            priority=1,
        ),
        EdgeRule(
            source=nid.BRANCH_VECTORDB_ENABLED,
            target=nid.BRANCH_ARE_ENABLED,
            priority=0,
        ),
        EdgeRule(
            source=nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            target=nid.BRANCH_ARE_ENABLED,
        ),
        # branch_are_enabled: guarded -> cp_10c (prio 1); skip -> sonar branch.
        # CP10 precedes CP10c (AC9a): CP10/ARE-MCP runs before this branch.
        EdgeRule(
            source=nid.BRANCH_ARE_ENABLED,
            target=nid.CP_10C_ARE_SCOPE_VALIDATION,
            priority=1,
        ),
        EdgeRule(
            source=nid.BRANCH_ARE_ENABLED,
            target=nid.BRANCH_SONARQUBE_ENABLED,
            priority=0,
        ),
        EdgeRule(
            source=nid.CP_10C_ARE_SCOPE_VALIDATION,
            target=nid.BRANCH_SONARQUBE_ENABLED,
        ),
        # branch_sonarqube_enabled: guarded -> cp_10d (prio 1); skip -> cp_11.
        EdgeRule(
            source=nid.BRANCH_SONARQUBE_ENABLED,
            target=nid.CP_10D_SONARQUBE,
            priority=1,
        ),
        EdgeRule(
            source=nid.BRANCH_SONARQUBE_ENABLED,
            target=nid.CP_11_GIT_HOOKS_AND_CLAUDE,
            priority=0,
        ),
        EdgeRule(source=nid.CP_10D_SONARQUBE, target=nid.CP_11_GIT_HOOKS_AND_CLAUDE),
        # CP11 -> vectordb branch (stage 2): CP10b follows CP11 (AC9b).
        EdgeRule(
            source=nid.CP_11_GIT_HOOKS_AND_CLAUDE,
            target=BRANCH_VECTORDB_ENABLED_STAGE2,
        ),
        EdgeRule(
            source=BRANCH_VECTORDB_ENABLED_STAGE2,
            target=nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            priority=1,
        ),
        EdgeRule(
            source=BRANCH_VECTORDB_ENABLED_STAGE2,
            target=nid.CP_12_VERIFY_REGISTRATION,
            priority=0,
        ),
        EdgeRule(
            source=nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            target=nid.CP_12_VERIFY_REGISTRATION,
        ),
    )

    return FlowDefinition(
        flow_id=INSTALLER_FLOW_ID,
        level=FlowLevel.COMPONENT,
        owner=INSTALLER_FLOW_OWNER,
        nodes=nodes,
        edges=edges,
    )


__all__ = [
    "BRANCH_VECTORDB_ENABLED_STAGE2",
    "INSTALLER_FLOW_ID",
    "INSTALLER_FLOW_OWNER",
    "build_installer_flow",
]
