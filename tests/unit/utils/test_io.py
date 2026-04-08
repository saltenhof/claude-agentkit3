"""Tests for agentkit.utils.io -- atomic write and directory helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.utils.io import atomic_write_text, atomic_write_yaml, ensure_dir


class TestAtomicWriteText:
    """Tests for atomic_write_text."""

    def test_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "output.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        atomic_write_text(target, "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "overwrite.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_temp_file_remains_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.txt"
        atomic_write_text(target, "content")
        remaining = list(tmp_path.iterdir())
        assert remaining == [target]

    def test_unicode_content(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.txt"
        content = "Umlaute: \u00e4\u00f6\u00fc\u00df, Emoji: \u2728, CJK: \u4e16\u754c"
        atomic_write_text(target, content)
        assert target.read_text(encoding="utf-8") == content

    def test_empty_content(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.txt"
        atomic_write_text(target, "")
        assert target.read_text(encoding="utf-8") == ""

    def test_json_roundtrip(self, tmp_path: Path) -> None:
        """Verify atomic_write_text works correctly for JSON persistence."""
        target = tmp_path / "data.json"
        data = {"key": "value", "nested": {"list": [1, 2, 3]}}
        content = json.dumps(data, indent=2, sort_keys=True)
        atomic_write_text(target, content)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == data


class TestAtomicWriteYaml:
    """Tests for atomic_write_yaml."""

    def test_writes_yaml(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yaml"
        data: dict[str, object] = {"name": "test", "version": 1}
        atomic_write_yaml(target, data)
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "dir" / "config.yaml"
        data: dict[str, object] = {"key": "value"}
        atomic_write_yaml(target, data)
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert loaded == data

    def test_preserves_insertion_order(self, tmp_path: Path) -> None:
        target = tmp_path / "ordered.yaml"
        data: dict[str, object] = {"z_last": 1, "a_first": 2, "m_middle": 3}
        atomic_write_yaml(target, data)
        text = target.read_text(encoding="utf-8")
        lines = [line.split(":")[0] for line in text.strip().splitlines()]
        assert lines == ["z_last", "a_first", "m_middle"]

    def test_unicode_values(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.yaml"
        data: dict[str, object] = {"name": "\u00dc\u00e4\u00f6"}
        atomic_write_yaml(target, data)
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert loaded["name"] == "\u00dc\u00e4\u00f6"


class TestEnsureDir:
    """Tests for ensure_dir."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "new_dir"
        result = ensure_dir(target)
        assert target.is_dir()
        assert result == target

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"
        result = ensure_dir(target)
        assert target.is_dir()
        assert result == target

    def test_idempotent_on_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        result = ensure_dir(target)
        assert target.is_dir()
        assert result == target

    def test_returns_path_for_chaining(self, tmp_path: Path) -> None:
        target = tmp_path / "chain"
        file_path = ensure_dir(target) / "file.txt"
        file_path.write_text("chained", encoding="utf-8")
        assert file_path.read_text(encoding="utf-8") == "chained"


class TestBackwardsCompatibility:
    """Verify that project_ops.shared.file_ops re-exports work."""

    def test_file_ops_reexport_atomic_write_text(self) -> None:
        from agentkit.project_ops.shared.file_ops import (
            atomic_write_text as reexported,
        )
        from agentkit.utils.io import atomic_write_text as original

        assert reexported is original

    def test_file_ops_reexport_atomic_write_yaml(self) -> None:
        from agentkit.project_ops.shared.file_ops import (
            atomic_write_yaml as reexported,
        )
        from agentkit.utils.io import atomic_write_yaml as original

        assert reexported is original

    def test_file_ops_reexport_ensure_dir(self) -> None:
        from agentkit.project_ops.shared.file_ops import (
            ensure_dir as reexported,
        )
        from agentkit.utils.io import ensure_dir as original

        assert reexported is original
