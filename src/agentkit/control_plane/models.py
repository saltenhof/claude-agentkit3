"""Pydantic request/response models for the control plane."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# RUNTIME re-import of the canonical FK-56 operating-mode literal from its SINGLE
# foundation definition (``core_types.operating_mode``). Pydantic must resolve this
# annotation at model-build time, so it cannot live behind ``TYPE_CHECKING``; the
# ``noqa: TC001`` is the deliberate suppression of the type-only-import hint. These
# read models (``EdgePointer``/``SessionRunBindingView``) re-use the ONE canonical
# object instead of redeclaring the inline literal -- true AK2 SSOT, no drift.
from agentkit.core_types.operating_mode import OperatingMode  # noqa: TC001
from agentkit.telemetry.events import EventType

_CORRELATION_HEADER = "X-Correlation-Id"
_bc_route_logger = logging.getLogger(__name__ + ".bc_route_response")


class TelemetryEventIngestRequest(BaseModel):
    """Canonical request payload for one telemetry ingest call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime
    source_component: str = Field(min_length=1)
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    event_id: str | None = None
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class TelemetryEventAccepted(BaseModel):
    """HTTP response body for a successfully ingested telemetry event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted"] = "accepted"
    event_id: str


class ApiErrorResponse(BaseModel):
    """Stable error contract for control-plane HTTP responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: str = Field(min_length=1)
    error: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    detail: object | None = None


# ---------------------------------------------------------------------------
# BC-route response helpers (relocated from control_plane_http.bc_route_response
# by AG3-090 AC011 fix — shared contract belongs in control_plane_records, not
# the entry boundary).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BcRouteResponse:
    """Serializable response produced by a BC HTTP adapter.

    Attributes:
        status_code: HTTP status code.
        body: Response body bytes.
        headers: Response headers.
    """

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


def bc_json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> BcRouteResponse:
    """Build a JSON BcRouteResponse."""
    return BcRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def bc_error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> BcRouteResponse:
    """Build a structured error BcRouteResponse (typed Pydantic, ARCH-55)."""
    payload = ApiErrorResponse(
        error_code=error_code,
        error=message,
        correlation_id=correlation_id,
        detail=detail,
    ).model_dump(mode="json", exclude_none=True)
    return BcRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def bc_unavailable_response(
    error_code: str,
    *,
    message: str,
    correlation_id: str,
) -> BcRouteResponse:
    """Return a structured 503 when the backend service is unavailable.

    FAIL-CLOSED: no silent empty-200 or bare 500.  ``error_code`` must be
    ``*_unavailable`` (ARCH-55 english, stable wire key).
    """
    _bc_route_logger.warning("BC service unavailable (%s): %s", error_code, message)
    return bc_error_response(
        HTTPStatus.SERVICE_UNAVAILABLE,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
    )


class _ControlPlaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")
    source_component: str = Field(min_length=1, default="project_edge_client")


class PhaseMutationRequest(_ControlPlaneRequest):
    """Canonical request payload for a phase mutation."""

    principal_type: str = Field(min_length=1)
    worktree_roots: list[str] = Field(min_length=1)
    detail: dict[str, object] = Field(default_factory=dict)


class ClosureCompleteRequest(_ControlPlaneRequest):
    """Canonical request payload for closure completion."""

    detail: dict[str, object] = Field(default_factory=dict)


class ProjectEdgeSyncRequest(BaseModel):
    """Canonical request payload for a bounded project-edge sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")
    freshness_class: Literal["baseline_read", "guarded_read", "mutation"] = (
        "guarded_read"
    )


class EdgePointer(BaseModel):
    """Atomic pointer to one locally materializable edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    export_version: str
    operating_mode: OperatingMode
    bundle_dir: str
    sync_after: datetime
    freshness_class: Literal["baseline_read", "guarded_read", "mutation"]
    generated_at: datetime


class SessionRunBindingView(BaseModel):
    """Serializable session binding materialized into the edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: list[str]
    binding_version: str
    operating_mode: OperatingMode


class StoryExecutionLockView(BaseModel):
    """Serializable lock state materialized into the edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    run_id: str
    lock_type: str
    status: Literal["ACTIVE", "INACTIVE", "INVALID"]
    worktree_roots: list[str]
    binding_version: str
    activated_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None


