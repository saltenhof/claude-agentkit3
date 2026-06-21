"""Unit tests for Skills top-surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Covers:
- bind_skill happy path (Claude Code + Codex harnesses)
- bind_skill Lifecycle transitions (BUNDLE_SELECTED -> BOUND -> VERIFIED)
- bind_skill fail-closed paths
- resolve_binding
- list_bound_skills
- collect_quality_metrics fails closed without a projection accessor

Platform note (FK-43 §43.4.1.1): the binding is a thin directory link — a
symbolic link on POSIX, a Windows directory junction. A junction needs no
Developer Mode, so binding works on EVERY supported platform; the tests no
longer skip on Windows-without-Developer-Mode. They assert against
``is_directory_link`` (symlink OR junction), not ``Path.is_symlink``, and the
link-layer is monkeypatched via :mod:`agentkit.backend.skills.links` (re-exported into
``agentkit.backend.skills.top``) rather than ``Path.symlink_to``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agentkit.backend.skills import SourceWindow
from agentkit.backend.skills.binding import SkillBindingMode, SkillLifecycleStatus
from agentkit.backend.skills.bundle_store import SkillBundleStore
from agentkit.backend.skills.errors import (
    SkillBindingFailedError,
    SkillBundleDigestMismatchError,
    SkillProfileNotSupportedError,
    SkillQualityMetricSourceUnavailableError,
)
from agentkit.backend.skills.links import (
    create_directory_link,
    is_directory_link,
    platform_binding_mode,
)
from agentkit.backend.skills.repository import InMemorySkillBindingRepository
from agentkit.backend.skills.top import Skills


def _directory_links_supported() -> bool:
    """Return True if the OS/process can create a binding link in tmp.

    Uses the production link layer: a symlink on POSIX, a directory junction on
    Windows. The junction path needs no Developer Mode, so this is True on every
    supported platform; the probe only guards exotic filesystems that reject
    both link kinds.
    """
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        link = Path(d) / "link"
        try:
            create_directory_link(link, src)
            return True
        except OSError:
            return False


_LINKS_AVAILABLE = _directory_links_supported()
_SKIP_NO_LINKS = pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
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
# bind_skill — happy path
# ---------------------------------------------------------------------------

@_SKIP_NO_LINKS
class TestBindSkillHappyPath:
    def test_creates_claude_code_link(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)

        link = project_root / ".claude" / "skills" / "implement"
        assert is_directory_link(link)
        assert link.resolve() == bundle_root.resolve()

    def test_creates_both_harness_links(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        # FK-43 §43.4.1 AK4: multi-harness Pflicht ab Tag 1; bind_skill setzt
        # immer beide Links (Claude Code + Codex), kein Kwarg-Override.
        skills.bind_skill("implement", bundle_root, project_root)

        claude_link = project_root / ".claude" / "skills" / "implement"
        codex_link = project_root / ".codex" / "skills" / "implement"
        assert is_directory_link(claude_link)
        assert is_directory_link(codex_link)

    def test_binding_saved_as_verified(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.status == SkillLifecycleStatus.VERIFIED

    def test_binding_records_platform_mode(self, tmp_path: Path) -> None:
        """The persisted binding_mode is the mode actually used on this platform
        (SYMLINK on POSIX, JUNCTION on Windows) — FK-43 §43.4.1.1."""
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.binding_mode == platform_binding_mode()

    def test_rebind_replaces_existing_link(self, tmp_path: Path) -> None:
        bundle1 = tmp_path / "bundle1"
        bundle1.mkdir()
        bundle2 = tmp_path / "bundle2"
        bundle2.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle1, project_root)
        skills.bind_skill("implement", bundle2, project_root)

        link = project_root / ".claude" / "skills" / "implement"
        assert is_directory_link(link)
        assert link.resolve() == bundle2.resolve()

    def test_skills_dir_created_if_absent(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        # No .claude/skills/ directory pre-exists
        assert not (project_root / ".claude").exists()
        skills.bind_skill("implement", bundle_root, project_root)
        assert (project_root / ".claude" / "skills").is_dir()

    def test_no_file_copy(self, tmp_path: Path) -> None:
        """Invariant: bind_skill must not copy files into the project."""
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "skill.md").write_text("skill content")
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)

        # The project must NOT contain a copy of skill.md
        assert not (project_root / "skill.md").exists()
        # Only the link exists at the bind point.
        link = project_root / ".claude" / "skills" / "implement"
        assert is_directory_link(link)


# ---------------------------------------------------------------------------
# bind_skill — Lifecycle transitions
# ---------------------------------------------------------------------------

@_SKIP_NO_LINKS
class TestBindSkillLifecycle:
    def test_verified_status_after_successful_bind(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)

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
        skills.bind_skill("implement", bundle1, project_root)
        b1 = skills.resolve_binding(project_root, "implement")

        skills.bind_skill("implement", bundle2, project_root)
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
        # FK-43 §43.5.2: manifest declares its own digest; mismatch is fail-closed.
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "manifest.json").write_text(
            '{"bundle_id": "x", "manifest_digest": "deadbeef"}'
        )
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        with pytest.raises(SkillBundleDigestMismatchError, match="mismatch"):
            skills.bind_skill("implement", bundle_root, project_root)

    @_SKIP_NO_LINKS
    def test_correct_digest_passes(self, tmp_path: Path) -> None:
        # FK-43 §43.5.2: manifest_digest covers the manifest payload *excluding*
        # the manifest_digest field itself (otherwise self-reference is impossible).
        import hashlib
        import json

        payload = {"bundle_id": "x"}
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        manifest = {"bundle_id": "x", "manifest_digest": digest}
        (bundle_root / "manifest.json").write_text(json.dumps(manifest))
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        # Should not raise: digest matches payload-without-digest.
        skills.bind_skill("implement", bundle_root, project_root)

    def test_profile_not_supported_raises(self, tmp_path: Path) -> None:
        # FK-43 §43.4.1: bundle declares variants but skill_name maps to none.
        import json

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        manifest = {"bundle_id": "x", "variants": {"CORE": "other_skill"}}
        (bundle_root / "manifest.json").write_text(json.dumps(manifest))
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        with pytest.raises(SkillProfileNotSupportedError, match="variants"):
            skills.bind_skill("implement", bundle_root, project_root)

    def test_link_failure_raises_binding_error_not_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Host-independent: an OSError from the link layer is converted to a
        fail-closed ``SkillBindingFailedError`` — never a file-copy fallback
        (invariant project_binding_is_link_only)."""
        import agentkit.backend.skills.top as top_mod

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        def _bad_link(link_path: Path, target: Path) -> SkillBindingMode:
            raise OSError("simulated OS link failure")

        monkeypatch.setattr(top_mod, "create_directory_link", _bad_link)

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="binding link"):
            skills.bind_skill("implement", bundle_root, project_root)
        # No copy fallback: the project contains no skill payload.
        assert not (project_root / "implement").exists()


