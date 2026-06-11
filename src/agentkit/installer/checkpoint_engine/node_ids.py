"""Stable installer checkpoint node identifiers (FK-50 §50.3.1).

The exact, NORMATIVE node-ID list of the minimal installer flow (FK-50 §50.3.1,
story §2.1.1). Centralised here so the flow definition, the handler registry and
the tests all reference ONE source of truth (no scattered string literals).

All identifiers are English (ARCH-55).
"""

from __future__ import annotations

from typing import Final

#: CP 1 — Python package check (``import agentkit; assert agentkit.__version__``).
CP_01_PACKAGE_CHECK: Final = "cp_01_package_check"
#: CP 2 — GitHub repo existence/auth check (``gh repo view``).
CP_02_REPO_CHECK: Final = "cp_02_repo_check"
#: CP 3 — reserved no-op (number stability; FK-50 §50.3 "entfaellt").
CP_03_RESERVED: Final = "cp_03_reserved"
#: CP 4 — reserved no-op (number stability; FK-50 §50.3 "entfaellt").
CP_04_RESERVED: Final = "cp_04_reserved"
#: CP 5 — pipeline config (``.agentkit/config/project.yaml``).
CP_05_PIPELINE_CONFIG: Final = "cp_05_pipeline_config"
#: CP 6 — project profile resolution (``core``/``are``).
CP_06_PROFILE_RESOLUTION: Final = "cp_06_profile_resolution"
#: CP 7 — State-Backend project registration.
CP_07_BACKEND_REGISTRATION: Final = "cp_07_backend_registration"
#: CP 8 — skill links + prompt-bundle binding.
CP_08_SKILL_BINDINGS: Final = "cp_08_skill_bindings"
#: CP 9 — hook registration via ``Governance.register_hooks``.
CP_09_HOOK_REGISTRATION: Final = "cp_09_hook_registration"
#: CP 10 — MCP-server registration (vectordb knowledge-base and/or ARE MCP).
CP_10_MCP_REGISTRATION: Final = "cp_10_mcp_registration"
#: CP 10a — ConceptContext properties + first indexing (vectordb only).
CP_10A_CONCEPT_CONTEXT_PROPERTIES: Final = "cp_10a_concept_context_properties"
#: CP 10b — concept-validation git hook (vectordb only, AFTER CP 11).
CP_10B_CONCEPT_VALIDATION_HOOK: Final = "cp_10b_concept_validation_hook"
#: CP 10c — ARE-scope validation (ARE only).
CP_10C_ARE_SCOPE_VALIDATION: Final = "cp_10c_are_scope_validation"
#: CP 10d — SonarQube availability + branch-plugin conformance (sonar only).
CP_10D_SONARQUBE: Final = "cp_10d_sonarqube_availability_and_conformance"
#: CP 11 — git hooks (``core.hooksPath``) + CLAUDE.md skeleton.
CP_11_GIT_HOOKS_AND_CLAUDE: Final = "cp_11_git_hooks_and_claude"
#: CP 12 — read-only verification of all prior checkpoints.
CP_12_VERIFY_REGISTRATION: Final = "cp_12_verify_registration"

#: Branch node: vectordb feature decision (two-stage — CP 10a before CP 11,
#: CP 10b after CP 11).
BRANCH_VECTORDB_ENABLED: Final = "branch_vectordb_enabled"
#: Branch node: ARE feature decision (routes CP 10c after CP 10).
BRANCH_ARE_ENABLED: Final = "branch_are_enabled"
#: Branch node: SonarQube feature decision (routes CP 10d).
BRANCH_SONARQUBE_ENABLED: Final = "branch_sonarqube_enabled"


__all__ = [
    "BRANCH_ARE_ENABLED",
    "BRANCH_SONARQUBE_ENABLED",
    "BRANCH_VECTORDB_ENABLED",
    "CP_01_PACKAGE_CHECK",
    "CP_02_REPO_CHECK",
    "CP_03_RESERVED",
    "CP_04_RESERVED",
    "CP_05_PIPELINE_CONFIG",
    "CP_06_PROFILE_RESOLUTION",
    "CP_07_BACKEND_REGISTRATION",
    "CP_08_SKILL_BINDINGS",
    "CP_09_HOOK_REGISTRATION",
    "CP_10A_CONCEPT_CONTEXT_PROPERTIES",
    "CP_10B_CONCEPT_VALIDATION_HOOK",
    "CP_10C_ARE_SCOPE_VALIDATION",
    "CP_10D_SONARQUBE",
    "CP_10_MCP_REGISTRATION",
    "CP_11_GIT_HOOKS_AND_CLAUDE",
    "CP_12_VERIFY_REGISTRATION",
]
