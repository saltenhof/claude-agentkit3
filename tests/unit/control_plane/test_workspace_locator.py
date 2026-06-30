"""Unit tests for the Backend story-workspace locator (AG3-123).

Pins the resolver contract: the FS anchor is resolved from canonical level-1
state (``project_registry``), NOT ``ctx.project_root`` / ``cwd`` / request data,
and an unresolvable workspace fails closed with the typed
:class:`StoryWorkspaceUnresolvedError` (FK-10 §10.6 / I3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.workspace_locator import (
    StateBackendStoryWorkspaceLocator,
    StoryWorkspace,
    StoryWorkspaceLocator,
    StoryWorkspaceUnresolvedError,
)
from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile


@dataclass(frozen=True)
class _RawRegistration:
    """A registry stand-in carrying a raw (possibly relative) ``project_root``.

    The :class:`ProjectRegistration` model now FORBIDS a relative ``project_root``
    (the registration boundary), so the locator's own defensive fail-closed check
    must be exercised against a raw stand-in rather than a real registration.
    """

    project_root: Path


def _registration(project_root: Path) -> ProjectRegistration:
    return ProjectRegistration(
        project_key="acme",
        project_root=project_root,
        github_owner="acme",
        github_repo="demo",
        runtime_profile=RuntimeProfile.CORE,
        config_version="3.0",
        config_digest="deadbeef",
        registered_at=datetime.now(tz=UTC),
    )


class _FakeRegistrationLookup:
    """A level-1 ``project_registry`` lookup fake (registered project_keys only)."""

    def __init__(self, registrations: dict[str, ProjectRegistration]) -> None:
        self._registrations = registrations

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self._registrations.get(project_key)


class _DecodeFailingRegistrationLookup:
    """A lookup whose row decode RAISES (a malformed/relative pre-existing row).

    Mirrors the productive repository, which decodes a ``project_registry`` row
    THROUGH the :class:`ProjectRegistration` model. A legacy/corrupt row with a
    relative ``project_root`` makes that decode raise a pydantic
    :class:`ValidationError` from inside the lookup -- the failure mode the locator
    must convert to a typed :class:`StoryWorkspaceUnresolvedError` (AG3-123 r2).
    """

    def get(self, project_key: str) -> ProjectRegistration:
        # Reproduce the real repository decode of a relative-root row: building the
        # model raises ValidationError (the model-floor rejects the relative root).
        return ProjectRegistration(
            project_key=project_key,
            project_root=Path("relative/legacy/root"),
            github_owner="acme",
            github_repo="demo",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            config_digest="deadbeef",
            registered_at=datetime.now(tz=UTC),
        )


class TestStateBackendStoryWorkspaceLocator:
    def test_resolves_anchor_from_project_registry(self, tmp_path: Path) -> None:
        """Happy path: the anchor is the registry ``project_root`` + story layout."""
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_FakeRegistrationLookup(
                {"acme": _registration(tmp_path)}
            )
        )

        workspace = locator.resolve("acme", "AG3-700", "run-1")

        assert isinstance(workspace, StoryWorkspace)
        assert workspace.project_root == tmp_path
        assert workspace.story_dir == tmp_path / "stories" / "AG3-700"
        assert workspace.run_id == "run-1"

    def test_unregistered_project_fails_closed(self) -> None:
        """Fail-closed: no registry entry -> typed StoryWorkspaceUnresolvedError."""
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_FakeRegistrationLookup({})
        )

        with pytest.raises(StoryWorkspaceUnresolvedError) as exc_info:
            locator.resolve("ghost", "AG3-700", "run-1")

        assert exc_info.value.detail == {
            "project_key": "ghost",
            "story_id": "AG3-700",
            "run_id": "run-1",
        }

    def test_relative_registry_root_fails_closed(self) -> None:
        """Fail-closed: a RELATIVE registry root never resolves (cwd-fallback leak).

        A relative ``project_root`` would make ``story_dir`` resolve against the
        backend process cwd -- exactly the dev-local fallback AG3-123 forbids -- so
        the locator MUST reject it with the typed StoryWorkspaceUnresolvedError.
        """
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_FakeRegistrationLookup(
                {"acme": _RawRegistration(Path("relative/project"))}  # type: ignore[dict-item]
            )
        )

        with pytest.raises(StoryWorkspaceUnresolvedError) as exc_info:
            locator.resolve("acme", "AG3-700", "run-1")

        assert "RELATIVE" in str(exc_info.value)
        assert exc_info.value.detail["project_root"] == str(  # type: ignore[index]
            Path("relative/project")
        )

    def test_row_decode_failure_converts_to_unresolved_error(self) -> None:
        """Fail-closed: a row that fails to DECODE never escapes as ValidationError.

        AG3-123 r2 (MAJOR 2): the productive repository decodes the row through the
        ``ProjectRegistration`` model, whose model-floor rejects a relative root --
        so a legacy/corrupt row raises a pydantic ``ValidationError`` from inside
        the lookup. The dispatcher only normalizes ``PipelineError``, so an escaping
        ``ValidationError`` would be a fail-OPEN crash. The locator MUST convert it
        to the typed :class:`StoryWorkspaceUnresolvedError` (a ``PipelineError``).
        """
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_DecodeFailingRegistrationLookup()
        )

        with pytest.raises(StoryWorkspaceUnresolvedError) as exc_info:
            locator.resolve("acme", "AG3-700", "run-1")

        # Not the raw ValidationError -- a typed, structured fail-closed rejection.
        assert not isinstance(exc_info.value, ValidationError)
        detail = exc_info.value.detail
        assert detail is not None
        assert detail["project_key"] == "acme"  # type: ignore[index]
        assert "decode_error" in detail
        # The pydantic decode failure is preserved as the cause (not swallowed).
        assert isinstance(exc_info.value.__cause__, ValidationError)

    def test_absent_registry_root_fails_closed(self, tmp_path: Path) -> None:
        """Fail-closed: an absolute-but-NONEXISTENT root fails at the locator.

        A stale/absent canonical anchor must surface as a typed
        StoryWorkspaceUnresolvedError at the locator, not proceed past it only to
        fail later as an opaque config/git error.
        """
        missing_root = tmp_path / "does-not-exist"
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_FakeRegistrationLookup(
                {"acme": _registration(missing_root)}
            )
        )

        with pytest.raises(StoryWorkspaceUnresolvedError) as exc_info:
            locator.resolve("acme", "AG3-700", "run-1")

        assert "does not exist" in str(exc_info.value)

    def test_registration_model_rejects_relative_root(self) -> None:
        """Registration boundary: a relative ``project_root`` cannot be persisted.

        The model-side floor (AG3-123) makes it IMPOSSIBLE to construct -- and thus
        to persist into ``project_registry`` -- a relative canonical anchor.
        """
        with pytest.raises(ValidationError, match="ABSOLUTE"):
            _registration(Path("relative/project"))

    def test_is_a_story_workspace_locator(self, tmp_path: Path) -> None:
        """The default impl satisfies the runtime-checkable port Protocol."""
        locator = StateBackendStoryWorkspaceLocator(
            registration_lookup=_FakeRegistrationLookup(
                {"acme": _registration(tmp_path)}
            )
        )
        assert isinstance(locator, StoryWorkspaceLocator)
