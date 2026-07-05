"""Integration: AG3-144 reconnect reconciliation at the real phase boundary.

FK-91 §91.1a Rule 14 (synchronous execution) + Rule 17 (transport timeouts have
no business meaning): a client whose connection drops during a synchronous
mutation never loses ownership or work -- it reconciles the outcome via
``GET /v1/project-edge/operations/{op_id}``. This path already exists
(AG3-138/140: the terminal result is stored under the CLIENT-supplied ``op_id``,
never server-minted, and a replay of the same ``op_id`` returns the stored
result without a second mutation). This module VERIFIES the path end-to-end
through the REAL public ``ControlPlaneRuntimeService`` API against real
Postgres -- true phase boundaries, never fabricated pipeline state -- and finds
it already complete (the expected outcome per the story): the pinning tests
below are the closing evidence, no code change was needed.

* AC1 -- a real ``start_phase`` call commits; ``get_operation(op_id)``
  reconciles to the SAME terminal result (the "client's connection dropped,
  it re-fetches by op_id" scenario).
* AC1 (idempotency) -- the client, still unsure whether its original call
  landed, RETRIES the identical mutation with the SAME client-supplied
  ``op_id``: the dispatcher is NOT invoked a second time (no double effect)
  and the result is the SAME (replayed) outcome.
* AC1 (no server minting) -- ``op_id`` is supplied by the client on every
  call; the backend never mints one (statically pinned separately by
  ``tests/contract/test_op_id_no_server_mint_pin.py``; this test proves the
  RUNTIME behavior: the SAME client op_id reconciles to the SAME result).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import PhaseDispatchResult, PhaseMutationRequest
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.state_backend.store import (
    boot_backend_instance_identity_global,
    save_story_context_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-reconnect"


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    """Bind the per-test isolated Postgres control-plane schema (K5 Postgres-only)."""
    del postgres_isolated_schema


def _seed_story_context(tmp_path: Path, story_id: str) -> None:
    project_root = tmp_path / _PROJECT
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    save_story_context_global(
        None,
        StoryContext(
            project_key=_PROJECT,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        ),
    )


def _request(*, story_id: str, op_id: str, session_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=[f"T:/worktrees/{story_id}"],
    )


class _CountingAdmittedDispatcher:
    """A dispatcher that always completes the phase and counts its own calls.

    Mirrors the real (possibly long) synchronous ``dispatch_phase`` -- this
    test uses the call count to prove a client's retry with the SAME op_id
    never re-dispatches (no double effect), exactly the property Rule 5/14/17
    depend on.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        self.call_count += 1
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


def test_get_operation_reconciles_a_dropped_connection_to_the_committed_result(
    tmp_path: Path,
) -> None:
    """AC1: a real, committed synchronous mutation reconciles via GET by op_id.

    Simulates: the client's HTTP connection to the ``start_phase`` response
    dropped AFTER the server committed but BEFORE the client observed the
    response body. The client never re-derives the outcome from anything but
    the stored terminal result under its OWN op_id (no server minting).
    """
    story_id = "AG3-950"
    run_id = "run-950"
    op_id = "op-reconnect-950"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-reconnect-950", _T0)
    dispatcher = _CountingAdmittedDispatcher()
    service = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )

    committed = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id=op_id, session_id="sess-A"),
    )
    assert committed.status == "committed"
    assert dispatcher.call_count == 1

    # The client's connection dropped; it never saw ``committed`` directly and
    # reconciles via GET, using ONLY the op_id it itself supplied.
    reconciled = service.get_operation(op_id)

    assert reconciled is not None
    assert reconciled.status == "replayed"
    assert reconciled.op_id == op_id
    assert reconciled.run_id == committed.run_id
    assert reconciled.phase == committed.phase
    assert reconciled.ownership_epoch == committed.ownership_epoch
    # The dispatcher was NOT re-invoked by the reconciling read.
    assert dispatcher.call_count == 1


def test_retrying_the_same_op_id_after_reconnect_has_no_double_effect(
    tmp_path: Path,
) -> None:
    """AC1 (idempotency): a client retry with the SAME op_id never re-dispatches.

    Models a client that, after a dropped connection, is unsure whether its
    mutation landed and simply RETRIES the identical call (rather than, or in
    addition to, reading via GET) -- the standard client-side reconnect
    behavior FK-91 §91.1a Rule 5 guarantees is safe.
    """
    story_id = "AG3-951"
    run_id = "run-951"
    op_id = "op-reconnect-951"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-reconnect-951", _T0)
    dispatcher = _CountingAdmittedDispatcher()
    service = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    request = _request(story_id=story_id, op_id=op_id, session_id="sess-A")

    first = service.start_phase(run_id=run_id, phase="setup", request=request)
    assert first.status == "committed"
    assert dispatcher.call_count == 1

    # The client retries the IDENTICAL mutation (same op_id, same body) --
    # the connection-drop's canonical client-side reconnect behavior.
    retried = service.start_phase(run_id=run_id, phase="setup", request=request)

    assert retried.status == "replayed"
    assert retried.op_id == op_id
    assert retried.run_id == first.run_id
    assert retried.ownership_epoch == first.ownership_epoch
    # No second dispatch, no second mutation -- exactly one phase execution.
    assert dispatcher.call_count == 1

    # A THIRD read via GET (e.g. a second reconnect) still reconciles to the
    # SAME committed outcome, still without a second dispatch.
    reread = service.get_operation(op_id)
    assert reread is not None
    assert reread.status == "replayed"
    assert dispatcher.call_count == 1
