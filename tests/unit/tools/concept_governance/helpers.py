"""Test builders for W2 using temporary working-tree concept corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from concept_governance.models import ChunkClassification
    from concept_ingester.discovery import ConceptChunk


class ScriptedEvaluator:
    """Fixed evaluator fake at the LLM classification boundary only."""

    def __init__(
        self,
        classify: Callable[[ConceptChunk], ChunkClassification],
        *,
        error: Exception | None = None,
    ) -> None:
        self._classify = classify
        self._error = error
        self.calls: list[str] = []

    @property
    def model(self) -> str:
        """Return the fixed model identity."""
        return "fixed/v1"

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Return a fixed classification or raise the scripted boundary error."""
        del vocabulary
        self.calls.append(chunk.chunk_id)
        if self._error is not None:
            raise self._error
        return self._classify(chunk)


def write_doc(
    concept_root: Path,
    name: str,
    doc_id: str,
    authority: str = "[]",
    defers_to: str = "[]",
) -> None:
    """Write one valid temporary domain concept with a single H2 chunk."""
    path = concept_root / "domain-design" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
concept_id: {doc_id}
title: {doc_id}
module: test
authority_over: {authority}
defers_to: {defers_to}
---
## Rule

The system must retain locks.
""",
        encoding="utf-8",
    )


def write_empty_baseline(path: Path) -> None:
    """Write the strict empty version-1 baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 1\nentries: []\n", encoding="utf-8")
