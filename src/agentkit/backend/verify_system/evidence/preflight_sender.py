"""File-capable preflight review sender port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class PreflightReviewSenderError(VerifySystemError):
    """Raised when the preflight reviewer transport cannot produce text."""


@runtime_checkable
class PreflightReviewSender(Protocol):
    """Narrow file-capable port for reviewer preflight and review sends."""

    def send(self, *, prompt: str, merge_paths: Sequence[Path]) -> str:
        """Send a prompt with attached merge paths and return raw reviewer text."""
        ...


@dataclass(frozen=True)
class FailClosedPreflightReviewSender:
    """Default sender that fails closed until a productive transport is injected."""

    reason: str = (
        "No productive file-capable preflight review transport is configured. "
        "AG3-062 defines only the PreflightReviewSender port; the concrete "
        "MCP-pool adapter is out of scope."
    )

    def send(self, *, prompt: str, merge_paths: Sequence[Path]) -> str:
        """Always raise ``PreflightReviewSenderError``."""
        del prompt, merge_paths
        raise PreflightReviewSenderError(self.reason)


__all__ = [
    "FailClosedPreflightReviewSender",
    "PreflightReviewSender",
    "PreflightReviewSenderError",
]
