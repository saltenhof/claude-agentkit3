"""Edge-Command-Queue vocabulary A-core (FK-91 §91.1b, AG3-145).

Blood-type A: pure, DB-free, unit-testable. FK-91 §91.1b defines the
Edge-Command-Queue (Auftrag/Meldung) that replaces backend-side physical
worktree operations (FK-10 §10.2.4a): the backend commissions a command, the
Project Edge executes it dev-locally and reports a typed result. This module
owns the closed, contract-pinned command-kind / result-type / lifecycle-status
vocabulary shared by both sides of the wire (backend command creation +
``harness_client`` edge executor) -- no I/O, no transactions.

Only ``provision_worktree`` / ``teardown_worktree`` / ``preflight_probe`` are
EXECUTED by this story (AG3-145 Teilschritt B); ``sync_push`` /
``takeover_reconcile`` / ``merge_local`` are REGISTERED here (contract-pinned
vocabulary) but their commissioning/execution belongs to AG3-147 / AG3-151 /
AG3-152 respectively. An edge that receives a command of a kind outside
:data:`EXECUTABLE_COMMAND_KINDS` reports a deterministic error result -- never
a silent no-op (Scope item 4).
"""

from __future__ import annotations

from typing import Literal

__all__ = (
    "ALL_COMMAND_KINDS",
    "ALL_COMMAND_STATUSES",
    "EXECUTABLE_COMMAND_KINDS",
    "OPEN_COMMAND_STATUSES",
    "RESULT_TYPES",
    "TAKEOVER_ERROR_RESULT_TYPES",
    "CommandKind",
    "CommandStatus",
    "ResultType",
    "TakeoverErrorResultType",
    "is_executable_command_kind",
    "is_known_command_kind",
)

#: FK-91 §91.1b "Auftragsarten (initial)": the closed set of command kinds the
#: Edge-Command-Queue can carry. Six total; only three are executed by THIS
#: story (see :data:`EXECUTABLE_COMMAND_KINDS`) -- the rest are registered
#: vocabulary owned by AG3-147 / AG3-151 / AG3-152.
CommandKind = Literal[
    "provision_worktree",
    "teardown_worktree",
    "preflight_probe",
    "sync_push",
    "takeover_reconcile",
    "merge_local",
]

ALL_COMMAND_KINDS: frozenset[str] = frozenset(
    {
        "provision_worktree",
        "teardown_worktree",
        "preflight_probe",
        "sync_push",
        "takeover_reconcile",
        "merge_local",
    }
)

#: AG3-145 Teilschritt B: the edge executors THIS story builds. A command of
#: any OTHER registered kind is a deterministic error result at the edge.
EXECUTABLE_COMMAND_KINDS: frozenset[str] = frozenset(
    {"provision_worktree", "teardown_worktree", "preflight_probe"}
)

#: FK-91 §91.1a Rule 16 (no wall-clock end): a command record's lifecycle
#: status. ``created`` = enqueued, not yet fetched by any GET; ``delivered`` =
#: the GET ack fired at least once; ``completed`` / ``failed`` are terminal (a
#: result was applied). There is deliberately no ``expired`` member -- open
#: commands never end by TTL (SOLL-165).
CommandStatus = Literal["created", "delivered", "completed", "failed"]

ALL_COMMAND_STATUSES: frozenset[str] = frozenset(
    {"created", "delivered", "completed", "failed"}
)

#: The non-terminal statuses a session's GET may return / a POST result may
#: resolve from (SOLL-165: no wall-clock end -- an open command stays open
#: indefinitely, never silently dropped by a status sweep).
OPEN_COMMAND_STATUSES: frozenset[str] = frozenset({"created", "delivered"})

#: FK-91 §91.1b "Result-Typen": the three named report shapes.
ResultType = Literal["branch_ref_report", "push_status_report", "worktree_report"]

RESULT_TYPES: frozenset[str] = frozenset(
    {"branch_ref_report", "push_status_report", "worktree_report"}
)

#: FK-91 §91.1b / FK-30 §30.6.3: the named takeover-family error states --
#: benannte Result-Zustaende, never a collective FAIL.
#: ``local_stale_or_dirty_takeover_target`` doubles as a named Check-8
#: preflight finding (AG3-145 Teilschritt C, FK-22 §22.3.1).
TakeoverErrorResultType = Literal[
    "remote_branch_diverged_after_takeover",
    "local_stale_or_dirty_takeover_target",
    "contested_local_writes",
]

TAKEOVER_ERROR_RESULT_TYPES: frozenset[str] = frozenset(
    {
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    }
)


def is_known_command_kind(kind: str) -> bool:
    """Return whether ``kind`` is one of the six registered command kinds."""
    return kind in ALL_COMMAND_KINDS


def is_executable_command_kind(kind: str) -> bool:
    """Return whether ``kind`` has a productive edge executor in THIS story.

    An edge dispatch loop uses this to decide between running an executor and
    reporting the deterministic "unsupported command kind" error result
    (never a silent no-op, AG3-145 Scope item 4).
    """
    return kind in EXECUTABLE_COMMAND_KINDS
