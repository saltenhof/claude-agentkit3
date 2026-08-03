"""Unit tests for target-project .gitignore link-bindpoint hygiene (AG3-048).

FK-43 §43.4.1.1: the installer must git-ignore the harness link bind points
(``.claude/skills/`` and ``.codex/skills/``) in the TARGET project so a Windows
junction / POSIX symlink is never committed as the central bundle content
(invariant ``project_local_repo_never_contains_canonical_skill_source``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.runner import _ensure_link_bindpoint_gitignore

if TYPE_CHECKING:
    from pathlib import Path


class TestGitignoreLinkBindpointHygiene:
    def test_creates_gitignore_when_absent(self, tmp_path: Path) -> None:
        rel = _ensure_link_bindpoint_gitignore(tmp_path)
        assert rel == ".gitignore"
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert ".claude/skills/" in content
        assert ".codex/skills/" in content
        assert "__pycache__/" in content
        assert "*.py[cod]" in content

    def test_idempotent_second_call_is_noop(self, tmp_path: Path) -> None:
        first = _ensure_link_bindpoint_gitignore(tmp_path)
        assert first is not None
        second = _ensure_link_bindpoint_gitignore(tmp_path)
        assert second is None  # nothing left to add
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert content.count(".claude/skills/") == 1
        assert content.count(".codex/skills/") == 1
        assert content.count("__pycache__/") == 1
        assert content.count("*.py[cod]") == 1

    def test_merges_into_existing_gitignore_preserving_content(
        self, tmp_path: Path
    ) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# existing\n__pycache__/\n.venv/\n", encoding="utf-8")
        rel = _ensure_link_bindpoint_gitignore(tmp_path)
        assert rel == ".gitignore"
        content = gitignore.read_text(encoding="utf-8")
        # Pre-existing entries are preserved.
        assert "__pycache__/" in content
        assert ".venv/" in content
        # New bind-point entries are appended.
        assert ".claude/skills/" in content
        assert ".codex/skills/" in content

    def test_existing_entry_without_trailing_slash_is_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".claude/skills\n", encoding="utf-8")  # no trailing slash
        _ensure_link_bindpoint_gitignore(tmp_path)
        content = gitignore.read_text(encoding="utf-8")
        claude_lines = [ln for ln in content.splitlines() if "claude/skills" in ln]
        assert len(claude_lines) == 1  # normalised match -> not re-added
        assert ".codex/skills/" in content


class TestForeignGitignoreIsNotRewritten:
    """The installer appends to a file the project owns -- it may not reformat it.

    A lossless codec alone was not enough: reading with universal newlines
    turned every CRLF into LF, so the write handed the project back a file it
    had not written. The bytes that were there before must still be there,
    unchanged, byte for byte.
    """

    def test_crlf_and_non_utf8_bytes_survive_untouched(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        # cp1252 'ä' (0xE4), CRLF endings, and a trailing blank line.
        original = b"# Gr\xe4sse\r\n*.tmp\r\n\r\n"
        gitignore.write_bytes(original)

        _ensure_link_bindpoint_gitignore(tmp_path)

        after = gitignore.read_bytes()
        assert after.startswith(original), "existing bytes were rewritten"
        appended = after[len(original) :]
        assert b"\r\n" in appended, "the project's line ending was not carried on"
        assert b"\n" not in appended.replace(b"\r\n", b""), "a lone LF was introduced"
        assert b"\xef\xbf\xbd" not in after, "a byte was replaced by U+FFFD"

    def test_entries_are_still_added(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_bytes(b"# Gr\xe4sse\r\n")

        _ensure_link_bindpoint_gitignore(tmp_path)

        text = gitignore.read_text(encoding="utf-8", errors="surrogateescape")
        assert ".claude/skills/" in text
        assert ".codex/skills/" in text
