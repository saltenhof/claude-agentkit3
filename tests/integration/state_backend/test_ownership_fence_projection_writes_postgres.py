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
  lease BEFORE the file write); the lock is proven to SPAN the file write
  (Codex round-2 TOCTOU fix) with a genuine two-connection concurrency test.
* ``artifact_envelopes`` (Codex round-2 CRITICAL 1) -- the
  ``StateBackendArtifactRepository`` Postgres write, fenced via the
  ``OwnershipFenceScope`` ContextVar (``bind_ownership_fence_scope`` /
  ``require_ownership_fence_scope``) instead of an explicit parameter, so the
  SAME fence protects the write regardless of which BC-internal layer
  (verify-system's QA-subflow, prompt-runtime materialization, the
  adversarial orchestrator, exploration drafting/review, the ARE-gate audit)
  produced the envelope.
* ``qa_check_outcomes`` (Codex round-2 CRITICAL 3) -- the
  ``FacadeQACheckOutcomesRepository`` Postgres write, fenced the same way.

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

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.closure.execution_report.records import ExecutionReport
from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import RunOwnershipRecord
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus, PolicyVerdict
from agentkit.backend.exceptions import CorruptStateError, OwnershipFenceViolationError
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema
from agentkit.backend.state_backend.store import (
    bind_ownership_fence_scope,
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_latest_verify_decision,
    load_qa_findings,
    load_qa_stage_results,
    record_closure_report,
    record_layer_artifacts,
    record_verify_decision,
    require_ownership_fence_scope,
    save_flow_execution,
)
from agentkit.backend.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.backend.state_backend.store.projection_repositories import (
    FacadeQACheckOutcomesRepository,
)
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import LayerResult
from agentkit.backend.verify_system.stage_registry.records import (
    CheckOutcome,
    QACheckOutcomeRecord,
)

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


def test_record_closure_report_lock_spans_the_projection_write(
    postgres_isolated_schema: str,
    tmp_path: Path,
) -> None:
    """Codex round-2 TOCTOU fix: the row lock is held for the WHOLE file write.

    The prior shape released the ``run_ownership_records`` row lock (committed
    the fence-only transaction) BEFORE writing ``closure.json`` -- a takeover
    landing in that window let the ex-owner still write the file. This is now
    structurally impossible: the file write happens INSIDE the same
    transaction as the fence. Proven here with a GENUINE second physical
    connection (not the size-1 state pool): while a background thread is
    blocked mid-write (inside the monkey-patched ``_write_projection``), a
    second raw connection's ``SELECT ... FOR UPDATE NOWAIT`` on the SAME
    ``run_ownership_records`` row MUST fail with ``LockNotAvailable`` -- proof
    the lock is still held. Releasing the writer lets it finish; the row is
    then provably free again.
    """
    story_id = "AG3-917"
    run_id = "run-917"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_flow(story_dir, story_id=story_id, run_id=run_id)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)

    write_started = threading.Event()
    release_write = threading.Event()
    original_write_projection = postgres_store._write_projection

    def _blocking_write_projection(path: object, payload: object) -> None:
        write_started.set()
        assert release_write.wait(timeout=5), "test probe never signalled release"
        original_write_projection(path, payload)  # type: ignore[arg-type]

    result: dict[str, object] = {}
    errors: list[BaseException] = []

    def _run_writer() -> None:
        postgres_store._write_projection = _blocking_write_projection
        try:
            result["path"] = record_closure_report(
                story_dir,
                _report(story_id, "completed"),
                owner_session_id="sess-A",
                expected_ownership_epoch=1,
                projection_dir=story_dir,
            )
        except BaseException as exc:  # noqa: BLE001 -- surfaced to the test thread
            errors.append(exc)
        finally:
            postgres_store._write_projection = original_write_projection

    writer_thread = threading.Thread(target=_run_writer)
    writer_thread.start()
    try:
        assert write_started.wait(timeout=5), "closure write never started"

        # A genuinely SEPARATE physical connection (not the size-1 state pool):
        # probes the SAME row the writer's fence transaction still holds.
        probe_conn = psycopg.connect(postgres_isolated_schema)
        try:
            ensure_versioned_schema(probe_conn)
            with pytest.raises(psycopg.errors.LockNotAvailable):
                probe_conn.execute(
                    "SELECT 1 FROM run_ownership_records "
                    "WHERE project_key = %s AND story_id = %s AND status = 'active' "
                    "FOR UPDATE NOWAIT",
                    (_PROJECT, story_id),
                )
            probe_conn.rollback()
        finally:
            release_write.set()
            writer_thread.join(timeout=5)
            assert not writer_thread.is_alive(), "writer thread did not finish"
            if errors:
                raise errors[0]
            # After the writer committed, the row is free again -- the lock did
            # NOT leak past the transaction's own commit.
            probe_conn.execute(
                "SELECT 1 FROM run_ownership_records "
                "WHERE project_key = %s AND story_id = %s AND status = 'active' "
                "FOR UPDATE NOWAIT",
                (_PROJECT, story_id),
            )
            probe_conn.rollback()
            probe_conn.close()
    finally:
        postgres_store._write_projection = original_write_projection

    assert result["path"] == story_dir / "closure.json"
    assert (story_dir / "closure.json").exists()


