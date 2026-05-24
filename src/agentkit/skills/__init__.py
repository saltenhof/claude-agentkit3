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
    UnknownPlaceholderError,
)
from agentkit.skills.placeholder import PlaceholderSubstitutor
from agentkit.skills.repository import (
    InMemorySkillBindingRepository,
    SkillBindingRepository,
)
from agentkit.skills.top import SkillQualityMetric, Skills

__all__ = [
    # Top-surface
    "Skills",
    "SkillQualityMetric",
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
    "SkillProfileNotSupportedError",
    "UnknownPlaceholderError",
]
