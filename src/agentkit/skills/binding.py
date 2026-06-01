"""SkillBinding entity and related StrEnum types (AG3-027, FK-43).

Implements the formal entity ``skills-and-bundles.entity.skill-binding``
and the state machine ``formal.skills-and-bundles.state-machine``.

Layer note: ``binding`` is layer 1 in BC 11's intra_bc_layer_order.
``SkillProfile`` lives in ``bundle_store`` (layer 0) and is re-exported
from here for convenience; do NOT move it back here — that would cause
an AC002 intra-BC layer violation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# SkillProfile lives in bundle_store (layer 0); imported here for BC-internal
# re-export via __init__.py. No circular import because bundle_store does
# not import from binding.
from agentkit.skills.bundle_store import SkillProfile as SkillProfile  # noqa: F401


class SkillLifecycleStatus(StrEnum):
    """Lifecycle states from ``formal.skills-and-bundles.state-machine``.

    Ordering matches the canonical state machine:
    REQUESTED -> PROFILE_RESOLVED -> BUNDLE_SELECTED -> BOUND -> VERIFIED
    Terminal error state: REJECTED.
    """

    REQUESTED = "REQUESTED"
    PROFILE_RESOLVED = "PROFILE_RESOLVED"
    BUNDLE_SELECTED = "BUNDLE_SELECTED"
    BOUND = "BOUND"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SkillBindingMode(StrEnum):
    """Binding mechanism — a thin filesystem link to the central bundle.

    Platform-aware per invariant ``project_binding_is_link_only``
    (formal.skills-and-bundles.invariants, FK-43 §43.4.1.1):

    * ``SYMLINK``  — symbolic link, used on POSIX.
    * ``JUNCTION`` — Windows directory junction, used on Windows because it
      needs no Developer Mode / ``SeCreateSymbolicLinkPrivilege`` (unlike a
      Windows symlink). Same semantics: a thin link to the central, versioned
      bundle directory — never a file copy.
    """

    SYMLINK = "SYMLINK"
    JUNCTION = "JUNCTION"


class HarnessKind(StrEnum):
    """Supported harness targets for skill symlink creation (FK-43 §43.4.1).

    * ``CLAUDE_CODE`` — Claude Code CLI harness (.claude/skills/).
    * ``CODEX``       — Codex harness (.codex/skills/).  FK-30 §30.11
      defines the Codex-side binding point; the path convention used here
      (``{project_root}/.codex/skills/{skill_name}``) follows that section.
      If FK-30 §30.11 mandates a different path in a future revision this
      constant must be updated.
    """

    CLAUDE_CODE = "CLAUDE_CODE"
    CODEX = "CODEX"


class SkillBinding(BaseModel):
    """Canonical binding of a skill bundle to a project harness path.

    Implements entity ``skills-and-bundles.entity.skill-binding``
    (formal.skills-and-bundles.entities, schema_version 1).

    Attributes:
        binding_id: Canonical identity key (uuid or deterministic hash).
        project_key: Stable key of the target project.
        skill_name: Logical skill name (e.g. ``"implement"``).
        bundle_id: Identifier of the bound ``SkillBundle``.
        bundle_version: Pinned version string of the bundle.
        target_path: Harness-specific link path within the project.
        binding_mode: The link mechanism actually used — ``SYMLINK`` on POSIX,
            ``JUNCTION`` on Windows (invariant ``project_binding_is_link_only``).
        status: Current lifecycle state.
        pinned_at: Timestamp when the bundle version was pinned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: str
    project_key: str
    skill_name: str
    bundle_id: str
    bundle_version: str
    target_path: Path
    binding_mode: SkillBindingMode
    status: SkillLifecycleStatus
    pinned_at: datetime
