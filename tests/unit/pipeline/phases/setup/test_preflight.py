"""Unit tests for setup phase preflight checks.

Tests use a stub StoryService (via duck typing) to avoid real DB or
GitHub CLI calls.  The new preflight checks are StoryService-based
(FK-22 §22.4.1), not GitHub-based.
"""

from __future__ import annotations

from agentkit.pipeline.phases.setup.preflight import PreflightCheck, PreflightResult, run_preflight
from agentkit.story_context_manager.story_model import (
    StoryStatus,
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
        dependencies: list[str] | None = None,
    ) -> None:
        self.story_display_id = story_display_id
        self.title = title
        self.status = status
        self.story_type = WireStoryType.IMPLEMENTATION
        self.dependencies = dependencies or []


class _StubService:
    """Duck-typed StoryService stub that resolves story lookups from a dict."""

    def __init__(self, stories: dict[str, _StubStory]) -> None:
        self._stories = stories

    def get_story(self, story_display_id: str) -> _StubStory | None:
        return self._stories.get(story_display_id)


def _approved_service(story_id: str = "AK3-1", **kwargs: object) -> _StubService:
    """Return a service containing one approved story with no dependencies."""
    story = _StubStory(story_display_id=story_id, status=StoryStatus.APPROVED, **kwargs)  # type: ignore[arg-type]
    return _StubService({story_id: story})


# ---------------------------------------------------------------------------
# story_exists check
# ---------------------------------------------------------------------------


class TestPreflightStoryExists:
    """Check 1: story_exists."""

    def test_passes_when_story_found(self) -> None:
        svc = _approved_service()
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        exists_check = next(c for c in result.checks if c.name == "story_exists")
        assert exists_check.passed is True

    def test_fails_when_story_not_found(self) -> None:
        svc = _StubService({})  # empty
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        exists_check = next(c for c in result.checks if c.name == "story_exists")
        assert exists_check.passed is False
        assert "AK3-99" in exists_check.message

    def test_story_attached_when_found(self) -> None:
        svc = _approved_service()
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        assert result.story is not None
        assert result.story.story_display_id == "AK3-1"

    def test_story_none_when_not_found(self) -> None:
        svc = _StubService({})
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        assert result.story is None


# ---------------------------------------------------------------------------
# status_approved check
# ---------------------------------------------------------------------------


class TestPreflightStatusApproved:
    """Check 2: status_approved."""

    def test_passes_when_approved(self) -> None:
        svc = _approved_service()
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        approved_check = next(c for c in result.checks if c.name == "status_approved")
        assert approved_check.passed is True

    def test_fails_when_backlog(self) -> None:
        story = _StubStory(status=StoryStatus.BACKLOG)
        svc = _StubService({"AK3-1": story})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        approved_check = next(c for c in result.checks if c.name == "status_approved")
        assert approved_check.passed is False
        assert "Backlog" in approved_check.message

    def test_fails_when_in_progress(self) -> None:
        story = _StubStory(status=StoryStatus.IN_PROGRESS)
        svc = _StubService({"AK3-1": story})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        approved_check = next(c for c in result.checks if c.name == "status_approved")
        assert approved_check.passed is False

    def test_fails_when_done(self) -> None:
        story = _StubStory(status=StoryStatus.DONE)
        svc = _StubService({"AK3-1": story})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        approved_check = next(c for c in result.checks if c.name == "status_approved")
        assert approved_check.passed is False

    def test_fails_when_story_not_fetched(self) -> None:
        svc = _StubService({})
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        approved_check = next(c for c in result.checks if c.name == "status_approved")
        assert approved_check.passed is False
        assert "Cannot check status" in approved_check.message


# ---------------------------------------------------------------------------
# dependencies_closed check
# ---------------------------------------------------------------------------


