"""Typed story-split artifact models (FK-54 §54.7/§54.8, story-lifecycle BC).

This module owns the typed Split-Plan, Split-Record and Story-Lineage entities
of the administrative ``scope_explosion`` recovery path. It is a CONSUMER of the
AG3-074-owned result axis (``ExitClass.SCOPE_SPLIT`` /
``validate_exit_class_constraints``); it does NOT define a second ``exit_class``
enum or a rival constraint (FIX-THE-MODEL / SINGLE SOURCE OF TRUTH).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.story_context_manager.terminal_state import (
    ExitClass,
    TerminalState,
    validate_exit_class_constraints,
)

#: Producer-id of every split artifact (single owner, §54.8.1).
STORY_SPLIT_PRODUCER_ID: Literal["story_split_service"] = "story_split_service"

#: The fixed reason recorded on the administrative split-cancel transition
#: (§54.8.7). English wire value (ARCH-55).
SPLIT_CANCEL_REASON: Literal["scope_split"] = "scope_split"


class SplitStatus(StrEnum):
    """Lifecycle status of a single split operation (§54.8.1).

    Attributes:
        FAILED: The entry gate or plan validation rejected the split before any
            mutation (fail-closed, §54.4).
        COMMITTED: The 7-step flow completed: source story ``Cancelled``,
            successors in ``Backlog``, dependencies rebound.
    """

    FAILED = "failed"
    COMMITTED = "committed"


class SuccessorStory(BaseModel):
    """One successor story declared by the split plan (§54.7).

    ``initial_project_status`` is fixed to ``Backlog`` (§54.5 #2): successors are
    always created in the Backlog and never inherit a runtime status.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    title: str
    scope_slice: str

    @field_validator("story_id", "title", "scope_slice")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("successor story fields must not be blank")
        return value


class DependencyRebinding(BaseModel):
    """One declared dependency-rebinding entry (§54.8.5 / §54.7).

    ``new_dependencies`` are the successor story-ids the removed edge is rebound
    to. An empty list is a declared, explicit DROP (``no_silent_drop`` is
    satisfied by the explicit declaration), but it may never silently vanish.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dependent_story_id: str
    old_dependency: str
    new_dependencies: tuple[str, ...] = ()

    @field_validator("dependent_story_id", "old_dependency")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dependency rebinding ids must not be blank")
        return value

    @field_validator("new_dependencies", mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            stripped = value.strip()
            return (stripped,) if stripped else ()
        if isinstance(value, list | tuple):
            return tuple(str(item) for item in value if str(item).strip())
        raise ValueError("new_dependencies must be a list of story ids")

    @model_validator(mode="after")
    def _no_self_edge(self) -> DependencyRebinding:
        if self.dependent_story_id in self.new_dependencies:
            raise ValueError(
                "dependency rebinding must not point a story at itself "
                f"({self.dependent_story_id!r})",
            )
        return self


class StoryLineage(BaseModel):
    """Materialized ``split_from`` / ``split_successors`` lineage (§54.8.5).

    DERIVED deterministically from ``source_story_id`` + the successors'
    ``story_id`` (no free plan input). ``split_from`` is the cancelled source on
    every successor; ``split_successors`` is the ordered successor set on the
    source story.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_story_id: str
    split_successors: tuple[str, ...]

    @property
    def split_from(self) -> str:
        """The source story id every successor was split from."""
        return self.source_story_id

    @property
    def superseded_by(self) -> tuple[str, ...]:
        """The successor ids the cancelled source is superseded by (§54.8.6)."""
        return self.split_successors


class SplitPlan(BaseModel):
    """Typed, human-approved split plan (§54.7, ``formal.story-split.entities``).

    ``story_lineage`` is DERIVED (not a free input) from ``source_story_id`` +
    ``successors[].story_id`` and is exposed via :meth:`story_lineage`. Validation
    is fail-closed: blank required fields, duplicate successor ids, a successor
    that re-uses the source id, and rebinding entries that reference an unknown
    new dependency are all rejected before any mutation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    source_story_id: str
    reason: str
    successors: tuple[SuccessorStory, ...]
    dependency_rebinding: tuple[DependencyRebinding, ...] = ()

    @field_validator("project_key", "source_story_id", "reason")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("split plan core fields must not be blank")
        return value

    @field_validator("successors")
    @classmethod
    def _require_successors(
        cls, value: tuple[SuccessorStory, ...]
    ) -> tuple[SuccessorStory, ...]:
        if not value:
            raise ValueError("split plan requires at least one successor story")
        return value

    @model_validator(mode="after")
    def _consistent_references(self) -> SplitPlan:
        successor_ids = [s.story_id for s in self.successors]
        if len(successor_ids) != len(set(successor_ids)):
            raise ValueError("split plan successor story_ids must be unique")
        if self.source_story_id in successor_ids:
            raise ValueError(
                "a successor story_id must differ from the source story_id "
                f"({self.source_story_id!r})",
            )
        successor_set = set(successor_ids)
        for entry in self.dependency_rebinding:
            for new_dep in entry.new_dependencies:
                if new_dep not in successor_set:
                    raise ValueError(
                        "dependency rebinding new_dependencies must reference a "
                        f"declared successor; {new_dep!r} is not in {sorted(successor_set)}",
                    )
            if entry.old_dependency != self.source_story_id:
                raise ValueError(
                    "dependency rebinding old_dependency must be the source story "
                    f"({self.source_story_id!r}); got {entry.old_dependency!r}",
                )
        return self

    @property
    def story_lineage(self) -> StoryLineage:
        """Deterministically derived lineage from source + successor ids."""
        return StoryLineage(
            source_story_id=self.source_story_id,
            split_successors=tuple(s.story_id for s in self.successors),
        )


def compute_plan_ref(plan_text: str) -> str:
    """Return the canonical ``plan_ref`` hash for a raw plan document.

    Deterministic content address of the human-approved plan artifact: the
    SHA-256 of the exact bytes the operator passed via ``--plan``. Two runs with
    an identical plan therefore resolve to the same ``plan_ref`` and (via
    :func:`derive_split_id`) the same split record (resume, AC11).

    Args:
        plan_text: The raw plan-document text as read from ``--plan``.

    Returns:
        The lowercase hex SHA-256 digest of ``plan_text``.
    """
    return hashlib.sha256(plan_text.encode("utf-8")).hexdigest()


def derive_split_id(project_key: str, source_story_id: str, plan_ref: str) -> str:
    """Deterministically derive the ``split_id`` from the resume key (§2.1 #3).

    The split_id is a content address of the resume key
    ``(project_key, source_story_id, plan_ref)`` so a re-run with identical
    ``--story``/``--plan`` finds the SAME split record without the CLI ever
    accepting a ``--split-id`` (AC11). The components are length-prefixed so two
    distinct triples can never collide via boundary ambiguity.

    Args:
        project_key: The project key.
        source_story_id: The source story display-id.
        plan_ref: The plan-document content hash (:func:`compute_plan_ref`).

    Returns:
        A stable ``split-<hex>`` identifier.
    """
    parts = (project_key, source_story_id, plan_ref)
    payload = "\x1f".join(f"{len(p)}:{p}" for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"split-{digest}"


class StorySplitRecord(BaseModel):
    """Auditable split-operation record (§54.8.1, identity ``split_id``).

    Mirrors the ``ControlPlaneOperationRecord`` leased pattern: ``split_id`` is
    the deterministic resume key (never CLI-supplied). The record CONSUMES the
    AG3-074 result axis: a ``COMMITTED`` split carries
    ``terminal_state=Cancelled`` + ``exit_class=scope_split`` and is validated
    against the shared :func:`validate_exit_class_constraints` (no second
    constraint).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: Literal["story_split_service"] = STORY_SPLIT_PRODUCER_ID
    split_id: str
    project_key: str
    source_story_id: str
    requested_by: str
    reason: str
    plan_ref: str
    status: SplitStatus
    successor_ids: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    terminal_state: TerminalState | None = None
    exit_class: ExitClass | None = None
    rejection_reason: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _validate_result_axis(self) -> StorySplitRecord:
        # CONSUME AG3-074: the exit_class/terminal_state pairing is validated by
        # the single shared owner, never by a private constraint.
        if self.exit_class is not None:
            if self.exit_class is not ExitClass.SCOPE_SPLIT:
                raise ValueError(
                    "story split records only carry exit_class=scope_split; "
                    f"got {self.exit_class.value!r}",
                )
            if self.terminal_state is None:
                raise ValueError(
                    "exit_class=scope_split requires a terminal_state (Cancelled)",
                )
            validate_exit_class_constraints(self.terminal_state, self.exit_class)
        if self.status is SplitStatus.COMMITTED and self.exit_class is None:
            raise ValueError(
                "a committed split must record exit_class=scope_split",
            )
        if self.status is SplitStatus.FAILED and self.exit_class is not None:
            raise ValueError(
                "a failed split must not carry an exit_class (no mutation)",
            )
        return self


__all__ = [
    "SPLIT_CANCEL_REASON",
    "STORY_SPLIT_PRODUCER_ID",
    "DependencyRebinding",
    "SplitPlan",
    "SplitStatus",
    "StoryLineage",
    "StorySplitRecord",
    "SuccessorStory",
    "compute_plan_ref",
    "derive_split_id",
]
