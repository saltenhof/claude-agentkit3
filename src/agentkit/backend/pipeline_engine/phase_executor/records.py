"""Phase-executor records: immutable attempt data for one phase execution.

Source of truth: FK-39 §39.4.1 — AttemptRecord schema.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.backend.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.backend.pipeline_engine.phase_executor.models import PhaseName

__all__ = ("AttemptRecord",)

_FAILURE_OUTCOMES = frozenset({
    AttemptOutcome.FAILED,
    AttemptOutcome.BLOCKED,
    AttemptOutcome.ESCALATED,
})


class AttemptRecord(BaseModel):
    """Immutable record of a single phase execution attempt.

    Identity: ``(run_id, phase, attempt)`` — consistent with Primary-Key
    in the ``attempts`` table (FK-39 §39.4.1).

    Args:
        run_id: The pipeline run identifier.
        phase: The phase name (``PhaseName`` StrEnum).
        attempt: Sequence number of this attempt within the phase (>= 1).
        outcome: Typed outcome of this attempt (``AttemptOutcome``).
        failure_cause: Required when ``outcome in {FAILED, BLOCKED, ESCALATED}``,
            must be ``None`` otherwise.  Enforced by Pydantic validator and by
            the DB CHECK constraint ``failure_cause_consistency``.
        started_at: Wall-clock timestamp when this attempt started.
        ended_at: Wall-clock timestamp when this attempt ended (>= started_at).
        detail: Untyped diagnostic payload (guard evaluations, artifact lists,
            resume trigger, etc.).  Long-term typed references are AG3-041 scope.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    phase: PhaseName
    attempt: int
    outcome: AttemptOutcome
    failure_cause: FailureCause | None = None
    started_at: datetime
    ended_at: datetime
    detail: dict[str, Any] | None = None

    @field_validator("attempt")
    @classmethod
    def _attempt_ge_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"attempt must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _validate_failure_cause_consistency(self) -> AttemptRecord:
        """FK-39 §39.4.3 Z. 425: failure_cause iff outcome in failure group."""
        if self.outcome in _FAILURE_OUTCOMES and self.failure_cause is None:
            raise ValueError(
                f"failure_cause must be set when outcome is {self.outcome!r}; "
                f"got None"
            )
        if self.outcome not in _FAILURE_OUTCOMES and self.failure_cause is not None:
            raise ValueError(
                f"failure_cause must be None when outcome is {self.outcome!r}; "
                f"got {self.failure_cause!r}"
            )
        return self

    @model_validator(mode="after")
    def _validate_ended_at_ge_started_at(self) -> AttemptRecord:
        if self.ended_at < self.started_at:
            raise ValueError(
                f"ended_at ({self.ended_at.isoformat()!r}) must be >= "
                f"started_at ({self.started_at.isoformat()!r})"
            )
        return self

    def attempt_correlation_id(self) -> str:
        """Ad-hoc correlation key: ``'{run_id}-{phase}-{attempt}'``."""
        return f"{self.run_id}-{self.phase}-{self.attempt}"

    def detail_json(self) -> str | None:
        """Serialize ``detail`` to a JSON string, or return ``None``."""
        if self.detail is None:
            return None
        return json.dumps(self.detail, sort_keys=True, default=str)
