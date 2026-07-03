"""Unit tests for the setup phase context builder (AG3-120).

AK3 owns the user story via ``story_id``; GitHub is only the code backend
(FK-12 §12.1.1, FK-91 §91.2 rule 9). The ``StoryContext`` is therefore built
purely from the AK3 StoryService record — never from a GitHub issue. These unit
tests exercise the single record-based ``build_story_context`` builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.errors import StoryModeResolutionError
from agentkit.backend.governance.setup_preflight_gate.context_builder import (
    build_story_context,
)
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    Story,
    StorySpecification,
    WireStoryMode,
    WireStoryType,
)
from agentkit.backend.story_context_manager.types import (
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from pathlib import Path


def _record(
    *,
    story_display_id: str = "AG3-200",
    story_number: int = 200,
    story_type: WireStoryType = WireStoryType.CONCEPT,
    title: str = "Refine the domain concept",
    labels: list[str] | None = None,
    mode: WireStoryMode | None = None,
    change_impact: ChangeImpact = ChangeImpact.LOCAL,
    concept_quality: ConceptQuality = ConceptQuality.HIGH,
    new_structures: bool = False,
    vectordb_conflict_resolved: bool = False,
) -> Story:
    """Build a ``Story`` stammdaten record (the StoryService truth source)."""
    return Story(
        project_key="test-project",
        story_number=story_number,
        story_display_id=story_display_id,
        title=title,
        story_type=story_type,
        participating_repos=["repo"],
        labels=labels if labels is not None else ["concept"],
        mode=mode,
        change_impact=change_impact,
        concept_quality=concept_quality,
        new_structures=new_structures,
        vectordb_conflict_resolved=vectordb_conflict_resolved,
    )


def _impl_record(
    *,
    story_display_id: str = "AG3-300",
    change_impact: ChangeImpact = ChangeImpact.LOCAL,
    concept_quality: ConceptQuality = ConceptQuality.HIGH,
    new_structures: bool = False,
    vectordb_conflict_resolved: bool = False,
) -> Story:
    """Build an implementation-type ``Story`` record for contract tests."""
    return _record(
        story_display_id=story_display_id,
        story_number=300,
        story_type=WireStoryType.IMPLEMENTATION,
        title="Implementation story",
        labels=["implementation"],
        change_impact=change_impact,
        concept_quality=concept_quality,
        new_structures=new_structures,
        vectordb_conflict_resolved=vectordb_conflict_resolved,
    )


class _FakeStoryService:
    """Minimal StoryService stub exposing ``get_story`` / ``get_story_detail``.

    A real ``StoryService`` + state-backend integration is exercised separately
    (AC2/AC3 integration test); this stub is acceptable for the pure builder
    unit logic.
    """

    def __init__(
        self,
        story: Story | None,
        spec: StorySpecification | None = None,
    ) -> None:
        self._story = story
        self._spec = spec

    def get_story(self, story_display_id: str) -> Story | None:
        del story_display_id
        return self._story

    def get_story_detail(
        self, story_display_id: str
    ) -> tuple[Story, StorySpecification | None] | None:
        del story_display_id
        if self._story is None:
            return None
        return self._story, self._spec


class TestBuildStoryContextFromRecord:
    """The context is built from the StoryService record, never from GitHub."""

    def test_concept_story_built_from_record(self, tmp_path: Path) -> None:
        """A CONCEPT story's context comes purely from the StoryService record."""
        service = _FakeStoryService(_record())
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-200",
            story_service=service,  # type: ignore[arg-type]
        )
        assert ctx.story_type is StoryType.CONCEPT
        assert ctx.title == "Refine the domain concept"
        assert ctx.project_root == tmp_path
        assert ctx.mode is WireStoryMode.STANDARD
        assert "repo" in ctx.participating_repos

    def test_implementation_story_built_from_record(self, tmp_path: Path) -> None:
        """An implementation story's type/labels/size come from the record."""
        service = _FakeStoryService(_impl_record(story_display_id="AG3-301"))
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-301",
            story_service=service,  # type: ignore[arg-type]
        )
        assert ctx.story_type is StoryType.IMPLEMENTATION
        assert ctx.title == "Implementation story"
        assert "implementation" in ctx.labels

    def test_fast_mode_passes_through_from_record(self, tmp_path: Path) -> None:
        """The operative fast/standard mode is read from the record (FK-24)."""
        service = _FakeStoryService(
            _impl_record(story_display_id="AG3-302")
        )
        service._story.mode = WireStoryMode.FAST  # type: ignore[union-attr]
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-302",
            story_service=service,  # type: ignore[arg-type]
        )
        assert ctx.mode is WireStoryMode.FAST

    def test_story_number_derived_from_story_id(self, tmp_path: Path) -> None:
        """story_number is derived deterministically from the story_id suffix."""
        service = _FakeStoryService(_record(story_display_id="AG3-200"))
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-200",
            story_service=service,  # type: ignore[arg-type]
        )
        assert ctx.story_id == "AG3-200"
        assert ctx.story_number == 200

    def test_unknown_story_fails_closed(self, tmp_path: Path) -> None:
        """A wired service that does not know the story fails closed (AC3).

        This is the fail-closed AK3-identity gate: an unresolvable story_id
        raises rather than fabricating stammdaten or reading GitHub.
        """
        service = _FakeStoryService(None)
        with pytest.raises(StoryModeResolutionError):
            build_story_context(
                tmp_path,
                "test-project",
                "AG3-404",
                story_service=service,  # type: ignore[arg-type]
            )

    def test_story_service_is_mandatory_no_standalone_fabrication(
        self, tmp_path: Path
    ) -> None:
        """The builder requires the authoritative service — no service-less seam.

        AG3-120 remediation (fail-closed hole): the production builder no longer
        fabricates a minimal CONCEPT context when the service is omitted. The
        story identity gate rests entirely on a resolvable AK3 ``story_id`` read
        through a wired ``StoryService``; calling without one is a TypeError, so
        no production caller can silently reach a fabrication path.
        """
        with pytest.raises(TypeError):
            build_story_context(  # type: ignore[call-arg]
                tmp_path,
                "test-project",
                "AG3-201",
            )


