"""Unit contract tests for canonical permission-lease records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentkit.backend.governance.ccag.permission_records import PermissionLeaseRecord


def test_lease_record_pins_binding_and_usage_fields() -> None:
    now = datetime.now(UTC)
    record = PermissionLeaseRecord(
        lease_id="lease-1", request_ref="req-1", project_key="proj",
        story_id="AG3-1", run_id="run-1", principal_type="worker",
        tool_name="Bash", operation_class="execute",
        path_classes=("codebase_story_scope",), request_fingerprint="sha256:x",
        max_uses=2, consumed=1, issued_at=now, expires_at=now + timedelta(minutes=30),
    )
    assert record.request_ref == "req-1"
    assert record.available is True
    assert record.model_copy(update={"consumed": 2}).available is False
