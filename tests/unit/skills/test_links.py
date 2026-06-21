"""Unit tests for the platform-aware link layer (AG3-027, FK-43 §43.4.1.1).

The binding link is a symbolic link on POSIX and a directory junction on
Windows. CI runs on Windows, so the Windows junction branch is exercised by the
``test_top``/``test_top_surface`` happy paths. These tests cover the POSIX
branches host-independently (by toggling the module's ``_IS_WINDOWS`` flag and
stubbing the OS call) so the POSIX deployment path is verified, not merely
excluded from coverage.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.skills import links as links_mod
from agentkit.backend.skills.binding import SkillBindingMode

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


class TestCreateDirectoryLinkWindowsBranch:
    """Windows junction branch of ``create_directory_link`` (host-independent).

    Covers the win32 branch on ANY platform by stubbing the DYNAMIC ``_winapi``
    import (the dynamic import is what keeps Linux mypy/CI clean): the function
    must call ``CreateJunction(absolute_target, link)`` and return ``JUNCTION``.
    """

    def test_windows_branch_creates_junction_via_winapi(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", True)

        recorded: dict[str, object] = {}

        def _create_junction(target: str, junction: str) -> None:
            recorded["target"] = target
            recorded["junction"] = junction

        # SimpleNamespace stands in for the ``_winapi`` module (its ``CreateJunction``
        # attribute mirrors the Windows API name without a non-PEP8 function def).
        fake_winapi = types.SimpleNamespace(CreateJunction=_create_junction)
        real_import = links_mod.importlib.import_module

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            return fake_winapi if name == "_winapi" else real_import(name, *args, **kwargs)

        monkeypatch.setattr(links_mod.importlib, "import_module", _fake_import)

        target = tmp_path / "bundle"
        target.mkdir()
        link = tmp_path / "link"

        mode = links_mod.create_directory_link(link, target)

        assert mode is SkillBindingMode.JUNCTION
        assert recorded["junction"] == str(link)
        # A junction stores an ABSOLUTE target path.
        assert recorded["target"] == str(target.resolve())


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


class TestReadDirectoryLinkTarget:
    """``read_directory_link_target`` resolves the REAL link target (AG3-111 §2.1 1b).

    The resolver lets the installer/Verify/cleanup derive the materialized-vs-raw
    binding mode from the link target without a new ``SkillBinding`` field. It runs on
    the host platform (a real link via ``create_directory_link``) AND covers the POSIX
    ``os.readlink`` branch host-independently.
    """

    def test_resolves_real_link_target_on_host(self, tmp_path: Path) -> None:
        # Real link on the platform the test runs on (Windows junction here): the
        # resolved target equals the absolute target directory.
        target = tmp_path / "variant-dir"
        target.mkdir()
        link = tmp_path / "bindpoint"
        links_mod.create_directory_link(link, target)

        resolved = links_mod.read_directory_link_target(link)

        assert resolved.resolve() == target.resolve()

    def test_strips_windows_extended_length_prefix(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The Windows junction branch: os.readlink returns the extended-length
        # ``\\?\`` prefix, which the resolver strips so the result compares equal to
        # an ordinary absolute Path.
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", True)
        target = tmp_path / "tgt"

        def _fake_readlink(_p: object) -> str:
            return f"\\\\?\\{target}"

        monkeypatch.setattr(links_mod.os, "readlink", _fake_readlink)

        resolved = links_mod.read_directory_link_target(tmp_path / "link")

        assert str(resolved) == str(target)
        assert not str(resolved).startswith("\\\\?\\")

    def test_posix_branch_returns_readlink_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # POSIX: no prefix stripping — os.readlink already returns the stored target.
        monkeypatch.setattr(links_mod, "_IS_WINDOWS", False)
        target = tmp_path / "posix-tgt"

        monkeypatch.setattr(links_mod.os, "readlink", lambda _p: str(target))

        resolved = links_mod.read_directory_link_target(tmp_path / "link")

        assert str(resolved) == str(target)
