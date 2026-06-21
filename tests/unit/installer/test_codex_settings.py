from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.codex_settings import (
    CODEX_HOOK_COMMAND,
    build_codex_config_toml,
    remove_codex_settings,
    write_codex_settings,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_build_codex_config_registers_hook_command() -> None:
    content = build_codex_config_toml()

    assert "[hooks.pre_tool_use]" in content
    assert CODEX_HOOK_COMMAND in content


def test_write_codex_settings_is_idempotent(tmp_path: Path) -> None:
    first = write_codex_settings(tmp_path)
    config_path = tmp_path / ".codex" / "config.toml"
    first_content = config_path.read_text(encoding="utf-8")

    second = write_codex_settings(tmp_path)

    assert first == ".codex\\config.toml" or first == ".codex/config.toml"
    assert second is None
    assert config_path.read_text(encoding="utf-8") == first_content


def test_remove_codex_settings_removes_file_and_empty_dir(tmp_path: Path) -> None:
    write_codex_settings(tmp_path)

    removed = remove_codex_settings(tmp_path)

    assert ".codex\\config.toml" in removed or ".codex/config.toml" in removed
    assert ".codex" in removed
    assert not (tmp_path / ".codex").exists()
