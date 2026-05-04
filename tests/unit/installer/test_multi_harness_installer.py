from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from agentkit.installer import InstallConfig, install_agentkit, uninstall_agentkit
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV

if TYPE_CHECKING:
    from pathlib import Path


def test_install_creates_claude_and_codex_settings(tmp_path: Path) -> None:
    result = install_agentkit(_make_config(tmp_path))

    assert result.success is True
    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert (tmp_path / ".codex" / "config.toml").is_file()
    assert "agentkit-hook-codex" in (
        tmp_path / ".codex" / "config.toml"
    ).read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path: Path) -> None:
    first = install_agentkit(_make_config(tmp_path))
    before = _file_snapshot(tmp_path)

    second = install_agentkit(_make_config(tmp_path))
    after = _file_snapshot(tmp_path)

    assert first.created_files
    assert second.created_files == ()
    assert after == before


def test_uninstall_removes_harness_settings(tmp_path: Path) -> None:
    install_agentkit(_make_config(tmp_path))

    result = uninstall_agentkit(tmp_path)

    assert result.success is True
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".codex" / "config.toml").exists()
    assert not (tmp_path / ".agentkit").exists()


def _make_config(project_root: Path) -> InstallConfig:
    return InstallConfig(
        project_key="ag3",
        project_name="AG3",
        project_root=project_root,
    )


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(autouse=True)
def _set_prompt_bundle_store_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        PROMPT_BUNDLE_STORE_ENV,
        str(tmp_path / ".prompt-bundle-store"),
    )
