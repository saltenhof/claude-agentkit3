"""Capability-adjudication vocabulary of the ``/v1`` boundary (FK-55 §55.10.3).

The hook process on the developer machine asks the core one question before a
tool runs: *may this principal perform this operation on this target?* The core
owns the answer -- the capability matrix, the principal resolution and the
canonical conflict-freeze record are core state (FK-01 §1.1a).

**One request per business transaction, not per component.** FK-55 §55.10.3
steps 1-5 (resolve principal, classify path, classify operation, consult matrix,
apply freeze overlay) are a single adjudication, so they are a single operation
here rather than five repository mirrors (AG3-239 AC 3).

**Why the local freeze state travels in the request.** The invariant
``principal-capabilities.invariant.freeze_has_backend_record_and_local_export``
requires an active freeze to exist BOTH as canonical backend record AND as
local, hook-readable export with a matching ``freeze_version``. The canonical
record is core state; the local export is a file on the developer machine that
only the edge can read. The edge therefore reports what its export says, and the
core compares the two and decides -- fail-closed on any disagreement. Splitting
it the other way would either put a database in the hook process or make the
invariant uncheckable.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AdjudicationOutcome(StrEnum):
    """The five outcomes of a capability adjudication (FK-55 §55.10.2)."""

    #: The matrix permits the operation; the hook does not block.
    PERMIT = "permit"
    #: Hard capability denial from the matrix or the freeze overlay.
    DENY = "deny"
    #: A MUTATING operation whose target cannot be classified to a PathClass.
    #: Fail-closed BLOCK in ALL modes -- ``normal`` is not a fail-open escape.
    UNCLASSIFIED_MUTATION = "unclassified_mutation"
    #: The capability zone is known but the permission is not (§55.6.1).
    UNKNOWN_PERMISSION = "unknown_permission"
    #: Non-mutating, target-less and unresolvable.
    UNRESOLVED = "unresolved"
    #: The adjudication itself faulted. Mapped to a deterministic BLOCK rather
    #: than an escaping runtime fault (FK-55 §55.10.5, FK-31 §31.2.7).
    FAULT = "fault"


class LocalFreezeState(BaseModel):
    """What the edge's local freeze export says, as the edge reads it.

    Attributes:
        present: Whether a local freeze export exists for the story at all.
        story_id: Story the local export names. A mismatch against the request
            story is a disagreement and fails closed.
        freeze_version: Monotonic version the local export carries. ``None``
            when the export is absent or unreadable -- both are disagreements
            when the core holds an active record.
        unreadable: The export exists but could not be parsed. Carried
            explicitly so a corrupt export is never indistinguishable from an
            absent one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    present: bool = False
    story_id: str | None = None
    freeze_version: int | None = None
    unreadable: bool = False


class CapabilityAdjudicationRequest(BaseModel):
    """Edge -> core request to adjudicate one principal operation.

    The event fields are the harness-neutral hook event reduced to what the
    adjudication needs. The context fields are resolved by the edge from its
    LOCAL run exports and are NOT re-derived by the core: the project-edge
    resolver is the single source of the operating mode and the story binding
    (FK-55 §55.10.3 step 2 -- deriving them from ``operation_args`` was AG3-032
    ERROR C).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Idempotency key (FK-91 §91.1a Rule 5), minted hook-side.
    op_id: str = Field(min_length=1)

    # -- the event ----------------------------------------------------------
    # The field set satisfies
    # ``governance.principal_capabilities.adjudication_input.AdjudicationInput``
    # structurally, so the core reads the request through its own port and never
    # imports the edge event type. mypy checks the match at the call site.
    operation: str = Field(min_length=1)
    operation_args: dict[str, object] = Field(default_factory=dict)
    principal_kind: str = Field(min_length=1)
    freshness_class: str | None = None
    #: Never ``None``: the classifier needs a concrete root, and an absent cwd
    #: must not silently become the CORE's working directory.
    cwd: str = ""
    session_id: str | None = None
    parent_session_id: str | None = None
    #: Attested CLI arguments (FK-55 §55.3a). NEVER prompt content.
    cli_args: list[str] | None = None

    # -- the locally resolved context ---------------------------------------
    execution_mode: str = Field(min_length=1)
    story_id: str | None = None
    story_scope_roots: list[str] = Field(default_factory=list)
    binding_revocation_reason: str | None = None
    new_owner_ref: str | None = None
    local_freeze: LocalFreezeState = LocalFreezeState()


class CapabilityAdjudicationResponse(BaseModel):
    """Core -> edge adjudication result.

    Attributes:
        outcome: Which of the FK-55 §55.10.2 outcomes applies.
        allowed: Whether the hook may let the tool proceed. Always ``False``
            for every outcome other than ``PERMIT`` -- the edge must not have to
            re-derive that mapping.
        guard_name: Guard identity for the hook's block payload.
        message: Operator-facing reason.
        violation_type: Violation vocabulary value, or ``None``.
        rule_id: The concept rule the core decided by (e.g.
            ``"FK-55-55.8.3-disowned-session"``). Carried over the wire rather
            than re-derived: the edge cannot know WHICH rule fired, and a
            generic placeholder would erase the audit trail the operator reads.
        detail: Fault class or diagnostic detail for the audit trail.
        freeze_disagreement: Set when the canonical record and the reported
            local export disagree. A disagreement is itself a fail-closed
            freeze, and naming it keeps a stale export from looking like a
            capability denial.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: AdjudicationOutcome
    allowed: bool = False
    guard_name: str = "principal_capability"
    message: str = ""
    violation_type: str | None = None
    rule_id: str | None = None
    detail: str | None = None
    freeze_disagreement: bool = False


__all__ = [
    "AdjudicationOutcome",
    "CapabilityAdjudicationRequest",
    "CapabilityAdjudicationResponse",
    "LocalFreezeState",
]
