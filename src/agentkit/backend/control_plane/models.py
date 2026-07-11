"""Pydantic request/response models for the control plane."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# RUNTIME re-import of the canonical FK-56 operating-mode literal from its SINGLE
# foundation definition (``core_types.operating_mode``). Pydantic must resolve this
# annotation at model-build time, so it cannot live behind ``TYPE_CHECKING``; the
# ``noqa: TC001`` is the deliberate suppression of the type-only-import hint. These
# read models (``EdgePointer``/``SessionRunBindingView``) re-use the ONE canonical
# object instead of redeclaring the inline literal -- true AK2 SSOT, no drift.
from agentkit.backend.core_types.operating_mode import OperatingMode  # noqa: TC001
from agentkit.backend.story_creation.reconciliation_evidence import ReconciliationEvidence
from agentkit.backend.telemetry.events import EventType

_CORRELATION_HEADER = "X-Correlation-Id"
_bc_route_logger = logging.getLogger(__name__ + ".bc_route_response")


def op_id_validation_error(exc: ValidationError) -> bool:
    """Return whether a wire-model ``ValidationError`` is (also) an ``op_id`` failure.

    FK-91 §91.1a Rule 5: ``op_id`` is a client-supplied, required idempotency key
    (AG3-140 -- no server-side ``default_factory`` mint remains). A mutating
    request that omits ``op_id`` (or sends an empty string) must fail closed with
    ``422`` specifically, distinct from the route's ordinary ``400`` payload-shape
    rejection for unrelated fields (AC1).
    """
    return any(err["loc"] and err["loc"][0] == "op_id" for err in exc.errors())


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


class GuardCounterMutationRequest(BaseModel):
    """Dev->Core request to mutate the guard-invocation counter scratchpad.

    AG3-129 (FK-10 §10.1.0 I1/I3): the short-lived hook process is a REST
    requester, never a direct-DB writer. This carries either a single
    ``record`` invocation (with an implicit week-rollover drain, FK-61
    §61.4.3) or a cross-story ``housekeeping`` sweep. Both are the pure
    volume-KPI counter (FK-30 "blockieren nie"): non-blocking on the Dev
    side; the counter is NOT the audit trail.
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


