"""Deterministic source-unit partition tests (FK-78 section 78.7)."""

from __future__ import annotations

import hashlib

from concept_toolchain.units import anchored_outline, derive_units, lf_normalize, section_index, text_digest

DOC = (
    "Preamble line one.\n"
    "Preamble line two.\n"
    "\n"
    "# Alpha\n"
    "Alpha body.\n"
    "\n"
    "## Beta\n"
    "Beta body.\n"
)


def test_preamble_before_first_heading_is_own_unit() -> None:
    units = derive_units("doc.md", DOC)
    assert units[0].locator == "doc.md#L1-L3"
    assert "Preamble line one." in units[0].text


def test_atx_headings_start_units() -> None:
    units = derive_units("doc.md", DOC)
    assert [unit.locator for unit in units] == ["doc.md#L1-L3", "doc.md#alpha", "doc.md#beta"]


def test_partition_is_complete_and_overlap_free() -> None:
    units = derive_units("doc.md", DOC)
    expected_start = 1
    for unit in units:
        assert unit.start_line == expected_start
        expected_start = unit.end_line + 1
    assert units[-1].end_line == len(DOC.split("\n"))


def test_setext_headings_start_units() -> None:
    text = "Title\n=====\nBody.\n\nSecond\n------\nMore.\n"
    units = derive_units("doc.md", text)
    assert [unit.locator for unit in units] == ["doc.md#title", "doc.md#second"]
    outline = anchored_outline(text)
    assert [(heading.level, heading.anchor) for heading in outline] == [(1, "title"), (2, "second")]


def test_headings_inside_fences_do_not_count() -> None:
    text = "# Real\n\n```md\n# Fenced\n```\n\nTail.\n"
    units = derive_units("doc.md", text)
    assert [unit.locator for unit in units] == ["doc.md#real"]
    assert "# Fenced" in units[0].text


def test_duplicate_headings_are_disambiguated() -> None:
    text = "# Section\nA.\n# Section\nB.\n# Section\nC.\n"
    units = derive_units("doc.md", text)
    assert [unit.locator for unit in units] == ["doc.md#section", "doc.md#section-1", "doc.md#section-2"]


def test_non_markdown_sources_partition_into_paragraphs() -> None:
    text = "first block line a\nfirst block line b\n\nsecond block\n\n\nthird block\n"
    units = derive_units("notes.txt", text)
    assert [unit.locator for unit in units] == ["notes.txt#L1-L2", "notes.txt#L4-L4", "notes.txt#L7-L7"]


def test_empty_source_has_no_units() -> None:
    assert derive_units("doc.md", "") == ()
    assert derive_units("doc.md", "\n\n  \n") == ()


def test_markdown_without_headings_is_one_preamble_unit() -> None:
    units = derive_units("doc.md", "Only prose.\nSecond line.\n")
    assert len(units) == 1
    assert units[0].locator == "doc.md#L1-L3"


def test_unit_digest_is_lf_normalized() -> None:
    lf_units = derive_units("doc.md", DOC)
    crlf_units = derive_units("doc.md", DOC.replace("\n", "\r\n"))
    assert [unit.digest for unit in lf_units] == [unit.digest for unit in crlf_units]


def test_unit_digest_matches_sha256_of_text() -> None:
    unit = derive_units("doc.md", DOC)[1]
    assert unit.digest == hashlib.sha256(unit.text.encode("utf-8")).hexdigest()


def test_section_index_maps_heading_anchors_only() -> None:
    index = section_index("doc.md", DOC)
    assert set(index) == {"alpha", "beta"}
    assert index["beta"].text.startswith("## Beta")


def test_text_digest_and_lf_normalize() -> None:
    assert lf_normalize("a\r\nb\rc") == "a\nb\nc"
    assert text_digest("a\r\nb") == hashlib.sha256(b"a\nb").hexdigest()


def test_frontmatter_stays_in_preamble_unit() -> None:
    text = "---\ntitle: X\n---\n\n# Head\nBody.\n"
    units = derive_units("doc.md", text)
    assert [unit.locator for unit in units] == ["doc.md#L1-L4", "doc.md#head"]
