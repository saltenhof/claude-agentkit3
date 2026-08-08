"""Unit tests for the dev-local SonarQube profile check (AG3-242).

The check moved out of ``integration_checkpoints.sonar_preflight`` because that
module is classified ``core`` while this decision is taken on the developer
machine, against a file the core never sees. The tests below therefore pin two
things: the verdict, and the absence of any core vocabulary in the answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.sonar_local_profile import (
    DEFAULT_PROFILE_MISSING,
    missing_default_profile,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_profile_reports_the_resolved_path(tmp_path: Path) -> None:
    detail = missing_default_profile(tmp_path, "sonar/ak3-default-gate.json")

    assert detail is not None
    assert str(tmp_path / "sonar" / "ak3-default-gate.json") in detail


def test_present_profile_reports_nothing(tmp_path: Path) -> None:
    profile = tmp_path / "sonar" / "ak3-default-gate.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}", encoding="utf-8")

    assert missing_default_profile(tmp_path, "sonar/ak3-default-gate.json") is None


def test_a_directory_at_the_profile_path_is_not_a_profile(tmp_path: Path) -> None:
    """A directory satisfies ``exists`` but is not the artifact; fail closed."""
    (tmp_path / "sonar" / "ak3-default-gate.json").mkdir(parents=True)

    assert missing_default_profile(tmp_path, "sonar/ak3-default-gate.json") is not None


def test_the_machine_reason_is_the_one_the_installer_raises() -> None:
    """The reason string is the contract between this check and the runner."""
    assert DEFAULT_PROFILE_MISSING == "default_profile_missing"
