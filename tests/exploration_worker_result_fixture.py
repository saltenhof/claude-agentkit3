"""Recorded real exploration-worker result fixture (AG3-055 record-replay).

The seven FK-23 §23.3.2 drafting steps are executed by a SPAWNED worker agent
(non-deterministic, LLM-backed) -- NOT engine-side and NOT rule-based. Tests must
therefore not call a live LLM; instead they REPLAY a once-recorded real worker /
LLM result as a reproducible fixture (the only mock seam is the LLM/worker
boundary, CLAUDE.md MOCKS-exception).

This module holds:

* :data:`RECORDED_WORKER_CHANGE_FRAME_PAYLOAD` -- a recorded real worker output:
  the raw seven-part change-frame JSON the worker emitted for a real exploration
  story. The content is DERIVED (a concrete, story-specific design) and is
  deliberately DISTINCT from the static plumbing fixture
  (``tests.exploration_change_frame_fixture.example_change_frame``) so a test can
  prove the persisted frame came from the (replayed) worker, not a constant.
* :class:`ReplayExplorationWorkerRunner` -- the record-replay ``ExplorationWorkerRunner``
  test double that returns the recorded payload (stamped with the requested
  scope) without spawning a worker or calling an LLM.
* :class:`EmptyExplorationWorkerRunner` -- a worker double that produced NO draft
  (empty result) for the fail-closed test.

``recorded_worker_payload`` re-stamps the recorded payload's ``story_id`` /
``run_id`` onto the requested scope so the replay matches the drafting core's
identity cross-check, while keeping the worker-derived CONTENT intact.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from agentkit.exploration.change_frame import CHANGE_FRAME_SCHEMA_VERSION
from agentkit.exploration.drafting.ports import ExplorationWorkerResult

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext

#: A recorded REAL worker run id (FK-02 §2.3.1 UUID). The replay re-stamps the
#: requested run id over this so the recorded content can be replayed under any
#: test scope.
RECORDED_RUN_ID = "44444444-4444-4444-8444-444444444444"

#: A once-recorded real exploration-worker output (the raw seven-part FK-23
#: §23.4.1 change-frame JSON). Worker-DERIVED content for a concrete story
#: (a feature-flag evaluation cache) -- intentionally different from the static
#: plumbing fixture so a persisted-frame assertion proves worker provenance.
RECORDED_WORKER_CHANGE_FRAME_PAYLOAD: dict[str, object] = {
    "schema_version": CHANGE_FRAME_SCHEMA_VERSION,
    "story_id": "PROJ-128",
    "run_id": RECORDED_RUN_ID,
    "created_at": "2026-06-05T14:15:00+00:00",
    "frozen": False,
    "goal_and_scope": {
        "changes": (
            "Add an in-memory evaluation cache in front of the feature-flag "
            "resolver so repeated flag lookups within a request avoid the store."
        ),
        "does_not_change": (
            "The flag-store schema and the admin write API stay unchanged; only "
            "the read path gains a request-scoped cache."
        ),
    },
    "affected_building_blocks": {
        "affected": [
            "flagging/flag-resolver",
            "flagging/request-context",
        ],
        "untouched": [
            "flagging/admin-api",
            "flagging/flag-store",
        ],
    },
    "solution_direction": {
        "pattern": "Request-scoped decorator around the existing FlagResolver.",
        "anchoring": (
            "A CachingFlagResolver wrapping the FlagResolver, bound per request "
            "in the request-context module."
        ),
        "rationale": (
            "Smallest fitting solution: the cache is a thin decorator on the "
            "read path, so the resolver contract and the store stay untouched."
        ),
    },
    "contract_changes": {
        "interfaces": [
            "FlagResolver.resolve gains a CachingFlagResolver decorator "
            "(same signature, no wire change)."
        ],
        "data_model": ["none (no persisted entity changes)"],
        "events": ["none"],
        "external_integrations": ["none"],
    },
    "conformance_statement": {
        "reference_documents": [
            "concepts/flagging-architecture.md",
            "guardrails/performance-budgets.md",
        ],
        "conformant": [
            "The decorator keeps the FlagResolver contract intact "
            "(flagging-architecture.md §3).",
            "Request-scoped lifetime respects the no-cross-request-state rule "
            "(performance-budgets.md §2).",
        ],
        "deviations": [
            "Cache invalidation is omitted because the cache lifetime is a "
            "single request -- justified by the request-scoped lifetime."
        ],
    },
    "verification_sketch": {
        "unit": (
            "CachingFlagResolver returns the cached verdict on the second "
            "lookup and delegates exactly once to the wrapped resolver."
        ),
        "integration": (
            "Two resolves of the same flag in one request hit the store once."
        ),
        "e2e": None,
    },
    "open_points": {
        "decided": [
            "Request-scoped cache instead of a shared TTL cache.",
        ],
        "assumptions": [
            "Flag verdicts are stable within a single request.",
        ],
        "approval_needed": [],
    },
}


def recorded_worker_payload(
    *, story_id: str, run_id: str
) -> dict[str, object]:
    """Return the recorded worker payload re-stamped onto ``(story_id, run_id)``.

    Keeps the worker-DERIVED content intact; only the identity fields are
    re-stamped so the replay matches the drafting core's identity cross-check for
    the test's scope (a real worker stamps the run's own ids on its draft).

    Args:
        story_id: The story display id to stamp.
        run_id: The run correlation id to stamp.

    Returns:
        A deep copy of the recorded payload with ``story_id`` / ``run_id`` set.
    """
    payload = copy.deepcopy(RECORDED_WORKER_CHANGE_FRAME_PAYLOAD)
    payload["story_id"] = story_id
    payload["run_id"] = run_id
    return payload


class ReplayExplorationWorkerRunner:
    """Record-replay ``ExplorationWorkerRunner`` (the LLM/worker boundary mock).

    Replays the recorded real worker output instead of spawning a worker / calling
    an LLM. Re-stamps the recorded payload onto the requested scope so the replayed
    content validates under the test's (story, run). Records the calls for
    assertions.

    Args:
        prompt_path: The materialized-prompt path to report (default mirrors a
            run-scoped ``worker-exploration`` instance path).
        story_id_override: When set, stamps THIS story id instead of the
            requested one (used to drive the foreign-identity fail-closed test).
    """

    def __init__(
        self,
        *,
        prompt_path: str = "_temp/prompts/run/inv/worker-exploration.md",
        story_id_override: str | None = None,
    ) -> None:
        self._prompt_path = prompt_path
        self._story_id_override = story_id_override
        self.calls: list[tuple[str, str, str]] = []

    def run_exploration_worker(
        self, ctx: StoryContext, *, run_id: str, invocation_id: str
    ) -> ExplorationWorkerResult:
        """Return the recorded worker result for the requested scope."""
        self.calls.append((ctx.story_id, run_id, invocation_id))
        story_id = self._story_id_override or ctx.story_id
        payload = recorded_worker_payload(story_id=story_id, run_id=run_id)
        return ExplorationWorkerResult(
            payload=payload, prompt_path=self._prompt_path
        )


class EmptyExplorationWorkerRunner:
    """An ``ExplorationWorkerRunner`` whose worker produced NO draft (empty)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def run_exploration_worker(
        self, ctx: StoryContext, *, run_id: str, invocation_id: str
    ) -> ExplorationWorkerResult:
        """Return an empty result (no draft) -> fail-closed in the drafting core."""
        self.calls.append((ctx.story_id, run_id, invocation_id))
        return ExplorationWorkerResult(payload=None, prompt_path="")


__all__ = [
    "RECORDED_RUN_ID",
    "RECORDED_WORKER_CHANGE_FRAME_PAYLOAD",
    "EmptyExplorationWorkerRunner",
    "ReplayExplorationWorkerRunner",
    "recorded_worker_payload",
]
