"""Pure story-freeze family vocabulary and admission rules (FK-56 §56.13f)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class FreezeKind(StrEnum):
    """Closed vocabulary of story-scoped freeze-family members."""

    CONFLICT_FREEZE = "conflict_freeze"
    SPLIT_ADMIN_FREEZE = "split_admin_freeze"
    RECONCILE_REPAIR = "reconcile_repair"
    CONTESTED_LOCAL_WRITES = "contested_local_writes"


MIN_FREEZE_EPOCH: Final = "1"
ERROR_CODE_STORY_FROZEN: Final = "story_frozen"

RESOLVING_COMMANDS_BY_KIND: Final = MappingProxyType(
    {
        FreezeKind.CONFLICT_FREEZE: frozenset({"resolve_conflict_freeze"}),
        FreezeKind.SPLIT_ADMIN_FREEZE: frozenset({"story_split_finalize"}),
        FreezeKind.RECONCILE_REPAIR: frozenset({"admin_abort_inflight_operation"}),
        FreezeKind.CONTESTED_LOCAL_WRITES: frozenset({"takeover_reconcile_clear"}),
    }
)


@dataclass(frozen=True)
class ActiveFreezeState:
    """Persistence-independent active freeze input for admission decisions."""

    kind: FreezeKind | None
    freeze_reason: str | None
    freeze_epoch: str | None
    readable: bool = True

    @classmethod
    def unreadable(cls) -> ActiveFreezeState:
        """Return the fail-closed sentinel for a failed persistence read."""

        return cls(kind=None, freeze_reason=None, freeze_epoch=None, readable=False)


def is_canonical_freeze_epoch(value: str) -> bool:
    """Return whether *value* is a canonical positive base-10 integer string."""

    return bool(value) and value.isascii() and value.isdecimal() and value[0] != "0"


def next_freeze_epoch(previous_epoch: str | None) -> str:
    """Mint the next story-scoped DB epoch without time or process state."""

    if previous_epoch is None:
        return MIN_FREEZE_EPOCH
    if not is_canonical_freeze_epoch(previous_epoch):
        raise ValueError(f"invalid persisted freeze_epoch: {previous_epoch!r}")
    return str(int(previous_epoch) + 1)


def active_freeze_state_from_record(record: object) -> ActiveFreezeState:
    """Map a persistence record/mapping to the pure admission input, fail-closed."""

    if isinstance(record, dict):
        raw_kind = record.get("kind")
        raw_reason = record.get("freeze_reason")
        raw_epoch = record.get("freeze_epoch")
    else:
        raw_kind = getattr(record, "kind", None)
        raw_reason = getattr(record, "freeze_reason", None)
        raw_epoch = getattr(record, "freeze_epoch", None)
    try:
        kind = raw_kind if isinstance(raw_kind, FreezeKind) else FreezeKind(str(raw_kind))
    except ValueError:
        kind = None
    reason = raw_reason if isinstance(raw_reason, str) and raw_reason.strip() else None
    epoch = raw_epoch if isinstance(raw_epoch, str) and is_canonical_freeze_epoch(raw_epoch) else None
    return ActiveFreezeState(kind=kind, freeze_reason=reason, freeze_epoch=epoch)


def command_resolves_freeze(command_id: str, freeze: ActiveFreezeState) -> bool:
    """Return whether the single registry explicitly allows this resolution."""

    if (
        not freeze.readable
        or freeze.kind is None
        or freeze.freeze_reason is None
        or freeze.freeze_epoch is None
    ):
        return False
    return command_id in RESOLVING_COMMANDS_BY_KIND[freeze.kind]


def freeze_error_code(kind: FreezeKind | str | None) -> str:
    """Return the distinct wire code for freeze kinds that own one."""

    if kind == FreezeKind.CONTESTED_LOCAL_WRITES:
        return FreezeKind.CONTESTED_LOCAL_WRITES.value
    return ERROR_CODE_STORY_FROZEN


__all__ = [
    "ActiveFreezeState",
    "ERROR_CODE_STORY_FROZEN",
    "FreezeKind",
    "MIN_FREEZE_EPOCH",
    "RESOLVING_COMMANDS_BY_KIND",
    "active_freeze_state_from_record",
    "command_resolves_freeze",
    "freeze_error_code",
    "is_canonical_freeze_epoch",
    "next_freeze_epoch",
]
