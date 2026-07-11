"""Postgres integration coverage for the FK-54 split admin-freeze saga."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.object_claims import (
    ObjectClaimStorePort,
    acquire_story_claim,
    release_story_claim,
    story_claim_key,
)
from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    ObjectMutationClaimRepository,
)
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.store.freeze_repository import FreezeRepository
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    WireStoryType,
)
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_split import (
    SplitPlan,
    SplitSourceState,
    StorySplitRequest,
    StorySplitSagaGuard,
    StorySplitService,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.story_model import Story

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


class _ProjectRepository:
    def __init__(self) -> None:
        self.project = Project(
            key="ak3",
            name="AgentKit 3",
            story_id_prefix="AK3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=2,
                repositories=["ak3"],
            ),
        )

    def get(self, key: str) -> Project | None:
        return self.project if key == self.project.key else None

    def list(self, *, include_archived: bool = False) -> list[Project]:
        del include_archived
        return [self.project]

    def save(self, project: Project) -> None:
        self.project = project


class _NoDependencies:
    def list_for_project(self, project_key: str) -> list[object]:
        del project_key
        return []

    def add(self, edge: object, *, project_key: str) -> None:
        raise AssertionError((edge, project_key))

    def remove(self, story_id: str, depends_on_story_id: str, kind: object) -> None:
        raise AssertionError((story_id, depends_on_story_id, kind))


class _Quiesce:
    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        del project_key, story_id, run_id
        return 1


class _Governance:
    def deactivate_locks(self, story_id: str) -> object:
        del story_id
        return object()


@dataclass(frozen=True)
class _Success:
    success: bool = True


class _Export:
    def export(self, *, story_id: str, story_dir: Path) -> object:
        del story_id, story_dir
        return _Success()


class _Superseded:
    def mark_superseded(self, *, story_id: str, superseded_by: tuple[str, ...]) -> int:
        del story_id, superseded_by
        return 1


class _GapClaimStore(ObjectClaimStorePort):
    """Real claim port with a deterministic pause after the quiesce release."""

    def __init__(self, delegate: ObjectMutationClaimRepository) -> None:
        self._delegate = delegate
        self.gap_open = threading.Event()
        self.continue_split = threading.Event()

    def acquire_claim(self, **kwargs: object) -> bool:
        return self._delegate.acquire_claim(**kwargs)

    def release_claim(
        self,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
    ) -> bool:
        released = self._delegate.release_claim(
            project_key,
            serialization_scope,
            scope_key,
            op_id,
        )
        if op_id.endswith(":quiesce"):
            self.gap_open.set()
            if not self.continue_split.wait(timeout=10):
                raise RuntimeError("test did not release the split gap")
        return released


def _create_story_service() -> tuple[StoryService, Story, Story]:
    service = StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_ProjectRepository(),  # type: ignore[arg-type]
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *args: None,
    )
    source = service.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Overscoped source",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="create-source",
    )
    service.approve_story(source.story_display_id, op_id="approve-source")
    service.begin_progress(source.story_display_id)
    independent = service.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Independent story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="create-independent",
    )
    service.approve_story(independent.story_display_id, op_id="approve-independent")
    return service, source, independent


def test_running_split_releases_source_claim_between_steps_and_independent_story_stays_mutable(
    tmp_path: Path,
) -> None:
    """AC7: no saga-duration claim exists; another story mutates in the gap."""
    story_service, source, independent = _create_story_service()
    claim_store = _GapClaimStore(ObjectMutationClaimRepository())
    freeze_store = FreezeRepository()
    service = StorySplitService(
        control_plane_repository=ControlPlaneRuntimeRepository(),
        story_service=story_service,
        dependency_repository=_NoDependencies(),  # type: ignore[arg-type]
        phase_state_quiesce=_Quiesce(),
        governance=_Governance(),
        successor_export=_Export(),
        superseded_index=_Superseded(),
        stories_root=tmp_path / "stories",
        source_state_loader=lambda _request: SplitSourceState(
            scope_explosion_established=True,
            paused_with_scope_explosion=True,
            competing_admin_operation_active=False,
        ),
        saga_guard=StorySplitSagaGuard(
            freeze_store=freeze_store,
            object_claim_store=claim_store,
            backend_instance_id="split-integration-instance",
            instance_incarnation=1,
            now_fn=lambda: _NOW,
        ),
        now_fn=lambda: _NOW,
    )
    plan = SplitPlan.model_validate(
        {
            "project_key": "ak3",
            "source_story_id": source.story_display_id,
            "reason": "scope_explosion",
            "successors": [
                {
                    "story_id": "plan-successor",
                    "title": "Bounded successor",
                    "scope_slice": "bounded slice",
                }
            ],
        }
    )
    request = StorySplitRequest(
        project_key="ak3",
        source_story_id=source.story_display_id,
        plan=plan,
        plan_text=plan.model_dump_json(),
        reason="scope_explosion",
        requested_by="human_cli",
        run_id="run-source",
        principal=Principal.HUMAN_CLI,
    )
    result: list[object] = []
    errors: list[BaseException] = []

    def _split() -> None:
        try:
            result.append(service.split_story(request))
        except BaseException as exc:  # noqa: BLE001 -- surfaced in test thread
            errors.append(exc)

    thread = threading.Thread(target=_split)
    thread.start()
    assert claim_store.gap_open.wait(timeout=10)

    active_freeze = freeze_store.read_freeze(
        source.story_display_id,
        FreezeKind.SPLIT_ADMIN_FREEZE,
    )
    assert active_freeze is not None
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- integration proof
        source_claim = conn.execute(
            "SELECT 1 FROM object_mutation_claims WHERE project_key=? AND "
            "serialization_scope='story' AND scope_key=?",
            ("ak3", source.story_display_id),
        ).fetchone()
        audit_count = conn.execute(
            "SELECT COUNT(*) AS count FROM governance_freeze_audit_records "
            "WHERE story_id=? AND kind=?",
            (source.story_display_id, FreezeKind.SPLIT_ADMIN_FREEZE.value),
        ).fetchone()
    assert source_claim is None
    assert audit_count is not None and int(audit_count["count"]) == 1

    independent_key = story_claim_key("ak3", independent.story_display_id)
    assert acquire_story_claim(
        ObjectMutationClaimRepository(),
        independent_key,
        op_id="independent-mutation",
        backend_instance_id="split-integration-instance",
        instance_incarnation=1,
        now=_NOW,
    ) is None
    try:
        story_service.begin_progress(independent.story_display_id)
    finally:
        release_story_claim(
            ObjectMutationClaimRepository(),
            independent_key,
            op_id="independent-mutation",
        )

    claim_store.continue_split.set()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert errors == []
    assert len(result) == 1
    assert str(story_service.get_story(independent.story_display_id).status) == "In Progress"
    assert freeze_store.read_freeze(
        source.story_display_id,
        FreezeKind.SPLIT_ADMIN_FREEZE,
    ) is None
