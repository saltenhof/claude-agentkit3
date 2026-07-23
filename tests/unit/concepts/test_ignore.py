""".conceptignore glob boundary tests (FK-13 §13.9.13).

Covers the four required boundary cases -- NOT via bare Path.match.
"""

from __future__ import annotations

from agentkit.concepts.ignore import is_ignored, load_patterns

_P = load_patterns


def test_research_double_star_matches_direct_and_deep() -> None:
    patterns = _P(["research/**"])
    assert is_ignored("research/notes.md", patterns)
    assert is_ignored("research/sub/deep.md", patterns)
    assert is_ignored("research/a/b/c.md", patterns)


def test_research_double_star_slash_star_excludes_direct_children() -> None:
    patterns = _P(["research/**/*"])
    assert not is_ignored("research/notes.md", patterns)  # direct child NOT matched
    assert is_ignored("research/sub/deep.md", patterns)
    assert is_ignored("research/a/b/c.md", patterns)


def test_star_md_does_not_match_subdir() -> None:
    patterns = _P(["*.md"])
    assert is_ignored("foo.md", patterns)
    assert not is_ignored("sub/foo.md", patterns)


def test_drafts_slash_star_md() -> None:
    patterns = _P(["drafts/*.md"])
    assert is_ignored("drafts/one.md", patterns)
    assert not is_ignored("drafts/sub/two.md", patterns)
    assert not is_ignored("drafts/readme.txt", patterns)


def test_comments_and_blanks_ignored() -> None:
    patterns = _P(["# comment", "", "   ", "*.tmp"])
    assert len(patterns) == 1
    assert is_ignored("x.tmp", patterns)


def test_question_mark_matches_one_char_not_slash() -> None:
    patterns = _P(["draft?.md"])
    assert is_ignored("draft1.md", patterns)
    assert not is_ignored("draft12.md", patterns)
    assert not is_ignored("draft/1.md", patterns)


def test_multiple_patterns_union() -> None:
    patterns = _P(["research/**", "*.tmp", "drafts/*.md"])
    assert is_ignored("research/x.md", patterns)
    assert is_ignored("y.tmp", patterns)
    assert is_ignored("drafts/z.md", patterns)
    assert not is_ignored("concept/keep.md", patterns)
