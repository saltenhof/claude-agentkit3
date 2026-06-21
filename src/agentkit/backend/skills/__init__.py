"""Agent-skills BC public surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Re-exports the canonical types from the sub-modules so callers can do::

    from agentkit.backend.skills import Skills, SkillBinding, SkillBundleStore, ...
"""

from __future__ import annotations

from agentkit.backend.skills.binding import (
    HarnessKind,
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.skills.bundle_store import (
    LogicalSkillId,
    SkillBundle,
    SkillBundleStore,
    SkillBundleVersion,
    SkillProfile,
)
from agentkit.backend.skills.errors import (
    SkillBindingFailedError,
    SkillBundleDigestMismatchError,
    SkillBundleNotFoundError,
    SkillError,
    SkillProfileNotSupportedError,
    SkillQualityMetricSourceUnavailableError,
    UnknownPlaceholderError,
    UnknownSkillNameError,
)
from agentkit.backend.skills.links import (
    create_directory_link,
    is_directory_link,
    platform_binding_mode,
    read_directory_link_target,
    remove_directory_link,
)
from agentkit.backend.skills.materialize import (
    bind_skill_materialized,
    bundle_has_placeholders,
)
from agentkit.backend.skills.placeholder import (
    SPAWN_SKILL_PROOF_PLACEHOLDER,
    PlaceholderSubstitutor,
)
from agentkit.backend.skills.quality_metric import AttributionState, SkillQualityMetric, SourceWindow
from agentkit.backend.skills.repository import (
    InMemorySkillBindingRepository,
    SkillBindingRepository,
)
from agentkit.backend.skills.top import Skills

__all__ = [
    # Top-surface
    "Skills",
    "AttributionState",
    "SkillQualityMetric",
    "SourceWindow",
    # Binding
    "HarnessKind",
    "SkillBinding",
    "SkillBindingMode",
    "SkillLifecycleStatus",
    "SkillProfile",
    # Bundle store
    "LogicalSkillId",
    "SkillBundle",
    "SkillBundleStore",
    "SkillBundleVersion",
    # Link mechanics (platform-aware: symlink on POSIX, junction on Windows)
    "create_directory_link",
    "is_directory_link",
    "platform_binding_mode",
    "read_directory_link_target",
    "remove_directory_link",
    # Materialized variant binding (AG3-111, FK-43 §43.4.1.1)
    "bind_skill_materialized",
    "bundle_has_placeholders",
    # Placeholder
    "PlaceholderSubstitutor",
    "SPAWN_SKILL_PROOF_PLACEHOLDER",
    # Repository
    "InMemorySkillBindingRepository",
    "SkillBindingRepository",
    # Errors
    "SkillError",
    "SkillBindingFailedError",
    "SkillBundleDigestMismatchError",
    "SkillBundleNotFoundError",
    "SkillQualityMetricSourceUnavailableError",
    "SkillProfileNotSupportedError",
    "UnknownSkillNameError",
    "UnknownPlaceholderError",
]
