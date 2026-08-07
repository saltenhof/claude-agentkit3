"""Deterministic physical-line spans and exact evidence extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

MAX_EVIDENCE_CHARS = 2_000


class SourceSpanReference(Protocol):
    """Structural contract shared by W2 and W3 response models.

    The members are declared read-only on purpose. Span extraction never writes
    a coordinate back, and every implementation (``NormativeAssertion``,
    ``QuotedAssertion``) is a frozen model. A protocol with mutable attributes
    would demand write access that no implementation offers -- and none can
    satisfy it.
    """

    @property
    def source_id(self) -> str:
        """Return the gate-owned source this reference points into."""

    @property
    def start_id(self) -> str:
        """Return the first boundary label of the referenced span."""

    @property
    def end_id(self) -> str:
        """Return the last boundary label of the referenced span."""


class SourceSpanContractError(ValueError):
    """Raised when evaluator-reported boundaries cannot name valid evidence."""


@dataclass(frozen=True)
class SourceSpan:
    """One deterministic physical-line span in gate-owned source text."""

    span_id: str
    start: int
    end: int


@dataclass(frozen=True)
class SourceSpanMap:
    """Gate-owned source text plus its deterministic boundary index."""

    source_id: str
    text: str
    spans: tuple[SourceSpan, ...]

    @property
    def annotated_text(self) -> str:
        """Return source text with non-source boundary labels inserted."""
        parts: list[str] = []
        for span in self.spans:
            parts.append(f"<{span.span_id}>")
            parts.append(self.text[span.start : span.end])
        return "".join(parts)

    @property
    def prompt_value(self) -> dict[str, str]:
        """Return the minimal source representation sent to an evaluator."""
        return {"source_id": self.source_id, "annotated_content": self.annotated_text}


@dataclass(frozen=True)
class ExtractedSourceSpan:
    """One validated exact slice of gate-owned source text."""

    source_id: str
    start: int
    end: int
    text: str


def build_source_span_map(source_id: str, text: str) -> SourceSpanMap:
    """Label physical source lines without normalizing their line endings."""
    lines = text.splitlines(keepends=True) or [text]
    spans: list[SourceSpan] = []
    cursor = 0
    for index, line in enumerate(lines):
        end = cursor + len(line)
        spans.append(SourceSpan(span_id=f"s{index:06d}", start=cursor, end=end))
        cursor = end
    return SourceSpanMap(source_id=source_id, text=text, spans=tuple(spans))


def extract_source_spans(
    references: tuple[SourceSpanReference, ...],
    sources: tuple[SourceSpanMap, ...],
    *,
    max_chars: int = MAX_EVIDENCE_CHARS,
) -> tuple[ExtractedSourceSpan, ...]:
    """Validate all references together and return exact, non-overlapping slices."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    source_by_id = {source.source_id: source for source in sources}
    if len(source_by_id) != len(sources):
        raise SourceSpanContractError("gate source IDs must be unique")
    extracted: list[ExtractedSourceSpan] = []
    intervals: dict[str, list[tuple[int, int]]] = {}
    for reference in references:
        source = source_by_id.get(reference.source_id)
        if source is None:
            raise SourceSpanContractError(f"reported foreign source {reference.source_id!r}")
        spans = {span.span_id: (index, span) for index, span in enumerate(source.spans)}
        start_item = spans.get(reference.start_id)
        if start_item is None:
            raise SourceSpanContractError(f"reported start span {reference.start_id!r} is absent")
        end_item = spans.get(reference.end_id)
        if end_item is None:
            raise SourceSpanContractError(f"reported end span {reference.end_id!r} is absent")
        start_index, start_span = start_item
        end_index, end_span = end_item
        if start_index > end_index:
            raise SourceSpanContractError("reported span boundaries are reversed")
        start = start_span.start
        end = end_span.end
        evidence = source.text[start:end]
        if not evidence.strip():
            raise SourceSpanContractError("reported span is empty")
        if len(evidence) > max_chars:
            raise SourceSpanContractError(
                f"reported span length {len(evidence)} exceeds maximum {max_chars}"
            )
        for other_start, other_end in intervals.setdefault(source.source_id, []):
            if start < other_end and other_start < end:
                raise SourceSpanContractError("reported spans overlap")
        intervals[source.source_id].append((start, end))
        extracted.append(
            ExtractedSourceSpan(
                source_id=source.source_id,
                start=start,
                end=end,
                text=evidence,
            )
        )
    return tuple(extracted)
