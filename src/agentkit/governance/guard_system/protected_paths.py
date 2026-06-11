"""Protected-path constants for the QA artifact protection.

Canonical location: ``agentkit.governance.guard_system.protected_paths``.

Rationale (FK-31 §31.3 + bc-cut-decisions.md §BC 4 + refactor list item 24):
- The constants configure the ``qa-artifact-protection`` hook of the
  GuardSystem (FK-31 §31.3, lines 420-487).
- BC-Cut §BC 4 positions the GuardSystem under ``agentkit.governance.guard_system``.
- Refactor item 24: "the PROTECTED_ARTIFACTS list belongs to the hook
  configuration in BC 4 (governance.guard_system), not to artifacts or
  state_backend".

Truth-boundary discipline: ``agentkit.governance`` is a
``protected_module_prefix`` per
``concept/formal-spec/truth-boundary-checker/invariants.md`` lines 24-52.
The wire string literals ("structural.json", "decision.json", ...)
therefore must not reside **in** this module. They live as cross-cutting
constants in ``agentkit.core_types.qa_artifact_names`` and are only imported
here for the tuple configuration of the hook.

Source:
- FK-31 §31.3 — ``concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md``
  (lines 420-487)
- ``concept/_meta/bc-cut-decisions.md §BC 4`` — lines 285-338
- ``concept/_meta/bc-cut-decisions.md §BC 8 refactor list item 24`` — line 1900
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` lines 24-52
"""

from __future__ import annotations

from agentkit.core_types.plane_artifact_names import (
    GOVERNANCE_FREEZE_EXPORT_RELPATH,
    SELF_PROTECTION_CONFIG_FILE_PARTS,
    SELF_PROTECTION_HOOK_SETTINGS_PARTS,
    SELF_PROTECTION_SYMLINK_DIR_PARTS,
)
from agentkit.core_types.qa_artifact_names import (
    ADVERSARIAL_SANDBOX_PREFIX,
    ALL_QA_ARTIFACT_FILES,
    CHANGE_FRAME_FILE,
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)
from agentkit.state_backend.paths import STATE_DB_DIR, STATE_DB_FILE

#: Protection list of all QA artifact filenames (FK-31 §31.3 + FK-27 §27.7).
#: Write access by sub-agents to these files is blocked in the GuardSystem as
#: long as the QA artifact lock is active (FK-31 §31.3).
#: Contains all 6 FK-27 artifacts + the guardrail artifact.
PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
)

#: Local conflict-freeze export (AG3-032, FK-55 §55.10.5 / FK-31 §31.2.7).
#: Project-relative path of the dual freeze materialization; belongs to the
#: ``governance_plane`` (FK-55 §55.4) and may be mutated only via official service
#: paths. Registered here as a protected governance path (AG3-023).
#: The path literal lives in ``core_types.plane_artifact_names`` (SINGLE SOURCE OF
#: TRUTH / truth boundary) and is only re-exported here — no literal in this
#: protected governance module.
PROTECTED_GOVERNANCE_FREEZE_EXPORT: str = GOVERNANCE_FREEZE_EXPORT_RELPATH

#: Exploration change-frame artifact (FK-23 §23.4.3).
#: The exploration worker (AG3-055, BC ``agent-skills``) writes this file to
#: ``_temp/qa/{story_id}/change_frame.json``; AG3-045 defines the schema + the
#: protection mechanics. This constant is the SINGLE SOURCE OF TRUTH for the
#: protected change-frame filename and is consumed EFFECTIVELY by the
#: ``ArtifactGuard`` (``governance.guards.artifact_guard``): a sub-agent write to
#: this file is blocked once the change-frame is **frozen** (guard-context signal
#: ``change_frame_frozen``) OR the freeze state is **unknown** (missing /
#: unreadable ``change_frame_freeze_known``) -- fail-closed (deep-review #5,
#: ARCH-48 default deny). The freeze trigger (setting ``frozen: true`` + feeding
#: ``change_frame_frozen`` and ``change_frame_freeze_known`` into the guard
#: context) is owned by AG3-047 (FK-23 §23.4.3: "protection runs via the hook
#: mechanism, not via file permissions"); a change-frame explicitly known to be
#: NOT frozen (before freeze, FK-25 §25.4.2) is editable, hence no block. The
#: protection mechanics are complete here / in the guard (AG3-045 AC8). The path
#: literal lives in ``core_types.qa_artifact_names`` (truth boundary -- no literal
#: in the protected governance namespace).
PROTECTED_CHANGE_FRAME: str = CHANGE_FRAME_FILE

#: Layer-3 adversarial sandbox prefix (AG3-044, FK-48 §48.1). All adversarial
#: spawns write under ``_temp/adversarial/{story_id}/{epoch}/``; this prefix is a
#: Protected-Path (AG3-023) so an ordinary worker cannot tamper with adversarial
#: test evidence. The path literal lives in ``core_types.qa_artifact_names``
#: (truth boundary -- no literal in the protected governance namespace).
PROTECTED_ADVERSARIAL_SANDBOX_PREFIX: str = ADVERSARIAL_SANDBOX_PREFIX


