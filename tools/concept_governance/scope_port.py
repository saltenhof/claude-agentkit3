"""Evaluator port separating W3 classification from deterministic policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from concept_governance.scope_contracts import ScopeEvaluation
    from concept_governance.scope_models import ScopePartition


class ScopeConsistencyEvaluator(Protocol):
    """Classify one closed scope partition without deciding policy."""

    @property
    def model(self) -> str:
        """Return the resolved backend identity."""
        ...

    def evaluate(self, partition: ScopePartition) -> ScopeEvaluation:
        """Return a typed contradiction classification."""
        ...


@runtime_checkable
class BatchScopeConsistencyEvaluator(ScopeConsistencyEvaluator, Protocol):
    """Evaluator owning a reused epoch-rotating Hub session."""

    def __enter__(self) -> BatchScopeConsistencyEvaluator:
        """Open the bounded batch lifecycle."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Close the lifecycle even after an incomplete sweep."""
        ...

    def checkpoint(self, partition_id: str) -> None:
        """Commit one parsed and policy-checked partition."""
        ...