# ---------------------------------------------------------------------------
# artifact_envelopes (Codex round-2 CRITICAL 1) -- OwnershipFenceScope
# ContextVar binding instead of an explicit parameter (FIX THE MODEL: the SAME
# fence protects the write regardless of which BC-internal layer -- verify-
# system's QA-subflow, prompt-runtime materialization, the adversarial
# orchestrator, exploration drafting/review, the ARE-gate audit -- produced
# the envelope).
# ---------------------------------------------------------------------------


def _artifact_envelope(
    *, story_id: str, run_id: str, payload: dict[str, object] | None = None
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage="implementation",
        attempt=1,
        producer=Producer(
            type=ProducerType.WORKER,
            name="worker-agent",
            id=ProducerId("w-1"),
        ),
        started_at=_NOW,
        finished_at=_NOW,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.HANDOVER,
        payload=payload,
    )


def test_artifact_envelope_valid_lease_writes_as_specified(tmp_path: Path) -> None:
    """AC3 positive: a bound, matching lease scope writes the envelope."""
    story_id = "AG3-918"
    run_id = "run-918"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)
    repo = StateBackendArtifactRepository(store_dir=story_dir)

    with bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ):
        ref = repo.write_envelope(_artifact_envelope(story_id=story_id, run_id=run_id))

    loaded = repo.read_envelope(ref)
    assert loaded is not None
    assert loaded.story_id == story_id


def test_artifact_envelope_no_bound_scope_rejects_hard(tmp_path: Path) -> None:
    """A write reaching the Postgres boundary with NO bound scope hard-fails.

    FIX THE MODEL: the write boundary REQUIRES the fence -- a caller that
    passes nothing is a hard runtime error (``CorruptStateError``), never a
    silent skip.
    """
    story_id = "AG3-919"
    run_id = "run-919"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)
    repo = StateBackendArtifactRepository(store_dir=story_dir)

    with pytest.raises(CorruptStateError, match="No OwnershipFenceScope is bound"):
        repo.write_envelope(_artifact_envelope(story_id=story_id, run_id=run_id))