class EdgeBundle(BaseModel):
    """Complete bundle that the local Project Edge Client publishes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current: EdgePointer
    session: SessionRunBindingView | None = None
    #: ``None`` only for a fast story (AG3-018 / FK-24 §24.3.4): a fast story
    #: materializes NO story-scoped ``story_execution`` lock, so the bundle
    #: carries no lock view and the local edge resolves to ``ai_augmented``
    #: (story-scoped guards do not activate; baseline guards remain). Every
    #: standard/exploration bundle still carries an authoritative lock.
    lock: StoryExecutionLockView | None = None
    qa_lock: StoryExecutionLockView | None = None
    tombstone_worktree_roots: list[str] = Field(default_factory=list)


class PhaseDispatchResult(BaseModel):
    """Normalized single-phase dispatch result (FK-45 §45.1.2 / §45.3).

    Returned by the deterministic phase dispatch and carried back on the
    control-plane mutation response so the calling orchestrator-skill reads the
    structured phase outcome (phase-state + orchestrator reaction) WITHOUT a
    second state-read path. One dispatch call == exactly one phase run.

    ``reaction`` mirrors the FK-45 §45.3 reaction table outcome class
    (``run_worker`` / ``advance`` / ``await_external`` / ``escalate`` /
    ``rejected``). ``next_phase`` is only suggested on a ``phase_completed``
    result; the orchestrator (not the dispatch) decides whether to call it.
    A ``rejected`` dispatch (pre-start guard / invalid transition) carries
    ``rejection_reason`` and never entered the phase handler.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: str
    status: Literal[
        "phase_completed",
        "yielded",
        "failed",
        "escalated",
        "rejected",
    ]
    reaction: Literal[
        "run_worker",
        "advance",
        "await_external",
        "escalate",
        "rejected",
    ]
    dispatched: bool
    next_phase: str | None = None
    yield_status: str | None = None
    rejection_reason: str | None = None
    errors: tuple[str, ...] = ()


class ControlPlaneMutationResult(BaseModel):
    """Shared response body for mutations, sync, and op reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["committed", "replayed", "synced", "rejected"]
    op_id: str
    operation_kind: str
    run_id: str | None = None
    phase: str | None = None
    #: ``None`` ONLY for a fail-closed REJECTED start (AG3-054; FK-20 §20.8.2).
    #: A rejected start materializes NO story-scoped guard regime -- no session
    #: binding, no lock-records, no ``phase_start`` edge bundle -- so there is no
    #: bundle to carry and the rejection is NOT stored as a committed op (a later
    #: retry re-evaluates once Approved+READY). Every committed / replayed /
    #: synced result still carries an authoritative ``edge_bundle``; the rejection
    #: travels on ``phase_dispatch``.
    edge_bundle: EdgeBundle | None = None
    #: AG3-054: the normalized single-phase dispatch outcome (FK-45 §45.1.2).
    #: ``None`` for non-dispatch operations (closure-complete, edge-sync) and
    #: for replays of pre-AG3-054 records; present on every ``start_phase``
    #: dispatch so the one truth carries both the idempotent edge bundle and the
    #: phase result without a second response path.
    phase_dispatch: PhaseDispatchResult | None = None

    @model_validator(mode="after")
    def _edge_bundle_optionality_is_bound_to_rejection(self) -> ControlPlaneMutationResult:
        """Enforce: ``edge_bundle`` is ``None`` ONLY for a ``rejected`` result.

        The field was widened to optional solely so a fail-closed REJECTED start
        (AG3-054; FK-20 §20.8.2) can travel without materializing a story-scoped
        edge bundle. That optionality must NOT leak to success statuses: a
        ``committed`` / ``replayed`` / ``synced`` result with ``edge_bundle=None``
        would let the project-edge client silently skip publishing an
        authoritative bundle (a fail-open activation gap). Conversely a
        ``rejected`` result MUST carry no bundle (it materialized none). Enforced
        at the model boundary (FAIL-CLOSED, fix the model).
        """
        if self.status == "rejected":
            if self.edge_bundle is not None:
                msg = "a 'rejected' ControlPlaneMutationResult must not carry an edge_bundle"
                raise ValueError(msg)
        elif self.edge_bundle is None:
            msg = (
                f"a {self.status!r} ControlPlaneMutationResult must carry an "
                "edge_bundle (None is allowed only for 'rejected')"
            )
            raise ValueError(msg)
        return self
