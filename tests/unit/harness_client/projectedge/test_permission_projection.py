"""Fail-closed tests for discardable local permission projections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.harness_client.projectedge.permission_projection import (
    LocalPermissionStateProjection,
    PermissionProjectionError,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_projection_fails_closed_without_local_database_fallback(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".agentkit" / "ccag" / "ccag_requests.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy local truth must be ignored")

    with pytest.raises(PermissionProjectionError, match="missing"):
        LocalPermissionStateProjection(tmp_path).verify(
            project_key="proj", story_id="AG3-131", run_id="run-1",
            request_ids=("req-1",),
        )


def test_divergent_projection_fails_closed(tmp_path: Path) -> None:
    projection = LocalPermissionStateProjection(tmp_path)
    projection.write_requests("proj", "AG3-131", "run-1", ("req-1",))

    with pytest.raises(PermissionProjectionError, match="divergent"):
        projection.verify(
            project_key="proj", story_id="AG3-131", run_id="run-1",
            request_ids=("req-2",),
        )


def test_matching_fresh_projection_is_accepted(tmp_path: Path) -> None:
    projection = LocalPermissionStateProjection(tmp_path)
    projection.write_requests("proj", "AG3-131", "run-1", ("req-1",))

    verified = projection.verify(
        project_key="proj", story_id="AG3-131", run_id="run-1",
        request_ids=("req-1",),
    )
    assert verified.open_request_ids == ("req-1",)