def is_adversarial_sandbox_path(relpath: str) -> bool:
    """Whether ``relpath`` is under the protected adversarial sandbox (AG3-044).

    FK-48 §48.1 / AG3-023: paths under ``_temp/adversarial/`` are Protected-Paths
    so adversarial test evidence is tamper-protected. The check is POSIX-relative
    and prefix-based; backslashes are normalised so a Windows-style path resolves
    identically (fail-closed: a non-matching path is NOT protected).

    Args:
        relpath: A POSIX-relative path (e.g. ``_temp/adversarial/AG3-044/1``).

    Returns:
        ``True`` iff the path is under the adversarial sandbox prefix.
    """
    normalised = relpath.replace("\\", "/").lstrip("./")
    return normalised.startswith(PROTECTED_ADVERSARIAL_SANDBOX_PREFIX)


# ---------------------------------------------------------------------------
# Self-protection path registry (FK-30 §30.5.4 / FK-15 §15.7.1).
#
# The ``SelfProtectionGuard`` (AG3-033) sources its protected paths exclusively
# from here — no governance module holds a second truth for protected paths
# (CLAUDE.md SINGLE SOURCE OF TRUTH; enforced by
# ``scripts/ci/check_concept_code_contracts.py``). The path literals live in
# ``core_types.plane_artifact_names`` or ``state_backend.paths`` and are only
# re-exported / collected into configuration tuples here.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Self-protection ZONES (FK-30 §30.5.4 / FK-15 §15.7.x).
#
# The ``SelfProtectionGuard`` (AG3-033) applies a separate, concept-anchored
# principal whitelist per protected zone (FK-31 §31.5.4 implicitly via
# FK-15 §15.7.3 "Only pipeline scripts (zone 2) write lock records"). No blanket
# trio whitelist anymore. The zones are defined here as path sets; the
# zone->principal policy is owned by the guard (business logic).
# ---------------------------------------------------------------------------

#: ZONE "harness" — harness-specific hook-settings files (FK-30 §30.5.4 /
#: FK-76 §76.5) and CCAG/skill symlink directories (FK-15 §15.7.1). These
#: binding points are materialized exclusively by the installer (FK-30 §30.3.1
#: "caller: installer"; FK-50 CP 9) via ``register_hooks`` — a deterministic
#: zone-2 process. Exact file tuples.
SELF_PROTECTION_HARNESS_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HOOK_SETTINGS_PARTS,
)

#: ZONE "harness" — directory prefixes (CCAG rules / skill symlinks, FK-15
#: §15.7.1). Every mutation UNDER one of these directories belongs to the
#: harness zone.
SELF_PROTECTION_HARNESS_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_SYMLINK_DIR_PARTS,
)

#: ZONE "governance" — governance configuration / installer manifest (FK-30
#: §30.5.4: ``.agentkit/config/project.yaml``, ``.installed-manifest.json``).
#: These belong — like lock records and edge bundles — to the governance truth
#: and are subject to the same pipeline/admin whitelist (FK-15 §15.4.1 line
#: "mutate central workflow state" / "create/end lock record").
SELF_PROTECTION_GOVERNANCE_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_CONFIG_FILE_PARTS,
)

#: Aggregate of all protected exact file paths (backward compatibility /
#: "is this path protected at all" check). Union of the harness and governance
#: zones.
SELF_PROTECTION_PROTECTED_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HARNESS_FILE_PARTS,
    *SELF_PROTECTION_GOVERNANCE_FILE_PARTS,
)

#: Aggregate of all protected directory prefixes (FK-30 §30.5.4). Currently
#: congruent with the harness zone (CCAG/skill symlinks); the governance-plane
#: directories (``_temp/governance``, ``.agent-guard``, ``.git``) are covered by
#: the ``PathClassifier`` via path classes, not via these tuples.
SELF_PROTECTION_PROTECTED_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HARNESS_DIR_PARTS,
)

#: Story-backend directory segment (``.agentkit``) and SQLite suffixes by which
#: the ``StoryCreationGuard`` (AG3-033) detects a direct story-DB INSERT
#: (FK-21 §21.13 / FK-31 §31.5). Source: ``state_backend.paths`` — no second
#: literal in the governance module.
STORY_DB_DIR_SEGMENT: str = STATE_DB_DIR
STORY_DB_SUFFIXES: tuple[str, ...] = tuple(
    sorted({"." + STATE_DB_FILE.rsplit(".", 1)[-1], ".sqlite"})
)

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "PROTECTED_ADVERSARIAL_SANDBOX_PREFIX",
    "PROTECTED_CHANGE_FRAME",
    "PROTECTED_GOVERNANCE_FREEZE_EXPORT",
    "PROTECTED_QA_ARTIFACTS",
    "SELF_PROTECTION_GOVERNANCE_FILE_PARTS",
    "SELF_PROTECTION_HARNESS_DIR_PARTS",
    "SELF_PROTECTION_HARNESS_FILE_PARTS",
    "SELF_PROTECTION_PROTECTED_DIR_PARTS",
    "SELF_PROTECTION_PROTECTED_FILE_PARTS",
    "STORY_DB_DIR_SEGMENT",
    "STORY_DB_SUFFIXES",
    "VERIFY_DECISION_FILE",
    "is_adversarial_sandbox_path",
]