# ---------------------------------------------------------------------------
# bind_skill — SELF-ATOMIC cleanup (AG3-048 Codex-r3 ERROR 2)
# ---------------------------------------------------------------------------

class _FailingSaveRepo(InMemorySkillBindingRepository):
    """Repo whose first ``save`` raises (simulating a DB outage after the
    links were already created). ``delete`` is recorded so the test can prove
    the self-atomic cleanup attempted to remove any persisted row."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_calls: list[tuple[str, str]] = []

    def save(self, binding: object) -> None:  # type: ignore[override]
        raise RuntimeError("DB outage during persist")

    def delete(self, project_key: str, skill_name: str) -> None:
        self.delete_calls.append((project_key, skill_name))
        super().delete(project_key, skill_name)


def _stub_create(*_a: object, **_k: object) -> SkillBindingMode:
    """No-op stand-in for ``_create_harness_links`` returning a valid mode."""
    return SkillBindingMode.SYMLINK


class TestBindSkillSelfAtomicCleanup:
    """``_remove_binding_artifacts`` and the self-atomic guard around persistence."""

    def test_cleanup_removes_links_and_row_host_independent(
        self, tmp_path: Path
    ) -> None:
        """Host-independent: ``_remove_binding_artifacts`` removes BOTH harness
        artifacts (here plain files standing in for links) AND best-effort
        deletes the persisted row. Proves the undo logic without needing a real
        link privilege. (AG3-048 Codex-r6 FINDING 1: this is now the ONE shared
        removal discipline used by cleanup AND unbind.)
        """
        from agentkit.backend.skills.binding import HarnessKind
        from agentkit.backend.skills.top import _harness_skill_dir

        project_root = tmp_path / "project"
        project_root.mkdir()
        harnesses = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)
        # Stand-in artifacts the partial bind would have created.
        for harness in harnesses:
            d = _harness_skill_dir(project_root, harness)
            d.mkdir(parents=True, exist_ok=True)
            (d / "implement").write_text("stub")

        repo = _FailingSaveRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)
        residual = skills._remove_binding_artifacts("implement", project_root, harnesses)
        assert residual.is_clean

        for harness in harnesses:
            assert not (_harness_skill_dir(project_root, harness) / "implement").exists()
        assert repo.delete_calls == [(project_root.stem, "implement")]

    def test_persist_failure_cleans_up_host_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Host-independent: with link creation stubbed to a no-op, a failing
        ``save`` exercises the full self-atomic guard — the ``except Exception``
        branch runs the cleanup and the original error propagates.
        """
        import agentkit.backend.skills.top as top_mod

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        monkeypatch.setattr(top_mod, "_create_harness_links", _stub_create)

        repo = _FailingSaveRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)
        with pytest.raises(RuntimeError, match="DB outage"):
            skills.bind_skill("implement", bundle_root, project_root)

        # Self-atomic: best-effort delete attempted; nothing persisted.
        assert repo.delete_calls == [(project_root.stem, "implement")]
        assert repo.load(project_root.stem, "implement") is None

    def test_success_path_host_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Host-independent happy path: with link creation + verification
        stubbed, a successful bind persists a VERIFIED binding (covers the
        BOUND->VERIFIED save sequence without a real link privilege)."""
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        monkeypatch.setattr(top_mod, "_create_harness_links", _stub_create)
        monkeypatch.setattr(top_mod, "_verify_harness_links", lambda *a, **k: None)

        repo = InMemorySkillBindingRepository()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)
        skills.bind_skill("implement", bundle_root, project_root)

        binding = skills.resolve_binding(project_root, "implement")
        assert binding is not None
        assert binding.status == SkillLifecycleStatus.VERIFIED

    @_SKIP_NO_LINKS
    def test_persist_failure_leaves_no_partial_state(self, tmp_path: Path) -> None:
        """When persistence fails AFTER the links are created, ``bind_skill`` is
        self-atomic — it removes the links and leaves NO persisted binding. The
        outcome is binary. Runs with real links on every supported platform.
        """
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        repo = _FailingSaveRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)
        with pytest.raises(RuntimeError, match="DB outage"):
            skills.bind_skill("implement", bundle_root, project_root)

        # No partial state: both harness links removed, no persisted row.
        assert not (project_root / ".claude" / "skills" / "implement").exists()
        assert not (project_root / ".codex" / "skills" / "implement").exists()
        assert repo.load(project_root.stem, "implement") is None
        # Cleanup attempted the best-effort delete.
        assert repo.delete_calls == [(project_root.stem, "implement")]

    def test_rebind_link_failure_deletes_stale_row_host_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex-r7 FINDING 1: a REBIND whose link creation fails must NOT leave
        the prior bind's persisted row behind (which would then point at a
        now-removed link). Because link creation is inside the self-atomic try,
        the failed rebind runs the cleanup and DELETES the stale row — the
        outcome is binary (fully bound or fully clean). Host-independent: link
        creation is stubbed (succeeds for the first bind, fails on the rebind).
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository

        bundle1 = tmp_path / "b1"
        bundle1.mkdir()
        bundle2 = tmp_path / "b2"
        bundle2.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        repo = InMemorySkillBindingRepository()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        calls = {"n": 0}

        def _create(_link_path: Path, _target: Path) -> SkillBindingMode:
            calls["n"] += 1
            if calls["n"] <= 2:  # first bind: both harness links succeed
                return SkillBindingMode.SYMLINK
            raise OSError("rebind link creation failed (simulated)")

        monkeypatch.setattr(top_mod, "create_directory_link", _create)
        monkeypatch.setattr(top_mod, "_verify_harness_links", lambda *a, **k: None)

        # First bind persists a VERIFIED row.
        skills.bind_skill("implement", bundle1, project_root)
        assert skills.resolve_binding(project_root, "implement") is not None

        # Rebind fails during link creation -> self-atomic cleanup deletes the
        # stale row. No SkillBindingPartialStateError (cleanup is clean).
        with pytest.raises(SkillBindingFailedError):
            skills.bind_skill("implement", bundle2, project_root)
        assert skills.resolve_binding(project_root, "implement") is None


# ---------------------------------------------------------------------------
# bind_skill — NO-SILENT-PARTIAL-STATE guarantee (AG3-048 Codex-r4 FINDING 1)
# ---------------------------------------------------------------------------

class _FailingDeleteRepo(InMemorySkillBindingRepository):
    """Repo whose ``save`` fails (after links) AND whose ``delete`` also fails —
    simulating a DB outage that affects both persist and the compensating
    cleanup delete (residual persisted row remains)."""

    def save(self, binding: object) -> None:  # type: ignore[override]
        raise RuntimeError("DB outage during persist")

    def delete(self, project_key: str, skill_name: str) -> None:
        raise RuntimeError("DB outage during cleanup delete")


class TestBindSkillNoSilentPartialState:
    """FINDING 1: cleanup that cannot fully undo must SURFACE the residual; it
    must NEVER return/report a clean failure when something remains. These tests
    are HOST-INDEPENDENT — link creation is stubbed and the leftover artifacts
    are plain files standing in for binding links.
    """

    def test_cleanup_removal_fails_raises_partial_state_naming_residual(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) Cleanup cannot remove a leftover harness artifact -> ``bind_skill``
        raises ``SkillBindingPartialStateError`` whose detail REPORTS the
        residual link path. Not silent, not "clean".
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.binding import HarnessKind
        from agentkit.backend.skills.errors import SkillBindingPartialStateError
        from agentkit.backend.skills.top import _harness_skill_dir

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        # Stub link creation: instead of real links, drop plain files at the
        # harness paths (host-independent stand-ins the cleanup must remove).
        def _fake_create(*_a: object, **_k: object) -> SkillBindingMode:
            for harness in (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX):
                d = _harness_skill_dir(project_root, harness)
                d.mkdir(parents=True, exist_ok=True)
                (d / "implement").write_text("stub")
            return SkillBindingMode.SYMLINK

        monkeypatch.setattr(top_mod, "_create_harness_links", _fake_create)

        # Make removal of the leftover artifacts fail so cleanup cannot remove
        # them -> residual must be reported.
        real_unlink = Path.unlink

        def _bad_unlink(self: Path, *a: object, **k: object) -> None:
            if self.name == "implement":
                raise OSError("cannot unlink (simulated)")
            real_unlink(self, *a, **k)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "unlink", _bad_unlink)

        repo = _FailingSaveRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        with pytest.raises(SkillBindingPartialStateError) as exc_info:
            skills.bind_skill("implement", bundle_root, project_root)

        detail = exc_info.value.detail
        residual = detail["residual_links"]
        assert isinstance(residual, list)
        # BOTH harness leftovers are reported (neither could be removed).
        claude_leftover = str(
            _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / "implement"
        )
        codex_leftover = str(
            _harness_skill_dir(project_root, HarnessKind.CODEX) / "implement"
        )
        assert claude_leftover in residual
        assert codex_leftover in residual
        # The original error is surfaced, not masked.
        assert "DB outage" in str(detail["original_error"])

    def test_persist_and_delete_fail_reports_persisted_row_remains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b-core) persist fails then the compensating delete ALSO fails ->
        ``SkillBindingPartialStateError`` with ``persisted_row_remains=True``.
        Host-independent (links stubbed to no-op, so no residual link).
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.errors import SkillBindingPartialStateError

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        monkeypatch.setattr(top_mod, "_create_harness_links", _stub_create)

        repo = _FailingDeleteRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        with pytest.raises(SkillBindingPartialStateError) as exc_info:
            skills.bind_skill("implement", bundle_root, project_root)

        detail = exc_info.value.detail
        assert detail["persisted_row_remains"] is True
        assert detail["residual_links"] == []  # links were stubbed no-op
        assert "DB outage" in str(detail["original_error"])

    def test_clean_cleanup_still_propagates_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When cleanup IS fully clean, the binary outcome holds: the ORIGINAL
        error propagates (NOT the partial-state error). Host-independent.
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.errors import SkillBindingPartialStateError

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        # No link artifacts left behind; delete succeeds -> cleanup is clean.
        monkeypatch.setattr(top_mod, "_create_harness_links", _stub_create)

        repo = _FailingSaveRepo()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        with pytest.raises(RuntimeError, match="DB outage") as exc_info:
            skills.bind_skill("implement", bundle_root, project_root)
        assert not isinstance(exc_info.value, SkillBindingPartialStateError)

    def test_link2_failure_rolls_back_link1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) When the SECOND harness link creation fails after the first
        succeeded, ``_create_harness_links`` rolls back link-1. Uses plain files
        as stand-ins via a patched link layer + a forced failure on the second
        harness; the removal of the rolled-back stand-in uses the real
        Path.unlink (host-independent).
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.binding import HarnessKind
        from agentkit.backend.skills.errors import SkillBindingFailedError
        from agentkit.backend.skills.top import _create_harness_links, _harness_skill_dir

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        harnesses = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)
        call_count = {"n": 0}

        def _fake_create(link_path: Path, target: Path) -> SkillBindingMode:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First harness: create a plain-file stand-in for the link.
                link_path.write_text("stub-link-1")
                return SkillBindingMode.SYMLINK
            # Second harness: fail (e.g. OS error mid-creation).
            raise OSError("link-2 creation failed (simulated)")

        monkeypatch.setattr(top_mod, "create_directory_link", _fake_create)

        with pytest.raises(SkillBindingFailedError, match="binding link"):
            _create_harness_links("implement", bundle_root, project_root, harnesses)

        # link-1 stand-in must be rolled back (removed) on the link-2 failure.
        link1 = _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / "implement"
        assert not link1.exists()

    def test_create_rollback_removal_failure_reports_residual_host_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AG3-048 Codex-r5 FINDING 1 (host-independent).

        link-1 created (plain-file stand-in), link-2 creation fails, and the
        rollback removal of link-1 ALSO fails. The raised error MUST be
        ``SkillBindingPartialStateError`` REPORTING link-1 as residual — never
        silent, and never only the link-2 ``SkillBindingFailedError``.
        """
        import agentkit.backend.skills.top as top_mod
        from agentkit.backend.skills.binding import HarnessKind
        from agentkit.backend.skills.errors import SkillBindingPartialStateError
        from agentkit.backend.skills.top import _create_harness_links, _harness_skill_dir

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        harnesses = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)
        call_count = {"n": 0}

        def _fake_create(link_path: Path, target: Path) -> SkillBindingMode:
            call_count["n"] += 1
            if call_count["n"] == 1:
                link_path.write_text("stub-link-1")
                return SkillBindingMode.SYMLINK
            raise OSError("link-2 creation failed (simulated)")

        link1 = _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / "implement"
        real_unlink = Path.unlink

        def _bad_unlink(self: Path, *, missing_ok: bool = False) -> None:
            # The rollback tries to remove the created link-1 stand-in -> fail,
            # leaving it behind. Any other unlink uses the real implementation.
            if self == link1:
                raise OSError("removal of link-1 failed (simulated)")
            real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(top_mod, "create_directory_link", _fake_create)
        monkeypatch.setattr(Path, "unlink", _bad_unlink)

        with pytest.raises(SkillBindingPartialStateError) as exc_info:
            _create_harness_links("implement", bundle_root, project_root, harnesses)

        # The residual link-1 is REPORTED (not silent, not only link-2 error).
        detail = exc_info.value.detail
        assert str(link1) in detail["residual_links"]
        assert detail["persisted_row_remains"] is False
        assert "link-2 creation failed" in detail["original_error"]
        # And it really does still exist on disk (honest report).
        assert link1.exists()


