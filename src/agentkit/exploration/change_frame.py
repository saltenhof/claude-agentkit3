"""ChangeFrame -- the exploration-phase design artifact (change-frame).

Source of truth: FK-23 §23.4 (the design artifact's seven mandatory parts),
FK-25 §25.4.2 (editable until gate-PASS, freeze afterwards). The Pydantic
model is the AK3 code-level representation of the change-frame.

Ownership (PO decision 2026-06-05, "Option Y"): the change-frame is PRODUCED by
the spawned exploration worker (AG3-055, BC ``agent-skills``); this BC
(``exploration-and-design``, AG3-045) owns only the **schema** and the
deterministic plumbing that consumes / validates / protects it. The handler
reads a persisted frame via a boundary port; it never fabricates one.

FK-23 §23.4.1 seven mandatory parts (English wire keys, ARCH-55)
----------------------------------------------------------------
The model fields are the §23.4.1 keys verbatim:

* ``goal_and_scope``            -- goal / scope (changes + does_not_change)
* ``affected_building_blocks``  -- affected building blocks (affected + untouched)
* ``solution_direction``        -- solution direction (pattern + anchoring + rationale)
* ``contract_changes``          -- contract changes (interfaces / data_model / ...)
* ``conformance_statement``     -- conformance statement (reference_documents / ...)
* ``verification_sketch``       -- verification sketch (unit / integration / e2e)
* ``open_points``               -- open points (decided / assumptions / approval_needed)

Plus the §23.4.1 identity / lifecycle fields ``schema_version``, ``story_id``,
``run_id``, ``created_at`` (mandatory) and ``frozen``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.artifacts.envelope import STORY_ID_PATTERN
from agentkit.exploration.mandate.fine_design import FineDesignDecision

#: ChangeFrame wire-schema version (FK-23 §23.4.1 ``schema_version``).
CHANGE_FRAME_SCHEMA_VERSION = "3.0"

#: A non-empty, non-whitespace string. Rejects ``""`` and whitespace-only
#: (incl. tabs/newlines) at the model boundary (fail-closed, ZERO DEBT).
_NonEmptyStr = Annotated[str, Field(min_length=1)]


def _require_non_blank(value: str, field_name: str) -> str:
    """Reject whitespace-only strings fail-closed.

    Pydantic's ``min_length`` rejects ``""`` but accepts ``"   "``/``"\\n"``;
    a change-frame field that is only whitespace is meaningless content and is
    rejected here at the model boundary.

    Args:
        value: The candidate string.
        field_name: The field name (for the error message).

    Returns:
        The original string (unchanged; intentionally NOT stripped -- content
        is the worker's, only blankness is rejected).

    Raises:
        ValueError: If the string is empty or whitespace-only.
    """
    if not value.strip():
        msg = f"{field_name} must not be empty or whitespace-only"
        raise ValueError(msg)
    return value


def _require_all_non_blank(values: list[str], field_name: str) -> list[str]:
    """Reject any empty / whitespace-only entry in a string list."""
    for entry in values:
        _require_non_blank(entry, field_name)
    return values


class _Part(BaseModel):
    """Base for the seven change-frame parts: immutable, no extra keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GoalAndScope(_Part):
    """FK-23 §23.4.1 ``goal_and_scope`` -- both fields non-blank (§23.4.2).

    Attributes:
        changes: What the change introduces / modifies. Non-blank.
        does_not_change: What deliberately stays untouched. Non-blank.
    """

    changes: _NonEmptyStr
    does_not_change: _NonEmptyStr

    @field_validator("changes", "does_not_change")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        return _require_non_blank(value, "goal_and_scope field")


class AffectedBuildingBlocks(_Part):
    """FK-23 §23.4.1 ``affected_building_blocks`` -- ``affected`` >= 1 (§23.4.2).

    Attributes:
        affected: Building blocks the change touches (>= 1 entry, each
            non-blank).
        untouched: Building blocks deliberately left untouched (may be empty;
            entries non-blank).
    """

    affected: list[_NonEmptyStr] = Field(min_length=1)
    untouched: list[_NonEmptyStr] = Field(default_factory=list)

    @field_validator("affected", "untouched")
    @classmethod
    def _entries_non_blank(cls, value: list[str]) -> list[str]:
        return _require_all_non_blank(value, "affected_building_blocks entry")


class SolutionDirection(_Part):
    """FK-23 §23.4.1 ``solution_direction`` -- all three fields non-blank.

    Attributes:
        pattern: The chosen architectural pattern. Non-blank.
        anchoring: Where the solution is anchored in the system. Non-blank.
        rationale: Why this is the smallest fitting solution. Non-blank.
    """

    pattern: _NonEmptyStr
    anchoring: _NonEmptyStr
    rationale: _NonEmptyStr

    @field_validator("pattern", "anchoring", "rationale")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        return _require_non_blank(value, "solution_direction field")


class ContractChanges(_Part):
    """FK-23 §23.4.1 ``contract_changes`` -- at least one array non-empty.

    Per §23.4.2 at least one of the four arrays must be non-empty (or carry an
    explicit "none" marker). All arrays default to empty; entries are non-blank.

    Attributes:
        interfaces: New / changed interfaces (e.g. endpoints).
        data_model: New / changed data-model entities.
        events: New / changed domain events.
        external_integrations: New / changed external integrations.
    """

    interfaces: list[_NonEmptyStr] = Field(default_factory=list)
    data_model: list[_NonEmptyStr] = Field(default_factory=list)
    events: list[_NonEmptyStr] = Field(default_factory=list)
    external_integrations: list[_NonEmptyStr] = Field(default_factory=list)

    @field_validator(
        "interfaces", "data_model", "events", "external_integrations"
    )
    @classmethod
    def _entries_non_blank(cls, value: list[str]) -> list[str]:
        return _require_all_non_blank(value, "contract_changes entry")

    @model_validator(mode="after")
    def _at_least_one_array_non_empty(self) -> ContractChanges:
        """At least one of the four arrays must be non-empty (FK-23 §23.4.2)."""
        if not (
            self.interfaces
            or self.data_model
            or self.events
            or self.external_integrations
        ):
            msg = (
                "contract_changes requires at least one non-empty array "
                "(interfaces / data_model / events / external_integrations); "
                "an explicit 'none' marker entry is the way to declare no "
                "contract change (FK-23 §23.4.2)"
            )
            raise ValueError(msg)
        return self


class ConformanceStatement(_Part):
    """FK-23 §23.4.1 ``conformance_statement`` -- ``reference_documents`` >= 1.

    The worker's self-conformance check against the reference documents
    (FK-23 §23.3.2 step 5); the independent doc-fidelity review (§23.5.1) is the
    second, independent pass (AG3-046).

    Attributes:
        reference_documents: Documents the worker considered (>= 1, each
            non-blank).
        conformant: Points that are conformant with the references (entries
            non-blank).
        deviations: Declared, justified deviations (entries non-blank).
    """

    reference_documents: list[_NonEmptyStr] = Field(min_length=1)
    conformant: list[_NonEmptyStr] = Field(default_factory=list)
    deviations: list[_NonEmptyStr] = Field(default_factory=list)

    @field_validator("reference_documents", "conformant", "deviations")
    @classmethod
    def _entries_non_blank(cls, value: list[str]) -> list[str]:
        return _require_all_non_blank(value, "conformance_statement entry")


class VerificationSketch(_Part):
    """FK-23 §23.4.1 ``verification_sketch`` -- at least one level described.

    Each level is optional individually; per §23.4.2 at least one test level
    must be described. A given level, when set, must be non-blank.

    Attributes:
        unit: Unit-test sketch (optional; non-blank when set).
        integration: Integration-test sketch (optional; non-blank when set).
        e2e: End-to-end-test sketch (optional; non-blank when set).
    """

    unit: str | None = None
    integration: str | None = None
    e2e: str | None = None

    @field_validator("unit", "integration", "e2e")
    @classmethod
    def _non_blank_when_set(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            msg = "verification_sketch level, when set, must not be blank"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _at_least_one_level(self) -> VerificationSketch:
        """At least one test level must be described (FK-23 §23.4.2)."""
        if self.unit is None and self.integration is None and self.e2e is None:
            msg = (
                "verification_sketch requires at least one described test level "
                "(unit / integration / e2e) (FK-23 §23.4.2)"
            )
            raise ValueError(msg)
        return self


class OpenPoints(_Part):
    """FK-23 §23.4.1 ``open_points`` -- all three arrays present (may be empty).

    Per FK-23 §23.4.2 the three sub-arrays MUST be present (they may be empty,
    but a missing key is a schema violation). They are therefore required fields
    with no default; a missing key fails closed (``ValidationError``).

    Attributes:
        decided: Decisions already taken (present; may be empty; entries
            non-blank).
        assumptions: Working assumptions, not yet verified (present; may be
            empty; entries non-blank).
        approval_needed: Points that need human / architecture approval
            (present; may be empty; entries non-blank).
    """

    decided: list[_NonEmptyStr]
    assumptions: list[_NonEmptyStr]
    approval_needed: list[_NonEmptyStr]

    @field_validator("decided", "assumptions", "approval_needed")
    @classmethod
    def _entries_non_blank(cls, value: list[str]) -> list[str]:
        return _require_all_non_blank(value, "open_points entry")


class ChangeFrame(BaseModel):
    """The exploration-phase design artifact (Change-Frame, FK-23 §23.4).

    Pydantic-v2 model with the seven mandatory parts (FK-23 §23.4.1, English
    wire keys) plus the identity / lifecycle fields. Immutable
    (``frozen=True``): the worker (AG3-055) produces a new instance per draft;
    the review / freeze stories (AG3-046/047) build successor instances. The
    freeze (setting ``frozen`` / ``frozen_at``) happens only AFTER the exit-gate
    passes (FK-25 §25.4.2) and is owned by AG3-047; this BC does not enforce a
    ``frozen``/``frozen_at`` consistency invariant (``frozen_at`` is optional
    even when ``frozen`` is ``True``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identity / persistence metadata (FK-23 §23.4.1 / §23.4.2) ---------
    schema_version: str = CHANGE_FRAME_SCHEMA_VERSION
    #: Story display id (FK-02 §2.3.1 ``{PREFIX}-{NNN}``). Validated against the
    #: shared ``STORY_ID_PATTERN`` (SSOT in ``artifacts.envelope``) so the frame's
    #: identity cannot drift from the wrapping ENTWURF envelope's ``story_id``.
    story_id: _NonEmptyStr
    #: Run correlation id (FK-02 §2.3.1: a UUID generated at setup). Parsed with
    #: :class:`uuid.UUID` -- a non-UUID value is rejected fail-closed.
    run_id: _NonEmptyStr
    #: ISO-8601 creation timestamp (FK-23 §23.4.2: ``created_at`` is a mandatory
    #: field). Mandatory and tz-aware (UTC); a naive timestamp is rejected.
    created_at: datetime

    # --- The seven mandatory parts (FK-23 §23.4.1) -------------------------
    goal_and_scope: GoalAndScope
    affected_building_blocks: AffectedBuildingBlocks
    solution_direction: SolutionDirection
    contract_changes: ContractChanges
    conformance_statement: ConformanceStatement
    verification_sketch: VerificationSketch
    open_points: OpenPoints

    # --- Optional eighth component (FK-25 §25.5.5 / §25.10, AG3-097) --------
    #: The class-2 fine-design decision protocol (FK-25 §25.5.5). The FK concept
    #: name is the German ``feindesign_entscheidungen``; the CODE wire-key is the
    #: English ``fine_design_decisions`` (ARCH-55 -- a German wire-key would be a
    #: doc-only nachzug, AG3-102, never code). Optional eighth component (default
    #: empty): a frame with no class-2 decision carries an empty list. Reuses the
    #: existing English-keyed :class:`FineDesignDecision` (NO duplicate schema).
    fine_design_decisions: tuple[FineDesignDecision, ...] = ()

    # --- Lifecycle (FK-23 §23.4.2 / §23.4.3 / FK-25 §25.4.2) ---------------
    frozen: bool = False
    #: Optional freeze timestamp, set by AG3-047's freeze trigger. Not a FK-23
    #: §23.4.1 wire key and FK-23 §23.4 does NOT mandate a ``frozen``/``frozen_at``
    #: consistency invariant -- this BC (AG3-045) deliberately does NOT enforce
    #: one: ``frozen_at`` stays optional even when ``frozen`` is ``True``, and
    #: setting/enforcing it is freeze logic owned by AG3-047, not here. The gate
    #: status itself lives on ``ExplorationPayload`` (FK-23 §23.5.0), not on the
    #: artifact.
    frozen_at: datetime | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema_version_fixed(cls, value: str) -> str:
        if value != CHANGE_FRAME_SCHEMA_VERSION:
            msg = (
                f"schema_version must be {CHANGE_FRAME_SCHEMA_VERSION!r}, "
                f"got {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("story_id")
    @classmethod
    def _story_id_matches_pattern(cls, value: str) -> str:
        """Reject a ``story_id`` that is not a valid story display id.

        FK-23 §23.4.2 demands a story-id-shaped value, not merely a non-blank
        string. Reuses the shared ``STORY_ID_PATTERN`` (FK-02 §2.3.1) so the
        frame can never carry an id the wrapping ENTWURF envelope would reject.
        """
        if STORY_ID_PATTERN.fullmatch(value) is None:
            msg = (
                f"story_id {value!r} must be a story display id matching "
                f"{STORY_ID_PATTERN.pattern!r} (FK-02 §2.3.1)"
            )
            raise ValueError(msg)
        return value

    @field_validator("run_id")
    @classmethod
    def _run_id_is_uuid(cls, value: str) -> str:
        """Reject a ``run_id`` that is not a UUID.

        FK-23 §23.4.2 / FK-02 §2.3.1: ``run_id`` is the UUID minted at setup.
        Parsing with :class:`uuid.UUID` rejects any non-UUID value fail-closed.
        """
        try:
            uuid.UUID(value)
        except ValueError as exc:
            msg = f"run_id {value!r} must be a UUID (FK-02 §2.3.1)"
            raise ValueError(msg) from exc
        return value

    @field_validator("created_at", "frozen_at")
    @classmethod
    def _timestamps_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            msg = "timestamps must be tz-aware (UTC); naive datetime not allowed"
            raise ValueError(msg)
        return value

    @classmethod
    def from_payload(cls, payload: object) -> ChangeFrame:
        """Validate a persisted JSON payload into a ``ChangeFrame`` (fail-closed).

        The single entry point the consuming handler uses to turn a persisted
        ENTWURF envelope payload (a plain ``dict`` off the wire) into a typed,
        validated frame. Any schema violation raises fail-closed
        (``pydantic.ValidationError``); a non-mapping payload is rejected with a
        clear ``TypeError``.

        Args:
            payload: The persisted change-frame JSON (expected: a mapping).

        Returns:
            The validated :class:`ChangeFrame`.

        Raises:
            TypeError: If ``payload`` is not a mapping.
            pydantic.ValidationError: If the payload violates the schema.
        """
        if not isinstance(payload, dict):
            msg = (
                "ChangeFrame payload must be a JSON object (mapping); got "
                f"{type(payload).__name__}"
            )
            raise TypeError(msg)
        return cls.model_validate(payload)


#: The seven FK-23 §23.4.1 mandatory-part field names (SSOT). Consumed by
#: the contract test instead of a duplicated literal copy.
SEVEN_PARTS: tuple[str, ...] = (
    "goal_and_scope",
    "affected_building_blocks",
    "solution_direction",
    "contract_changes",
    "conformance_statement",
    "verification_sketch",
    "open_points",
)


__all__ = [
    "CHANGE_FRAME_SCHEMA_VERSION",
    "SEVEN_PARTS",
    "AffectedBuildingBlocks",
    "ChangeFrame",
    "ConformanceStatement",
    "ContractChanges",
    "GoalAndScope",
    "OpenPoints",
    "SolutionDirection",
    "VerificationSketch",
]
