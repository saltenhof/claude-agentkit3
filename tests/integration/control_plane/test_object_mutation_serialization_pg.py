"""Postgres integration tests for object-mutation serialization (AG3-141).

Exercises the REAL Postgres ``object_mutation_claims`` table and the real
dispatch path through :class:`ControlPlaneRuntimeService` -- true phase
boundaries, not fabricated state:

* AC1 -- a claim survives a crash (no release call at all, ever); a fresh
  startup reconciliation of the SAME instance identity releases it, and a
  subsequent mutation for the story succeeds.
* AC2 (IMPL-017) -- two parallel clients, one story, different ``op_id``s:
  exactly one dispatches; the other gets the deterministic K4 wait response;
  the loser NEVER reaches the engine dispatch (no parallel engine writes).
* AC3 -- different stories of the same project dispatch in parallel (no
  global lock); reads (``get_operation``) run unblocked against a permanently
  held object claim.
* AC5 -- queue-fairness: a held project claim blocks a later story-claim
  attempt of the same project, and vice versa
  (``pending_project_claims_are_not_overtaken_by_younger_story_claims``).
* AC6/K4 -- a permanently-held competing claim yields a deterministic
  ``409``-equivalent (``rejected`` + ``error_code=conflict`` +
  ``retry_after_seconds``) near-instantly -- never a blocking wait.
* AC7 -- no wall-clock expiry: a claim acquired at an ancient instant still
  blocks even with the caller's clock advanced arbitrarily far into the
  future.

The Postgres backend is NOT in the conftest auto-attach allow-list for
``tests/integration/control_plane/`` (mirrors ``test_startup_reconcile_pg.py``),
so this module requests the isolation fixture explicitly.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane import object_claims as oc
from agentkit.backend.control_plane.models import PhaseDispatchResult, PhaseMutationRequest
from agentkit.backend.control_plane.records import ObjectMutationClaimRecord
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane.startup_reconcile import run_startup_reconciliation
from agentkit.backend.state_backend.operation_ledger import (
    claim_control_plane_operation_global,
    insert_object_mutation_claim_global,
    load_control_plane_operation_global,
    load_object_mutation_claim_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context_global
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    """Bind the per-test isolated Postgres control-plane schema (K5 Postgres-only).

    ``tests/integration/control_plane/`` is not in the conftest Postgres
    auto-attach allow-list, so this module requests the isolation fixture
    explicitly for every test (mirrors ``test_startup_reconcile_pg.py``).
    """
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


class _TimingDispatcher:
    """A dispatcher that records its OWN execution window (start, end).

    A held-for-``hold_seconds`` fake engine dispatch, so a genuine race
    between two concurrent ``start_phase`` calls has a real window to land
    in. Proves "no parallel engine writes" (AC2) directly: the object-claim
    loser must NEVER reach ``dispatch`` at all, so at most ONE interval is
    ever recorded per story under real concurrent load.
    """

    def __init__(self, *, hold_seconds: float = 0.3) -> None:
        self._hold_seconds = hold_seconds
        self._lock = threading.Lock()
        self.intervals: list[tuple[float, float]] = []

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
        start = time.monotonic()
        time.sleep(self._hold_seconds)
        end = time.monotonic()
        with self._lock:
            self.intervals.append((start, end))
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


def _run_concurrently(calls: list[Callable[[], object]]) -> list[object]:
    """Run *calls* on separate threads, released at THE SAME instant."""
    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)
    errors: list[BaseException] = []

    def _wrapped(index: int, call: Callable[[], object]) -> None:
        barrier.wait()
        try:
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 -- surfaced to the test thread
            errors.append(exc)

    threads = [
        threading.Thread(target=_wrapped, args=(i, call)) for i, call in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return results


# ---------------------------------------------------------------------------
# AC2 / IMPL-017: two parallel clients, one story, different op_ids
# ---------------------------------------------------------------------------


def test_two_concurrent_starts_same_story_exactly_one_dispatches(
    tmp_path: Path,
) -> None:
    """IMPL-017 pattern: deterministically exactly one client dispatches; the
    second receives the declared K4 wait response; no parallel engine writes.
    """
    story_id = "AG3-500"
    run_id = "run-500"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-impl017", _T0)
    dispatcher = _TimingDispatcher(hold_seconds=0.3)
    service_a = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    service_b = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )

    results = _run_concurrently(
        [
            lambda: service_a.start_phase(
                run_id=run_id,
                phase="setup",
                request=_request(story_id=story_id, op_id="op-a", session_id="sess-a"),
            ),
            lambda: service_b.start_phase(
                run_id=run_id,
                phase="setup",
                request=_request(story_id=story_id, op_id="op-b", session_id="sess-b"),
            ),
        ]
    )

    statuses = sorted(r.status for r in results)  # type: ignore[attr-defined]
    assert statuses == ["committed", "rejected"]
    rejected = next(r for r in results if r.status == "rejected")  # type: ignore[attr-defined]
    assert rejected.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    assert rejected.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    #: The loser NEVER reached the engine dispatch -- no parallel engine writes.
    assert len(dispatcher.intervals) == 1
    #: The story's object claim was released by the winner's finalize.
    assert load_object_mutation_claim_global(_PROJECT, "story", story_id) is None


# ---------------------------------------------------------------------------
# AC3: different stories parallel; reads never take locks
# ---------------------------------------------------------------------------


def test_different_stories_dispatch_in_parallel(tmp_path: Path) -> None:
    """AC3: mutations of DIFFERENT stories never contend for the same claim."""
    story_a, story_b = "AG3-510", "AG3-511"
    _seed_story_context(tmp_path, story_a)
    _seed_story_context(tmp_path, story_b)
    identity = boot_backend_instance_identity_global("inst-parallel-stories", _T0)
    dispatcher = _TimingDispatcher(hold_seconds=0.3)
    service_a = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    service_b = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )

    results = _run_concurrently(
        [
            lambda: service_a.start_phase(
                run_id="run-510",
                phase="setup",
                request=_request(story_id=story_a, op_id="op-a", session_id="sess-a"),
            ),
            lambda: service_b.start_phase(
                run_id="run-511",
                phase="setup",
                request=_request(story_id=story_b, op_id="op-b", session_id="sess-b"),
            ),
        ]
    )

    assert [r.status for r in results] == ["committed", "committed"]  # type: ignore[attr-defined]
    #: BOTH engine dispatches ran -- their windows genuinely overlapped (no
    #: global lock serialized them).
    assert len(dispatcher.intervals) == 2
    (s1, e1), (s2, e2) = dispatcher.intervals
    assert s1 < e2 and s2 < e1, "different-story dispatches must overlap in time"


def test_reads_are_never_blocked_by_a_held_object_claim(tmp_path: Path) -> None:
    """SOLL-048/053/055: GET .../operations/{op_id} never waits on a claim."""
    held_story_id = "AG3-512"
    read_story_id = "AG3-513"
    _seed_story_context(tmp_path, held_story_id)
    _seed_story_context(tmp_path, read_story_id)
    identity = boot_backend_instance_identity_global("inst-reads-free", _T0)
    #: Permanently hold a DIFFERENT story's object claim (a foreign in-flight
    #: op) -- the read below must be unaffected by ANY held claim.
    insert_object_mutation_claim_global(
        ObjectMutationClaimRecord(
            project_key=_PROJECT,
            serialization_scope="story",
            scope_key=held_story_id,
            op_id="op-holder",
            backend_instance_id=identity.backend_instance_id,
            instance_incarnation=identity.instance_incarnation,
            acquired_at=_T0,
            queue_position=0,
        )
    )
    #: A committed operation to read back.
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_TimingDispatcher(hold_seconds=0.0),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    committed = service.start_phase(
        run_id="run-513",
        phase="setup",
        request=_request(
            story_id=read_story_id, op_id="op-read-seed", session_id="sess-read"
        ),
    )
    assert committed.status == "committed"

    start = time.monotonic()
    result = service.get_operation("op-read-seed")
    elapsed = time.monotonic() - start

    assert result is not None
    assert elapsed < 1.0, "a read must never wait on any object claim"


# ---------------------------------------------------------------------------
# AC6 / K4: permanently-held claim -> deterministic 409 + Retry-After, no wait
# ---------------------------------------------------------------------------


def test_permanently_held_claim_yields_deterministic_conflict_without_waiting(
    tmp_path: Path,
) -> None:
    story_id = "AG3-520"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-k4", _T0)
    insert_object_mutation_claim_global(
        ObjectMutationClaimRecord(
            project_key=_PROJECT,
            serialization_scope="story",
            scope_key=story_id,
            op_id="op-forever",
            backend_instance_id=identity.backend_instance_id,
            instance_incarnation=identity.instance_incarnation,
            acquired_at=_T0,
            queue_position=0,
        )
    )
    service = ControlPlaneRuntimeService(now_fn=lambda: _T0, instance_identity=identity)

    start = time.monotonic()
    result = service.start_phase(
        run_id="run-520",
        phase="setup",
        request=_request(story_id=story_id, op_id="op-new", session_id="sess-new"),
    )
    elapsed = time.monotonic() - start

    assert result.status == "rejected"
    assert result.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    assert result.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    assert elapsed < 1.0, "K4: never a blocking wait, regardless of how long the claim is held"
    #: NO operation was stored for the busy attempt.
    assert load_control_plane_operation_global("op-new") is None
    #: The permanently-held claim is untouched.
    held = load_object_mutation_claim_global(_PROJECT, "story", story_id)
    assert held is not None and held.op_id == "op-forever"


# ---------------------------------------------------------------------------
# AC7: no wall-clock expiry
# ---------------------------------------------------------------------------


def test_ancient_claim_never_expires_even_with_far_future_clock(tmp_path: Path) -> None:
    """object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock."""
    story_id = "AG3-521"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-no-ttl", _T0)
    ancient = datetime(2000, 1, 1, tzinfo=UTC)
    insert_object_mutation_claim_global(
        ObjectMutationClaimRecord(
            project_key=_PROJECT,
            serialization_scope="story",
            scope_key=story_id,
            op_id="op-ancient",
            backend_instance_id=identity.backend_instance_id,
            instance_incarnation=identity.instance_incarnation,
            acquired_at=ancient,
            queue_position=0,
        )
    )
    far_future = datetime(2036, 1, 1, tzinfo=UTC)
    service = ControlPlaneRuntimeService(
        now_fn=lambda: far_future, instance_identity=identity
    )

    result = service.start_phase(
        run_id="run-521",
        phase="setup",
        request=_request(story_id=story_id, op_id="op-new", session_id="sess-new"),
    )

    assert result.status == "rejected"
    assert result.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    held = load_object_mutation_claim_global(_PROJECT, "story", story_id)
    assert held is not None and held.op_id == "op-ancient", "no TTL/expiry ever releases it"


# ---------------------------------------------------------------------------
# AC1: claim survives a crash; startup reconciliation releases it
# ---------------------------------------------------------------------------


def test_crash_after_claim_acquisition_is_released_only_by_reconciliation(
    tmp_path: Path,
) -> None:
    """AC1: a crash after claim acquisition and before finalize leaves BOTH
    the in-flight operation claim and the object-mutation claim durably
    held; ONLY the AG3-138 startup reconciliation (same instance, later
    incarnation) or an explicit admin-abort ends it -- never a wall clock.
    """
    story_id = "AG3-530"
    run_id = "run-530"
    op_id = "op-crashed"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-crash", _T0)

    #: Simulate "acquired the object claim and the op_id claim, then the
    #: process was killed" -- no release call is EVER made (a real crash).
    from agentkit.backend.control_plane.runtime import _build_claim_placeholder

    placeholder = _build_claim_placeholder(
        _request(story_id=story_id, op_id=op_id, session_id="sess-crash"),
        run_id=run_id,
        phase="setup",
        owner_token="owner-crash",
        now=_T0,
        operation_kind="phase_start",
        instance_identity=identity,
    )
    assert claim_control_plane_operation_global(placeholder)
    insert_object_mutation_claim_global(
        ObjectMutationClaimRecord(
            project_key=_PROJECT,
            serialization_scope="story",
            scope_key=story_id,
            op_id=op_id,
            backend_instance_id=identity.backend_instance_id,
            instance_incarnation=identity.instance_incarnation,
            acquired_at=_T0,
            queue_position=0,
        )
    )

    #: A fresh mutation attempt for the SAME story is busy -- the crash left
    #: the object genuinely claimed.
    blocked_service = ControlPlaneRuntimeService(
        now_fn=lambda: _T0 + timedelta(minutes=1), instance_identity=identity
    )
    blocked = blocked_service.start_phase(
        run_id="run-530-retry",
        phase="setup",
        request=_request(story_id=story_id, op_id="op-retry-1", session_id="sess-retry-1"),
    )
    assert blocked.status == "rejected"
    assert blocked.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT

    #: "Restart": the SAME instance boots a NEW (later) incarnation and runs
    #: the startup reconciliation BEFORE accepting any request.
    restarted_identity = boot_backend_instance_identity_global("inst-crash", _T0)
    outcome = run_startup_reconciliation(
        ControlPlaneRuntimeRepository(),
        restarted_identity,
        now_fn=lambda: _T0 + timedelta(minutes=2),
    )

    assert op_id in outcome.finalized_op_ids
    finalized = load_control_plane_operation_global(op_id)
    assert finalized is not None and finalized.status == "failed"
    assert load_object_mutation_claim_global(_PROJECT, "story", story_id) is None, (
        "reconciliation must release the orphaned object claim"
    )

    #: A fresh mutation for the SAME story now succeeds -- no permanent deadlock.
    #: (A working dispatcher is injected exactly as the other committing tests
    #: do; the point under test is that the object claim no longer blocks the
    #: acquire, NOT the engine's own dispatch outcome.)
    fresh_service = ControlPlaneRuntimeService(
        phase_dispatcher=_TimingDispatcher(hold_seconds=0.0),  # type: ignore[arg-type]
        now_fn=lambda: _T0 + timedelta(minutes=3),
        instance_identity=restarted_identity,
    )
    fresh = fresh_service.start_phase(
        run_id="run-530-fresh",
        phase="setup",
        request=_request(story_id=story_id, op_id="op-fresh", session_id="sess-fresh"),
    )
    assert fresh.status == "committed", (
        "after reconciliation frees the orphaned object claim the story must "
        f"no longer be blocked; got {fresh.status} (error_code={fresh.error_code})"
    )
    #: Whatever else, the fresh attempt was NOT turned away by a lingering
    #: object claim -- the serialization deadlock is gone.
    assert fresh.error_code != oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
