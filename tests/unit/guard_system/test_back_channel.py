"""Sub-agent back-channel filter tests."""

from __future__ import annotations

from agentkit.backend.governance.guard_system.back_channel import (
    BackChannelStatus,
    filter_back_channel,
    rejected_content_keys,
)


def test_back_channel_allows_only_typed_bounded_fields() -> None:
    msg = filter_back_channel(
        {
            "status": "blocked",
            "error_class": "policy_violation",
            "next_step": "request_review",
            "artifact_refs": ["qa/findings.json", "diff --git a/x b/x"],
            "reason": {"code": "secret_hit", "detail": "blocked by scan"},
            "raw_diff": "diff --git a/x b/x\n+secret",
            "context_json": {"full": "content"},
            "prompt": ["free prompt list"],
        }
    )
    assert msg.status is BackChannelStatus.BLOCKED
    assert msg.error_class == "policy_violation"
    assert msg.next_step == "request_review"
    assert msg.artifact_refs == ("qa/findings.json",)
    assert msg.reason == {"code": "secret_hit", "detail": "blocked by scan"}


def test_back_channel_reports_rejected_content_keys() -> None:
    assert rejected_content_keys(
        {"raw_diff": "...", "are_bundle_json": "...", "status": "ok"}
    ) == ("raw_diff", "are_bundle_json")


def test_back_channel_drops_unbounded_free_text() -> None:
    msg = filter_back_channel(
        {
            "status": "ok",
            "next_step": "x" * 200,
            "reason": "free form paragraph",
            "artifact_refs": ["ok/ref", "line1\nline2"],
        }
    )
    assert msg.status is BackChannelStatus.OK
    assert msg.next_step is None
    assert msg.reason is None
    assert msg.artifact_refs == ("ok/ref",)
