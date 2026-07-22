"""Chunking overflow and heading splits."""

from __future__ import annotations

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile


def test_heading_split_h2_h3() -> None:
    body = """Intro line.

## One

Paragraph one.

### One A

Detail.

## Two

Paragraph two.
"""
    profile = get_profile(IngestProfileId.FK13_STORY)
    chunks, findings = chunk_markdown(body, profile=profile, title="Doc")
    assert not findings
    headings = [c.section_heading for c in chunks]
    assert "One" in headings
    assert "Two" in headings
    assert any("One A" in h or h == "One A" for h in headings)


def test_overflow_split_deterministic() -> None:
    # Build text large enough to exceed token limit when not split by headings.
    para = "word " * 400
    body = f"## Big\n\n{para}\n\n{para}\n\n{para}"
    profile = get_profile(IngestProfileId.FK13_STORY)
    chunks, findings = chunk_markdown(body, profile=profile, title="BigDoc")
    assert findings  # overflow finding reported
    assert len(chunks) >= 2
    # Deterministic: same input -> same hashes
    chunks2, _ = chunk_markdown(body, profile=profile, title="BigDoc")
    assert [c.content_hash for c in chunks] == [c.content_hash for c in chunks2]
