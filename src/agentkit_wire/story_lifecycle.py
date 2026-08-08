"""Story-lifecycle vocabulary of the ``/v1`` boundary (FK-54 / FK-53 / FK-58).

Split, reset and exit are the three administrative story-lifecycle operations
the operator triggers from the developer machine and the core executes. Both
sides speak them on the wire: the edge CLI builds the request and renders the
response, the core route validates it and commits the saga.

Membership follows the frozen classification --
``architecture-conformance.symbol_boundary.story_split_http_models``,
``...story_reset_http_models`` and ``...story_exit_http_models``. All three
entries carry ``module_dissolves: true``: the whole public surface of
``story_split.http_models``, ``story_reset.http_models`` and
``story_exit.http_models`` moves here and the three source modules are gone.
The target is the single ``agentkit_wire.story_lifecycle`` module named by
``architecture-conformance.wire_module.story_lifecycle`` (``symbol_count: 6``,
``hull_closed: true``).

Nothing here validates a *reason* against a closed set. ``ExitReason`` (FK-58)
stays with the core, which is the only side that may decide whether an exit
reason is admissible; the wire carries the string it was given and the core
answers ``400 invalid_story_exit_reason`` when it is not one. One validator, not
two.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StorySplitMutationRequest(BaseModel):
    """Wire request consumed by the single control-plane writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)


class StorySplitMutationResponse(BaseModel):
    """Stable terminal response returned by the writer-owned split route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    split_id: str
    source_story_id: str
    successor_ids: tuple[str, ...]
    resumed: bool


class StoryResetMutationRequest(BaseModel):
    """Authenticated administrative reset request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str
    reason: str
    project_root: str
    escalation_ref: str | None = None
    dry_run: bool = False
    force: bool = False


class StoryResetMutationResponse(BaseModel):
    """Plan or committed reset result returned by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    status: str
    reset_id: str
    story_id: str
    run_id: str | None = None
    planned_domains: tuple[str, ...] = ()
    clean_state: bool | None = None
    purge_summary: dict[str, int] = {}
    resumed: bool = False


class StoryExitMutationRequest(BaseModel):
    """Authenticated administrative exit request without identity attestations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str
    run_id: str
    reason: str
    note: str | None = None


class StoryExitMutationResponse(BaseModel):
    """Committed story-exit result returned by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    exit_id: str
    story_id: str
    operating_mode: str
    artifact_dir: str


__all__ = [
    "StoryExitMutationRequest",
    "StoryExitMutationResponse",
    "StoryResetMutationRequest",
    "StoryResetMutationResponse",
    "StorySplitMutationRequest",
    "StorySplitMutationResponse",
]
