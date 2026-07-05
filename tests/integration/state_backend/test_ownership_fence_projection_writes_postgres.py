"""Integration: AG3-144 ownership-lease fence on story PROJECTION writes.

FK-91 §91.1a Rule 15 (no-lease-no-write) already fences the REGIME commits
(start/complete/fail/closure/resume) via AG3-142's ``_enforce_ownership_fence_row``
(see the sibling ``test_ownership_fence_postgres.py``). This module proves the
SAME fence, reused verbatim (never a second mechanism), now also guards the
mutating story PROJECTION writes AG3-144 targets:

* ``record_layer_artifacts`` -- ``qa_stage_results`` + ``qa_findings``
  (batch delete+rebuild) + the projection file.
* ``record_verify_decision`` -- ``decision_records`` + the projection file.
* ``record_closure_report`` -- the closure-report projection file (no DB row
  for this artifact; the fence transaction's sole purpose is to reject a lost
  lease BEFORE the file write).

Each surface gets:

* a POSITIVE test (AC3): a valid, matching lease snapshot -> the write lands
  exactly as specified;
* a combined NEGATIVE + TOCTOU test (AC2/AC4): the epoch drift is injected via
  the SANCTIONED AG3-137 single-writer surface (a direct UPDATE on
  ``run_ownership_records``, mirroring ``test_ownership_fence_postgres.py``'s
  ``_raw_update_ownership_row``) AFTER the caller's snapshot was captured --
  exactly the window a real (possibly long) QA-subflow execution occupies in
  production. The commit -- which still presents the STALE snapshot -- is
  rejected with :class:`OwnershipFenceViolationError`, and the projection
  (DB rows + file) is proven BYTE-IDENTICAL to its pre-attempt state (no
  partial write, no batch delete+rebuild for the layer-artifacts case).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.execution_report.records import ExecutionReport
from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import RunOwnershipRecord
from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.store import (
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_latest_verify_decision,
    load_qa_findings,
    load_qa_stage_results,
    record_closure_report,
    record_layer_artifacts,
    record_verify_decision,
    save_flow_execution,
)
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"


def _seed_flow(story_dir: Path, *, story_id: str, run_id: str) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
            started_at=_NOW,
        ),
    )


def _seed_active_ownership(
    *, story_id: str, run_id: str, owner_session_id: str = "sess-A", epoch: int = 1
) -> None:
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            owner_session_id=owner_session_id,
            ownership_epoch=epoch,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="audit:test-projection-fence",
        )
    )


def _hijack_ownership(*, story_id: str, new_owner: str, new_epoch: int) -> None:
    """Sanctioned AG3-137 single-writer surface: simulate a mid-flight takeover.

    Mirrors ``test_ownership_fence_postgres.py::_raw_update_ownership_row`` --
    AG3-148's productive transfer-confirm CAS does not exist yet; this touches
    the table directly through the SAME global connection the productive store
    uses (never a second physical connection, never a new production write
    primitive).
    """
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- sanctioned test-only direct touch
        conn.execute(
            """
            UPDATE run_ownership_records
            SET owner_session_id = ?, ownership_epoch = ?
            WHERE project_key = ? AND story_id = ? AND status = 'active'
            """,
            (new_owner, new_epoch, _PROJECT, story_id),
        )


# ---------------------------------------------------------------------------
# record_layer_artifacts -- qa_stage_results / qa_findings (batch)
# ---------------------------------------------------------------------------


def test_record_layer_artifacts_valid_lease_writes_as_specified(
    tmp_path: Path,
) -> None:
    """AC3 positive: a matching lease snapshot writes the QA rows + projection."""
    story_id = "AG3-910"
    run_id = "run-910"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    produced = record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(layer="structural", passed=True, findings=()),
        ),
        attempt_nr=1,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )

    assert produced == ("structural.json",)
    assert (story_dir / "structural.json").exists()
    stages = load_qa_stage_results(
        story_dir, project_key=_PROJECT, story_id=story_id, run_id=run_id, attempt_no=1,
    )
    assert len(stages) == 1
    assert stages[0].status == "PASS"


def test_record_layer_artifacts_lost_lease_rejects_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """AC2/AC4 (no TOCTOU): a stale snapshot rejects; the prior batch survives
    BYTE-IDENTICAL (no delete+rebuild), and no projection file is (re)written.
    """
    story_id = "AG3-911"
    run_id = "run-911"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    # A genuine PRIOR batch, written under the SAME valid lease.
    record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(layer="structural", passed=False, findings=()),
        ),
        attempt_nr=1,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )
    prior_stages = load_qa_stage_results(
        story_dir, project_key=_PROJECT, story_id=story_id, run_id=run_id, attempt_no=1,
    )
    assert len(prior_stages) == 1
    assert prior_stages[0].status == "FAIL"
    prior_projection = (story_dir / "structural.json").read_bytes()

    # The race: ownership moves on AFTER this caller's own early snapshot.
    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    # This caller still presents its STALE (sess-A, epoch=1) snapshot, and
    # attempts to REBUILD the SAME scope with a DIFFERENT (passed=True) result
    # -- proving a successful commit would have been observably different.
    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        record_layer_artifacts(
            story_dir,
            layer_results=(
                LayerResult(layer="structural", passed=True, findings=()),
            ),
            attempt_nr=1,
            owner_session_id="sess-A",
            expected_ownership_epoch=1,
            projection_dir=story_dir,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    assert excinfo.value.detail["current_ownership_epoch"] == 2
    # NOTHING changed: the prior batch (delete+rebuild never ran) and the
    # projection file are byte-identical to before the rejected attempt.
    rejected_stages = load_qa_stage_results(
        story_dir, project_key=_PROJECT, story_id=story_id, run_id=run_id, attempt_no=1,
    )
    assert len(rejected_stages) == 1
    assert rejected_stages[0].status == "FAIL"
    assert (story_dir / "structural.json").read_bytes() == prior_projection


def test_record_layer_artifacts_findings_batch_survives_rejected_rebuild(
    tmp_path: Path,
) -> None:
    """AC2 (qa_findings batch delete+rebuild): a rejected write never deletes
    the prior findings batch -- the delete-then-insert never starts because
    the fence runs BEFORE the loop over ``layer_payload_rows``.
    """
    from agentkit.backend.verify_system.protocols import Finding, Severity, TrustClass

    story_id = "AG3-912"
    run_id = "run-912"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    prior_finding = Finding(
        layer="structural",
        check="context_exists",
        severity=Severity.BLOCKING,
        message="context.json is missing",
        trust_class=TrustClass.SYSTEM,
        file_path="context.json",
        line_number=1,
    )
    record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(layer="structural", passed=False, findings=(prior_finding,)),
        ),
        attempt_nr=1,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )
    prior_findings = load_qa_findings(
        story_dir, project_key=_PROJECT, story_id=story_id, run_id=run_id, attempt_no=1,
    )
    assert len(prior_findings) == 1

    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    with pytest.raises(OwnershipFenceViolationError):
        record_layer_artifacts(
            story_dir,
            layer_results=(
                LayerResult(layer="structural", passed=True, findings=()),
            ),
            attempt_nr=1,
            owner_session_id="sess-A",
            expected_ownership_epoch=1,
            projection_dir=story_dir,
        )

    rejected_findings = load_qa_findings(
        story_dir, project_key=_PROJECT, story_id=story_id, run_id=run_id, attempt_no=1,
    )
    assert len(rejected_findings) == 1
    assert rejected_findings[0].check_id == "context_exists"


# ---------------------------------------------------------------------------
# record_verify_decision -- decision_records
# ---------------------------------------------------------------------------


def _decision(summary: str, *, passed: bool) -> VerifyDecision:
    return VerifyDecision(
        passed=passed,
        verdict=PolicyVerdict.PASS if passed else PolicyVerdict.FAIL,
        layer_results=(),
        all_findings=(),
        blocking_findings=(),
        summary=summary,
    )


def test_record_verify_decision_valid_lease_writes_as_specified(
    tmp_path: Path,
) -> None:
    """AC3 positive: a matching lease snapshot writes the decision row + file."""
    story_id = "AG3-913"
    run_id = "run-913"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    record_verify_decision(
        story_dir,
        decision=_decision("ok", passed=True),
        attempt_nr=1,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )

    decision = load_latest_verify_decision(story_dir)
    assert decision is not None
    assert decision["status"] == "PASS"
    assert (story_dir / "decision.json").exists()


def test_record_verify_decision_lost_lease_rejects_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """AC2/AC4 (no TOCTOU): a stale snapshot rejects; the prior decision row
    and projection file survive BYTE-IDENTICAL.
    """
    story_id = "AG3-914"
    run_id = "run-914"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    record_verify_decision(
        story_dir,
        decision=_decision("original pass", passed=True),
        attempt_nr=1,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )
    prior_decision = load_latest_verify_decision(story_dir)
    prior_projection = (story_dir / "decision.json").read_bytes()

    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        record_verify_decision(
            story_dir,
            decision=_decision("ex-owner overwrite attempt", passed=False),
            attempt_nr=1,
            owner_session_id="sess-A",
            expected_ownership_epoch=1,
            projection_dir=story_dir,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    rejected_decision = load_latest_verify_decision(story_dir)
    assert rejected_decision == prior_decision
    assert (story_dir / "decision.json").read_bytes() == prior_projection


# ---------------------------------------------------------------------------
# record_closure_report -- projection file only (no dedicated DB row)
# ---------------------------------------------------------------------------


def _report(story_id: str, status: str) -> ExecutionReport:
    return ExecutionReport(
        story_id=story_id,
        story_type="implementation",
        status=status,
        phases_executed=("setup", "implementation", "closure"),
        story_closed=status == "completed",
    )


def test_record_closure_report_valid_lease_writes_as_specified(
    tmp_path: Path,
) -> None:
    """AC3 positive: a matching lease snapshot writes the closure projection."""
    story_id = "AG3-915"
    run_id = "run-915"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    path = record_closure_report(
        story_dir,
        _report(story_id, "completed"),
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )

    assert path == story_dir / "closure.json"
    assert path.exists()


def test_record_closure_report_lost_lease_rejects_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """AC2/AC4 (no TOCTOU): a stale snapshot rejects BEFORE the projection
    file is ever written -- there is no dedicated DB row for this artifact,
    so the fence's sole job is to gate the file write.
    """
    story_id = "AG3-916"
    run_id = "run-916"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        record_closure_report(
            story_dir,
            _report(story_id, "completed"),
            owner_session_id="sess-A",
            expected_ownership_epoch=1,
            projection_dir=story_dir,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    assert not (story_dir / "closure.json").exists()
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-HIJACK"
