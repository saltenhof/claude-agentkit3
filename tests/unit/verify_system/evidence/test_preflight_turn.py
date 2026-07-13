"""Tests for the productive preflight prompt and sender boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentkit.backend.verify_system.evidence as evidence_api
from agentkit.backend.verify_system.evidence import (
    FailClosedPreflightReviewSender,
    PreflightReviewSenderError,
    preflight_turn,
    render_preflight_prompt,
)


def test_fail_closed_preflight_sender_raises_without_productive_transport() -> None:
    with pytest.raises(PreflightReviewSenderError, match="No productive file-capable"):
        FailClosedPreflightReviewSender().send(
            prompt="prompt",
            merge_paths=[Path("src/app.py")],
            attempt_id="attempt",
            request_hash="0" * 64,
        )


def test_preflight_prompt_uses_preflight_sentinel_not_template_prefix() -> None:
    prompt = render_preflight_prompt("header", "AG3-062")

    assert "[PREFLIGHT:review-preflight-v1:AG3-062]" in prompt
    assert "[TEMPLATE:" not in prompt
    assert "[SENTINEL:" not in prompt


def test_legacy_preflight_turn_is_not_exposed() -> None:
    """The unwired two-send legacy orchestration cannot be reactivated."""
    assert not hasattr(evidence_api, "PreflightTurn")
    assert not hasattr(preflight_turn, "PreflightTurn")