# ---------------------------------------------------------------------------
# resolve_binding
# ---------------------------------------------------------------------------

class TestResolveBinding:
    def test_returns_none_when_no_binding(self, tmp_path: Path) -> None:
        # Does NOT call bind_skill — no link needed.
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        result = skills.resolve_binding(project_root, "implement")
        assert result is None

    @_SKIP_NO_LINKS
    def test_returns_binding_after_bind(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("implement", bundle_root, project_root)
        result = skills.resolve_binding(project_root, "implement")
        assert result is not None
        assert result.skill_name == "implement"


# ---------------------------------------------------------------------------
# unbind_skill
# ---------------------------------------------------------------------------

class TestUnbindSkillHostIndependent:
    """``unbind_skill`` needs no link privilege (best-effort removal)."""

    def test_unbind_deletes_persisted_binding(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        from agentkit.backend.skills.binding import (
            SkillBinding,
            SkillLifecycleStatus,
        )
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository

        project_root = tmp_path / "project"
        project_root.mkdir()
        repo = InMemorySkillBindingRepository()
        repo.save(
            SkillBinding(
                binding_id="b1",
                project_key=project_root.stem,
                skill_name="implement",
                bundle_id="implement-core",
                bundle_version="4.0.0",
                target_path=project_root / ".claude" / "skills" / "implement",
                binding_mode=platform_binding_mode(),
                status=SkillLifecycleStatus.VERIFIED,
                pinned_at=datetime.now(tz=UTC),
            )
        )
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        skills.unbind_skill("implement", project_root)

        assert repo.load(project_root.stem, "implement") is None

    def test_unbind_absent_is_noop(self, tmp_path: Path) -> None:
        """Idempotent: unbinding a skill that was never bound is not an error."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        skills = _make_skills()
        skills.unbind_skill("never-bound", project_root)  # must not raise
        assert skills.resolve_binding(project_root, "never-bound") is None

    def test_unbind_residual_link_raises_partial_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AG3-048 Codex-r6 FINDING 1: a host-independent reproduction of the
        whack-a-mole bug — the link removal FAILS while the repo delete SUCCEEDS.
        ``unbind_skill`` must NOT silently swallow the surviving harness artifact:
        it RAISES ``SkillBindingPartialStateError`` reporting the residual link, so
        the installer maps it to ``RollbackIncomplete`` rather than a false-clean
        rollback.
        """
        from agentkit.backend.skills.errors import SkillBindingPartialStateError
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository

        project_root = tmp_path / "project"
        project_root.mkdir()
        # Materialise a harness skill artifact that survives removal: a real file
        # at the Claude Code bind point, plus a patched unlink that fails for it
        # AND leaves it on disk (the survivor case, host-independent).
        claude_link = project_root / ".claude" / "skills" / "implement"
        claude_link.parent.mkdir(parents=True)
        claude_link.write_text("residual", encoding="utf-8")

        repo = InMemorySkillBindingRepository()
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        real_unlink = Path.unlink

        def _failing_unlink(self: Path, *, missing_ok: bool = False) -> None:
            # Fail to remove the Claude Code artifact (leave it on disk), but let
            # any other path (e.g. the Codex bind point, which does not exist)
            # behave normally so the repo delete still runs.
            if self == claude_link:
                raise OSError("simulated unlink failure (artifact survives)")
            real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _failing_unlink)

        with pytest.raises(SkillBindingPartialStateError) as exc_info:
            skills.unbind_skill("implement", project_root)

        # The residual is REPORTED (link still present), not swallowed.
        residual = exc_info.value.detail.get("residual_links")
        assert residual == [str(claude_link)]
        assert exc_info.value.detail.get("persisted_row_remains") is False
        # The repo delete still succeeded (it ran despite the removal failure).
        assert repo.load(project_root.stem, "implement") is None
        # The artifact really is still on disk (honest reproduction).
        assert claude_link.exists()


class TestReadBundleManifestFailClosed:
    """``_read_bundle_manifest`` fail-closed paths (no link needed; the manifest
    is read BEFORE any link creation)."""

    def test_malformed_manifest_json_raises(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "manifest.json").write_text("{ not json", encoding="utf-8")
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="parse manifest"):
            skills.bind_skill("implement", bundle_root, project_root)

    def test_non_object_manifest_raises(self, tmp_path: Path) -> None:
        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        (bundle_root / "manifest.json").write_text("[]", encoding="utf-8")
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        with pytest.raises(SkillBindingFailedError, match="must be a JSON object"):
            skills.bind_skill("implement", bundle_root, project_root)