class TestPreflightDependenciesClosed:
    """Check 3: dependencies_closed."""

    def test_passes_when_no_dependencies(self) -> None:
        svc = _approved_service()
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        dep_check = next(c for c in result.checks if c.name == "dependencies_closed")
        assert dep_check.passed is True
        assert "No dependencies" in dep_check.message

    def test_passes_when_all_deps_done(self) -> None:
        dep1 = _StubStory(story_display_id="AK3-2", status=StoryStatus.DONE)
        dep2 = _StubStory(story_display_id="AK3-3", status=StoryStatus.DONE)
        main = _StubStory(story_display_id="AK3-1", dependencies=["AK3-2", "AK3-3"])
        svc = _StubService({"AK3-1": main, "AK3-2": dep1, "AK3-3": dep2})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        dep_check = next(c for c in result.checks if c.name == "dependencies_closed")
        assert dep_check.passed is True
        assert "2" in dep_check.message

    def test_fails_when_dep_not_done(self) -> None:
        dep = _StubStory(story_display_id="AK3-2", status=StoryStatus.IN_PROGRESS)
        main = _StubStory(story_display_id="AK3-1", dependencies=["AK3-2"])
        svc = _StubService({"AK3-1": main, "AK3-2": dep})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        dep_check = next(c for c in result.checks if c.name == "dependencies_closed")
        assert dep_check.passed is False
        assert "AK3-2" in dep_check.message

    def test_fails_when_dep_missing(self) -> None:
        main = _StubStory(story_display_id="AK3-1", dependencies=["AK3-99"])
        svc = _StubService({"AK3-1": main})  # dep not in service
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        dep_check = next(c for c in result.checks if c.name == "dependencies_closed")
        assert dep_check.passed is False
        assert "AK3-99" in dep_check.message
        assert "missing" in dep_check.message

    def test_fails_when_story_not_fetched(self) -> None:
        svc = _StubService({})
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        dep_check = next(c for c in result.checks if c.name == "dependencies_closed")
        assert dep_check.passed is False
        assert "Cannot check dependencies" in dep_check.message


# ---------------------------------------------------------------------------
# PreflightResult.passed aggregate
# ---------------------------------------------------------------------------


class TestPreflightResultPassed:
    """PreflightResult.passed reflects aggregate of all checks."""

    def test_passed_true_when_all_checks_pass(self) -> None:
        svc = _approved_service()
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        assert result.passed is True
        assert len(result.checks) == 3
        assert all(c.passed for c in result.checks)

    def test_passed_false_when_not_approved(self) -> None:
        story = _StubStory(status=StoryStatus.BACKLOG)
        svc = _StubService({"AK3-1": story})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        assert result.passed is False

    def test_passed_false_when_story_missing(self) -> None:
        svc = _StubService({})
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        assert result.passed is False
        assert len(result.checks) == 3  # all three checks run regardless

    def test_all_checks_run_even_when_story_missing(self) -> None:
        """All checks always run (fail-closed pattern)."""
        svc = _StubService({})
        result = run_preflight("AK3-99", svc)  # type: ignore[arg-type]

        check_names = {c.name for c in result.checks}
        assert check_names == {"story_exists", "status_approved", "dependencies_closed"}

    def test_single_open_dep_fails_result(self) -> None:
        dep = _StubStory(story_display_id="AK3-2", status=StoryStatus.BACKLOG)
        main = _StubStory(story_display_id="AK3-1", dependencies=["AK3-2"])
        svc = _StubService({"AK3-1": main, "AK3-2": dep})
        result = run_preflight("AK3-1", svc)  # type: ignore[arg-type]

        assert result.passed is False


# ---------------------------------------------------------------------------
# PreflightCheck and PreflightResult dataclass contracts
# ---------------------------------------------------------------------------


def test_preflight_check_is_frozen() -> None:
    check = PreflightCheck(name="story_exists", passed=True, message="ok")
    import pytest
    with pytest.raises((AttributeError, TypeError)):
        check.passed = False  # type: ignore[misc]


def test_preflight_result_is_frozen() -> None:
    result = PreflightResult(passed=True, checks=())
    import pytest
    with pytest.raises((AttributeError, TypeError)):
        result.passed = False  # type: ignore[misc]
