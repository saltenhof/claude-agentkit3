"""Integration: the AG3-055 produce -> AG3-045 consume change-frame loop.

Proves the worker-driven drafting (producer) closes the loop the AG3-045 handler
(consumer/validator) reads: ``ExplorationDrafting`` writes the ENTWURF envelope +
the protected ``change_frame.json`` (via the REAL persistence ports over a
tmp_path sqlite store), and the productive ``ExplorationPhaseHandler`` then
reads/validates it -- it no longer hits ``_NO_CHANGE_FRAME_MESSAGE``.

The ONLY doubled seam is the LLM/worker boundary (the recorded real worker result
replayed via ``tests.exploration_worker_result_fixture``); all persistence,
identity cross-checks and the handler's consume path run for real.

A second test drives the PRODUCTIVE ``StateBackendExplorationWorkerRunner`` end to
end: it materializes ``worker-exploration.md`` over the AG3-044 worker-spawn path
(proving the AG3-015/FK-44 wiring + the selector picking the exploration template)
and reads back the worker's raw draft, which the drafting core then persists.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.exploration_worker_result_fixture import (
    ReplayExplorationWorkerRunner,
    recorded_worker_payload,
)
from tests.phase_state_factory import make_phase_state

from agentkit.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_drafting,
    build_exploration_phase_handler,
)
from agentkit.core_types.qa_artifact_names import (
    CHANGE_FRAME_DRAFT_FILE,
    CHANGE_FRAME_FILE,
)
from agentkit.exploration.drafting.drafting import (
    ExplorationDrafting,
    ExplorationDraftRequest,
)
from agentkit.exploration.drafting.persistence import ArtifactChangeFrameSink
from agentkit.exploration.phase import _NO_CHANGE_FRAME_MESSAGE
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseStatus,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY_ID = "PROJ-128"
_RUN_ID = "66666666-6666-4666-8666-666666666666"


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


def _bind_flow(story_dir: Path) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id=_STORY_ID,
            run_id=_RUN_ID,
            flow_id="exploration",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _envelope() -> object:
    return PhaseEnvelopeStore.make_fresh_envelope(
        make_phase_state(
            story_id=_STORY_ID,
            phase="exploration",
            status=PhaseStatus.IN_PROGRESS,
            payload=ExplorationPayload(),
        )
    )


def test_drafting_then_handler_consumes_the_frame(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)

    # Producer: the worker-driven drafting writes the ENTWURF envelope + file.
    manager = build_artifact_manager(sd)
    drafting = ExplorationDrafting(
        worker_runner=ReplayExplorationWorkerRunner(),
        change_frame_sink=ArtifactChangeFrameSink(manager),
        change_frame_writer=StateBackendExplorationChangeFrameAdapter(manager),
    )
    drafting.draft(
        ExplorationDraftRequest(
            ctx=ctx, story_dir=sd, run_id=_RUN_ID, invocation_id="inv-1"
        )
    )

    # Consumer: the AG3-045 handler reads/validates the persisted frame and no
    # longer hits the fail-closed "no change-frame" path (review=None -> FAILED,
    # NOT ESCALATED-with-_NO_CHANGE_FRAME_MESSAGE).
    result = build_exploration_phase_handler(sd).on_enter(ctx, _envelope())

    assert result.status is PhaseStatus.FAILED  # valid frame, no review wired
    assert all(_NO_CHANGE_FRAME_MESSAGE not in e for e in result.errors)


def test_handler_no_frame_no_draft_emits_worker_spawn(tmp_path: Path) -> None:
    """Loop step 1: no change-frame AND no worker draft -> emit a typed spawn.

    Drives the REAL productive handler (drafting + presence ports wired). With no
    worker draft present the handler EMITS a typed exploration-worker
    ``SpawnRequest`` (WORKER / INITIAL) into ``agents_to_spawn`` and returns
    ``IN_PROGRESS`` -- the AG3-044/054 spawn-and-await, NOT a dead-end ESCALATED.
    """
    from agentkit.core_types import SpawnKind, SpawnReason

    sd = _story_dir(tmp_path)
    _bind_flow(sd)

    result = build_exploration_phase_handler(sd).on_enter(_ctx(sd), _envelope())

    assert result.status is PhaseStatus.IN_PROGRESS
    assert result.updated_state is not None
    orders = result.updated_state.agents_to_spawn
    assert len(orders) == 1
    assert orders[0].kind is SpawnKind.WORKER
    assert orders[0].spawn_reason is SpawnReason.INITIAL
    assert orders[0].target_id == _STORY_ID


def test_handler_consumes_worker_draft_through_the_real_loop(
    tmp_path: Path,
) -> None:
    """Loop step 2: a worker DRAFT present -> the handler's drafting consumes it.

    Drives the REAL produce->consume loop through the REGISTERED phase handler
    (NOT by seeding the canonical change_frame.json directly): the spawned worker's
    RAW draft (``change_frame.draft.json``) is replayed into the protected QA dir,
    the prompt bundle is bound (so the productive worker-runner materializes
    ``worker-exploration.md`` and reads the raw draft), and the handler's wired
    ``ExplorationDrafting`` CONSUMES -> validates -> persists the canonical frame.
    The handler then proceeds past the no-change-frame branch (review=None ->
    FAILED, never the ``_NO_CHANGE_FRAME_MESSAGE`` dead-end), and the canonical
    protected change_frame.json was materialized BY the loop.
    """
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    save_story_context(sd, ctx)
    _install_prompt_bundle(ctx.project_root)

    # The spawned worker's RAW draft (its FK-23 ChangeFrame JSON), as the prompt
    # instructs it to write. The handler-driven drafting reads + validates it.
    qa_dir = resolve_qa_story_dir(sd, story_id=_STORY_ID)
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / CHANGE_FRAME_DRAFT_FILE).write_text(
        json.dumps(recorded_worker_payload(story_id=_STORY_ID, run_id=_RUN_ID)),
        encoding="utf-8",
    )
    # The canonical change_frame.json does NOT exist yet -- the loop must create it.
    assert not (qa_dir / CHANGE_FRAME_FILE).is_file()

    result = build_exploration_phase_handler(sd).on_enter(ctx, _envelope())

    # The handler consumed the draft (no spawn emitted, no no-change-frame
    # dead-end) and proceeded to the gate; review=None fails closed -> FAILED.
    assert result.status is PhaseStatus.FAILED
    assert all(_NO_CHANGE_FRAME_MESSAGE not in e for e in result.errors)
    assert result.updated_state is not None
    assert not result.updated_state.agents_to_spawn
    # The canonical protected change_frame.json was materialized BY the loop.
    assert (qa_dir / CHANGE_FRAME_FILE).is_file()


def test_productive_worker_runner_materializes_prompt_and_reads_draft(
    tmp_path: Path,
) -> None:
    """The productive runner spawns over the AG3-044 path + reads the raw draft.

    Exercises ``build_exploration_drafting`` end to end: the productive
    ``StateBackendExplorationWorkerRunner`` materializes ``worker-exploration.md``
    (AG3-015/FK-44; the selector picks the exploration template for the
    EXPLORATION route) and reads the worker's raw draft, which the drafting core
    validates + persists. The worker's raw draft is seeded into the protected
    QA dir (the harness worker's output stand-in).
    """
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    save_story_context(sd, ctx)
    _install_prompt_bundle(ctx.project_root)

    # Seed the worker's raw draft (the harness worker output the runner reads).
    qa_dir = resolve_qa_story_dir(sd, story_id=_STORY_ID)
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / CHANGE_FRAME_DRAFT_FILE).write_text(
        json.dumps(recorded_worker_payload(story_id=_STORY_ID, run_id=_RUN_ID)),
        encoding="utf-8",
    )

    drafting = build_exploration_drafting(sd, ctx)
    result = drafting.draft(
        ExplorationDraftRequest(
            ctx=ctx, story_dir=sd, run_id=_RUN_ID, invocation_id="inv-prod"
        )
    )

    # The materialized prompt is the EXPLORATION template (selector wiring):
    # the bundle declares ONLY worker-exploration, so a successful render proves
    # the selector picked it for the EXPLORATION route; the sentinel confirms it.
    from pathlib import Path as _Path

    prompt_text = _Path(result.prompt_path).read_text(encoding="utf-8")
    assert "worker-exploration-v1" in prompt_text
    # The canonical change_frame.json was produced from the worker's raw draft.
    cf = qa_dir / CHANGE_FRAME_FILE
    assert cf.is_file()
    assert result.change_frame.run_id == _RUN_ID


def test_worker_runner_fails_closed_on_context_scope_divergence(
    tmp_path: Path,
) -> None:
    """ERROR-2: persisted context B + request A -> fail-closed, NO artifact.

    The productive ``StateBackendExplorationWorkerRunner`` materializes the prompt
    from the StoryContext persisted at ``story_dir`` (resolved WITHOUT the
    requested ids) but reads the draft for the REQUEST's story_id. The prompt
    context and the artifact identity must therefore not diverge: a persisted
    context belonging to a DIFFERENT story than the requested scope is refused
    fail-closed BEFORE the prompt is materialized and BEFORE any draft is read --
    no prompt, no draft, no artifact.
    """
    from agentkit.exceptions import CorruptStateError
    from agentkit.prompt_runtime import PromptRuntime
    from agentkit.state_backend.store.exploration_worker_runner import (
        StateBackendExplorationWorkerRunner,
    )

    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    # The context persisted at this story_dir is story B (PROJ-128). The loader
    # used for prompt materialization resolves it WITHOUT the requested ids.
    persisted_b = _ctx(sd)
    save_story_context(sd, persisted_b)
    _install_prompt_bundle(persisted_b.project_root)
    # The request is for story A (PROJ-777) -> the prompt context (B) and the
    # draft-read identity (A) would diverge. Must fail closed BEFORE the prompt.
    request_a = StoryContext(
        project_key="test-project",
        story_id="PROJ-777",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="A different requested story",
        project_root=sd.parent.parent,
    )

    runner = StateBackendExplorationWorkerRunner(
        sd, PromptRuntime(request_a.project_root, build_artifact_manager(sd))
    )
    with pytest.raises(CorruptStateError, match="scope mismatch"):
        runner.run_exploration_worker(
            request_a, run_id=_RUN_ID, invocation_id="inv-div"
        )

    # No prompt materialized, no draft read, NO artifact: the canonical
    # change_frame.json exists under neither the persisted nor the requested story.
    assert not (
        resolve_qa_story_dir(sd, story_id=_STORY_ID) / CHANGE_FRAME_FILE
    ).is_file()
    assert not (
        resolve_qa_story_dir(sd, story_id="PROJ-777") / CHANGE_FRAME_FILE
    ).is_file()


def _install_prompt_bundle(project_root: Path | None) -> None:
    """Install + bind a minimal prompt bundle with worker-exploration.md.

    Materialization (rendered) needs a bound bundle whose manifest declares the
    ``worker-exploration`` template; this seeds the central store, binds it and
    copies the real ``worker-exploration.md`` template into it.
    """
    assert project_root is not None
    import hashlib
    import importlib.resources

    from agentkit.installer.paths import (
        prompt_bundle_lock_path,
        prompt_bundle_store_dir,
    )
    from agentkit.prompt_runtime.runtime import build_prompt_bundle_lock_content

    bundle_id, version = "test-bundle", "1.0.0"
    bundle_root = prompt_bundle_store_dir(bundle_id, version)
    prompts_dir = bundle_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    template = (
        importlib.resources.files("agentkit.resources.internal.prompts")
        / "worker-exploration.md"
    ).read_text(encoding="utf-8")
    (prompts_dir / "worker-exploration.md").write_text(template, encoding="utf-8")
    sha256 = hashlib.sha256(template.encode("utf-8")).hexdigest()
    manifest = {
        "bundle_id": bundle_id,
        "bundle_version": version,
        "templates": {
            "worker-exploration": {
                "relpath": "prompts/worker-exploration.md",
                "sha256": sha256,
            }
        },
    }
    manifest_text = json.dumps(manifest)
    (bundle_root / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock = build_prompt_bundle_lock_content(
        bundle_id=bundle_id,
        bundle_version=version,
        manifest_file="manifest.json",
        manifest_text=manifest_text,
    )
    lock_path = prompt_bundle_lock_path(project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(lock, encoding="utf-8")
