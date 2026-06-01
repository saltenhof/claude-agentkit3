"""Unit tests for the platform-aware link layer (AG3-027, FK-43 §43.4.1.1).

The binding link is a symbolic link on POSIX and a directory junction on
Windows. CI runs on Windows, so the Windows junction branch is exercised by the
``test_top``/``test_top_surface`` happy paths. These tests cover the POSIX
branches host-independently (by toggling the module's ``_IS_WINDOWS`` flag and
stubbing the OS call) so the POSIX deployment path is verified, not merely
excluded from coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.skills import links as links_mod
from agentkit.skills.binding import SkillBindingMode

if TYPE_CHECKING:
    import pytest


class TestPlatformBindingMode:
    def test_windows_is_junction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", True)
        assert links_mod.platform_binding_mode() is SkillBindingMode.JUNCTION

    def test_posix_is_symlink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", False)
        assert links_mod.platform_binding_mode() is SkillBindingMode.SYMLINK


class TestCreateDirectoryLinkPosixBranch:
    """POSIX branch of ``create_directory_link`` (host-independent)."""

    def test_posix_calls_symlink_to_and_returns_symlink_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", False)

        target = tmp_path / "bundle"
        target.mkdir()
        link = tmp_path / "link"

        recorded: dict[str, object] = {}

        def _fake_symlink(self: Path, t: object, **_k: object) -> None:
            recorded["self"] = self
            recorded["target"] = t

        monkeypatch.setattr(Path, "symlink_to", _fake_symlink)

        mode = links_mod.create_directory_link(link, target)

        assert mode is SkillBindingMode.SYMLINK
        assert recorded["self"] == link
        # Codex-r7-r2: the POSIX branch resolves the target to an absolute path.
        assert recorded["target"] == target.resolve()


class TestRemoveDirectoryLinkNonJunctionBranch:
    """Non-junction (symlink/plain) branch of ``remove_directory_link``.

    A plain file is not a junction, so ``os.path.isjunction`` is False and the
    function removes it via ``Path.unlink`` — the same branch a POSIX symlink
    takes. Verifies the target is detached without recursion.
    """

    def test_non_junction_path_is_unlinked(self, tmp_path: Path) -> None:
        artifact = tmp_path / "artifact"
        artifact.write_text("payload", encoding="utf-8")

        links_mod.remove_directory_link(artifact)

        assert not artifact.exists()


class TestIsDirectoryLink:
    def test_plain_file_is_not_a_link(self, tmp_path: Path) -> None:
        f = tmp_path / "f"
        f.write_text("x", encoding="utf-8")
        assert links_mod.is_directory_link(f) is False

    def test_missing_path_is_not_a_link(self, tmp_path: Path) -> None:
        assert links_mod.is_directory_link(tmp_path / "nope") is False
