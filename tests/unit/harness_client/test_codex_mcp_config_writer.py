"""Codex MCP config writer — real-file boundary tests (AG3-175 AC 3/7, R01–R03)."""

from __future__ import annotations

import os
import tomllib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
    CodexMcpConfigError,
    CodexMcpServerEntry,
    load_codex_mcp_document,
    merge_mcp_server,
    project_codex_mcp_config_path,
    write_mcp_server,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def _entry(
    *,
    command: str = "agentkit-mcp-story-kb",
    cwd: str = "/proj",
    env: dict[str, str] | None = None,
) -> CodexMcpServerEntry:
    return CodexMcpServerEntry(
        command=command,
        args=(),
        cwd=cwd,
        env=env
        or {
            "PROJECT_ID": "P1",
            "WEAVIATE_HOST": "weaviate.example.test",
            "WEAVIATE_HTTP_PORT": "9903",
            "WEAVIATE_GRPC_PORT": "50051",
        },
        required=True,
    )


def test_write_creates_project_local_table_only(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = _entry(cwd=str(root))
    path = write_mcp_server(root, "story-knowledge-base", entry)
    assert path == root / ".codex" / "config.toml"
    assert path.is_file()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = data["mcp_servers"]["story-knowledge-base"]
    assert server["command"] == entry.command
    assert server["required"] is True
    assert server["env"]["PROJECT_ID"] == "P1"
    assert server["cwd"] == str(root)


def test_never_writes_userspace_codex_home(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """AC 3: isolated CODEX_HOME stays untouched."""
    project = tmp_path / "proj"
    project.mkdir()
    userspace = tmp_path / "userspace-codex"
    userspace.mkdir()
    sentinel = userspace / "config.toml"
    sentinel.write_text("# userspace sentinel\n", encoding="utf-8")
    before = sentinel.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(userspace))
    write_mcp_server(project, "story-knowledge-base", _entry(cwd=str(project)))
    assert sentinel.read_bytes() == before
    assert (project / ".codex" / "config.toml").is_file()
    other = tmp_path / "other-proj"
    other.mkdir()
    root, before_b, err = load_codex_mcp_document(other)
    assert err is None
    assert root == {}
    assert before_b is None
    assert not (other / ".codex" / "config.toml").exists()


def test_preserves_foreign_top_level_and_foreign_mcp_servers(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    codex = root / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        "\n".join(
            [
                "[hooks.pre_tool_use]",
                'command = "agentkit-hook-codex"',
                "",
                "[mcp_servers.foreign-tool]",
                'command = "echo"',
                'args = ["hi"]',
                'cwd = "/tmp"',
                "",
                "[mcp_servers.foreign-tool.env]",
                'X = "1"',
                "",
                "[user.custom]",
                'key = "keep-me"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    data = tomllib.loads((codex / "config.toml").read_text(encoding="utf-8"))
    assert data["hooks"]["pre_tool_use"]["command"] == "agentkit-hook-codex"
    assert data["user"]["custom"]["key"] == "keep-me"
    assert data["mcp_servers"]["foreign-tool"]["command"] == "echo"
    assert data["mcp_servers"]["foreign-tool"]["env"]["X"] == "1"
    assert "story-knowledge-base" in data["mcp_servers"]


def test_r01_preserves_foreign_datetime_array_of_tables(tmp_path: Path) -> None:
    """R01: foreign datetime + [[array-of-tables]] must not refuse registration."""
    root = tmp_path / "proj"
    root.mkdir()
    codex = root / ".codex"
    codex.mkdir()
    foreign = (
        'released = 1979-05-27T07:32:00Z\n'
        "\n"
        "[[plugins]]\n"
        'name = "alpha"\n'
        "\n"
        "[[plugins]]\n"
        'name = "beta"\n'
        "\n"
        "[hooks.pre_tool_use]\n"
        'command = "keep"\n'
    )
    (codex / "config.toml").write_text(foreign, encoding="utf-8")
    write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    text = (codex / "config.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert isinstance(data["released"], datetime)
    assert data["released"] == datetime(1979, 5, 27, 7, 32, tzinfo=UTC)
    assert data["plugins"] == [{"name": "alpha"}, {"name": "beta"}]
    assert data["hooks"]["pre_tool_use"]["command"] == "keep"
    assert "story-knowledge-base" in data["mcp_servers"]
    # Foreign source spans remain (surgical merge, not full re-serialize).
    assert "1979-05-27T07:32:00Z" in text
    assert "[[plugins]]" in text


def test_r01_preserves_foreign_nested_array_of_tables(tmp_path: Path) -> None:
    """R01: nested AoT ``[[tool.items]]`` must survive registration."""
    root = tmp_path / "proj"
    root.mkdir()
    codex = root / ".codex"
    codex.mkdir()
    foreign = (
        "[tool]\n"
        'kind = "linter"\n'
        "\n"
        "[[tool.items]]\n"
        'id = "one"\n'
        "\n"
        "[[tool.items]]\n"
        'id = "two"\n'
    )
    (codex / "config.toml").write_text(foreign, encoding="utf-8")
    write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    text = (codex / "config.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["tool"]["kind"] == "linter"
    assert data["tool"]["items"] == [{"id": "one"}, {"id": "two"}]
    assert "[[tool.items]]" in text
    assert "story-knowledge-base" in data["mcp_servers"]


def test_r02_preserves_foreign_control_char_value_as_valid_toml(tmp_path: Path) -> None:
    """R02: foreign string with control char stays valid, value-equal TOML."""
    root = tmp_path / "proj"
    root.mkdir()
    codex = root / ".codex"
    codex.mkdir()
    # tomllib decodes "\\b" to U+0008; surgical merge must not re-emit raw 0x08.
    foreign = 'note = "\\b"\n'
    (codex / "config.toml").write_text(foreign, encoding="utf-8")
    before_parsed = tomllib.loads(foreign)
    write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    text = (codex / "config.toml").read_text(encoding="utf-8")
    after = tomllib.loads(text)  # must not raise Illegal character
    assert after["note"] == before_parsed["note"] == "\b"
    assert "story-knowledge-base" in after["mcp_servers"]
    # Foreign line span preserved literally.
    assert 'note = "\\b"' in text or 'note = "\\u0008"' in text or "note =" in text


def test_idempotent_merge_is_value_equal(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = _entry(cwd=str(root))
    write_mcp_server(root, "story-knowledge-base", entry)
    first = (root / ".codex" / "config.toml").read_bytes()
    _text, changed = merge_mcp_server(root, "story-knowledge-base", entry)
    assert changed is False
    write_mcp_server(root, "story-knowledge-base", entry)
    assert (root / ".codex" / "config.toml").read_bytes() == first


def test_foreign_occupied_own_name_non_table_refuses(tmp_path: Path) -> None:
    """Own server name occupied by a non-table → named error, byte-identical."""
    root = tmp_path / "proj"
    root.mkdir()
    path = root / ".codex" / "config.toml"
    path.parent.mkdir()
    original = b'[mcp_servers]\nstory-knowledge-base = "not-a-table"\n'
    path.write_bytes(original)
    with pytest.raises(CodexMcpConfigError) as excinfo:
        write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    assert "table" in excinfo.value.detail.lower() or "non-table" in excinfo.value.detail
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "payload,match",
    [
        (b"\xff\xfe not utf8", "UTF-8"),
        (b"mcp_servers = 42\n", "table"),
        (b'[mcp_servers.story-knowledge-base]\ncommand = 7\n', "command"),
        (
            b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nargs = "nope"\n',
            "args",
        ),
        (
            b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nrequired = "yes"\n',
            "required",
        ),
        (
            b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nenv = "x"\n',
            "env",
        ),
        (
            b'[mcp_servers.story-knowledge-base]\ncommand = "c"\ncwd = 99\n',
            "cwd",
        ),
        (b"mcp_servers = []\n", "table"),
        (
            b'[mcp_servers."story-knowledge-base"]\ncommand = "c"\n'
            b'[mcp_servers."story-knowledge-base"]\ncommand = "d"\n',
            "TOML",
        ),
        # Duplicate key in same table (tomllib).
        (
            b'[mcp_servers.foreign]\ncommand = "a"\ncommand = "b"\n',
            "TOML",
        ),
    ],
)
def test_strict_matrix_refuses_write(
    tmp_path: Path, payload: bytes, match: str
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    path = root / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_bytes(payload)
    before = path.read_bytes()
    with pytest.raises(CodexMcpConfigError) as excinfo:
        write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    assert match.lower() in excinfo.value.detail.lower() or match in excinfo.value.detail
    assert path.read_bytes() == before


def test_empty_cwd_on_entry_refused(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(CodexMcpConfigError, match="cwd"):
        write_mcp_server(
            root,
            "story-knowledge-base",
            CodexMcpServerEntry(
                command="x",
                args=(),
                cwd="",
                env={"PROJECT_ID": "P"},
                required=True,
            ),
        )


def test_symlink_escape_refused(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "config.toml"
    outside_file.write_text("x = 1\n", encoding="utf-8")
    codex = root / ".codex"
    try:
        os.symlink(outside, codex, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink not available: {exc}")
    before = outside_file.read_bytes()
    with pytest.raises(CodexMcpConfigError, match="escape|symlink|junction"):
        write_mcp_server(root, "story-knowledge-base", _entry(cwd=str(root)))
    assert outside_file.read_bytes() == before


def test_project_path_helper_is_project_local(tmp_path: Path) -> None:
    root = tmp_path / "p"
    assert project_codex_mcp_config_path(root) == root / ".codex" / "config.toml"