class GuardCounterMutationAccepted(BaseModel):
    """HTTP response body for an accepted guard-counter mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted"] = "accepted"
    operation: Literal["record", "housekeeping"]
    drained: int = 0


class WorkerHealthStateResponse(BaseModel):
    """Server-mediated worker-health read result (AG3-129, FK-10 §10.3.2).

    ``state`` is the canonical ``AgentHealthState`` wire object, or ``None``
    when no health row exists for the ``(story_id, worker_id)`` scope. A
    transport / core-unreachable fault is a fail-closed error on the Dev
    side (never a silent empty ``None``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: dict[str, object] | None = None


class WorkerHealthSaveAccepted(BaseModel):
    """HTTP response body for an accepted worker-health write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted"] = "accepted"
    story_id: str
    worker_id: str


class TelemetryEventQueryResponse(BaseModel):
    """Server-mediated telemetry read result (AG3-129).

    Returns the canonical execution events for one ``(project_key, story_id)``
    scope, optionally filtered by ``event_type``. Backs the REST event emitter's
    ``query`` so the hook reads counts (web-call / commit) via the core instead
    of opening the database directly (FK-10 §10.1.0 I1).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: list[dict[str, object]] = Field(default_factory=list)


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
    #: FK-91 §91.1a Rule 5: client-supplied idempotency key. AG3-140: no server
    #: default remains -- an omitted op_id fails closed at validation (422).
    op_id: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class PhaseMutationRequest(_ControlPlaneRequest):
    """Canonical request payload for a phase mutation."""

    principal_type: str = Field(min_length=1)
    worktree_roots: list[str] = Field(min_length=1)
    detail: dict[str, object] = Field(default_factory=dict)


class ClosureCompleteRequest(_ControlPlaneRequest):
    """Canonical request payload for closure completion."""

    detail: dict[str, object] = Field(default_factory=dict)


class AdminAbortRequest(BaseModel):
    """Request payload for ``POST /v1/project-edge/operations/{op_id}/admin-abort``.

    FK-91 §91.1a ``admin_abort_inflight_operation`` (FK-55 §55.5
    ``admin_transition``): the target operation is identified by the URL path
    ``op_id`` (idempotent by construction -- a second abort call against an
    already-resolved op_id deterministically 409s, AC6). ``reason`` is a
    mandatory, audited justification (mirrors the Begruendungspflicht of the
    takeover-request endpoint); ``session_id``/``principal_type`` attribute the
    administrative actor for the audit trail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    principal_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class AdminTakeoverReconcileClearRequest(BaseModel):
    """Request payload for the pre-AG3-151 takeover reconcile admin clear.

    The productive reconcile contract arrives with AG3-151. Until then the frozen
    AG3-148 contract permits exactly one clear path: an audited
    ``admin_transition`` performed by a privileged human/service principal. The
    runtime writes the operation ledger row and the transfer-record clear in one
    transaction; callers may not clear by writing ``reconcile_ref`` directly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    principal_type: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class ProjectEdgeSyncRequest(BaseModel):
    """Canonical request payload for a bounded project-edge sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    #: FK-91 §91.1a Rule 5: client-supplied idempotency key (AG3-140: no server
    #: default).
    op_id: str = Field(min_length=1)
    freshness_class: Literal["baseline_read", "guarded_read", "mutation"] = (
        "guarded_read"
    )


class TakeoverRequest(BaseModel):
    """Request payload for ``takeover-request``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    principal_type: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    worktree_roots: list[str] = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class TakeoverRepoChallenge(BaseModel):
    """Per-repository pushed-only SHA evidence in a takeover challenge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    takeover_base_sha: str | None = None
    last_push_at: datetime | None = None
    push_lag_hint: str | None = None
    base_quality: str = Field(min_length=1)


class TakeoverChallenge(BaseModel):
    """Wire form of a versioned takeover challenge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    requesting_session_id: str = Field(min_length=1)
    requesting_principal_type: str = Field(min_length=1)
    current_owner_session_id: str = Field(min_length=1)
    ownership_epoch: int = Field(ge=1)
    binding_version: str = Field(min_length=1)
    phase_status: str = Field(min_length=1)
    owner_principal_type: str = Field(min_length=1)
    owner_bound_since: datetime | None = None
    last_owner_api_contact_at: datetime | None = None
    last_owner_api_contact_note: str = Field(min_length=1)
    open_operation_ids: list[str] = Field(default_factory=list)
    takeover_history_refs: list[str] = Field(default_factory=list)
    repos: list[TakeoverRepoChallenge] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    loss_corridor_notice_key: str = Field(min_length=1)
    loss_corridor_notice_text: str = Field(min_length=1)
    expires_at: datetime | None = None


class TakeoverConfirmRequest(BaseModel):
    """Wire payload for ``takeover-confirm`` (selector and audit only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class RecoveryRequest(BaseModel):
    """Wire payload for explicit human crash-recovery acquisition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class TakeoverDenyRequest(BaseModel):
    """Wire payload for human denial (selector and audit only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_component: str = Field(min_length=1, default="project_edge_client")


class TakeoverApprovalView(BaseModel):
    """Wire view of a takeover approval request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    requested_by_session_id: str = Field(min_length=1)
    requested_by_principal_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    status: Literal["pending", "approved", "denied", "expired", "invalidated"]
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by_session_id: str | None = None
    decision_reason: str | None = None


class PendingHumanApprovalResponse(BaseModel):
    """Typed pending-human-approval response for agent-initiated requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["pending_human_approval"] = "pending_human_approval"
    op_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    approval: TakeoverApprovalView


class CreateStoryInputs(BaseModel):
    """Typed story master data for the agent-facing create (FK-91 §91.1a).

    Carries ONLY the story content the caller supplies — never the
    ``reconciliation`` evidence. The evidence is produced exclusively by the real
    reconciliation runtime and attached internally by
    :meth:`CreateStoryRequest.from_evidence`, so the official create surface can
    never be handed a self-consistent, hand-built evidence dict (FK-21 §21.4 SSOT,
    FIX-THE-MODEL). ``repos`` is the caller-proposed repo set; the authoritative
    ``participating_repos`` comes from the reconciliation outcome (repo-affinity).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    project_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    story_type: str = Field(alias="type", min_length=1)
    repos: list[str] = Field(min_length=1)
    epic: str = ""
    module: str = ""
    size: str | None = None
    mode: str | None = None
    change_impact: str | None = None
    concept_quality: str | None = None
    owner: str = ""
    risk: str | None = None
    labels: list[str] = Field(default_factory=list)
    new_structures: bool = False


class CreateStoryRequest(BaseModel):
    """Canonical request payload for the agent-facing story create (FK-91 §91.1a).

    Carries the story master data (``CreateStoryInputs`` content via the wire
    ``type`` alias), the idempotency ``op_id`` (Rule #5) and the typed
    ``reconciliation`` evidence (FK-21 §21.4/§21.12) that the non-bypassable
    create boundary (``POST /v1/stories``) requires. The model serializes to the
    exact wire body the route consumes: the story content keys at top level, plus
    ``op_id`` and ``reconciliation``. The ``reconciliation`` block is mandatory —
    an absent / inconsistent block fail-closes at the route before any persistence
    (no in-body bypass, no dummy evidence).

    ``reconciliation`` is a typed :class:`ReconciliationEvidence`, NOT a raw dict:
    the request cannot be built around a hand-assembled, self-consistent evidence
    dict that fakes a reconciliation that never ran. The official client builds
    this request via :meth:`from_evidence` from a real reconciliation outcome
    only (FK-21 §21.4 "proof the reconciliation actually ran").
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    #: FK-91 §91.1a Rule 5: client-supplied idempotency key (AG3-140: no server
    #: default remains).
    op_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    story_type: str = Field(alias="type", min_length=1)
    repos: list[str] = Field(min_length=1)
    reconciliation: ReconciliationEvidence
    epic: str = ""
    module: str = ""
    size: str | None = None
    mode: str | None = None
    change_impact: str | None = None
    concept_quality: str | None = None
    owner: str = ""
    risk: str | None = None
    labels: list[str] = Field(default_factory=list)
    new_structures: bool = False

    @classmethod
    def from_evidence(
        cls,
        inputs: CreateStoryInputs,
        evidence: ReconciliationEvidence,
        *,
        op_id: str,
        participating_repos: tuple[str, ...] | None = None,
    ) -> CreateStoryRequest:
        """Build a create request from master data + REAL reconciliation evidence.

        The ``evidence`` MUST come from the deterministic reconciliation runtime
        (:meth:`StoryCreationReconciler.reconcile_only`), never hand-built. The
        authoritative ``repos`` are the reconciliation's ``participating_repos``
        (repo-affinity, FK-21 §21.9) when supplied, falling back to the caller's
        proposed set otherwise.

        Args:
            inputs: The typed story master data (no evidence).
            evidence: The self-validating reconciliation evidence (real runtime).
            op_id: The idempotency key (Rule #5).
            participating_repos: The authoritative repo set from the outcome; when
                ``None`` the caller-proposed ``inputs.repos`` is used.

        Returns:
            A fully-typed :class:`CreateStoryRequest` ready to post.
        """
        repos = (
            list(participating_repos)
            if participating_repos is not None
            else list(inputs.repos)
        )
        return cls(
            op_id=op_id,
            project_key=inputs.project_key,
            title=inputs.title,
            story_type=inputs.story_type,
            repos=repos,
            reconciliation=evidence,
            epic=inputs.epic,
            module=inputs.module,
            size=inputs.size,
            mode=inputs.mode,
            change_impact=inputs.change_impact,
            concept_quality=inputs.concept_quality,
            owner=inputs.owner,
            risk=inputs.risk,
            labels=list(inputs.labels),
            new_structures=inputs.new_structures,
        )

    def to_wire_body(self) -> dict[str, object]:
        """Serialize to the exact ``POST /v1/stories`` wire body.

        The story content keys are emitted under their wire names (``type`` for
        ``story_type``); ``op_id`` and the typed ``reconciliation`` evidence are
        carried as the transport-level keys the route's fail-closed gate reads.
        Optional keys that were not provided are omitted so the server applies
        its own defaults (no spurious ``None`` overriding a typed default).
        """
        body = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        # ``labels``/``new_structures`` always present (have defaults); keep them
        # only when meaningful so an empty default does not mask server policy.
        if not body.get("labels"):
            body.pop("labels", None)
        return body


class CreatedStorySummary(BaseModel):
    """Typed view of the created story returned by ``POST /v1/stories`` (201).

    Validates the backend-allocated story summary wire payload (the route's
    ``story_to_wire_summary``). ``story_id`` is the backend-allocated canonical
    display id (FK-91 §91.1a: the Control Plane is the single story truth — the
    id is never client-assigned). ``correlation_id`` carries the stable
    correlation propagated for the call (Rule #7).
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    story_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    title: str
    status: str
    type: str
    correlation_id: str = ""


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
    """Serializable session binding materialized into the edge bundle.

    AG3-142 (SOLL-034 behaviour part): ``status`` / ``revocation_reason`` mirror
    the AG3-137 schema addition on ``SessionRunBindingRecord`` so a REVOKED
    binding (e.g. ``revocation_reason="ownership_transferred"``, FK-56 §56.7a)
    is materialized into the local edge bundle instead of silently vanishing --
    the local ``ProjectEdgeResolver.resolve()`` and the server-side binding
    resolution both need this to surface deterministic ``binding_invalid``
    rather than falling back to ``ai_augmented`` (no ``binding=None`` erasure).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: list[str]
    binding_version: str
    operating_mode: OperatingMode
    status: str = "active"
    revocation_reason: str | None = None
    new_owner_ref: str | None = None


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


class EdgeFreezeStateView(BaseModel):
    """One active blocking freeze-family member published to ProjectEdge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "conflict_freeze",
        "split_admin_freeze",
        "reconcile_repair",
        "contested_local_writes",
    ]
    freeze_reason: str = Field(min_length=1)
    freeze_epoch: str = Field(min_length=1)
    block_reason: Literal[
        "conflict_freeze",
        "split_admin_freeze",
        "reconcile_repair",
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    ]


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
    active_freezes: list[EdgeFreezeStateView] = Field(default_factory=list)
    active_freezes_readable: bool = True


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
    attempt_id: str | None = None
    executor_run_id: str | None = None
    next_phase: str | None = None
    yield_status: str | None = None
    rejection_reason: str | None = None
    errors: tuple[str, ...] = ()


#: Terminal statuses (AG3-138) that materialize NO story-scoped guard regime --
#: an ``edge_bundle`` is therefore never carried for them, exactly like
#: ``rejected``. ``aborted``: an explicit ``admin_abort_inflight_operation``
#: with no partial engine writes detected. ``repair``: an orphaned/aborted
#: operation whose engine writes (``phase_states``/``flow_executions``) were
#: already partially persisted -- an explicit, auditable reconcile/repair
#: state (IMPL-005), never silently ``failed``. ``failed``: the deterministic
#: startup-reconciliation outcome for an orphaned claim of the OWN instance's
#: earlier incarnation with no partial writes (FK-91 §91.1a rule 16). ``resolved``:
#: an open ``repair`` state that was productively closed out via the admin-abort
#: repair-resolve path (AC10), which lifts the story-scoped mutation lock.
_NO_EDGE_BUNDLE_STATUSES = frozenset(
    {
        "rejected",
        "aborted",
        "repair",
        "failed",
        "resolved",
        "offered",
        "pending_human_approval",
        "challenge_reissued",
        "approved",
        "denied",
        "expired",
        "invalidated",
    }
)


class OwnershipTransferredDetail(BaseModel):
    """Structured ex-owner rejection detail (FK-91 §91.1a Rule 18, AG3-142).

    Carried on ``ControlPlaneMutationResult.ownership_conflict`` for a
    ``rejected`` result whose ``error_code`` is ``"ownership_transferred"``
    (mapped to HTTP 403 FORBIDDEN by
    ``control_plane_http.app._mutation_result_response`` -- distinct from the
    generic 409 CONFLICT every other rejection cause gets): a mutating call
    whose caller no longer matches the story's active ``run_ownership_records``
    row (wrong ``owner_session_id`` or a stale ``ownership_epoch``). Carries --
    at minimum, per Rule 18 -- the reason, the new owner and the transfer
    instant. This EXTENDS the FK-91 Rule 8 error contract
    (``error_code`` on the SAME result body; ``correlation_id`` travels on the
    ``X-Correlation-Id`` header of every response, Rule 7) rather than
    replacing it -- mirrors the existing K4 busy-object-claim rejection shape
    (``error_code`` + ``retry_after_seconds`` on the SAME
    ``ControlPlaneMutationResult``). Built by
    :func:`~agentkit.backend.control_plane.runtime._ownership_transferred_rejection`
    from either the EARLY admission check
    (:class:`~agentkit.backend.control_plane.ownership_fence.OwnershipAdmission`)
    or a commit-time :class:`~agentkit.backend.exceptions.
    OwnershipFenceViolationError` (no TOCTOU).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str
    new_owner_session_id: str
    new_ownership_epoch: int
    transferred_at: datetime


class FreezeConflictDetail(BaseModel):
    """Structured Rule-8 detail for a story-freeze admission rejection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str | None
    freeze_reason: str | None
    freeze_epoch: str | None
    state_readable: bool


class ControlPlaneMutationResult(BaseModel):
    """Shared response body for mutations, sync, and op reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal[
        "committed",
        "replayed",
        "synced",
        "rejected",
        "aborted",
        "repair",
        "failed",
        "resolved",
        "offered",
        "pending_human_approval",
        "challenge_reissued",
        "approved",
        "denied",
        "expired",
        "invalidated",
    ]
    op_id: str
    operation_kind: str
    run_id: str | None = None
    phase: str | None = None
    #: ``None`` ONLY for a status in :data:`_NO_EDGE_BUNDLE_STATUSES` (AG3-054;
    #: FK-20 §20.8.2). A rejected/aborted/repair/failed outcome materializes NO
    #: story-scoped guard regime -- no session binding, no lock-records, no
    #: ``phase_start`` edge bundle -- so there is no bundle to carry. Every
    #: committed / replayed / synced result still carries an authoritative
    #: ``edge_bundle``; the rejection/abort detail travels on ``phase_dispatch``
    #: / ``admin_note``.
    edge_bundle: EdgeBundle | None = None
    #: AG3-054: the normalized single-phase dispatch outcome (FK-45 §45.1.2).
    #: ``None`` for non-dispatch operations (closure-complete, edge-sync) and
    #: for replays of pre-AG3-054 records; present on every ``start_phase``
    #: dispatch so the one truth carries both the idempotent edge bundle and the
    #: phase result without a second response path.
    phase_dispatch: PhaseDispatchResult | None = None
    #: AG3-138: the machine-readable, auditable reason for an ``aborted`` /
    #: ``repair`` / ``failed`` / ``resolved`` terminal outcome (e.g. why an
    #: admin-abort target went to ``repair`` instead of ``aborted``, why startup
    #: reconciliation finalized an orphaned claim, or the audited actor/reason that
    #: resolved a ``repair`` state). ``None`` for every other status. The
    #: SEVERITY-SEMANTIK guardrail: a ``repair`` state is a visible, auditable
    #: handling requirement, never a silently discarded fact.
    admin_note: str | None = None
    #: AG3-141 (FK-91 §91.1a Rule 8, K4/IMPL-016): a stable, machine-readable
    #: error classification for a ``rejected`` result caused by a busy object
    #: mutation claim (``object_claims.ERROR_CODE_OBJECT_CLAIM_CONFLICT``).
    #: ``None`` for every other rejection cause and every non-``rejected``
    #: status.
    error_code: str | None = None
    freeze_conflict: FreezeConflictDetail | None = None
    #: AG3-141 (K4): the pinned client retry-hint budget (seconds) for a
    #: busy-object ``rejected`` result. Carried into the HTTP ``Retry-After``
    #: header (``control_plane_http.app._mutation_result_response``). ``None``
    #: for every other rejection cause -- there is no implication of a
    #: server-side wait; the caller retries the WHOLE request after the hint.
    retry_after_seconds: int | None = None
    #: AG3-142 (SOLL-017 accountability): the ``ownership_epoch`` of the active
    #: ``run_ownership_records`` row a COMMITTED regime operation (or its
    #: replay) was admitted/committed under -- ``1`` for the setup start that
    #: inserts the record, the active record's current epoch for every later
    #: start/complete/fail/resume/closure on the SAME run. ``None`` for
    #: non-regime operations (``project_edge_sync``, admin-abort/repair-resolve,
    #: startup-reconciliation) and for ``rejected`` results (nothing committed).
    #: Business continuity of artifacts/attempts/QA stays keyed on ``run_id``;
    #: this field is audit-only accountability, never a second continuity key.
    ownership_epoch: int | None = None
    #: AG3-142 (FK-91 §91.1a Rule 18, FK-56 §56.13c): the structured ex-owner
    #: detail for a ``rejected`` result whose ``error_code`` is
    #: ``ownership_transferred`` -- a mutating call whose run-ownership no
    #: longer matches the story's active record. ``None`` for every other
    #: rejection cause and every non-``rejected`` status.
    ownership_conflict: OwnershipTransferredDetail | None = None
    #: AG3-148: the non-materializing human challenge offered by
    #: ``takeover-request``. The challenge is the single CAS echo source for a
    #: later ``takeover-confirm``; no edge bundle is materialized at offer time.
    takeover_challenge: TakeoverChallenge | None = None
    #: AG3-148: agent-initiated takeover requests never auto-transfer. They
    #: persist a pending approval and return this typed handle until a human
    #: explicitly approves and confirms.
    pending_human_approval: PendingHumanApprovalResponse | None = None
    #: AG3-151: per-repo backend classifications returned by the official
    #: takeover-reconcile-worktree mutation.
    takeover_reconcile: TakeoverReconcileResponse | None = None

    @model_validator(mode="after")
    def _edge_bundle_optionality_is_bound_to_rejection(self) -> ControlPlaneMutationResult:
        """Enforce: ``edge_bundle`` is ``None`` ONLY for a non-materializing result.

        The field was widened to optional solely so a fail-closed REJECTED start
        (AG3-054; FK-20 §20.8.2) -- and, since AG3-138, an admin-abort/startup-
        reconciliation ``aborted``/``repair``/``failed`` outcome -- can travel
        without materializing a story-scoped edge bundle. That optionality must
        NOT leak to success statuses: a ``committed`` / ``replayed`` / ``synced``
        result with ``edge_bundle=None`` would let the project-edge client
        silently skip publishing an authoritative bundle (a fail-open activation
        gap). Conversely a non-materializing result MUST carry no bundle (it
        materialized none). Enforced at the model boundary (FAIL-CLOSED, fix the
        model).
        """
        if self.status in _NO_EDGE_BUNDLE_STATUSES:
            if self.edge_bundle is not None:
                msg = (
                    f"a {self.status!r} ControlPlaneMutationResult must not "
                    "carry an edge_bundle"
                )
                raise ValueError(msg)
        elif self.edge_bundle is None:
            msg = (
                f"a {self.status!r} ControlPlaneMutationResult must carry an "
                f"edge_bundle (None is allowed only for {sorted(_NO_EDGE_BUNDLE_STATUSES)})"
            )
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Edge-Command-Queue wire models (FK-91 §91.1b, AG3-145)
# ---------------------------------------------------------------------------


class EdgeCommandView(BaseModel):
    """One open command as materialized to the GET response (AG3-145)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str = Field(min_length=1)
    command_kind: str = Field(min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)
    status: Literal["created", "delivered"]
    created_at: datetime


class OpenEdgeCommandsResponse(BaseModel):
    """Response body for ``GET .../story-runs/{run_id}/commands`` (AG3-145).

    FK-91 §91.1a Rule 13: this is a pure read -- it takes no lock/claim. The
    GET call itself acks delivery server-side (``status`` moves ``created`` ->
    ``delivered``); this response body carries no separate ack field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    commands: list[EdgeCommandView] = Field(default_factory=list)


# --- Command payloads (the backend -> edge commission body, per repo) ---------


class ProvisionWorktreeCommandPayload(BaseModel):
    """Typed ``provision_worktree`` command payload (FK-91 §91.1b, FK-12 §12.5.1).

    The backend commissions ONE per participating repo. It carries only what the
    edge cannot derive itself -- the repo NAME (not path; FK-10 §10.2.4a: the
    backend derives NO physical path), the story branch and the base ref. The
    edge resolves the physical repo path from its LOCAL project config.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base_ref: str = Field(min_length=1, default="main")


class TeardownWorktreeCommandPayload(BaseModel):
    """Typed ``teardown_worktree`` command payload (FK-91 §91.1b, FK-12 §12.5.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)


class PreflightProbeCommandPayload(BaseModel):
    """Typed ``preflight_probe`` command payload (FK-91 §91.1b, FK-22 §22.3.1).

    A pure-collection probe of ONE participating repo: the edge reports the
    branch class + head SHA and the local worktree state (marker + path); it
    makes NO decision (the backend decides in the preflight checks 7/8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)


class SyncPushCommandPayload(BaseModel):
    """Typed ``sync_push`` command payload (FK-91 §91.1b, FK-10 §10.2.4b, AG3-147).

    The backend commissions ONE per participating repo. It carries only what the
    edge cannot derive itself -- the repo NAME (not path; FK-10 §10.2.4a: the
    backend derives NO physical path) and the story branch. The official push
    target ref is ALWAYS ``story/{story_id}`` (there is no WIP-ref push path,
    In-Scope #7 / AC10); the edge derives it from ``story_id`` and rejects any
    other ref at the push gate. The edge resolves the physical repo path from its
    LOCAL project config and runs the bounded online-ownership check itself
    (FK-15 §15.5.4: online-required, no ACTIVE-bundle re-sync fallback).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    boundary_type: str | None = None
    boundary_id: str | None = None
    boundary_epoch: int | None = Field(default=None, ge=1)
    ownership_epoch: int | None = Field(default=None, ge=1)


class TakeoverReconcileCommandPayload(BaseModel):
    """Backend-commissioned reconcile contract for one transferred repo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    takeover_base_sha: str = Field(min_length=1)


class BranchRefReport(BaseModel):
    """``branch_ref_report`` (FK-91 §91.1b / FK-10 §10.2.4b): per-repo branch
    class + head SHA, reported after every sync point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["branch_ref_report"] = "branch_ref_report"
    repo_id: str = Field(min_length=1)
    branch_class: Literal["no_branch", "branch_present"]
    head_sha: str | None = None


class PushStatusReport(BaseModel):
    """``push_status_report`` (FK-91 §91.1b): push success vs. backlog per repo.

    Reported by the AG3-147 ``sync_push`` edge executor after every sync point.
    ``head_sha`` folds the FK-91 ``branch_ref_report`` head SHA into this one
    wire result so a single ``sync_push`` command result carries BOTH pieces the
    two-stage push barrier + freshness projection consume together (FK-10
    §10.2.4b): the pushed branch head AND whether it reached the remote. It is
    the Edge-reported head of ``story/{story_id}`` (``None`` only when the local
    branch head could not be resolved -- a fail-closed backlog).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["push_status_report"] = "push_status_report"
    repo_id: str = Field(min_length=1)
    push_outcome: Literal["pushed", "behind_remote"]
    head_sha: str | None = None
    boundary_type: str | None = None
    boundary_id: str | None = None
    boundary_epoch: int | None = Field(default=None, ge=1)
    ownership_epoch: int | None = Field(default=None, ge=1)


class WorktreeReport(BaseModel):
    """``worktree_report`` (FK-91 §91.1b): provisioning/teardown outcome per repo.

    ``worktree_root`` is the physical path the Edge provisioned/tore down --
    the SINGLE SOURCE OF TRUTH for the session's ``worktree_roots`` (FK-56
    §56.8, FK-10 §10.2.4a): the backend never derives this path itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["worktree_report"] = "worktree_report"
    repo_id: str = Field(min_length=1)
    outcome: Literal["provisioned", "torn_down", "no_op"]
    worktree_root: str | None = None
    branch: str | None = None
    head_sha: str | None = None
    marker_present: bool = False


class TakeoverQuarantineDetail(BaseModel):
    """Quarantine detail on a ``takeover_reconcile`` result (FK-56 §56.13e).

    Foundation shape only -- ``takeover_reconcile`` execution (the quarantine
    mechanics) is AG3-151.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["takeover_quarantine_detail"] = "takeover_quarantine_detail"
    repo_id: str = Field(min_length=1)
    quarantine_path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TakeoverErrorResult(BaseModel):
    """Named takeover-family error result (FK-30 §30.6.3), never a collective FAIL.

    Foundation shape only -- ``takeover_reconcile`` execution is AG3-151.
    ``local_stale_or_dirty_takeover_target`` doubles as a named Check-8
    preflight finding (AG3-145 Teilschritt C, FK-22 §22.3.1).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal[
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    ]
    repo_id: str = Field(min_length=1)
    detail: str = ""


TakeoverReconcileReportedResult = Annotated[
    WorktreeReport | TakeoverErrorResult,
    Field(discriminator="result_type"),
]


class TakeoverReconcileWorktreeRequest(BaseModel):
    """Official new-owner report for a commissioned takeover reconcile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    results: list[TakeoverReconcileReportedResult] = Field(min_length=1)
    quarantine_details: list[TakeoverQuarantineDetail] = Field(default_factory=list)


class TakeoverReconcileResultView(BaseModel):
    """Backend classification returned for one participating repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    result_type: Literal[
        "identity_ok",
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    ]
    detail: str = Field(min_length=1)
    quarantine_detail: TakeoverQuarantineDetail | None = None


class TakeoverReconcileResponse(BaseModel):
    """Structured reconcile outcome attached to the mutation response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[TakeoverReconcileResultView] = Field(min_length=1)


class PreflightProbeReport(BaseModel):
    """``preflight_probe_report`` (FK-91 §91.1b, FK-22 §22.3.1): a PURE per-repo
    collection -- branch class + head SHA plus the local worktree state (marker
    content + path). The edge makes NO decision; the backend's preflight checks
    7/8 decide on this evidence (AG3-145 Teilschritt C).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["preflight_probe_report"] = "preflight_probe_report"
    repo_id: str = Field(min_length=1)
    branch_present: bool
    head_sha: str | None = None
    worktree_present: bool = False
    worktree_path: str | None = None
    marker_present: bool = False
    marker_story_id: str | None = None
    marker_run_id: str | None = None


class CommandErrorResult(BaseModel):
    """Deterministic error result for a failed/unsupported command (Scope item 4).

    An Edge that receives a command kind outside its executable set (or whose
    executor raises) reports this instead of a silent no-op.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["command_error"] = "command_error"
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)


#: The closed, discriminated wire union of every Edge-Command-Queue result
#: shape (FK-91 §91.1b, AG3-145 AC9): the three named result types, the
#: preflight-probe collection, the takeover quarantine detail and the named
#: takeover error states, plus the generic command-error fallback.
EdgeCommandResultPayload = Annotated[
    BranchRefReport
    | PushStatusReport
    | WorktreeReport
    | PreflightProbeReport
    | TakeoverQuarantineDetail
    | TakeoverErrorResult
    | CommandErrorResult,
    Field(discriminator="result_type"),
]


class EdgeCommandResultRequest(BaseModel):
    """Canonical request payload for ``POST .../commands/{command_id}/result`` (AG3-145).

    FK-91 §91.1b: client-``op_id`` is MANDATORY (Rule 5 -- no server minting,
    ``min_length=1``, no ``default_factory``, independent of the BC-wide
    retrofit AG3-140 owns for pre-existing routes); the completion commit is
    story-serialized (Rule 13, via the AG3-141 object-claim helper) and
    Rule-15 ownership-fenced against the active record (AG3-142 reuse).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    #: FK-91 §91.1a Rule 5: client-supplied idempotency key. No server default
    #: remains -- an omitted op_id fails closed at validation (422).
    op_id: str = Field(min_length=1)
    result: EdgeCommandResultPayload


class PushFreshnessView(BaseModel):
    """One repo's push-freshness / backlog read row (AG3-147, FK-10 §10.2.4b).

    The read-model projection of a ``push_freshness_records`` row (In-Scope #3,
    AC5). It is INFORMATION only -- a consumer (AG3-148/AG3-153) never derives
    an ownership transition from silence/staleness (no automatic silence ->
    transfer). ARCH-55: English wire keys.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    last_reported_head_sha: str | None = None
    last_pushed_head_sha: str | None = None
    last_reported_at: datetime
    last_sync_point_id: str | None = None
    last_command_id: str | None = None
    backlog: bool
    backlog_detail: str | None = None


class PushFreshnessListResponse(BaseModel):
    """Response body for the push-freshness read surface (AG3-147, AC5).

    ``GET .../story-runs/{run_id}/push-freshness`` returns one
    :class:`PushFreshnessView` per participating repo (the data basis for the
    ownership-position display and takeover challenge; consumers AG3-148/AG3-153).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    freshness: list[PushFreshnessView] = Field(default_factory=list)


class PushOwnershipConfirmation(BaseModel):
    """The bounded online-ownership answer for the Edge-Push-Gate (AG3-147, AC6).

    ``GET .../story-runs/{run_id}/push-ownership`` -- the fresh online check the
    official Edge-Push-Gate runs IMMEDIATELY before a ``story/*`` push (FK-15
    §15.5.4: online-required, bounded). Read-only, no lock/claim. ``owner_confirmed``
    is ``True`` iff the story's ACTIVE ``run_ownership_records`` row admits THIS
    run/session (the exact :func:`evaluate_ownership_admission` rule the mutating
    fences reuse) -- it deliberately consults NO ACTIVE bundle, so a stale bundle
    can never grant a push (the FK-56 §56.9a re-sync fallback does not apply to
    the push path). The edge treats an unreachable server as ``server_reachable``
    ``False`` (offline: local work yes, push no) -- never as a confirmation.
    ARCH-55: English wire keys.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    owner_confirmed: bool
    detail: str = ""


class EdgeCommandMutationResult(BaseModel):
    """Response body for ``POST .../commands/{command_id}/result`` (AG3-145).

    Deliberately NOT :class:`ControlPlaneMutationResult`: a command-result
    commit never materializes a story-scoped ``edge_bundle`` (that model's
    edge-bundle-optionality invariant would force one on every ``committed``
    status) -- this endpoint owns its own small, dedicated result shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "replayed", "rejected"]
    command_id: str
    op_id: str
    #: AG3-141 (K4): a busy-object-claim rejection's stable error code (mirrors
    #: ``ControlPlaneMutationResult.error_code``). ``None`` otherwise.
    error_code: str | None = None
    #: AG3-141 (K4): the retry-hint budget (seconds) for a busy-object
    #: rejection. ``None`` for every other outcome.
    retry_after_seconds: int | None = None
    #: AG3-142 (FK-91 §91.1a Rule 18): the structured ex-owner detail for a
    #: ``rejected`` result whose ``error_code`` is ``ownership_transferred``.
    ownership_conflict: OwnershipTransferredDetail | None = None
