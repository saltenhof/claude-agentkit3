"""Discardable short-TTL local projection of central permission state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

_PROJECTION_TTL_SECONDS = 30


class PermissionProjectionError(RuntimeError):
    """A local permission projection is missing or diverges from central state."""


class PermissionStateProjection(BaseModel):
    """Hook-readable projection; never canonical permission truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    open_request_ids: tuple[str, ...] = ()
    active_lease_fingerprints: tuple[str, ...] = ()
    permission_state_version: str = Field(min_length=1)
    projected_at: datetime
    valid_until: datetime


class LocalPermissionStateProjection:
    """Write and verify the local ``permission_state.json`` projection."""

    def __init__(self, project_root: Path) -> None:
        self._path = project_root / ".agent-guard" / "permission_state.json"

    def write_requests(
        self, project_key: str, story_id: str, run_id: str,
        request_ids: tuple[str, ...],
    ) -> PermissionStateProjection:
        """Replace the projection after a successful central read."""
        now = datetime.now(UTC)
        version = _version(request_ids, ())
        projection = PermissionStateProjection(
            project_key=project_key, story_id=story_id, run_id=run_id,
            open_request_ids=request_ids, permission_state_version=version,
            projected_at=now, valid_until=now + timedelta(seconds=_PROJECTION_TTL_SECONDS),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._path, json.dumps(projection.model_dump(mode="json"), sort_keys=True)
        )
        return projection

    def verify(
        self, *, project_key: str, story_id: str, run_id: str,
        request_ids: tuple[str, ...], lease_fingerprints: tuple[str, ...] = (),
    ) -> PermissionStateProjection:
        """Fail closed when the local projection is missing, stale, or divergent."""
        try:
            projection = PermissionStateProjection.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise PermissionProjectionError("permission projection is missing or invalid") from exc
        expected = (project_key, story_id, run_id, request_ids, lease_fingerprints)
        actual = (
            projection.project_key, projection.story_id, projection.run_id,
            projection.open_request_ids, projection.active_lease_fingerprints,
        )
        if projection.valid_until <= datetime.now(UTC) or actual != expected:
            raise PermissionProjectionError("permission projection is stale or divergent")
        if projection.permission_state_version != _version(request_ids, lease_fingerprints):
            raise PermissionProjectionError("permission projection version diverges")
        return projection


def _version(request_ids: tuple[str, ...], leases: tuple[str, ...]) -> str:
    import hashlib

    raw = json.dumps([sorted(request_ids), sorted(leases)], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "LocalPermissionStateProjection",
    "PermissionProjectionError",
    "PermissionStateProjection",
]
