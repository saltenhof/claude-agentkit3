"""Unit tests for installer file operation fallbacks."""

from __future__ import annotations

import errno
import os
import shutil
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import ProjectError
from agentkit.installer import file_ops

if TYPE_CHECKING:
    from pathlib import Path


def test_hardlink_falls_back_to_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("payload", encoding="utf-8")
    seen: list[tuple[str, Path, Path]] = []

    def fake_link(src: Path, dst: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device")

    def fake_symlink(src: Path, dst: Path) -> None:
        seen.append(("symlink", src, dst))
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(os, "link", fake_link)
    monkeypatch.setattr(os, "symlink", fake_symlink)

    file_ops.create_or_replace_hardlink(source, target)

    assert seen == [("symlink", source, target)]
    assert target.read_text(encoding="utf-8") == "payload"


def test_hardlink_falls_back_to_copy_when_symlink_cannot_be_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("payload", encoding="utf-8")
    seen: list[tuple[str, Path, Path]] = []

    def fake_link(src: Path, dst: Path) -> None:
        raise OSError("hardlink unavailable")

    def fake_symlink(src: Path, dst: Path) -> None:
        raise OSError("symlink unavailable")

    def fake_copy(src: Path, dst: Path) -> None:
        seen.append(("copy", src, dst))
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(os, "link", fake_link)
    monkeypatch.setattr(os, "symlink", fake_symlink)
    monkeypatch.setattr(shutil, "copy2", fake_copy)
    monkeypatch.setattr(file_ops, "_can_fallback_to_symlink", lambda exc: True)
    monkeypatch.setattr(file_ops, "_can_fallback_to_copy", lambda exc: True)

    file_ops.create_or_replace_hardlink(source, target)

    assert seen == [("copy", source, target)]
    assert target.read_text(encoding="utf-8") == "payload"


def test_hardlink_raises_prompt_binding_error_when_symlink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(os, "link", lambda src, dst: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(
        os,
        "symlink",
        lambda src, dst: (_ for _ in ()).throw(OSError("symlink unavailable")),
    )
    monkeypatch.setattr(file_ops, "_can_fallback_to_symlink", lambda exc: True)
    monkeypatch.setattr(file_ops, "_can_fallback_to_copy", lambda exc: False)

    with pytest.raises(ProjectError, match="prompt binding"):
        file_ops.create_or_replace_hardlink(source, target)
