"""Unit tests for SkillBinding, SkillLifecycleStatus, SkillBindingMode, SkillProfile.

Verifies:
- SkillLifecycleStatus is a StrEnum with the correct values.
- SkillBindingMode is a StrEnum with SYMLINK.
- SkillProfile is a StrEnum with CORE / ARE.
- SkillBinding is a frozen Pydantic v2 model with extra=forbid.
- HarnessKind is a StrEnum with CLAUDE_CODE / CODEX.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.skills.binding import (
    HarnessKind,
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
    SkillProfile,
)

# ---------------------------------------------------------------------------
# SkillLifecycleStatus
# ---------------------------------------------------------------------------

class TestSkillLifecycleStatus:
    def test_is_str_enum(self) -> None:
        assert issubclass(SkillLifecycleStatus, StrEnum)

    def test_all_states_present(self) -> None:
        expected = {
            "REQUESTED",
            "PROFILE_RESOLVED",
            "BUNDLE_SELECTED",
            "BOUND",
            "VERIFIED",
            "REJECTED",
        }
        actual = {s.value for s in SkillLifecycleStatus}
        assert actual == expected

    def test_str_values_equal_names(self) -> None:
        for status in SkillLifecycleStatus:
            assert status == status.value
            assert str(status) == status.value


# ---------------------------------------------------------------------------
# SkillBindingMode
# ---------------------------------------------------------------------------

class TestSkillBindingMode:
    def test_is_str_enum(self) -> None:
        assert issubclass(SkillBindingMode, StrEnum)

    def test_symlink_present(self) -> None:
        assert SkillBindingMode.SYMLINK == "SYMLINK"


# ---------------------------------------------------------------------------
# SkillProfile
# ---------------------------------------------------------------------------

class TestSkillProfile:
    def test_is_str_enum(self) -> None:
        assert issubclass(SkillProfile, StrEnum)

    def test_core_and_are_present(self) -> None:
        assert SkillProfile.CORE == "CORE"
        assert SkillProfile.ARE == "ARE"


# ---------------------------------------------------------------------------
# HarnessKind
# ---------------------------------------------------------------------------

class TestHarnessKind:
    def test_is_str_enum(self) -> None:
        assert issubclass(HarnessKind, StrEnum)

    def test_claude_code_and_codex_present(self) -> None:
        assert HarnessKind.CLAUDE_CODE == "CLAUDE_CODE"
        assert HarnessKind.CODEX == "CODEX"


# ---------------------------------------------------------------------------
# SkillBinding model
# ---------------------------------------------------------------------------

def _make_binding(**kwargs: object) -> SkillBinding:
    defaults: dict[str, object] = {
        "binding_id": "test-binding-id",
        "project_key": "proj-a",
        "skill_name": "implement",
        "bundle_id": "core-bundle",
        "bundle_version": "1.0.0",
        "target_path": Path("/tmp/proj/.claude/skills/implement"),
        "binding_mode": SkillBindingMode.SYMLINK,
        "status": SkillLifecycleStatus.VERIFIED,
        "pinned_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return SkillBinding.model_validate(defaults)


class TestSkillBinding:
    def test_valid_construction(self) -> None:
        binding = _make_binding()
        assert binding.skill_name == "implement"
        assert binding.status == SkillLifecycleStatus.VERIFIED

    def test_frozen_mutation_raises(self) -> None:
        binding = _make_binding()
        with pytest.raises((TypeError, ValidationError)):
            binding.skill_name = "other"  # type: ignore[misc]

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            SkillBinding(
                binding_id="x",
                project_key="p",
                skill_name="s",
                bundle_id="b",
                bundle_version="1.0",
                target_path=Path("/tmp"),
                binding_mode=SkillBindingMode.SYMLINK,
                status=SkillLifecycleStatus.VERIFIED,
                pinned_at=datetime(2026, 1, 1, tzinfo=UTC),
                extra_field_not_allowed="bad",  # type: ignore[call-arg]
            )

    def test_all_lifecycle_statuses_accepted(self) -> None:
        for status in SkillLifecycleStatus:
            b = _make_binding(status=status)
            assert b.status == status

    def test_path_field_accepts_path_object(self) -> None:
        p = Path("/some/path")
        binding = _make_binding(target_path=p)
        assert binding.target_path == p
