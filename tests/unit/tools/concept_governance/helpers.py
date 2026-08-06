"""Test builders for W2 using temporary working-tree concept corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from concept_governance.models import ChunkClassification
    from concept_governance.scope_contracts import ScopeEvaluation
    from concept_governance.scope_models import ScopePartition
    from concept_ingester.discovery import ConceptChunk


class ScriptedLlmClient:
    """Fixed transport fake at the LLM boundary only.

    Everything above it — prompt rendering, the three-stage parser, the
    escape repairs and the deterministic policy — stays productive, so a
    test can hand over the exact bytes a model sent and watch the real
    chain decide.
    """

    def __init__(self, responses: list[str | Exception]) -> None:
        """Initialize with one scripted response per expected call."""
        self.responses = responses
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, *, role: str, prompt: str) -> str:
        """Return the next scripted response or raise the scripted error."""
        del role
        self.prompts.append(prompt)
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


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


class ScriptedScopeEvaluator:
    """Fixed W3 evaluator fake at the LLM classification boundary only."""

    def __init__(
        self,
        classify: Callable[[ScopePartition], ScopeEvaluation],
        *,
        fail_at: int | None = None,
        error: Exception | None = None,
        model: str = "fixed/v1",
    ) -> None:
        self._classify = classify
        self._fail_at = fail_at
        self._error = error
        self._model = model
        self.calls: list[ScopePartition] = []

    @property
    def model(self) -> str:
        """Return the fixed model identity."""
        return self._model

    def evaluate(self, partition: ScopePartition) -> ScopeEvaluation:
        """Return one fixed response or fail at the scripted call."""
        self.calls.append(partition)
        if self._fail_at == len(self.calls) and self._error is not None:
            raise self._error
        return self._classify(partition)


def write_doc(
    concept_root: Path,
    name: str,
    doc_id: str,
    authority: str = "[]",
    defers_to: str = "[]",
    content: str = "The system must retain locks.",
) -> None:
    """Write one valid temporary domain concept with a single H2 chunk.

    ``status`` and ``doc_kind`` are MANDATORY frontmatter fields (FK-13 §13.9.6);
    without them the SSOT discovery core reports E-SCHEMA-002 and the ingester
    adapter refuses the corpus (no partial corpus, AG3-174 R06).
    """
    path = concept_root / "domain-design" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
concept_id: {doc_id}
title: {doc_id}
module: test
status: active
doc_kind: core
authority_over: {authority}
defers_to: {defers_to}
---
## Rule

{content}
        """,
        encoding="utf-8",
        newline="",
    )


def write_empty_baseline(path: Path) -> None:
    """Write the strict empty version-1 baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 1\nentries: []\n", encoding="utf-8")


def source_reference_fields(source_id: str, text: str, evidence: str) -> dict[str, str]:
    """Return boundary IDs for one exact test excerpt."""
    from concept_governance.source_spans import build_source_span_map

    start = text.index(evidence)
    end = start + len(evidence)
    span_map = build_source_span_map(source_id, text)
    by_start = {span.start: span.span_id for span in span_map.spans}
    by_end = {span.end: span.span_id for span in span_map.spans}
    return {
        "source_id": source_id,
        "start_id": by_start[start],
        "end_id": by_end[end],
    }
