"""Integration: AG3-147 hard push barriers at REAL phase boundaries (AC1/AC2/AC3).

Drives the PUBLIC :class:`ControlPlaneRuntimeService` API against real Postgres
with pipeline state produced by a REAL predecessor path (a genuine
``start_phase(setup)`` mints the active ownership the boundary then requires) --
never hand-assembled. The two-stage barrier evidence is supplied by an injected
:class:`PushBarrierEvidencePort` fake carrying prepared per-repo inputs, so the
test controls exactly the (edge-report, server-ref-read) pair the A-core
aggregates. Covers:

* AC1 -- both single negative paths: (a) edge reports pushed but the server head
  SHA mismatches, (b) the server head resolves but there is NO edge report. The
  Edge report alone is never sufficient.
* AC2 -- the phase-completion AND the closure-entry boundary types, each a hard
  fail-closed barrier on a real boundary.
* AC3 -- multi-repo: one un-verified repo blocks even when all others are verified.

``tests/integration/control_plane/`` is NOT auto-attached to the Postgres
fixture, so this module requests it explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.push_sync import RepoPushVerificationInput
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

_T0 = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_SHA_X = "x" * 40
_SHA_Y = "y" * 40


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


@dataclass(frozen=True)
class _FakeBarrierPort:
    inputs: tuple[RepoPushVerificationInput, ...]

    def collect_repo_inputs(
        self, *, project_key: str, story_id: str, run_id: str
    ) -> tuple[RepoPushVerificationInput, ...]:
        del project_key, story_id, run_id
        return self.inputs


class _AdmittedDispatcher:
    def dispatch(
        self, *, ctx: object, phase: str, run_id: str, run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> object:
        from agentkit.backend.control_plane.models import PhaseDispatchResult

        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase, status="phase_completed", reaction="advance",
            dispatched=True, next_phase="implementation",
        )


def _verified(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_X,
        server_ref_resolved=True,
        server_head_sha=_SHA_X,
    )


def _server_mismatch(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_X,
        server_ref_resolved=True,
        server_head_sha=_SHA_Y,  # server does not confirm the edge-reported head
    )


def _no_edge_report(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=False,  # server would pass, but NO edge report
        edge_reported_pushed=False,
        edge_reported_head_sha=None,
        server_ref_resolved=True,
        server_head_sha=_SHA_X,
    )


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


def _request(*, story_id: str, op_id: str, session_id: str = "sess-A") -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=[f"T:/worktrees/{story_id}"],
    )


def _service(
    inputs: tuple[RepoPushVerificationInput, ...], *, ident: str
) -> ControlPlaneRuntimeService:
    identity = boot_backend_instance_identity_global(ident, _T0)
    return ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        push_barrier_evidence=_FakeBarrierPort(inputs),  # type: ignore[arg-type]
    )


def _admit_run(service: ControlPlaneRuntimeService, *, story_id: str, run_id: str) -> None:
    """Mint the active ownership via a REAL setup start (not hand-assembled)."""
    result = service.start_phase(
        run_id=run_id, phase="setup",
        request=_request(story_id=story_id, op_id=f"op-setup-{story_id}"),
    )
    assert result.status == "committed"


# ---------------------------------------------------------------------------
# AC1 / AC2 phase-completion barrier
# ---------------------------------------------------------------------------


def test_phase_completion_barrier_blocks_when_server_head_mismatches_edge(tmp_path: Path) -> None:
    """AC1(a): edge reports a push but the server ref-read does not confirm it."""
    story_id, run_id = "AG3-901", "run-901"
    _seed_story_context(tmp_path, story_id)
    service = _service((_server_mismatch("api"),), ident="inst-901")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id, phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-901"),
    )

    assert result.status == "rejected"
    assert result.phase_dispatch is not None
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_phase_completion_barrier_blocks_when_no_edge_report(tmp_path: Path) -> None:
    """AC1(b): the server head resolves but there is NO edge report -> block."""
    story_id, run_id = "AG3-902", "run-902"
    _seed_story_context(tmp_path, story_id)
    service = _service((_no_edge_report("api"),), ident="inst-902")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id, phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-902"),
    )

    assert result.status == "rejected"
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_phase_completion_barrier_passes_when_verified(tmp_path: Path) -> None:
    """The barrier passes (commits) when the repo is server-verified-pushed."""
    story_id, run_id = "AG3-903", "run-903"
    _seed_story_context(tmp_path, story_id)
    service = _service((_verified("api"),), ident="inst-903")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id, phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-903"),
    )

    assert result.status == "committed"


def test_setup_completion_is_not_gated_by_the_push_barrier(tmp_path: Path) -> None:
    """The barrier is scoped to the code-bearing implementation phase: a setup
    completion (nothing pushed yet) is NOT fail-closed-blocked."""
    story_id, run_id = "AG3-904", "run-904"
    _seed_story_context(tmp_path, story_id)
    # Blocking evidence, yet a setup completion must pass (not a gated phase).
    service = _service((_no_edge_report("api"),), ident="inst-904")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id, phase="setup",
        request=_request(story_id=story_id, op_id="op-complete-setup-904"),
    )

    assert result.status == "committed"


# ---------------------------------------------------------------------------
# AC3 multi-repo teildivergenz
# ---------------------------------------------------------------------------


def test_phase_completion_barrier_blocks_on_one_unverified_repo(tmp_path: Path) -> None:
    """AC3: one un-verified repo blocks even when every other repo is verified."""
    story_id, run_id = "AG3-905", "run-905"
    _seed_story_context(tmp_path, story_id)
    service = _service(
        (_verified("api"), _server_mismatch("web"), _verified("infra")),
        ident="inst-905",
    )
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id, phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-905"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason or ""
    assert "push_barrier_unverified" in reason
    assert "web" in reason  # the blocking repo is named


# ---------------------------------------------------------------------------
# AC2 / AC12 closure-entry barrier (verify_pushed_across_repos precondition)
# ---------------------------------------------------------------------------


def _closure_request(*, story_id: str, op_id: str) -> ClosureCompleteRequest:
    return ClosureCompleteRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id="sess-A",
        op_id=op_id,
    )


def test_closure_entry_barrier_blocks_unverified_push(tmp_path: Path) -> None:
    """AC2/AC12: closure entry is fail-closed-blocked when the story branch is
    not server-verified-pushed in a participating repo (SOLL-190)."""
    story_id, run_id = "AG3-906", "run-906"
    _seed_story_context(tmp_path, story_id)
    service = _service((_server_mismatch("api"),), ident="inst-906")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_closure(
        run_id=run_id, request=_closure_request(story_id=story_id, op_id="op-closure-906"),
    )

    assert result.status == "rejected"
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_closure_entry_barrier_passes_when_verified(tmp_path: Path) -> None:
    """Closure proceeds past the barrier when every repo is server-verified-pushed."""
    story_id, run_id = "AG3-907", "run-907"
    _seed_story_context(tmp_path, story_id)
    service = _service((_verified("api"),), ident="inst-907")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_closure(
        run_id=run_id, request=_closure_request(story_id=story_id, op_id="op-closure-907"),
    )

    assert result.status == "committed"
