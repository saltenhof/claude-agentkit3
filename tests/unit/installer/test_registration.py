"""Unit tests for the AG3-039 installer registration entities (FK-50 §50.3/§50.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.installer.registration import (
    CP7_STATE_BACKEND_REGISTRATION,
    CheckpointResult,
    CheckpointStatus,
    ProjectRegistration,
    RuntimeProfile,
)


def _registration(**overrides: object) -> ProjectRegistration:
    base: dict[str, object] = {
        "project_key": "demo",
        "project_root": Path("/srv/demo"),
        "github_owner": "acme",
        "github_repo": "demo",
        "runtime_profile": RuntimeProfile.CORE,
        "config_version": "1",
        "config_digest": "a" * 64,
        "registered_at": datetime(2026, 6, 4, tzinfo=UTC),
    }
    base.update(overrides)
    return ProjectRegistration(**base)  # type: ignore[arg-type]


def test_runtime_profile_values() -> None:
    assert RuntimeProfile.CORE == "core"
    assert RuntimeProfile.ARE == "are"
    assert {p.value for p in RuntimeProfile} == {"core", "are"}


def test_checkpoint_status_values() -> None:
    assert {s.value for s in CheckpointStatus} == {
        "pass",
        "created",
        "updated",
        "skipped",
        "failed",
    }


def test_registration_minimal_optional_timestamps_default_none() -> None:
    reg = _registration()
    assert reg.last_verified_at is None
    assert reg.last_upgraded_at is None
    assert reg.runtime_profile is RuntimeProfile.CORE


def test_registration_is_frozen() -> None:
    reg = _registration()
    with pytest.raises(ValidationError):
        reg.config_digest = "b" * 64  # type: ignore[misc]


def test_registration_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _registration(unexpected="x")


@pytest.mark.parametrize(
    "missing",
    [
        "project_key",
        "project_root",
        "github_owner",
        "github_repo",
        "runtime_profile",
        "config_version",
        "config_digest",
        "registered_at",
    ],
)
def test_registration_requires_all_mandatory_fields(missing: str) -> None:
    kwargs: dict[str, object] = {
        "project_key": "demo",
        "project_root": Path("/srv/demo"),
        "github_owner": "acme",
        "github_repo": "demo",
        "runtime_profile": RuntimeProfile.CORE,
        "config_version": "1",
        "config_digest": "a" * 64,
        "registered_at": datetime(2026, 6, 4, tzinfo=UTC),
    }
    del kwargs[missing]
    with pytest.raises(ValidationError):
        ProjectRegistration(**kwargs)  # type: ignore[arg-type]


def test_registration_rejects_unknown_runtime_profile() -> None:
    with pytest.raises(ValidationError):
        _registration(runtime_profile="hybrid")


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        ("..", "demo"),  # path-traversal owner
        ("acme", ".."),  # path-traversal repo
        ("acme", "."),  # current-dir repo token
        ("-bad", "demo"),  # leading-hyphen owner
        ("bad-", "demo"),  # trailing-hyphen owner
        ("a--b", "demo"),  # consecutive hyphens owner
        ("ac me", "demo"),  # embedded space owner
        ("acme/evil", "demo"),  # slash in owner
        ("acme\n", "demo"),  # trailing newline owner (ERROR-1)
        ("acme", "demo\n"),  # trailing newline repo (ERROR-1)
        ("", "demo"),  # empty owner
        ("acme", ""),  # empty repo
        ("a" * 40, "demo"),  # owner too long
        ("acme", "r" * 101),  # repo too long
        ("äcme", "demo"),  # non-ASCII owner
    ],
)
def test_registration_rejects_malformed_github_coordinates(
    owner: str, repo: str
) -> None:
    """AG3-039 R7 ERROR-2: a malformed coordinate can never be constructed.

    Defense-in-depth / data SSOT: the model validator runs
    ``validate_github_coordinate`` so NO code path (direct construct, repository
    save, test) can ever persist an invalid GitHub owner/repo. The single
    validation truth is shared with the CLI / URL parser / CP 7 port.
    """
    with pytest.raises(ValidationError):
        _registration(github_owner=owner, github_repo=repo)


def test_registration_accepts_valid_boundary_github_coordinates() -> None:
    """Valid boundary coordinates are NOT falsely rejected by the validator."""
    reg = _registration(github_owner="a" * 39, github_repo="r" * 100)
    assert reg.github_owner == "a" * 39
    assert reg.github_repo == "r" * 100
    dotted = _registration(github_owner="a-b", github_repo="repo.js")
    assert dotted.github_repo == "repo.js"


def test_checkpoint_result_frozen_and_forbids_extra() -> None:
    result = CheckpointResult(
        checkpoint=CP7_STATE_BACKEND_REGISTRATION,
        status=CheckpointStatus.CREATED,
        detail="ok",
        duration_ms=3,
    )
    assert result.checkpoint == "cp_07_state_backend_registration"
    with pytest.raises(ValidationError):
        result.status = CheckpointStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CheckpointResult(
            checkpoint="x",
            status=CheckpointStatus.PASS,
            detail=None,
            duration_ms=0,
            extra="nope",  # type: ignore[call-arg]
        )


def test_checkpoint_result_detail_optional() -> None:
    # CREATED is a non-actionable outcome (no reason required, FK-50 §50.4); a
    # missing free-form ``detail`` stays optional.
    result = CheckpointResult(
        checkpoint="x", status=CheckpointStatus.CREATED, duration_ms=0
    )
    assert result.detail is None


@pytest.mark.parametrize("status", [CheckpointStatus.SKIPPED, CheckpointStatus.FAILED])
def test_checkpoint_result_skip_or_fail_requires_reason(
    status: CheckpointStatus,
) -> None:
    """FK-50 §50.4: SKIPPED/FAILED without a reason is rejected (fail-closed)."""
    with pytest.raises(ValidationError, match="requires a non-empty 'reason'"):
        CheckpointResult(checkpoint="x", status=status, duration_ms=0)
    # whitespace-only reason is equally invalid
    with pytest.raises(ValidationError, match="requires a non-empty 'reason'"):
        CheckpointResult(checkpoint="x", status=status, reason="   ", duration_ms=0)


@pytest.mark.parametrize(
    "status",
    [CheckpointStatus.PASS, CheckpointStatus.CREATED, CheckpointStatus.UPDATED],
)
def test_checkpoint_result_non_actionable_status_needs_no_reason(
    status: CheckpointStatus,
) -> None:
    """FK-50 §50.4: PASS/CREATED/UPDATED are non-actionable; reason stays optional."""
    result = CheckpointResult(checkpoint="x", status=status, duration_ms=0)
    assert result.reason is None


def test_checkpoint_result_reason_defaults_none_and_is_settable() -> None:
    """FK-50 §50.4 machine-readable reason: optional, defaults to None (W5)."""
    default = CheckpointResult(
        checkpoint="x", status=CheckpointStatus.CREATED, duration_ms=0
    )
    assert default.reason is None
    with_reason = CheckpointResult(
        checkpoint="x",
        status=CheckpointStatus.SKIPPED,
        detail="idempotent skip",
        reason="config_digest_unchanged",
        duration_ms=0,
    )
    assert with_reason.reason == "config_digest_unchanged"
