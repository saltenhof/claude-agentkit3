"""File-capable preflight review sender port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient


class PreflightReviewSenderError(VerifySystemError):
    """Raised when the preflight reviewer transport cannot produce text."""


@runtime_checkable
class PreflightReviewSender(Protocol):
    """Narrow file-capable port for reviewer preflight and review sends."""

    def send(
        self,
        *,
        prompt: str,
        merge_paths: Sequence[Path],
        attempt_id: str,
        request_hash: str,
    ) -> str:
        """Send one audited attempt and return raw reviewer text.

        Implementations must correlate the call by ``attempt_id`` and
        ``request_hash``. A repeated attempt id must never execute a second
        completion with different input.
        """
        ...


@dataclass(frozen=True)
class FailClosedPreflightReviewSender:
    """Default sender that fails closed until a productive transport is injected."""

    reason: str = (
        "No productive file-capable preflight review transport is configured. "
        "AG3-062 defines only the PreflightReviewSender port; the concrete "
        "MCP-pool adapter is out of scope."
    )

    def send(
        self,
        *,
        prompt: str,
        merge_paths: Sequence[Path],
        attempt_id: str,
        request_hash: str,
    ) -> str:
        """Always raise ``PreflightReviewSenderError``."""
        del prompt, merge_paths, attempt_id, request_hash
        raise PreflightReviewSenderError(self.reason)


@dataclass(frozen=True)
class LlmPreflightReviewSender:
    """Productive preflight adapter for an already-composed LLM transport.

    The coordinator durably audits ``attempt_id`` before this adapter is
    entered and never reuses an incomplete attempt after a crash. Therefore a
    transport call is made at most once for each audited attempt identity.
    """

    client: LlmClient

    def send(
        self,
        *,
        prompt: str,
        merge_paths: Sequence[Path],
        attempt_id: str,
        request_hash: str,
    ) -> str:
        """Run the once-only preflight completion for an audited attempt."""
        del merge_paths
        if not attempt_id or not request_hash:
            raise PreflightReviewSenderError(
                "preflight transport requires audited attempt correlation"
            )
        try:
            response = self.client.complete(role="review_preflight", prompt=prompt)
        except Exception as exc:  # noqa: BLE001 -- transport boundary is fail-closed
            raise PreflightReviewSenderError(
                f"preflight transport failed for audited attempt {attempt_id}: {exc}"
            ) from exc
        if not response.strip():
            raise PreflightReviewSenderError("preflight transport returned empty text")
        return response


__all__ = [
    "FailClosedPreflightReviewSender",
    "LlmPreflightReviewSender",
    "PreflightReviewSender",
    "PreflightReviewSenderError",
]
