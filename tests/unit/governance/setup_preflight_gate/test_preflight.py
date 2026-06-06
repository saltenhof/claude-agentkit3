"""Unit tests for the ten setup preflight checks (FK-22 §22.3.1, AG3-034).

Tests use a stub StoryService (duck typing) and ``tmp_path`` fixtures for the
filesystem checks — no mock filesystem (story.md §8).  Each of the ten checks
has a happy-path and a fail-path test; the aggregate test proves all ten run
even after an early failure (FK-22 §22.3.2, AK1) and that exceptions become
fail-closed FAILs (AK4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightContext,
    PreflightStatus,
    run_preflight,
)
from agentkit.state_backend.store.mode_lock_repository import ModeLockRecord
from agentkit.story_context_manager.story_model import (
    StoryStatus,
    WireStoryMode,
    WireStoryType,
)

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


class _StubStory:
    """Minimal Story stub for preflight tests."""

    def __init__(
        self,
        *,
        story_display_id: str = "AK3-1",
        title: str = "Test story",
        status: StoryStatus = StoryStatus.APPROVED,
        story_type: WireStoryType = WireStoryType.IMPLEMENTATION,
        size: object | None = None,
        mode: WireStoryMode | None = None,
        participating_repos: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> None:
        from agentkit.core_types import StorySize

        self.story_display_id = story_display_id
        self.title = title
        self.status = status
        self.story_type = story_type
        self.size = size if size is not None else StorySize.M
        self.mode = mode
        # Honor an explicit empty list (no-repos fail case); only default when None.
        self.participating_repos = (
            ["repo-a"] if participating_repos is None else participating_repos
        )
        self.dependencies = dependencies or []


class _StubService:
    """Duck-typed StoryService stub resolving lookups + listing from a dict."""

    def __init__(self, stories: dict[str, _StubStory]) -> None:
        self._stories = stories

    def get_story(self, story_display_id: str) -> _StubStory | None:
        return self._stories.get(story_display_id)

    def list_stories(self, project_key: str) -> list[_StubStory]:
        _ = project_key
        return list(self._stories.values())


def _ctx(
    service: _StubService,
    *,
    story_id: str = "AK3-1",
    project_root: Path | None = None,
    mode_lock: ModeLockRecord | None = None,
    **probe_overrides: object,
) -> PreflightContext:
    """Build a PreflightContext with the story pre-resolved (Check 1)."""
    return PreflightContext(
        story_display_id=story_id,
        project_key="proj",
        project_root=project_root or Path.cwd(),
        service=service,  # type: ignore[arg-type]
        story=service.get_story(story_id),
        mode_lock=mode_lock,
        **probe_overrides,  # type: ignore[arg-type]
    )


def _result_of(check_id: PreflightCheckId, ctx: PreflightContext):  # type: ignore[no-untyped-def]
    result = run_preflight("", _service_of(ctx), context=ctx)
    return next(c for c in result.checks if c.check_id is check_id)


def _service_of(ctx: PreflightContext) -> _StubService:
    return ctx.service  # type: ignore[return-value]


def _approved_service(story_id: str = "AK3-1", **kwargs: object) -> _StubService:
    kwargs.setdefault("status", StoryStatus.APPROVED)
    story = _StubStory(story_display_id=story_id, **kwargs)  # type: ignore[arg-type]
    return _StubService({story_id: story})


# ---------------------------------------------------------------------------
# Check 1: story_exists
# ---------------------------------------------------------------------------


class TestStoryExists:
    def test_pass(self) -> None:
        chk = _result_of(PreflightCheckId.STORY_EXISTS, _ctx(_approved_service()))
        assert chk.status is PreflightStatus.PASS

    def test_fail_has_cleanup_hint(self) -> None:
        ctx = _ctx(_StubService({}), story_id="AK3-99")
        chk = _result_of(PreflightCheckId.STORY_EXISTS, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None
        assert "AK3-99" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Check 2: story_attributes_consistent
# ---------------------------------------------------------------------------


class TestStoryAttributesConsistent:
    def test_pass(self) -> None:
        chk = _result_of(
            PreflightCheckId.STORY_ATTRIBUTES_CONSISTENT, _ctx(_approved_service())
        )
        assert chk.status is PreflightStatus.PASS

    def test_fail_no_repos(self) -> None:
        svc = _approved_service(participating_repos=[])
        chk = _result_of(PreflightCheckId.STORY_ATTRIBUTES_CONSISTENT, _ctx(svc))
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None


# ---------------------------------------------------------------------------
# Check 3: status_approved
# ---------------------------------------------------------------------------


class TestStatusApproved:
    def test_pass(self) -> None:
        chk = _result_of(PreflightCheckId.STATUS_APPROVED, _ctx(_approved_service()))
        assert chk.status is PreflightStatus.PASS

    def test_fail_backlog(self) -> None:
        svc = _approved_service(status=StoryStatus.BACKLOG)
        chk = _result_of(PreflightCheckId.STATUS_APPROVED, _ctx(svc))
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None
        assert "Backlog" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Check 4: dependencies_done
# ---------------------------------------------------------------------------


class TestDependenciesDone:
    def test_pass_no_deps(self) -> None:
        chk = _result_of(PreflightCheckId.DEPENDENCIES_DONE, _ctx(_approved_service()))
        assert chk.status is PreflightStatus.PASS

    def test_fail_open_dep(self) -> None:
        dep = _StubStory(story_display_id="AK3-2", status=StoryStatus.IN_PROGRESS)
        main = _StubStory(story_display_id="AK3-1", dependencies=["AK3-2"])
        svc = _StubService({"AK3-1": main, "AK3-2": dep})
        chk = _result_of(PreflightCheckId.DEPENDENCIES_DONE, _ctx(svc))
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None
        assert "AK3-2" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Check 5: no_execution_artifacts
# ---------------------------------------------------------------------------


class TestNoExecutionArtifacts:
    def test_pass_clean(self, tmp_path: Path) -> None:
        ctx = _ctx(_approved_service(), project_root=tmp_path)
        chk = _result_of(PreflightCheckId.NO_EXECUTION_ARTIFACTS, ctx)
        assert chk.status is PreflightStatus.PASS

    def test_fail_residue(self, tmp_path: Path) -> None:
        residue = tmp_path / "_temp" / "stories" / "AK3-1"
        residue.mkdir(parents=True)
        (residue / "worker-manifest.json").write_text("{}", encoding="utf-8")
        ctx = _ctx(_approved_service(), project_root=tmp_path)
        chk = _result_of(PreflightCheckId.NO_EXECUTION_ARTIFACTS, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None


# ---------------------------------------------------------------------------
# Check 6: no_active_runtime_residue
# ---------------------------------------------------------------------------


class TestNoActiveRuntimeResidue:
    def test_pass(self, tmp_path: Path) -> None:
        ctx = _ctx(
            _approved_service(),
            project_root=tmp_path,
            active_runtime_residue=lambda _root, _sid: False,
        )
        chk = _result_of(PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE, ctx)
        assert chk.status is PreflightStatus.PASS

    def test_fail(self, tmp_path: Path) -> None:
        ctx = _ctx(
            _approved_service(),
            project_root=tmp_path,
            active_runtime_residue=lambda _root, _sid: True,
        )
        chk = _result_of(PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None

    def test_default_probe_fails_closed_when_unwired(self, tmp_path: Path) -> None:
        # Finding B: no injected probe -> the default raises -> AK4 fail-closed
        # FAIL (never a silent optimistic PASS).
        ctx = _ctx(_approved_service(), project_root=tmp_path)
        chk = _result_of(PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.detail is not None
        assert chk.detail.startswith("exception: RuntimeError")


# ---------------------------------------------------------------------------
# Check 7: no_story_branch
# ---------------------------------------------------------------------------


class TestNoStoryBranch:
    def test_pass(self) -> None:
        ctx = _ctx(_approved_service(), branch_exists=lambda _root, _sid: False)
        chk = _result_of(PreflightCheckId.NO_STORY_BRANCH, ctx)
        assert chk.status is PreflightStatus.PASS

    def test_fail(self) -> None:
        ctx = _ctx(_approved_service(), branch_exists=lambda _root, _sid: True)
        chk = _result_of(PreflightCheckId.NO_STORY_BRANCH, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None
        assert "story/AK3-1" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Check 8: no_stale_worktree
# ---------------------------------------------------------------------------


class TestNoStaleWorktree:
    def test_pass_clean(self, tmp_path: Path) -> None:
        ctx = _ctx(_approved_service(), project_root=tmp_path)
        chk = _result_of(PreflightCheckId.NO_STALE_WORKTREE, ctx)
        assert chk.status is PreflightStatus.PASS

    def test_fail_stale(self, tmp_path: Path) -> None:
        (tmp_path / "_worktrees" / "AK3-1").mkdir(parents=True)
        ctx = _ctx(_approved_service(), project_root=tmp_path)
        chk = _result_of(PreflightCheckId.NO_STALE_WORKTREE, ctx)
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None


# ---------------------------------------------------------------------------
# Check 9: no_scope_overlap
# ---------------------------------------------------------------------------


class TestNoScopeOverlap:
    def test_pass_no_overlap(self) -> None:
        main = _StubStory(story_display_id="AK3-1", participating_repos=["repo-a"])
        other = _StubStory(
            story_display_id="AK3-2",
            status=StoryStatus.IN_PROGRESS,
            participating_repos=["repo-b"],
        )
        svc = _StubService({"AK3-1": main, "AK3-2": other})
        chk = _result_of(PreflightCheckId.NO_SCOPE_OVERLAP, _ctx(svc))
        assert chk.status is PreflightStatus.PASS

    def test_fail_overlap(self) -> None:
        main = _StubStory(story_display_id="AK3-1", participating_repos=["repo-a"])
        other = _StubStory(
            story_display_id="AK3-2",
            status=StoryStatus.IN_PROGRESS,
            participating_repos=["repo-a"],
        )
        svc = _StubService({"AK3-1": main, "AK3-2": other})
        chk = _result_of(PreflightCheckId.NO_SCOPE_OVERLAP, _ctx(svc))
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None
        assert "AK3-2" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Check 10: no_competing_story_mode_active
# ---------------------------------------------------------------------------


class TestNoCompetingStoryModeActive:
    def test_pass_idle_lock(self) -> None:
        chk = _result_of(
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
            _ctx(_approved_service(), mode_lock=None),
        )
        assert chk.status is PreflightStatus.PASS

    def test_pass_same_route(self) -> None:
        # Standard story, lock holds standard (decoupled mode axis) -> compatible.
        lock = ModeLockRecord(
            project_key="proj",
            active_mode="standard",
            holder_count=1,
            updated_at="2026-06-01T00:00:00Z",
        )
        chk = _result_of(
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
            _ctx(_approved_service(), mode_lock=lock),
        )
        assert chk.status is PreflightStatus.PASS

    def test_fail_competing_fast(self) -> None:
        # Standard story (mode=None), lock holds fast with a holder -> FAIL.
        lock = ModeLockRecord(
            project_key="proj",
            active_mode="fast",
            holder_count=2,
            updated_at="2026-06-01T00:00:00Z",
        )
        chk = _result_of(
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
            _ctx(_approved_service(), mode_lock=lock),
        )
        assert chk.status is PreflightStatus.FAIL
        assert chk.cleanup_hint is not None

    def test_read_error_fails_closed_not_idle(self) -> None:
        # E-E: a mode-lock READ error must fail closed (Check 10 FAIL via the
        # fail-closed reader), NEVER be masked as an idle lock that hides a real
        # mode conflict.
        def _boom_reader(_project_key: str) -> ModeLockRecord | None:
            raise RuntimeError("mode-lock backend unreachable")

        chk = _result_of(
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
            _ctx(_approved_service(), mode_lock_reader=_boom_reader),
        )
        assert chk.status is PreflightStatus.FAIL
        assert "exception" in (chk.detail or "")


# ---------------------------------------------------------------------------
# Aggregate: all ten run, fail-closed, exceptions -> FAIL (AK1, AK4)
# ---------------------------------------------------------------------------


class TestPreflightResultAggregate:
    def test_all_ten_checks_run_on_happy_path(self, tmp_path: Path) -> None:
        # Wire benign run-aware probes (Finding B): the standalone git/state
        # defaults fail closed on a non-repo tmp_path, so the orchestrator-path
        # probes are injected here (the documented run-aware seam).
        ctx = _ctx(
            _approved_service(),
            project_root=tmp_path,
            branch_exists=lambda _root, _sid: False,
            active_runtime_residue=lambda _root, _sid: False,
        )
        result = run_preflight("AK3-1", _approved_service(), context=ctx)  # type: ignore[arg-type]
        assert len(result.checks) == 10
        assert result.overall is PreflightStatus.PASS
        assert result.passed is True
        assert {c.check_id for c in result.checks} == set(PreflightCheckId)

    def test_branch_default_probe_fails_closed_on_non_repo(
        self, tmp_path: Path
    ) -> None:
        # Finding B: with NO injected branch probe the real git default runs;
        # on a non-repo tmp_path it raises and the check fails closed (AK4),
        # never silently passing.
        result = run_preflight(
            "AK3-1",
            _approved_service(),  # type: ignore[arg-type]
            project_key="proj",
            project_root=tmp_path,
        )
        branch = next(
            c for c in result.checks if c.check_id is PreflightCheckId.NO_STORY_BRANCH
        )
        assert branch.status is PreflightStatus.FAIL
        assert branch.cleanup_hint is not None
        assert result.overall is PreflightStatus.FAIL

    def test_all_ten_run_even_when_story_missing(self, tmp_path: Path) -> None:
        ctx = _ctx(
            _StubService({}),
            story_id="AK3-99",
            project_root=tmp_path,
            branch_exists=lambda _root, _sid: False,
            active_runtime_residue=lambda _root, _sid: False,
        )
        result = run_preflight("AK3-99", _StubService({}), context=ctx)  # type: ignore[arg-type]
        assert len(result.checks) == 10
        assert result.overall is PreflightStatus.FAIL
        # story_exists, status_approved, dependencies, attributes, scope all fail.
        assert PreflightCheckId.STORY_EXISTS in result.failed_check_ids

    def test_failed_check_ids_match_failures(self, tmp_path: Path) -> None:
        ctx = _ctx(
            _approved_service(status=StoryStatus.BACKLOG),
            project_root=tmp_path,
            branch_exists=lambda _root, _sid: False,
            active_runtime_residue=lambda _root, _sid: False,
        )
        result = run_preflight("AK3-1", _approved_service(), context=ctx)  # type: ignore[arg-type]
        assert PreflightCheckId.STATUS_APPROVED in result.failed_check_ids
        assert result.failed_check_ids == tuple(
            c.check_id for c in result.checks if c.status is PreflightStatus.FAIL
        )

    def test_fast_story_runs_only_the_four_minimum_checks(
        self, tmp_path: Path
    ) -> None:
        """FIX-5 (FK-24 §24.3.4): a fast story runs ONLY the four minimum checks.

        story_exists, no active run, no stale worktree, mode-conflict §24.3.3;
        status/dependencies/scope-overlap are OUT for fast. The mode is read from
        the AUTHORITATIVE resolved story record (FIX-1), not labels.
        """
        svc = _approved_service(mode=WireStoryMode.FAST)
        ctx = _ctx(
            svc,
            project_root=tmp_path,
            active_runtime_residue=lambda _root, _sid: False,
        )
        result = run_preflight("AK3-1", svc, context=ctx)  # type: ignore[arg-type]
        assert {c.check_id for c in result.checks} == {
            PreflightCheckId.STORY_EXISTS,
            PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE,
            PreflightCheckId.NO_STALE_WORKTREE,
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
        }
        assert len(result.checks) == 4
        # The OUT-for-fast checks are not even run (no FAIL leaks from them).
        ran = {c.check_id for c in result.checks}
        assert PreflightCheckId.NO_SCOPE_OVERLAP not in ran
        assert PreflightCheckId.STATUS_APPROVED not in ran
        assert PreflightCheckId.DEPENDENCIES_DONE not in ran
        assert result.overall is PreflightStatus.PASS

    def test_fast_story_skips_scope_overlap_even_when_it_would_fail(
        self, tmp_path: Path
    ) -> None:
        """FIX-5: scope-overlap is OUT for fast even when a standard story fails it.

        A fast story whose repos overlap an active story must still PASS preflight
        (the scope-overlap check is not in the fast minimum set).
        """
        active = _StubStory(
            story_display_id="AK3-2",
            status=StoryStatus.IN_PROGRESS,
            participating_repos=["repo-a"],
        )
        fast = _StubStory(
            story_display_id="AK3-1",
            status=StoryStatus.APPROVED,
            mode=WireStoryMode.FAST,
            participating_repos=["repo-a"],
        )
        svc = _StubService({"AK3-1": fast, "AK3-2": active})
        ctx = _ctx(
            svc,
            project_root=tmp_path,
            active_runtime_residue=lambda _root, _sid: False,
        )
        result = run_preflight("AK3-1", svc, context=ctx)  # type: ignore[arg-type]
        assert result.overall is PreflightStatus.PASS
        assert PreflightCheckId.NO_SCOPE_OVERLAP not in {
            c.check_id for c in result.checks
        }

    def test_exception_in_check_becomes_failclosed_fail(self, tmp_path: Path) -> None:
        def _boom(_root: Path, _sid: str) -> bool:
            raise RuntimeError("probe blew up")

        ctx = _ctx(
            _approved_service(),
            project_root=tmp_path,
            active_runtime_residue=_boom,
        )
        result = run_preflight("AK3-1", _approved_service(), context=ctx)  # type: ignore[arg-type]
        residue = next(
            c
            for c in result.checks
            if c.check_id is PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE
        )
        assert residue.status is PreflightStatus.FAIL
        assert residue.detail is not None
        assert residue.detail.startswith("exception: RuntimeError")
        assert residue.cleanup_hint is not None
        # Still ten checks: no check silently skipped.
        assert len(result.checks) == 10


def test_models_are_frozen() -> None:
    chk = _result_of(PreflightCheckId.STORY_EXISTS, _ctx(_approved_service()))
    with pytest.raises((AttributeError, TypeError, ValueError)):
        chk.status = PreflightStatus.FAIL  # type: ignore[misc]
