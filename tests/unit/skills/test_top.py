"""Unit tests for Skills top-surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Covers:
- bind_skill happy path (Claude Code + Codex harnesses)
- bind_skill Lifecycle transitions (BUNDLE_SELECTED -> BOUND -> VERIFIED)
- bind_skill fail-closed paths
- resolve_binding
- list_bound_skills
- collect_quality_metrics raises NotImplementedError
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from agentkit.skills.binding import (
    HarnessKind,
    SkillLifecycleStatus,
)
from agentkit.skills.bundle_store import SkillBundleStore
from agentkit.skills.errors import (
    SkillBindingFailedError,
    SkillBundleDigestMismatchError,
)
from agentkit.skills.repository import InMemorySkillBindingRepository
from agentkit.skills.top import Skills


def _symlinks_supported() -> bool:
    """Return True if the OS/process can create symlinks in tmp_path.

    On Windows without Developer Mode, symlink_to raises OSError [WinError 1314].
    Story §8: tests may skip; CI must support symlinks.
    """
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        link = Path(d) / "link"
        try:
            link.symlink_to(src)
            return True
        except OSError:
            return False


_SYMLINKS_AVAILABLE = _symlinks_supported()
_SKIP_SYMLINKS = pytest.mark.skipif(
    not _SYMLINKS_AVAILABLE,
    reason=(
        "Symlinks not supported without Developer Mode on Windows "
        "(Story §8: CI must support symlinks; local dev may skip)"
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skills() -> Skills:
    return Skills(
        bundle_store=SkillBundleStore(),
        binding_repo=InMemorySkillBindingRepository(),
    )


# ---------------------------------------------------------------------------
# bind_skill — happy path (Claude Code only, default harness)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _SYMLINKS_AVAILABLE,
    reason="Symlinks not supported without Developer Mode (Story §8)",
)
class TestBindSkillHappyPath:
    def test_creates_claude_code_symlink(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj-a")

        link = project_root / ".claude" / "skills" / "implement"
        assert link.is_symlink()
        assert link.resolve() == bundle_root.resolve()

    def test_creates_both_harness_symlinks(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill(
            "implement",
            bundle_root,
            project_root,
            harnesses=(HarnessKind.CLAUDE_CODE, HarnessKind.CODEX),
            project_key="proj-a",
        )

        claude_link = project_root / ".claude" / "skills" / "implement"
        codex_link = project_root / ".codex" / "skills" / "implement"
        assert claude_link.is_symlink()
        assert codex_link.is_symlink()

    def test_binding_saved_as_verified(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj-a")

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.status == SkillLifecycleStatus.VERIFIED

    def test_binding_has_symlink_mode(self, tmp_path: Path) -> None:
        from agentkit.skills.binding import SkillBindingMode

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj-a")

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.binding_mode == SkillBindingMode.SYMLINK

    def test_rebind_replaces_existing_symlink(self, tmp_path: Path) -> None:
        bundle1 = tmp_path / "bundle1"
        bundle1.mkdir()
        bundle2 = tmp_path / "bundle2"
        bundle2.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle1, project_root, project_key="proj")
        skills.bind_skill("implement", bundle2, project_root, project_key="proj")

        link = project_root / ".claude" / "skills" / "implement"
        assert link.is_symlink()
        assert link.resolve() == bundle2.resolve()

    def test_skills_dir_created_if_absent(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        # No .claude/skills/ directory pre-exists
        assert not (project_root / ".claude").exists()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj")
        assert (project_root / ".claude" / "skills").is_dir()

    def test_no_file_copy(self, tmp_path: Path) -> None:
        """Invariant: bind_skill must not copy files into the project."""
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "skill.md").write_text("skill content")
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj")

        # The project must NOT contain a copy of skill.md
        assert not (project_root / "skill.md").exists()
        # Only the symlink exists
        link = project_root / ".claude" / "skills" / "implement"
        assert link.is_symlink()


# ---------------------------------------------------------------------------
# bind_skill — Lifecycle transitions
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _SYMLINKS_AVAILABLE,
    reason="Symlinks not supported without Developer Mode (Story §8)",
)
class TestBindSkillLifecycle:
    def test_verified_status_after_successful_bind(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj")

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.status == SkillLifecycleStatus.VERIFIED

    def test_binding_id_is_stable_across_rebind(self, tmp_path: Path) -> None:
        bundle1 = tmp_path / "bundle1"
        bundle1.mkdir()
        bundle2 = tmp_path / "bundle2"
        bundle2.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle1, project_root, project_key="proj")
        b1 = skills.resolve_binding(project_root, "implement")

        skills.bind_skill("implement", bundle2, project_root, project_key="proj")
        b2 = skills.resolve_binding(project_root, "implement")

        assert b1 is not None and b2 is not None
        assert b1.binding_id == b2.binding_id  # deterministic from (project_key, skill_name)


# ---------------------------------------------------------------------------
# bind_skill — Fail-closed paths
# ---------------------------------------------------------------------------

class TestBindSkillFailClosed:
    def test_missing_project_root_raises(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "does_not_exist"

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="project_root"):
            skills.bind_skill("implement", bundle_root, project_root)

    def test_missing_bundle_root_raises(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        bundle_root = tmp_path / "no_bundle"

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="bundle_root"):
            skills.bind_skill("implement", bundle_root, project_root)

    def test_digest_mismatch_raises(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "manifest.json").write_text('{"bundle_id": "x"}')
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        with pytest.raises(SkillBundleDigestMismatchError, match="mismatch"):
            skills.bind_skill(
                "implement",
                bundle_root,
                project_root,
                expected_manifest_digest="aaaaaa",
            )

    @pytest.mark.skipif(
        not _SYMLINKS_AVAILABLE,
        reason="Symlinks not supported without Developer Mode (Story §8)",
    )
    def test_correct_digest_passes(self, tmp_path: Path) -> None:
        import hashlib

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        manifest_content = b'{"bundle_id": "x"}'
        (bundle_root / "manifest.json").write_bytes(manifest_content)
        digest = hashlib.sha256(manifest_content).hexdigest()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        # Should not raise
        skills.bind_skill(
            "implement",
            bundle_root,
            project_root,
            expected_manifest_digest=digest,
        )

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows-specific symlink privilege test",
    )
    def test_symlink_failure_raises_binding_error_not_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates a Windows OSError on symlink_to to verify fail-closed behaviour."""
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        def _bad_symlink(self: Path, target: object, **kwargs: object) -> None:
            raise OSError("A required privilege is not held by the client")

        monkeypatch.setattr(Path, "symlink_to", _bad_symlink)

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="Developer Mode"):
            skills.bind_skill("implement", bundle_root, project_root)


