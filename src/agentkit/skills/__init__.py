"""Agent-skills BC public surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Re-exports the canonical types from the sub-modules so callers can do::

    from agentkit.skills import Skills, SkillBinding, SkillBundleStore, ...
"""

from __future__ import annotations

from agentkit.skills.binding import (
    HarnessKind,
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.skills.bundle_store import (
    LogicalSkillId,
    SkillBundle,
    SkillBundleStore,
    SkillBundleVersion,
    SkillProfile,
)
from agentkit.skills.errors import (
    SkillBindingFailedError,
    SkillBundleDigestMismatchError,
    SkillBundleNotFoundError,
    SkillError,
    SkillProfileNotSupportedError,
    SkillQualityMetricSourceUnavailableError,
    UnknownPlaceholderError,
    UnknownSkillNameError,
)
from agentkit.skills.links import (
    create_directory_link,
    is_directory_link,
    platform_binding_mode,
    remove_directory_link,
)
from agentkit.skills.placeholder import PlaceholderSubstitutor
from agentkit.skills.quality_metric import AttributionState, SkillQualityMetric, SourceWindow
from agentkit.skills.repository import (
    InMemorySkillBindingRepository,
    SkillBindingRepository,
)
from agentkit.skills.top import Skills

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
    "remove_directory_link",
    # Placeholder
    "PlaceholderSubstitutor",
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
