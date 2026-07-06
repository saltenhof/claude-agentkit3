"""Unit tests for the Edge-Command-Queue vocabulary A-core (FK-91 §91.1b, AG3-145).

Blood-type A: pure, DB-free vocabulary pins and pure predicate tests. No I/O.
"""

from __future__ import annotations

from agentkit.backend.control_plane import edge_commands as ec


def test_all_command_kinds_pins_the_six_registered_kinds() -> None:
    """FK-91 §91.1b: exactly the six initial command kinds, no more, no less."""
    assert {
        "provision_worktree",
        "teardown_worktree",
        "preflight_probe",
        "sync_push",
        "takeover_reconcile",
        "merge_local",
    } == ec.ALL_COMMAND_KINDS


def test_executable_command_kinds_is_the_ag3_145_subset() -> None:
    """The edge executes four of the six kinds: the AG3-145 worktree/preflight
    trio plus the AG3-147 ``sync_push`` official Edge-Push-Gate path."""
    assert {
        "provision_worktree",
        "teardown_worktree",
        "preflight_probe",
        "sync_push",
    } == ec.EXECUTABLE_COMMAND_KINDS
    assert ec.EXECUTABLE_COMMAND_KINDS < ec.ALL_COMMAND_KINDS


def test_all_command_statuses_has_no_wall_clock_expiry_member() -> None:
    """SOLL-165 (FK-91 §91.1a Rule 16): no 'expired' status exists at all."""
    assert {"created", "delivered", "completed", "failed"} == ec.ALL_COMMAND_STATUSES
    assert not (ec.ALL_COMMAND_STATUSES & {"expired", "timed_out", "lapsed"})


def test_open_command_statuses_are_exactly_the_non_terminal_ones() -> None:
    assert {"created", "delivered"} == ec.OPEN_COMMAND_STATUSES
    assert ec.OPEN_COMMAND_STATUSES < ec.ALL_COMMAND_STATUSES


def test_result_types_pins_the_three_named_report_shapes() -> None:
    assert {
        "branch_ref_report",
        "push_status_report",
        "worktree_report",
    } == ec.RESULT_TYPES


def test_takeover_error_result_types_pins_the_named_takeover_family() -> None:
    """FK-30 §30.6.3: the three named takeover error states -- never a collective FAIL."""
    assert {
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    } == ec.TAKEOVER_ERROR_RESULT_TYPES
    # Doubles as a named Check-8 preflight finding (AG3-145 Teilschritt C).
    assert "local_stale_or_dirty_takeover_target" in ec.TAKEOVER_ERROR_RESULT_TYPES


def test_is_known_command_kind_accepts_all_six_and_rejects_unknown() -> None:
    for kind in ec.ALL_COMMAND_KINDS:
        assert ec.is_known_command_kind(kind) is True
    assert ec.is_known_command_kind("bogus_kind") is False
    assert ec.is_known_command_kind("") is False


def test_is_executable_command_kind_true_only_for_the_ag3_145_subset() -> None:
    for kind in ec.EXECUTABLE_COMMAND_KINDS:
        assert ec.is_executable_command_kind(kind) is True
    for kind in ec.ALL_COMMAND_KINDS - ec.EXECUTABLE_COMMAND_KINDS:
        assert ec.is_executable_command_kind(kind) is False
    assert ec.is_executable_command_kind("bogus_kind") is False
