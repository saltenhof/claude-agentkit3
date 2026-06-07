"""Unit tests for ExplorationDrafting (AG3-055; worker-driven change-frame).

The seven FK-23 §23.3.2 steps are WORKER behaviour (spawned agent, FK-23 §23.3),
not engine-side and not rule-based. These tests exercise the bloodgroup-A
``ExplorationDrafting`` orchestration against REAL persistence ports (the
productive ``ArtifactChangeFrameSink`` + the AG3-045
``StateBackendExplorationChangeFrameAdapter`` writer over a tmp_path sqlite
store); the ONLY doubled seam is the LLM/worker boundary, replayed via the
recorded real worker result (``tests.exploration_worker_result_fixture``).

Covered:

* a valid recorded worker result -> a validated, persisted ChangeFrame with the
  seven parts present and content DERIVED from the worker (not the static
  plumbing constant, not a ``conformant=True`` default);
* fail-closed edges: no StoryContext / empty worker result / schema-invalid
  worker result / a worker draft stamped with a foreign identity -> NO artifact
  written, a clear rejection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import example_change_frame
from tests.exploration_worker_result_fixture import (
    EmptyExplorationWorkerRunner,
    ReplayExplorationWorkerRunner,
    recorded_worker_payload,
)

from agentkit.artifacts.errors import ArtifactNotFoundError
from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.exploration.change_frame import SEVEN_PARTS, ChangeFrame
from agentkit.exploration.drafting.drafting import (
    DraftingError,
    ExplorationDrafting,
    ExplorationDraftRequest,
)
from agentkit.exploration.drafting.persistence import ArtifactChangeFrameSink
from agentkit.exploration.drafting.ports import ExplorationWorkerResult
from agentkit.exploration.register import EXPLORATION_ENTWURF_STAGE
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY_ID = "PROJ-128"
_RUN_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(tmp_path: Path) -> Path:
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _ctx(story_dir: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Feature-flag evaluation cache",
        project_root=story_dir.parent.parent,
    )


def _drafting(
    story_dir: Path, worker_runner: object
) -> ExplorationDrafting:
    manager = build_artifact_manager(story_dir)
    return ExplorationDrafting(
        worker_runner=worker_runner,  # type: ignore[arg-type]
        change_frame_sink=ArtifactChangeFrameSink(manager),
        change_frame_writer=StateBackendExplorationChangeFrameAdapter(manager),
    )


def _request(story_dir: Path) -> ExplorationDraftRequest:
    return ExplorationDraftRequest(
        ctx=_ctx(story_dir),
        story_dir=story_dir,
        run_id=_RUN_ID,
        invocation_id="inv-001",
    )


def test_draft_produces_validated_change_frame_from_worker(
    tmp_path: Path,
) -> None:
    sd = _story_dir(tmp_path)
    runner = ReplayExplorationWorkerRunner()
    drafting = _drafting(sd, runner)

    result = drafting.draft(_request(sd))

    # The worker boundary was actually invoked for the requested scope.
    assert runner.calls == [(_STORY_ID, _RUN_ID, "inv-001")]
    frame = result.change_frame
    assert isinstance(frame, ChangeFrame)
    assert frame.story_id == _STORY_ID
    assert frame.run_id == _RUN_ID
    # All seven FK-23 parts are present on the validated frame.
    dumped = frame.model_dump(mode="json")
    for part in SEVEN_PARTS:
        assert part in dumped
    # Content is DERIVED from the worker, NOT the static plumbing constant.
    static_frame = example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID)
    assert frame.goal_and_scope != static_frame.goal_and_scope
    assert "evaluation cache" in frame.goal_and_scope.changes
    # Not a conformant=True default: the worker declared a justified deviation.
    assert frame.conformance_statement.deviations


def test_draft_persists_envelope_and_change_frame_file(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    drafting = _drafting(sd, ReplayExplorationWorkerRunner())

    result = drafting.draft(_request(sd))

    # 1. ENTWURF envelope readable via the productive manager.
    manager = build_artifact_manager(sd)
    envelope = manager.read_latest(
        story_id=_STORY_ID,
        run_id=_RUN_ID,
        artifact_class=ArtifactClass.ENTWURF,
        stage=EXPLORATION_ENTWURF_STAGE,
    )
    assert envelope.payload["story_id"] == _STORY_ID
    # 2. Protected change_frame.json materialized at the AG3-045 read path.
    expected = resolve_qa_story_dir(sd, story_id=_STORY_ID) / CHANGE_FRAME_FILE
    assert result.change_frame_path == expected
    assert expected.is_file()


def test_draft_without_story_context_fails_closed(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    drafting = _drafting(sd, ReplayExplorationWorkerRunner())
    request = ExplorationDraftRequest(
        ctx=None, story_dir=sd, run_id=_RUN_ID, invocation_id="inv-001"
    )

    with pytest.raises(DraftingError, match="requires a StoryContext"):
        drafting.draft(request)

    _assert_no_artifact_written(sd)


def test_draft_empty_worker_result_fails_closed(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    runner = EmptyExplorationWorkerRunner()
    drafting = _drafting(sd, runner)

    with pytest.raises(DraftingError, match="no change-frame draft"):
        drafting.draft(_request(sd))

    assert runner.calls  # the worker WAS invoked; it just produced nothing
    _assert_no_artifact_written(sd)


def test_draft_schema_invalid_worker_result_is_rejected(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)

    class _InvalidRunner:
        def run_exploration_worker(
            self, ctx: StoryContext, *, run_id: str, invocation_id: str
        ) -> ExplorationWorkerResult:
            del ctx, run_id, invocation_id
            # affected_building_blocks.affected empty -> schema violation.
            bad = recorded_worker_payload(story_id=_STORY_ID, run_id=_RUN_ID)
            bad["affected_building_blocks"] = {"affected": [], "untouched": []}
            return ExplorationWorkerResult(payload=bad, prompt_path="p")

    drafting = _drafting(sd, _InvalidRunner())

    with pytest.raises(ValueError):  # noqa: PT011  # pydantic ValidationError
        drafting.draft(_request(sd))

    _assert_no_artifact_written(sd)


def test_draft_foreign_identity_is_rejected(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    # The worker stamped a DIFFERENT story id than the requested scope.
    runner = ReplayExplorationWorkerRunner(story_id_override="OTHER-999")
    drafting = _drafting(sd, runner)

    with pytest.raises(DraftingError, match="foreign inner frame"):
        drafting.draft(_request(sd))

    _assert_no_artifact_written(sd)


def test_draft_rolls_back_file_when_envelope_write_fails(tmp_path: Path) -> None:
    """WARNING-1 atomicity: an envelope-write failure leaves NO partial state.

    The protected ``change_frame.json`` is written FIRST, the ENTWURF envelope
    second. If the envelope write fails, the just-written file is rolled back, so
    a later handler read can never consume a frame whose ENTWURF envelope was
    never materialized (no envelope without a file, no file without an envelope).
    """
    sd = _story_dir(tmp_path)
    manager = build_artifact_manager(sd)

    class _FailingSink:
        def persist(self, change_frame: object, *, attempt: int = 1) -> object:
            del change_frame, attempt
            msg = "simulated envelope-write failure"
            raise RuntimeError(msg)

    drafting = ExplorationDrafting(
        worker_runner=ReplayExplorationWorkerRunner(),
        change_frame_sink=_FailingSink(),  # type: ignore[arg-type]
        change_frame_writer=StateBackendExplorationChangeFrameAdapter(manager),
    )

    with pytest.raises(RuntimeError, match="simulated envelope-write failure"):
        drafting.draft(_request(sd))

    # The protected file was rolled back AND no ENTWURF envelope exists: no
    # partial-success state remains (the original failure is re-raised unchanged).
    _assert_no_artifact_written(sd)


def _assert_no_artifact_written(story_dir: Path) -> None:
    """Assert neither the ENTWURF envelope nor the change_frame.json exists."""
    manager = build_artifact_manager(story_dir)
    with pytest.raises(ArtifactNotFoundError):
        manager.read_latest(
            story_id=_STORY_ID,
            run_id=_RUN_ID,
            artifact_class=ArtifactClass.ENTWURF,
            stage=EXPLORATION_ENTWURF_STAGE,
        )
    cf = resolve_qa_story_dir(story_dir, story_id=_STORY_ID) / CHANGE_FRAME_FILE
    assert not cf.exists()
