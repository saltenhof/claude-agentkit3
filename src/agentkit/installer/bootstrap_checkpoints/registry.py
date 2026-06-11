"""Checkpoint handler and branch-predicate registries (FK-50 §50.3.1).

Wires every ``step`` node id of the installer flow to its handler and every
``branch`` node id to its pure feature predicate. The :class:`CheckpointEngine`
validates at construction that the registries cover every node, so a missing
wiring fails closed (ZERO DEBT — no silently skipped checkpoint).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.installer.bootstrap_checkpoints.cp01_to_06 import (
    cp01_package_check,
    cp02_repo_check,
    cp03_reserved,
    cp04_reserved,
    cp05_pipeline_config,
    cp06_profile_resolution,
)
from agentkit.installer.bootstrap_checkpoints.cp07_to_09 import (
    cp07_backend_registration,
    cp08_skill_bindings,
    cp09_hook_registration,
)
from agentkit.installer.bootstrap_checkpoints.cp10 import (
    cp10_mcp_registration,
    cp10a_concept_context_properties,
    cp10b_concept_validation_hook,
    cp10c_are_scope_validation,
    cp10d_sonarqube,
)
from agentkit.installer.bootstrap_checkpoints.cp11_to_12 import (
    cp11_git_hooks_and_claude,
    cp12_verify_registration,
)
from agentkit.installer.checkpoint_engine import node_ids as nid
from agentkit.installer.checkpoint_engine.flow import BRANCH_VECTORDB_ENABLED_STAGE2

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.installer.checkpoint_engine.engine import CheckpointHandler


def build_handler_registry() -> dict[str, CheckpointHandler]:
    """Return the node-id -> :class:`CheckpointHandler` registry."""
    return {
        nid.CP_01_PACKAGE_CHECK: cp01_package_check,
        nid.CP_02_REPO_CHECK: cp02_repo_check,
        nid.CP_03_RESERVED: cp03_reserved,
        nid.CP_04_RESERVED: cp04_reserved,
        nid.CP_05_PIPELINE_CONFIG: cp05_pipeline_config,
        nid.CP_06_PROFILE_RESOLUTION: cp06_profile_resolution,
        nid.CP_07_BACKEND_REGISTRATION: cp07_backend_registration,
        nid.CP_08_SKILL_BINDINGS: cp08_skill_bindings,
        nid.CP_09_HOOK_REGISTRATION: cp09_hook_registration,
        nid.CP_10_MCP_REGISTRATION: cp10_mcp_registration,
        nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES: cp10a_concept_context_properties,
        nid.CP_10B_CONCEPT_VALIDATION_HOOK: cp10b_concept_validation_hook,
        nid.CP_10C_ARE_SCOPE_VALIDATION: cp10c_are_scope_validation,
        nid.CP_10D_SONARQUBE: cp10d_sonarqube,
        nid.CP_11_GIT_HOOKS_AND_CLAUDE: cp11_git_hooks_and_claude,
        nid.CP_12_VERIFY_REGISTRATION: cp12_verify_registration,
    }


def _vectordb_enabled(context: CheckpointContext) -> bool:
    """Branch predicate: ``features.vectordb`` (both vectordb branch stages)."""
    return context.vectordb_enabled


def _are_enabled(context: CheckpointContext) -> bool:
    """Branch predicate: ``features.are``."""
    return context.are_enabled


def _sonarqube_enabled(context: CheckpointContext) -> bool:
    """Branch predicate: ``sonarqube.available`` (CP 10d applicability)."""
    return context.sonarqube_enabled


def build_branch_predicate_registry() -> dict[
    str, Callable[[CheckpointContext], bool]
]:
    """Return the branch node-id -> predicate registry.

    The two-stage vectordb branch binds the SAME ``_vectordb_enabled`` predicate
    at both flow positions (stage 1 before CP 11, stage 2 after CP 11), so the
    two-stage decision routes consistently (story §2.1.1 / AC2).
    """
    return {
        nid.BRANCH_VECTORDB_ENABLED: _vectordb_enabled,
        BRANCH_VECTORDB_ENABLED_STAGE2: _vectordb_enabled,
        nid.BRANCH_ARE_ENABLED: _are_enabled,
        nid.BRANCH_SONARQUBE_ENABLED: _sonarqube_enabled,
    }


__all__ = [
    "build_branch_predicate_registry",
    "build_handler_registry",
]
