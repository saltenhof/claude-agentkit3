"""Unit contract tests for canonical permission-request records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentkit.backend.governance.ccag.permission_records import PermissionRequestRecord
from agentkit.backend.governance.ccag.requests import DEFAULT_TTL_SECONDS


def test_request_record_pins_central_entity_fields() -> None:
    now = datetime.now(UTC)
    record = PermissionRequestRecord(
        request_id="req-1", project_key="proj", story_id="AG3-1", run_id="run-1",
        principal_type="worker", tool_name="Bash", operation_class="execute",
        path_classes=("codebase_story_scope",), request_fingerprint="sha256:x",
        status="pending", requested_at=now, expires_at=now + timedelta(minutes=30),
    )
    assert record.project_key == "proj"
    assert record.resolution is None
    assert DEFAULT_TTL_SECONDS == 1800


def test_request_record_rejects_missing_path_class() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        PermissionRequestRecord(
            request_id="req-1", project_key="proj", story_id="AG3-1", run_id="run-1",
            principal_type="worker", tool_name="Bash", operation_class="execute",
            path_classes=(), request_fingerprint="sha256:x", status="pending",
            requested_at=now, expires_at=now + timedelta(minutes=30),
        )
