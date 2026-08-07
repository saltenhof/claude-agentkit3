"""Request and result vocabulary of the ``/v1`` mutation endpoints.

Membership follows
``architecture-conformance.symbol_boundary.control_plane_models``. AG3-239 moved
the one symbol its bounded context needs; the remaining
``wire_exported_symbols`` of that entry follow in their owning bounded-context
stories.

Why this module exists at all is best shown by this symbol.
``/v1/governance/guard-counters`` was a finished, correctly mediated endpoint --
the hook process already reached the core over REST and never touched a
database. It still counted as a distribution boundary violation, purely because
its request model had no home that both sides were allowed to import. The
endpoint was never the problem; the vocabulary was.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GuardCounterMutationRequest(BaseModel):
    """Dev->Core request to mutate the guard-invocation counter scratchpad.

    AG3-129 (FK-10 §10.1.0 I1/I3): the short-lived hook process is a REST
    requester, never a direct-DB writer. This carries either a single ``record``
    invocation (with an implicit week-rollover drain, FK-61 §61.4.3) or a
    cross-story ``housekeeping`` sweep. Both are the pure volume-KPI counter
    (FK-30 "blockieren nie"): non-blocking on the Dev side; the counter is NOT
    the audit trail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["record", "housekeeping"]
    occurred_at: datetime
    #: Idempotency key (FK-91 §91.1a Rule 5): a replayed ``op_id`` is
    #: processed exactly once, so a retried record never double-counts the pure
    #: volume KPI. AG3-140: client-supplied (hook-side mint); no server default.
    op_id: str = Field(min_length=1)
    project_key: str | None = None
    story_id: str | None = None
    guard_key: str | None = None
    blocked: bool | None = None

    @model_validator(mode="after")
    def _require_record_fields(self) -> GuardCounterMutationRequest:
        """Fail-closed: a ``record`` operation must carry its full scope."""
        if self.operation == "record" and (
            not self.project_key
            or not self.story_id
            or not self.guard_key
            or self.blocked is None
        ):
            raise ValueError(
                "guard-counter record requires project_key, story_id, "
                "guard_key and blocked",
            )
        return self


__all__ = ["GuardCounterMutationRequest"]