class TestConceptRefsProjection:
    """Real build-path contract for StorySpecification.concept_refs.

    Valid refs must NOT fire Trigger 1; absent refs must fail closed.
    """

    def test_valid_concept_refs_do_not_fire_trigger_1(self, tmp_path: Path) -> None:
        """Valid spec.concept_refs are populated → Trigger 1 does NOT fire →
        execution_route is EXECUTION (AC8)."""
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# Real concept doc", encoding="utf-8")

        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryService(
            _impl_record(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=spec,
        )
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-300",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.execution_route is StoryMode.EXECUTION
        assert str(concept_file) in ctx.concept_refs

    def test_absent_concept_refs_fires_trigger_1(self, tmp_path: Path) -> None:
        """Absent spec.concept_refs yields empty refs → Trigger 1 fires →
        execution_route is EXPLORATION (fail-closed, AC8)."""
        spec = StorySpecification(need=None, solution=None, acceptance=[], concept_refs=None)
        service = _FakeStoryService(
            _impl_record(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=spec,
        )
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-301",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.execution_route is StoryMode.EXPLORATION
        assert ctx.concept_refs == ()

    def test_no_spec_fires_trigger_1(self, tmp_path: Path) -> None:
        """spec=None yields empty refs → Trigger 1 fires → EXPLORATION (fail-closed)."""
        service = _FakeStoryService(
            _impl_record(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=None,
        )
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-302",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.execution_route is StoryMode.EXPLORATION
        assert ctx.concept_refs == ()

    def test_vectordb_conflict_projects_and_forces_exploration(self, tmp_path: Path) -> None:
        """AG3-068 (FK-21 §21.12): the authoritative vectordb_conflict_resolved
        flag is projected and a resolved conflict forces Exploration even when all
        OTHER triggers are neutral."""
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# Real concept doc", encoding="utf-8")
        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryService(
            _impl_record(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
                vectordb_conflict_resolved=True,
            ),
            spec=spec,
        )
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-303",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.vectordb_conflict_resolved is True
        assert ctx.execution_route is StoryMode.EXPLORATION

    def test_no_vectordb_conflict_allows_execution(self, tmp_path: Path) -> None:
        """AG3-068 baseline: with the conflict flag False and all triggers
        neutral, the route stays Execution — isolating the flag's effect."""
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# Real concept doc", encoding="utf-8")
        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryService(
            _impl_record(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
                vectordb_conflict_resolved=False,
            ),
            spec=spec,
        )
        ctx = build_story_context(
            tmp_path,
            "test-project",
            "AG3-304",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.vectordb_conflict_resolved is False
        assert ctx.execution_route is StoryMode.EXECUTION


class TestNewStructuresPersistenceRoundTrip:
    """new_structures field round-trips through service create and idempotency."""

    def test_create_story_persists_new_structures_true(self) -> None:
        """create_story with new_structures=True stores the flag on the Story record."""
        from agentkit.backend.project_management.entities import Project, ProjectConfiguration
        from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
            InMemoryInflightIdempotencyGuard,
        )
        from agentkit.backend.story_context_manager.service import StoryService
        from agentkit.backend.story_context_manager.story_repository import (
            InMemoryStoryRepository,
        )

        class _ProjRepo:
            def get(self, key: str) -> Project | None:
                if key == "ak3":
                    return Project(
                        key="ak3",
                        name="AgentKit 3",
                        story_id_prefix="AK3",
                        configuration=ProjectConfiguration(
                            repo_url="",
                            default_branch="main",
                            default_worker_count=1,
                            repositories=["ak3"],
                        ),
                    )
                return None

        svc = StoryService(
            story_repository=InMemoryStoryRepository(),
            project_repository=_ProjRepo(),  # type: ignore[arg-type]
            idempotency_guard=InMemoryInflightIdempotencyGuard(),
            event_emitter=lambda *a: None,
        )
        from agentkit.backend.story_context_manager.story_model import CreateStoryInput

        story = svc.create_story(
            CreateStoryInput(
                project_key="ak3",
                title="Story with new_structures",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["ak3"],
                new_structures=True,
            ),
            op_id="op-ns-001",
        )
        assert story.new_structures is True

    def test_create_story_idempotency_body_includes_new_structures(self) -> None:
        """new_structures is part of the idempotency body; a mismatch raises an error."""
        from agentkit.backend.project_management.entities import Project, ProjectConfiguration
        from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
            InMemoryInflightIdempotencyGuard,
        )
        from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError
        from agentkit.backend.story_context_manager.service import StoryService
        from agentkit.backend.story_context_manager.story_model import CreateStoryInput
        from agentkit.backend.story_context_manager.story_repository import (
            InMemoryStoryRepository,
        )

        class _ProjRepo:
            def get(self, key: str) -> Project | None:
                if key == "ak3":
                    return Project(
                        key="ak3",
                        name="AgentKit 3",
                        story_id_prefix="AK3",
                        configuration=ProjectConfiguration(
                            repo_url="",
                            default_branch="main",
                            default_worker_count=1,
                            repositories=["ak3"],
                        ),
                    )
                return None

        svc = StoryService(
            story_repository=InMemoryStoryRepository(),
            project_repository=_ProjRepo(),  # type: ignore[arg-type]
            idempotency_guard=InMemoryInflightIdempotencyGuard(),
            event_emitter=lambda *a: None,
        )

        svc.create_story(
            CreateStoryInput(
                project_key="ak3",
                title="Same story",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["ak3"],
                new_structures=False,
            ),
            op_id="op-idem-ns-001",
        )
        with pytest.raises(IdempotencyMismatchError):
            svc.create_story(
                CreateStoryInput(
                    project_key="ak3",
                    title="Same story",
                    story_type=WireStoryType.IMPLEMENTATION,
                    repos=["ak3"],
                    new_structures=True,
                ),
                op_id="op-idem-ns-001",
            )
