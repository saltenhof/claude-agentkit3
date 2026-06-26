"""Unit tests for the setup phase context builder.

Uses monkeypatch on ``get_issue`` to avoid real GitHub CLI calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.errors import StoryModeResolutionError
from agentkit.backend.governance.setup_preflight_gate.context_builder import (
    _extract_mode,
    _extract_story_type,
    build_internal_story_context,
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
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.integration_clients.github.issues import IssueData

if TYPE_CHECKING:
    from pathlib import Path


def _internal_story(
    *,
    story_display_id: str = "AG3-200",
    story_type: WireStoryType = WireStoryType.CONCEPT,
    title: str = "Refine the domain concept",
) -> Story:
    """Build a non-code-producing ``Story`` record (StoryService stammdaten)."""
    return Story(
        project_key="test-project",
        story_number=200,
        story_display_id=story_display_id,
        title=title,
        story_type=story_type,
        participating_repos=["repo"],
        labels=["concept"],
    )


class _FakeStoryServiceWithRecord:
    """Minimal StoryService stub exposing ``get_story`` and ``get_story_detail``."""

    def __init__(self, story: Story | None) -> None:
        self._story = story
        self.issue_calls = 0

    def get_story(self, story_display_id: str) -> Story | None:
        del story_display_id
        return self._story

    def get_story_detail(self, story_display_id: str) -> tuple[Story, object] | None:
        del story_display_id
        if self._story is None:
            return None
        # No spec in the minimal stub — concept_refs will be empty (fail-closed).
        return self._story, None


def _make_issue(
    *,
    number: int = 42,
    title: str = "Add widget feature",
    state: str = "OPEN",
    labels: tuple[str, ...] = (),
    body: str = "Issue body",
    url: str = "https://github.com/owner/repo/issues/42",
) -> IssueData:
    """Create an ``IssueData`` for testing."""
    return IssueData(
        number=number,
        title=title,
        state=state,
        body=body,
        labels=labels,
        url=url,
    )


class TestExtractStoryType:
    """Tests for label-based story type extraction."""

    def test_bug_label(self) -> None:
        """Label ``"bug"`` maps to BUGFIX."""
        assert _extract_story_type(("bug",)) == StoryType.BUGFIX

    def test_bugfix_label(self) -> None:
        """Label ``"bugfix"`` maps to BUGFIX."""
        assert _extract_story_type(("bugfix",)) == StoryType.BUGFIX

    def test_concept_label(self) -> None:
        """Label ``"concept"`` maps to CONCEPT."""
        assert _extract_story_type(("concept",)) == StoryType.CONCEPT

    def test_research_label(self) -> None:
        """Label ``"research"`` maps to RESEARCH."""
        assert _extract_story_type(("research",)) == StoryType.RESEARCH

    def test_no_match_defaults_to_implementation(self) -> None:
        """No recognised label defaults to IMPLEMENTATION."""
        assert _extract_story_type(("enhancement", "docs")) == StoryType.IMPLEMENTATION

    def test_empty_labels_defaults_to_implementation(self) -> None:
        """Empty labels default to IMPLEMENTATION."""
        assert _extract_story_type(()) == StoryType.IMPLEMENTATION

    def test_case_insensitive(self) -> None:
        """Label matching is case-insensitive."""
        assert _extract_story_type(("BUG",)) == StoryType.BUGFIX
        assert _extract_story_type(("Concept",)) == StoryType.CONCEPT
        assert _extract_story_type(("RESEARCH",)) == StoryType.RESEARCH


class TestExtractMode:
    """Tests for label-based fast/standard mode extraction (FK-24 §24.3.3)."""

    def test_fast_label_maps_to_fast(self) -> None:
        assert _extract_mode(("fast",)) is WireStoryMode.FAST

    def test_fast_label_case_insensitive(self) -> None:
        assert _extract_mode(("FAST",)) is WireStoryMode.FAST

    def test_no_fast_label_defaults_to_standard(self) -> None:
        assert _extract_mode(("bug", "priority:high")) is WireStoryMode.STANDARD

    def test_empty_labels_default_to_standard(self) -> None:
        assert _extract_mode(()) is WireStoryMode.STANDARD


class TestBuildStoryContext:
    """Tests for ``build_story_context``."""

    def test_fast_label_passes_through_to_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A ``fast`` label on an impl story derives ``StoryContext.mode=fast``.

        This is the genuine derivation path (FK-24 §24.3.3) feeding the
        SEPARATE fast axis — execution_route stays a normal path value.
        """
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("fast",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type is StoryType.IMPLEMENTATION
        assert ctx.mode is WireStoryMode.FAST

    def test_default_mode_is_standard(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=()),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.mode is WireStoryMode.STANDARD

    def test_bug_label_produces_bugfix_type(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Label ``"bug"`` results in StoryType.BUGFIX."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("bug",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.BUGFIX
        assert ctx.implementation_contract is None

    def test_concept_label_produces_concept_type(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Label ``"concept"`` results in StoryType.CONCEPT."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("concept",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.CONCEPT
        assert ctx.implementation_contract is None

    def test_research_label_produces_research_type(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Label ``"research"`` results in StoryType.RESEARCH."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("research",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.RESEARCH
        assert ctx.implementation_contract is None

    def test_no_label_defaults_to_implementation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """No recognised label defaults to IMPLEMENTATION."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("enhancement",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.IMPLEMENTATION
        assert ctx.implementation_contract == ImplementationContract.STANDARD

    def test_story_id_generated_from_issue_nr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """story_id is derived as ``"STORY-{issue_nr}"`` when not provided."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(number=42),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_id == "STORY-42"

    def test_explicit_story_id_is_used(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Explicit story_id overrides the auto-generated one."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(),
        )
        ctx = build_story_context(
            "owner",
            "repo",
            42,
            tmp_path,
            "test-project",
            story_id="CUSTOM-99",
        )
        assert ctx.story_id == "CUSTOM-99"

    def test_context_fields_are_populated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """All key StoryContext fields are correctly populated."""
        issue = _make_issue(
            number=42,
            title="Add widget feature",
            labels=("bug", "priority:high"),
        )
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: issue,
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")

        assert ctx.issue_nr == 42
        assert ctx.title == "Add widget feature"
        assert ctx.project_root == tmp_path
        assert "repo" in ctx.participating_repos
        assert "bug" in ctx.labels
        assert "priority:high" in ctx.labels
        assert ctx.created_at is not None

    def test_mode_from_profile_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Mode is set from the story type profile's default_mode."""
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("concept",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        # Concept profile's default mode is None (no execution_route)
        assert ctx.execution_route is None


class TestBuildInternalStoryContext:
    """AG3-054 PART B (#2): an internal story builds its context WITHOUT GitHub."""

    def test_internal_context_does_not_call_get_issue(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An internal story context is built from StoryService -- never GitHub.

        ``get_issue`` is patched to RAISE: if the internal path touched GitHub at
        all the test would fail. It must build the context purely from the
        authoritative ``StoryService`` record.
        """

        def _explode(owner: str, repo: str, nr: int) -> object:
            del owner, repo, nr
            raise AssertionError("get_issue must NOT be called for an internal story")

        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            _explode,
        )
        service = _FakeStoryServiceWithRecord(_internal_story())

        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-200",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.story_type is StoryType.CONCEPT
        assert ctx.title == "Refine the domain concept"
        assert ctx.project_root == tmp_path
        assert ctx.issue_nr is None
        assert ctx.mode is WireStoryMode.STANDARD

    def test_internal_context_unknown_story_fails_closed(
        self,
        tmp_path: Path,
    ) -> None:
        """A wired service that does not know the story fails closed (no fabrication)."""
        service = _FakeStoryServiceWithRecord(None)
        with pytest.raises(StoryModeResolutionError):
            build_internal_story_context(
                tmp_path,
                "test-project",
                "AG3-404",
                story_service=service,  # type: ignore[arg-type]
            )

    def test_internal_context_standalone_builds_minimal_concept(
        self,
        tmp_path: Path,
    ) -> None:
        """No wired service (standalone) builds a minimal CONCEPT context, no GitHub."""
        ctx = build_internal_story_context(tmp_path, "test-project", "AG3-201", story_service=None)
        assert ctx.story_type is StoryType.CONCEPT
        assert ctx.project_root == tmp_path
        assert ctx.issue_nr is None


# ---------------------------------------------------------------------------
# ERROR-4: Tests for real build-path contract — StorySpec refs in run context
# ---------------------------------------------------------------------------


def _impl_story(
    *,
    story_display_id: str = "AG3-300",
    change_impact: ChangeImpact = ChangeImpact.LOCAL,
    concept_quality: ConceptQuality = ConceptQuality.HIGH,
    new_structures: bool = False,
    vectordb_conflict_resolved: bool = False,
) -> Story:
    """Build an implementation-type Story for contract tests."""
    return Story(
        project_key="test-project",
        story_number=300,
        story_display_id=story_display_id,
        title="Implementation story",
        story_type=WireStoryType.IMPLEMENTATION,
        participating_repos=["repo"],
        labels=["implementation"],
        change_impact=change_impact,
        concept_quality=concept_quality,
        new_structures=new_structures,
        vectordb_conflict_resolved=vectordb_conflict_resolved,
    )


class _FakeStoryServiceWithSpec:
    """Minimal StoryService stub that returns a Story with an optional spec.

    Used to test the real build-path contract: spec.concept_refs in StoryContext.
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

    def get_story_detail(self, story_display_id: str) -> tuple[Story, StorySpecification | None] | None:
        del story_display_id
        if self._story is None:
            return None
        return self._story, self._spec


class TestConceptRefsProjection:
    """ERROR-4: Real build-path contract for StorySpecification.concept_refs.

    Valid refs must NOT fire Trigger 1; absent refs must fail closed.
    """

    def test_internal_path_valid_concept_refs_do_not_fire_trigger_1(self, tmp_path: Path) -> None:
        """build_internal_story_context: valid spec.concept_refs are populated
        → Trigger 1 does NOT fire → execution_route is EXECUTION (AC8).

        This proves the projection is actually wired: a story that would route to
        Exploration via Trigger 1 (no concept paths) instead routes to Execution
        when the spec carries valid refs.
        """
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# Real concept doc", encoding="utf-8")

        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=spec,
        )
        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-300",
            story_service=service,  # type: ignore[arg-type]
        )

        # All triggers neutral + valid concept_refs → Execution.
        assert ctx.execution_route is StoryMode.EXECUTION
        # concept_refs is populated with the spec ref.
        assert str(concept_file) in ctx.concept_refs

    def test_internal_path_absent_concept_refs_fires_trigger_1(self, tmp_path: Path) -> None:
        """build_internal_story_context: absent spec.concept_refs yields empty refs
        → Trigger 1 fires → execution_route is EXPLORATION (fail-closed, AC8).

        This proves fail-closed behavior: a story with no concept refs in its
        spec routes to Exploration via Trigger 1.
        """
        # Spec with no concept_refs (genuinely absent, not a stub shortcut).
        spec = StorySpecification(need=None, solution=None, acceptance=[], concept_refs=None)
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=spec,
        )
        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-301",
            story_service=service,  # type: ignore[arg-type]
        )

        # No concept_refs → concept_refs=() → Trigger 1 fires → Exploration.
        assert ctx.execution_route is StoryMode.EXPLORATION
        assert ctx.concept_refs == ()

    def test_internal_path_no_spec_fires_trigger_1(self, tmp_path: Path) -> None:
        """build_internal_story_context: spec=None yields empty refs
        → Trigger 1 fires → execution_route is EXPLORATION (fail-closed).
        """
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=None,
        )
        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-302",
            story_service=service,  # type: ignore[arg-type]
        )

        # No spec → concept_refs=() → Trigger 1 fires → Exploration.
        assert ctx.execution_route is StoryMode.EXPLORATION
        assert ctx.concept_refs == ()

    def test_internal_path_vectordb_conflict_projects_and_forces_exploration(self, tmp_path: Path) -> None:
        """AG3-068 (FK-21 §21.12): build_internal_story_context projects the
        authoritative ``vectordb_conflict_resolved`` flag into the StoryContext,
        and a resolved conflict forces Exploration even when all OTHER triggers
        are neutral (Trigger 1 satisfied via valid concept_refs).

        This proves the projection is actually wired through the real build path:
        the ONLY difference from the Execution baseline below is the flag.
        """
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# Real concept doc", encoding="utf-8")
        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
                vectordb_conflict_resolved=True,
            ),
            spec=spec,
        )
        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-303",
            story_service=service,  # type: ignore[arg-type]
        )

        # The flag is projected onto the authoritative StoryContext...
        assert ctx.vectordb_conflict_resolved is True
        # ...and forces Exploration despite all other triggers being neutral.
        assert ctx.execution_route is StoryMode.EXPLORATION

    def test_internal_path_no_vectordb_conflict_allows_execution(self, tmp_path: Path) -> None:
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
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
                vectordb_conflict_resolved=False,
            ),
            spec=spec,
        )
        ctx = build_internal_story_context(
            tmp_path,
            "test-project",
            "AG3-304",
            story_service=service,  # type: ignore[arg-type]
        )

        assert ctx.vectordb_conflict_resolved is False
        assert ctx.execution_route is StoryMode.EXECUTION

    def test_github_path_no_service_fires_trigger_1(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """build_story_context without story_service: concept_refs=() (fail-closed).

        No StoryService → no spec available → concept_refs stays empty →
        Trigger 1 fires for implementing story types.
        """
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("implementation",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project", story_service=None)
        # No service → no concept_refs → Trigger 1 → Exploration.
        assert ctx.execution_route is StoryMode.EXPLORATION
        assert ctx.concept_refs == ()

    def test_github_path_with_service_and_valid_concept_refs_do_not_fire_trigger_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """build_story_context with service + valid spec.concept_refs → EXECUTION.

        This proves the GitHub build path also reads concept_refs via
        _resolve_trigger_inputs.
        """
        concept_file = tmp_path / "doc.md"
        concept_file.write_text("# Concept doc", encoding="utf-8")

        spec = StorySpecification(
            need=None,
            solution=None,
            acceptance=[],
            concept_refs=[str(concept_file)],
        )
        service = _FakeStoryServiceWithSpec(
            _impl_story(
                story_display_id="STORY-42",
                change_impact=ChangeImpact.LOCAL,
                concept_quality=ConceptQuality.HIGH,
                new_structures=False,
            ),
            spec=spec,
        )
        monkeypatch.setattr(
            "agentkit.backend.governance.setup_preflight_gate.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(number=42, labels=()),
        )
        ctx = build_story_context(
            "owner",
            "repo",
            42,
            tmp_path,
            "test-project",
            story_id="STORY-42",
            story_service=service,  # type: ignore[arg-type]
        )
        # Valid concept_refs wired through service → Trigger 1 does NOT fire → Execution.
        assert ctx.execution_route is StoryMode.EXECUTION
        assert str(concept_file) in ctx.concept_refs


class TestNewStructuresPersistenceRoundTrip:
    """ERROR-4: new_structures field round-trips through service create and idempotency.

    Reproducing test for ERROR-2: StoryService.create_story must persist
    new_structures=True into the Story record; idempotency body must include it
    so a replay with a different value raises IdempotencyMismatchError.
    """

    def test_create_story_persists_new_structures_true(self) -> None:
        """create_story with new_structures=True stores the flag on the Story record."""
        from agentkit.backend.project_management.entities import Project, ProjectConfiguration
        from agentkit.backend.story_context_manager.idempotency import (
            InMemoryIdempotencyKeyRepository,
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
            idempotency_repository=InMemoryIdempotencyKeyRepository(),
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
        """new_structures is part of the idempotency body; a mismatch raises an error.

        This is the direct reproducing test for ERROR-2: creating the same op_id
        with a different new_structures value must raise IdempotencyMismatchError.
        """
        from agentkit.backend.project_management.entities import Project, ProjectConfiguration
        from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError
        from agentkit.backend.story_context_manager.idempotency import (
            InMemoryIdempotencyKeyRepository,
        )
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
            idempotency_repository=InMemoryIdempotencyKeyRepository(),
            event_emitter=lambda *a: None,
        )

        # First create with new_structures=False.
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
        # Second call with same op_id but different new_structures → mismatch.
        with pytest.raises(IdempotencyMismatchError):
            svc.create_story(
                CreateStoryInput(
                    project_key="ak3",
                    title="Same story",
                    story_type=WireStoryType.IMPLEMENTATION,
                    repos=["ak3"],
                    new_structures=True,  # different!
                ),
                op_id="op-idem-ns-001",
            )
