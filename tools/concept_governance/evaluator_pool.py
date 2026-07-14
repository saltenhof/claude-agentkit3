"""Deterministic backend routing over independent evaluator slot pools."""

from __future__ import annotations

import uuid
from queue import Queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

    from concept_governance.models import ChunkClassification
    from concept_governance.port import AuthorityProseEvaluator, EvaluationBatchLifecycle


class RoutedAuthorityProseEvaluator:
    """Route each stable chunk ID to one backend family and any free slot."""

    def __init__(
        self,
        evaluators: dict[str, tuple[AuthorityProseEvaluator, ...]],
        route_models: tuple[str, ...],
        lifecycle: EvaluationBatchLifecycle | None = None,
    ) -> None:
        """Build queues whose repeated route entries weight backend capacity."""
        if not route_models or any(model not in evaluators for model in route_models):
            raise ValueError("route models require non-empty evaluator pools")
        self._pools: dict[str, Queue[AuthorityProseEvaluator]] = {}
        for model, slots in evaluators.items():
            pool: Queue[AuthorityProseEvaluator] = Queue()
            for evaluator in slots:
                pool.put(evaluator)
            self._pools[model] = pool
        self._route_models = route_models
        self._lifecycle = lifecycle
        self.parallelism = 1 if lifecycle is not None else sum(len(slots) for slots in evaluators.values())
        self._model = route_models[0] if len(set(route_models)) == 1 else "governance-pool/v1"

    def __enter__(self) -> RoutedAuthorityProseEvaluator:
        """Open the optional productive batch lifecycle."""
        if self._lifecycle is not None:
            self._lifecycle.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Close the optional productive batch lifecycle."""
        del exc_type, exc_value, traceback
        if self._lifecycle is not None:
            self._lifecycle.close()

    @property
    def model(self) -> str:
        """Return the run-level identity used for operational failures."""
        return self._model

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Classify through the chunk's deterministic backend family."""
        route_index = uuid.UUID(chunk.chunk_id).int % len(self._route_models)
        model = self._route_models[route_index]
        pool = self._pools[model]
        evaluator = pool.get()
        try:
            try:
                return evaluator.evaluate(chunk, vocabulary)
            except Exception as exc:
                raise RoutedEvaluationError(model, exc) from exc
        finally:
            pool.put(evaluator)


class RoutedEvaluationError(ValueError):
    """Evaluator failure annotated with the deterministic routed backend."""

    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.model = model
        self.cause = cause
