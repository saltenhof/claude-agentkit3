"""Unit tests for WorkerSession (FK-26 §26.2) context resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types import SpawnReason
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.implementation.worker_session import (
    WorkerContextItemKey,
    WorkerSession,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from agentkit.backend.prompt_runtime.composer import ComposeConfig


class _FakeLoader:
    """In-memory StoryContextLoaderPort for unit tests (no state backend)."""

    def __init__(self, ctx: StoryContext | None) -> None:
        self._ctx = ctx

    def load(self, story_id: str, run_id: str) -> StoryContext | None:
        del story_id, run_id
        return self._ctx


def _ctx(story_type: StoryType = StoryType.IMPLEMENTATION) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-044",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        title="Worker loop + manifest",
    )


def test_resolve_worker_context_reads_story_context() -> None:
    """resolve_worker_context builds a typed WorkerContext from StoryContext."""
    session = WorkerSession(
        SpawnReason.INITIAL,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(_ctx()),
    )
    context = session.resolve_worker_context()
    assert context.story_id == "AG3-044"
    assert context.run_id == "run-1"
    assert context.spawn_reason is SpawnReason.INITIAL
    assert context.items[WorkerContextItemKey.STORY_BRIEF] == "Worker loop + manifest"
    assert (
        context.items[WorkerContextItemKey.STORY_TYPE]
        == StoryType.IMPLEMENTATION.value
    )
    # Non-remediation spawn: no feedback item.
    assert WorkerContextItemKey.FEEDBACK not in context.items


def test_remediation_context_carries_feedback() -> None:
    """A remediation spawn resolves the feedback item (FK-26 §26.2.3)."""
    session = WorkerSession(
        SpawnReason.REMEDIATION,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(_ctx()),
    )
    context = session.resolve_worker_context()
    assert WorkerContextItemKey.FEEDBACK in context.items
    assert context.items[WorkerContextItemKey.FEEDBACK].endswith("feedback.json")


def test_resolve_fails_closed_without_story_context() -> None:
    """No persisted StoryContext -> fail-closed (no spawn against unknown story)."""
    session = WorkerSession(
        SpawnReason.INITIAL,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(None),
    )
    with pytest.raises(CorruptStateError, match="cannot resolve a StoryContext"):
        session.resolve_worker_context()


def test_project_key_property_resolves_from_context() -> None:
    """The project_key property reads the resolved StoryContext."""
    session = WorkerSession(
        SpawnReason.INITIAL,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(_ctx()),
    )
    assert session.project_key == "test-project"


@dataclass(frozen=True)
class _FakeInstance:
    prompt_path: Path


class _FakePromptRuntime:
    """PromptRuntime double recording the materialize_prompt call (no bundle)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ComposeConfig, str]] = []

    def materialize_prompt(
        self,
        ctx: StoryContext,
        template_name: str,
        config: ComposeConfig,
        *,
        run_id: str,
        invocation_id: str,
        render_mode: str = "rendered",
        attempt: int = 1,
    ) -> _FakeInstance:
        del ctx, render_mode, attempt
        self.calls.append((template_name, config, invocation_id))
        return _FakeInstance(prompt_path=Path(f"prompts/{run_id}/{template_name}.md"))


def test_compose_worker_prompt_selects_remediation_template() -> None:
    """compose_worker_prompt picks the spawn-reason template and materialises it."""
    session = WorkerSession(
        SpawnReason.REMEDIATION,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(_ctx()),
    )
    context = session.resolve_worker_context()
    runtime = _FakePromptRuntime()
    path = session.compose_worker_prompt(
        context,
        runtime,  # type: ignore[arg-type]
        invocation_id="inv-1",
    )
    assert path.endswith("worker-remediation.md")
    template_name, config, invocation_id = runtime.calls[0]
    assert template_name == "worker-remediation"
    assert config.spawn_reason is SpawnReason.REMEDIATION
    assert invocation_id == "inv-1"


def test_compose_worker_prompt_initial_template() -> None:
    """An INITIAL implementation spawn materialises the implementation template."""
    session = WorkerSession(
        SpawnReason.INITIAL,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(_ctx()),
    )
    context = session.resolve_worker_context()
    runtime = _FakePromptRuntime()
    path = session.compose_worker_prompt(
        context, runtime, invocation_id="inv-1"  # type: ignore[arg-type]
    )
    assert path.endswith("worker-implementation.md")
