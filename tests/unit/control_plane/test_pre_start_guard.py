"""Unit tests for the fail-closed pre-start run-admission guard (AG3-054).

Pins ``story-workflow.invariant.phase_start_requires_release_and_readiness``
(FK-20 §20.8.2, FK-70 §70.8): the fresh-run setup start is admitted ONLY when the
persisted ``StoryStatus`` is Approved (Tor 1) AND ExecutionPlanning reports
computed ``PlanningStatus`` READY with a scheduling admission (Tor 2). Either gate
missing -- or any surface erroring -- rejects fail-closed (never default-allow).
The two axes are kept orthogonal: READY/BLOCKED is never treated as a
``StoryStatus``.

The two surfaces are external read ports (story-service / execution-planning);
the test doubles here are at those sanctioned boundaries only -- the guard logic
itself is exercised for real.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.control_plane.dispatch import PreStartGuard


@dataclass
class _FakeApprovalReader:
    approved: bool = True
    raises: bool = False
    seen: list[tuple[str, str]] | None = None

    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        if self.seen is not None:
            self.seen.append((project_key, story_display_id))
        if self.raises:
            msg = "story service unreachable"
            raise RuntimeError(msg)
        return self.approved


@dataclass
class _FakeSchedulingReader:
    admitted: bool = True
    raises: bool = False
    seen: list[tuple[str, str]] | None = None

    def is_ready_and_admitted(self, project_key: str, story_display_id: str) -> bool:
        if self.seen is not None:
            self.seen.append((project_key, story_display_id))
        if self.raises:
            msg = "planning unreachable"
            raise RuntimeError(msg)
        return self.admitted


def _guard(
    *,
    approved: bool = True,
    admitted: bool = True,
    approval_raises: bool = False,
    scheduling_raises: bool = False,
) -> PreStartGuard:
    return PreStartGuard(
        approval_reader=_FakeApprovalReader(
            approved=approved, raises=approval_raises
        ),
        scheduling_reader=_FakeSchedulingReader(
            admitted=admitted, raises=scheduling_raises
        ),
    )


class TestPreStartGuardPositive:
    def test_admits_when_approved_and_ready_and_admitted(self) -> None:
        """The only positive case: Approved AND READY+admission."""
        result = _guard().evaluate(project_key="P", story_display_id="AG3-001")
        assert result is None


class TestPreStartGuardNegative:
    def test_rejects_when_not_approved(self) -> None:
        """Tor 1 missing: StoryStatus != Approved rejects."""
        result = _guard(approved=False).evaluate(
            project_key="P", story_display_id="AG3-001"
        )
        assert result is not None
        assert "Approved" in result

    def test_rejects_when_not_ready_or_not_admitted(self) -> None:
        """Tor 2 missing: not READY / no scheduling admission rejects."""
        result = _guard(admitted=False).evaluate(
            project_key="P", story_display_id="AG3-001"
        )
        assert result is not None
        assert "READY" in result or "scheduling" in result

    def test_rejects_when_approval_surface_errors(self) -> None:
        """Fail-closed: an unresolvable Tor 1 surface rejects (never allows)."""
        result = _guard(approval_raises=True).evaluate(
            project_key="P", story_display_id="AG3-001"
        )
        assert result is not None
        assert "could not be resolved" in result

    def test_rejects_when_scheduling_surface_errors(self) -> None:
        """Fail-closed: an unresolvable Tor 2 surface rejects (never allows)."""
        result = _guard(scheduling_raises=True).evaluate(
            project_key="P", story_display_id="AG3-001"
        )
        assert result is not None
        assert "could not be resolved" in result


class TestPreStartGuardAxisSeparation:
    def test_tor1_evaluated_before_tor2_and_short_circuits(self) -> None:
        """Approval missing short-circuits before scheduling is consulted.

        Proves the axes are distinct reads, not one collapsed boolean: when Tor 1
        fails the scheduling surface is never queried.
        """
        approval = _FakeApprovalReader(approved=False, seen=[])
        scheduling = _FakeSchedulingReader(admitted=True, seen=[])
        guard = PreStartGuard(
            approval_reader=approval, scheduling_reader=scheduling
        )

        result = guard.evaluate(project_key="P", story_display_id="AG3-001")

        assert result is not None
        assert approval.seen == [("P", "AG3-001")]
        # Tor 2 not consulted once Tor 1 already rejected -> two separate axes.
        assert scheduling.seen == []

    def test_both_surfaces_consulted_on_admit(self) -> None:
        """A positive admission consults BOTH orthogonal surfaces."""
        approval = _FakeApprovalReader(approved=True, seen=[])
        scheduling = _FakeSchedulingReader(admitted=True, seen=[])
        guard = PreStartGuard(
            approval_reader=approval, scheduling_reader=scheduling
        )

        result = guard.evaluate(project_key="P", story_display_id="AG3-001")

        assert result is None
        assert approval.seen == [("P", "AG3-001")]
        assert scheduling.seen == [("P", "AG3-001")]
