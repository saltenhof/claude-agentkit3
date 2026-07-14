"""Evaluator port separating LLM classification from W2 policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

    from concept_governance.models import ChunkClassification


class AuthorityProseEvaluator(Protocol):
    """Classify one deterministic concept chunk without deciding policy."""

    @property
    def model(self) -> str:
        """Return the resolved model/backend identity."""
        ...

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Return a typed classification for one chunk."""
        ...


@runtime_checkable
class BatchAuthorityProseEvaluator(AuthorityProseEvaluator, Protocol):
    """Evaluator that owns bounded external lease epochs for one run."""

    def __enter__(self) -> BatchAuthorityProseEvaluator:
        """Acquire resources for the corpus batch."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Release batch resources even when evaluation fails."""
        ...

    def checkpoint(self, chunk_id: str) -> None:
        """Commit one fully parsed and policy-processed chunk."""
        ...


class EvaluationBatchLifecycle(Protocol):
    """Lifecycle seam used by productive routed evaluators."""

    def open(self) -> None:
        """Acquire the batch resource."""
        ...

    def close(self) -> None:
        """Release the batch resource best-effort."""
        ...

    def checkpoint(self, chunk_id: str) -> None:
        """Rotate the lease when the bounded epoch is complete."""
        ...