def test_artifact_envelope_lost_lease_rejects_and_writes_nothing(tmp_path: Path) -> None:
    """AC2/AC4 (no TOCTOU): a stale bound scope rejects; the prior envelope
    survives BYTE-IDENTICAL (the UPSERT never runs -- the SAME record_key
    would otherwise have been overwritten).
    """
    story_id = "AG3-922"
    run_id = "run-922"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)
    repo = StateBackendArtifactRepository(store_dir=story_dir)

    prior = _artifact_envelope(story_id=story_id, run_id=run_id, payload={"v": "prior"})
    with bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ):
        ref = repo.write_envelope(prior)
    prior_read = repo.read_envelope(ref)
    assert prior_read is not None
    assert prior_read.payload == {"v": "prior"}

    # The race: ownership moves on AFTER this caller's own early snapshot.
    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    # This caller still presents its STALE (sess-A, epoch=1) scope and attempts
    # to overwrite the SAME record_key with an observably different payload.
    ex_owner_attempt = _artifact_envelope(
        story_id=story_id, run_id=run_id, payload={"v": "ex-owner-overwrite"}
    )
    with pytest.raises(OwnershipFenceViolationError) as excinfo, bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ):
        repo.write_envelope(ex_owner_attempt)

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    rejected_read = repo.read_envelope(ref)
    assert rejected_read is not None
    assert rejected_read.payload == {"v": "prior"}, (
        "the ex-owner's overwrite must NOT have landed -- byte-identical to "
        "the prior legitimate write"
    )


def test_require_ownership_fence_scope_rejects_cross_story_reuse(tmp_path: Path) -> None:
    """A bound scope for a DIFFERENT story never fences a foreign write."""
    del tmp_path
    with bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id="AG3-923-A",
        run_id="run-923-a",
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ), pytest.raises(CorruptStateError, match="story_id mismatch"):
        require_ownership_fence_scope(story_id="AG3-923-B")


# ---------------------------------------------------------------------------
# qa_check_outcomes (Codex round-2 CRITICAL 3) -- OwnershipFenceScope
# ContextVar binding (same mechanism as artifact_envelopes).
# ---------------------------------------------------------------------------


def _check_outcome_record(
    *, story_id: str, run_id: str, check_id: str = "structural.check"
) -> QACheckOutcomeRecord:
    return QACheckOutcomeRecord(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        stage_id="structural",
        attempt_no=1,
        check_id=check_id,
        outcome=CheckOutcome.CLEAN,
        occurred_at=_NOW,
        check_proposal_ref=None,
        override_id=None,
    )


def test_qa_check_outcomes_valid_lease_writes_as_specified(tmp_path: Path) -> None:
    """AC3 positive: a bound, matching lease scope writes the check-outcome row."""
    story_id = "AG3-924"
    run_id = "run-924"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)
    repo = FacadeQACheckOutcomesRepository(story_dir)

    with bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ):
        repo.write(_check_outcome_record(story_id=story_id, run_id=run_id))

    rows = repo.read(project_key=_PROJECT, story_id=story_id, run_id=run_id)
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.CLEAN


def test_qa_check_outcomes_transfer_before_emitter_loop_rejects_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """AC2 (Rule 18): an ownership transfer BEFORE the CheckOutcomeEmitter loop
    starts -- the exact AG3-108/AG3-144 scenario -- rejects every row in the
    loop; ``qa_check_outcomes`` ends up with NOTHING written.
    """
    story_id = "AG3-925"
    run_id = "run-925"
    story_dir = tmp_path / story_id
    story_dir.mkdir(parents=True)
    _seed_active_ownership(story_id=story_id, run_id=run_id, owner_session_id="sess-A", epoch=1)
    repo = FacadeQACheckOutcomesRepository(story_dir)

    # The transfer happens BEFORE the (simulated) CheckOutcomeEmitter loop --
    # this caller's bound scope below still presents the now-STALE snapshot it
    # captured at the top of its own on_enter() call.
    _hijack_ownership(story_id=story_id, new_owner="sess-HIJACK", new_epoch=2)

    with pytest.raises(OwnershipFenceViolationError) as excinfo, bind_ownership_fence_scope(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-A",
        expected_ownership_epoch=1,
    ):
        for check_id in ("check.one", "check.two", "check.three"):
            repo.write(
                _check_outcome_record(
                    story_id=story_id, run_id=run_id, check_id=check_id
                )
            )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    rows = repo.read(project_key=_PROJECT, story_id=story_id, run_id=run_id)
    assert rows == [], "qa_check_outcomes must have NOTHING written after the rejection"