# ---------------------------------------------------------------------------
# resolve_binding
# ---------------------------------------------------------------------------

class TestResolveBinding:
    def test_returns_none_when_no_binding(self, tmp_path: Path) -> None:
        # Does NOT call bind_skill — no symlink needed.
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        result = skills.resolve_binding(project_root, "implement")
        assert result is None

    @pytest.mark.skipif(
        not _SYMLINKS_AVAILABLE,
        reason="Symlinks not supported without Developer Mode (Story §8)",
    )
    def test_returns_binding_after_bind(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root, project_key="proj")
        result = skills.resolve_binding(project_root, "implement")
        assert result is not None
        assert result.skill_name == "implement"


# ---------------------------------------------------------------------------
# list_bound_skills
# ---------------------------------------------------------------------------

class TestListBoundSkills:
    def test_empty_list_when_nothing_bound(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        result = skills.list_bound_skills(project_root)
        assert result == []

    @pytest.mark.skipif(
        not _SYMLINKS_AVAILABLE,
        reason="Symlinks not supported without Developer Mode (Story §8)",
    )
    def test_returns_all_bound_skills_sorted(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("zzz", bundle, project_root, project_key="proj")
        skills.bind_skill("aaa", bundle, project_root, project_key="proj")
        skills.bind_skill("mmm", bundle, project_root, project_key="proj")

        result = skills.list_bound_skills(project_root)
        names = [b.skill_name for b in result]
        assert names == sorted(names)

    @pytest.mark.skipif(
        not _SYMLINKS_AVAILABLE,
        reason="Symlinks not supported without Developer Mode (Story §8)",
    )
    def test_isolates_by_project(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        proj_b = tmp_path / "proj_b"
        proj_b.mkdir()

        skills = _make_skills()
        skills.bind_skill("skill-x", bundle, proj_a, project_key="proj_a")
        skills.bind_skill("skill-y", bundle, proj_b, project_key="proj_b")

        result_a = skills.list_bound_skills(proj_a)
        result_b = skills.list_bound_skills(proj_b)

        # resolve_binding uses project_root.stem as project_key when not provided
        # but here we passed explicit project_key; list_bound_skills uses project_root.stem
        # This should still work because project_root.stem == "proj_a" matches project_key
        # Let's verify isolation
        assert all(b.project_key == "proj_a" for b in result_a)
        assert all(b.project_key == "proj_b" for b in result_b)


# ---------------------------------------------------------------------------
# collect_quality_metrics
# ---------------------------------------------------------------------------

class TestCollectQualityMetrics:
    def test_raises_not_implemented_error(self) -> None:
        skills = _make_skills()
        with pytest.raises(NotImplementedError, match="follow-up story"):
            skills.collect_quality_metrics("implement")

    def test_error_message_references_theme(self) -> None:
        skills = _make_skills()
        with pytest.raises(NotImplementedError) as exc_info:
            skills.collect_quality_metrics("semantic-review")
        assert "telemetry" in str(exc_info.value).lower() or "THEME" in str(exc_info.value)