class TestListBoundSkills:
    def test_empty_list_when_nothing_bound(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        result = skills.list_bound_skills(project_root)
        assert result == []

    def test_lists_persisted_bindings_host_independent(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        from agentkit.backend.skills.binding import (
            SkillBinding,
            SkillLifecycleStatus,
        )
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository

        project_root = tmp_path / "project"
        project_root.mkdir()
        repo = InMemorySkillBindingRepository()
        for name in ("zzz", "aaa"):
            repo.save(
                SkillBinding(
                    binding_id=f"b-{name}",
                    project_key=project_root.stem,
                    skill_name=name,
                    bundle_id=f"{name}-core",
                    bundle_version="4.0.0",
                    target_path=project_root / ".claude" / "skills" / name,
                    binding_mode=platform_binding_mode(),
                    status=SkillLifecycleStatus.VERIFIED,
                    pinned_at=datetime.now(tz=UTC),
                )
            )
        skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

        result = skills.list_bound_skills(project_root)
        assert [b.skill_name for b in result] == ["aaa", "zzz"]

    @_SKIP_NO_LINKS
    def test_returns_all_bound_skills_sorted(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = _make_skills()
        skills.bind_skill("zzz", bundle, project_root)
        skills.bind_skill("aaa", bundle, project_root)
        skills.bind_skill("mmm", bundle, project_root)

        result = skills.list_bound_skills(project_root)
        names = [b.skill_name for b in result]
        assert names == sorted(names)

    @_SKIP_NO_LINKS
    def test_isolates_by_project(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        proj_b = tmp_path / "proj_b"
        proj_b.mkdir()

        skills = _make_skills()
        skills.bind_skill("skill-x", bundle, proj_a)
        skills.bind_skill("skill-y", bundle, proj_b)

        result_a = skills.list_bound_skills(proj_a)
        result_b = skills.list_bound_skills(proj_b)

        assert all(b.project_key == "proj_a" for b in result_a)
        assert all(b.project_key == "proj_b" for b in result_b)


# ---------------------------------------------------------------------------
# collect_quality_metrics
# ---------------------------------------------------------------------------

class TestCollectQualityMetrics:
    def test_requires_projection_accessor(self) -> None:
        skills = _make_skills()
        with pytest.raises(SkillQualityMetricSourceUnavailableError):
            skills.collect_quality_metrics(
                "semantic-review",
                project_key="AK3",
                source_window=SourceWindow(),
            )
