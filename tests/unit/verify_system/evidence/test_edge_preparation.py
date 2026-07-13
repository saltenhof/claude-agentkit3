"""Boundary tests for the AG3-156 two-yield evidence protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import CommandErrorResult
from agentkit.backend.control_plane.records import EdgeCommandRecord
from agentkit.backend.core_types.verify_evidence import (
    VerifyEvidenceCanonicalRequest,
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
    VerifyEvidenceReport,
    VerifyEvidenceRepository,
    VerifyEvidenceRequest,
    VerifyEvidenceStage,
    VerifyTestCommand,
)
from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.backend.verify_system.evidence.edge_preparation import (
    EvidencePreparationInput,
    VerifyEvidencePreparationCoordinator,
    VerifyEvidencePreparationError,
    _candidate_digest,
    _command_record,
    _payload,
    _wait_budget,
    _waiting,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass
class MemoryEdgeCommands:
    """In-memory command-record port with the production transition shape."""

    records: dict[str, EdgeCommandRecord] = field(default_factory=dict)

    def load_command(self, command_id: str) -> EdgeCommandRecord | None:
        return self.records.get(command_id)

    def reconcile_verify_evidence_generation(self, **kwargs: object) -> tuple[bool, bool]:
        record = kwargs["record"]
        assert isinstance(record, EdgeCommandRecord)
        superseded = False
        for command_id, current in tuple(self.records.items()):
            if command_id == record.command_id:
                continue
            if current.status in {"created", "delivered"}:
                self.records[command_id] = replace(current, status="superseded")
                superseded = True
        inserted = record.command_id not in self.records
        self.records.setdefault(record.command_id, record)
        return superseded, inserted

    def supersede_verify_evidence(self, **kwargs: object) -> bool:
        command_id = str(kwargs["command_id"])
        current = self.records[command_id]
        if current.status not in {"created", "delivered"}:
            return False
        self.records[command_id] = replace(current, status="superseded")
        return True


@dataclass
class RecordingSender:
    """Preflight sender that records audited attempt correlation."""

    response: str
    crash_once: bool = False
    attempt_ids: list[str] = field(default_factory=list)

    def send(
        self,
        *,
        prompt: str,
        merge_paths: Sequence[Path],
        attempt_id: str,
        request_hash: str,
    ) -> str:
        assert prompt
        assert merge_paths
        assert len(request_hash) == 64
        self.attempt_ids.append(attempt_id)
        if self.crash_once:
            self.crash_once = False
            raise RuntimeError("simulated crash after LLM response")
        return self.response


@dataclass
class Clock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


def _inputs(tmp_path: Path, *, head: str = "a" * 40) -> EvidencePreparationInput:
    story_dir = tmp_path / "stories" / "AG3-156"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "story.md").write_text("# AG3-156\n", encoding="utf-8")
    return EvidencePreparationInput(
        project_key="project",
        story_id="AG3-156",
        run_id="run-156",
        implementation_attempt=1,
        owner_session_id="session-1",
        ownership_epoch=3,
        repositories=(
            VerifyEvidenceRepository(
                repo_id="app",
                expected_head_sha=head,
                changed_paths=("src/app.py",),
            ),
        ),
        spawn_worktree_repo="app",
        story_dir=story_dir,
    )


def _complete_base(store: MemoryEdgeCommands, command_id: str) -> None:
    record = store.records[command_id]
    payload = record.payload
    file = VerifyEvidenceFile.from_content(
        repo_id="app", path="src/app.py", content="def app():\n    return 1\n"
    )
    report = VerifyEvidenceReport(
        stage="base_collection",
        batch_id=str(payload["batch_id"]),
        generation=str(payload["generation"]),
        candidate_digest=str(payload["candidate_digest"]),
        request_digest=str(payload["request_digest"]),
        files=(file,),
    )
    store.records[command_id] = replace(
        record,
        status="completed",
        result_type="verify_evidence_report",
        result_payload=report.model_dump(mode="json"),
    )


def _complete_dynamic(store: MemoryEdgeCommands, command_id: str) -> None:
    record = store.records[command_id]
    payload = record.payload
    candidate = VerifyEvidenceFile.from_content(
        repo_id="app", path="src/context.py", content="CONTEXT = 1\n"
    )
    report = VerifyEvidenceReport(
        stage="dynamic_requests",
        batch_id=str(payload["batch_id"]),
        generation=str(payload["generation"]),
        candidate_digest=str(payload["candidate_digest"]),
        request_digest=str(payload["request_digest"]),
        observations=(
            VerifyEvidenceObservation(
                request_index=0,
                status=VerifyEvidenceObservationStatus.COLLECTED,
                candidates=(candidate,),
            ),
        ),
    )
    store.records[command_id] = replace(
        record,
        status="completed",
        result_type="verify_evidence_report",
        result_payload=report.model_dump(mode="json"),
    )


def _complete_empty_dynamic(store: MemoryEdgeCommands, command_id: str) -> None:
    record = store.records[command_id]
    payload = record.payload
    report = VerifyEvidenceReport(
        stage="dynamic_requests",
        batch_id=str(payload["batch_id"]),
        generation=str(payload["generation"]),
        candidate_digest=str(payload["candidate_digest"]),
        request_digest=str(payload["request_digest"]),
    )
    store.records[command_id] = replace(
        record,
        status="completed",
        result_type="verify_evidence_report",
        result_payload=report.model_dump(mode="json"),
    )


def test_two_yields_then_fenced_resume_applies_d3_bundle(tmp_path: Path) -> None:
    store = MemoryEdgeCommands()
    sender = RecordingSender(
        '{"requests":[{"type":"NEED_FILE","target":"src/context.py","reason":"review"}]}'
    )
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=sender,
    )
    inputs = _inputs(tmp_path)

    first = coordinator.advance(inputs, None)
    assert first.waiting and first.cursor is not None
    _complete_base(store, first.cursor.command_id)

    second = coordinator.advance(inputs, first.cursor)
    assert second.waiting and second.cursor is not None
    assert second.cursor.stage == "dynamic_requests"
    assert len(sender.attempt_ids) == 1
    base_manifest = store.records[second.cursor.command_id].payload["base_manifest"]
    assert isinstance(base_manifest, dict)
    dynamic_payload = store.records[second.cursor.command_id].payload
    assert dynamic_payload["raw_preflight_response"] == sender.response
    assert dynamic_payload["preflight_requests"] == [
        {
            "request_type": "NEED_FILE",
            "target": "src/context.py",
            "region": None,
            "reason": "review",
        }
    ]
    checkpointed_manifest = BundleManifest.model_validate(base_manifest)
    assert ("app", "src/app.py") in {
        (entry.repo_id, entry.path.as_posix())
        for entry in checkpointed_manifest.entries
    }
    _complete_dynamic(store, second.cursor.command_id)

    final = coordinator.advance(inputs, second.cursor)
    assert not final.waiting and final.manifest is not None
    assert ("app", "src/context.py") in {
        (entry.repo_id, entry.path.as_posix()) for entry in final.manifest.entries
    }
    assert [item.status for item in final.request_results] == ["RESOLVED"]


def test_crash_after_preflight_response_never_reuses_attempt(tmp_path: Path) -> None:
    store = MemoryEdgeCommands()
    sender = RecordingSender('{"requests":[]}', crash_once=True)
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=sender,
    )
    inputs = _inputs(tmp_path)
    first = coordinator.advance(inputs, None)
    assert first.cursor is not None
    _complete_base(store, first.cursor.command_id)

    with pytest.raises(RuntimeError, match="simulated crash"):
        coordinator.advance(inputs, first.cursor)
    resumed = coordinator.advance(inputs, first.cursor)

    assert resumed.waiting
    assert len(sender.attempt_ids) == 2
    assert len(set(sender.attempt_ids)) == 2
    audit_attempts = [
        record
        for record in store.records.values()
        if record.payload.get("preflight_checkpoint_state") == "started"
    ]
    assert len(audit_attempts) == 2
    assert all(record.status == "superseded" for record in audit_attempts)


def test_deadline_supersedes_and_emits_request_timeout(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 7, 13, tzinfo=UTC))
    store = MemoryEdgeCommands()
    sender = RecordingSender(
        '{"requests":[{"type":"NEED_FILE","target":"missing.py","reason":"review"}]}'
    )
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=sender,
        now=clock,
        collection_margin=timedelta(seconds=5),
    )
    inputs = _inputs(tmp_path)
    base = coordinator.advance(inputs, None)
    assert base.cursor is not None
    clock.value += timedelta(seconds=6)
    dynamic = coordinator.advance(inputs, base.cursor)
    assert store.records[base.cursor.command_id].status == "superseded"
    assert dynamic.cursor is not None
    clock.value += timedelta(seconds=6)

    final = coordinator.advance(inputs, dynamic.cursor)

    assert final.request_results[0].status == "TIMEOUT"
    assert store.records[dynamic.cursor.command_id].status == "superseded"


def test_120_second_test_contract_completes_after_old_30_second_cap(
    tmp_path: Path,
) -> None:
    """A maximum-duration test can report after 30 seconds and be consumed."""
    clock = Clock(datetime(2026, 7, 13, tzinfo=UTC))
    store = MemoryEdgeCommands()
    inputs = _inputs(tmp_path)
    requests = (
        VerifyEvidenceRequest(
            request_index=0,
            request_type="NEED_TEST_EVIDENCE",
            target="pytest -q tests/test_slow.py",
            test_command=VerifyTestCommand(
                arguments=("-q", "tests/test_slow.py"),
                timeout_seconds=120,
            ),
        ),
    )
    budget = _wait_budget(requests, collection_margin=timedelta(seconds=30))
    assert budget == timedelta(seconds=150)
    candidate_digest = _candidate_digest(inputs.repositories, ())
    manifest = BundleManifest.from_entries(
        [],
        truncated=False,
        warnings=[],
        evidence_epoch=clock.value,
    )
    payload = _payload(
        inputs,
        stage=VerifyEvidenceStage.DYNAMIC_REQUESTS,
        candidate_digest=candidate_digest,
        request_digest="f" * 64,
        generation_seed="120-second-contract",
        deadline_at=clock.value + budget,
        requests=requests,
        preflight_requests=(
            VerifyEvidenceCanonicalRequest(
                request_type="NEED_TEST_EVIDENCE",
                target="pytest -q tests/test_slow.py",
                reason="verify slow contract",
            ),
        ),
        preflight_attempt_id="attempt-120",
        preflight_checkpoint_state="ready",
        preflight_request_hash="e" * 64,
        raw_preflight_response='{"requests":[]}',
        base_manifest=manifest.model_dump(mode="json"),
    )
    record = _command_record(inputs, payload)
    store.records[record.command_id] = record
    cursor = _waiting(inputs, payload, record.command_id).cursor
    assert cursor is not None
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
        now=clock,
    )
    clock.value += timedelta(seconds=31)

    still_waiting = coordinator.advance(inputs, cursor)

    assert still_waiting.waiting
    report = VerifyEvidenceReport(
        stage="dynamic_requests",
        batch_id=payload.batch_id,
        generation=payload.generation,
        candidate_digest=payload.candidate_digest,
        request_digest=payload.request_digest,
        observations=(
            VerifyEvidenceObservation(
                request_index=0,
                status=VerifyEvidenceObservationStatus.COLLECTED,
                content="exit_code=0\n1 passed",
            ),
        ),
    )
    store.records[record.command_id] = replace(
        record,
        status="completed",
        result_type=report.result_type,
        result_payload=report.model_dump(mode="json"),
    )

    completed = coordinator.advance(inputs, cursor)

    assert not completed.waiting
    assert completed.request_results[0].status == "RESOLVED"


def test_edge_command_failure_surfaces_real_reason_in_base_manifest(
    tmp_path: Path,
) -> None:
    """Resume projects a terminal edge error without relabeling it TIMEOUT."""
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    )
    inputs = _inputs(tmp_path)
    base = coordinator.advance(inputs, None)
    assert base.cursor is not None
    record = store.records[base.cursor.command_id]
    failure = CommandErrorResult(
        error_code="command_execution_failed",
        message="payload schema version is unsupported",
    )
    store.records[record.command_id] = replace(
        record,
        status="failed",
        result_type=failure.result_type,
        result_payload=failure.model_dump(mode="json"),
    )

    dynamic = coordinator.advance(inputs, base.cursor)

    assert dynamic.cursor is not None
    manifest_data = store.records[dynamic.cursor.command_id].payload["base_manifest"]
    manifest = BundleManifest.model_validate(manifest_data)
    assert any(
        "command_execution_failed" in warning
        and "payload schema version is unsupported" in warning
        for warning in manifest.warnings
    )
    assert all("EDGE_EVIDENCE_TIMEOUT" not in warning for warning in manifest.warnings)


def test_schema_skewed_failure_surfaces_real_reason_before_payload_validation(
    tmp_path: Path,
) -> None:
    """A typed error from an unreadable command never degrades to ValidationError."""
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    )
    inputs = _inputs(tmp_path)
    base = coordinator.advance(inputs, None)
    assert base.cursor is not None
    record = store.records[base.cursor.command_id]
    skewed_payload = dict(record.payload)
    skewed_payload["schema_version"] = "0.9"
    failure = CommandErrorResult(
        error_code="command_execution_failed",
        message="payload schema version is unsupported",
    )
    store.records[record.command_id] = replace(
        record,
        payload=skewed_payload,
        status="failed",
        result_type=failure.result_type,
        result_payload=failure.model_dump(mode="json"),
    )

    with pytest.raises(
        VerifyEvidencePreparationError,
        match="command_execution_failed: payload schema version is unsupported",
    ):
        coordinator.advance(inputs, base.cursor)


def test_candidate_drift_supersedes_before_new_generation(tmp_path: Path) -> None:
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    )
    first = coordinator.advance(_inputs(tmp_path), None)
    assert first.cursor is not None

    drifted = coordinator.advance(_inputs(tmp_path, head="b" * 40), first.cursor)

    assert drifted.cursor is not None
    assert drifted.cursor.command_id != first.cursor.command_id
    assert store.records[first.cursor.command_id].status == "superseded"


def test_candidate_flap_back_to_a_recollects_with_fresh_generation(
    tmp_path: Path,
) -> None:
    """A -> B -> A never rebinds the cursor to A's superseded command."""
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    )
    candidate_a = _inputs(tmp_path)
    first_a = coordinator.advance(candidate_a, None)
    assert first_a.cursor is not None
    candidate_b = _inputs(tmp_path, head="b" * 40)
    commissioned_b = coordinator.advance(candidate_b, first_a.cursor)
    assert commissioned_b.cursor is not None

    second_a = coordinator.advance(candidate_a, commissioned_b.cursor)

    assert second_a.cursor is not None
    assert second_a.cursor.command_id != first_a.cursor.command_id
    assert store.records[second_a.cursor.command_id].status == "created"


def test_reset_cursor_loss_still_supersedes_old_open_generation(tmp_path: Path) -> None:
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    )
    inputs = _inputs(tmp_path)
    first = coordinator.advance(inputs, None)
    assert first.cursor is not None

    new_owner = replace(inputs, owner_session_id="session-2", ownership_epoch=4)
    recommissioned = coordinator.advance(new_owner, None)

    assert recommissioned.cursor is not None
    assert recommissioned.cursor.command_id != first.cursor.command_id
    assert store.records[first.cursor.command_id].status == "superseded"


def test_worker_manifest_hints_bind_payload_and_candidate_generation(
    tmp_path: Path,
) -> None:
    """Productive worker-manifest path keys participate in Stage A and drift."""
    inputs = _inputs(tmp_path)
    first_store = MemoryEdgeCommands()
    first = VerifyEvidencePreparationCoordinator(
        edge_commands=first_store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    ).advance(inputs, None)
    assert first.cursor is not None
    initial_digest = first.cursor.candidate_digest
    (inputs.story_dir / "worker-manifest.json").write_text(
        json.dumps(
            {
                "files_changed": ["app:src/hinted.py"],
                "tests_added": ["app:tests/test_hinted.py"],
            }
        ),
        encoding="utf-8",
    )
    hinted_store = MemoryEdgeCommands()
    hinted = VerifyEvidencePreparationCoordinator(
        edge_commands=hinted_store,  # type: ignore[arg-type]
        sender=RecordingSender('{"requests":[]}'),
    ).advance(inputs, None)
    assert hinted.cursor is not None
    payload = hinted_store.records[hinted.cursor.command_id].payload

    assert payload["worker_hint_paths"] == [
        "app:src/hinted.py",
        "app:tests/test_hinted.py",
    ]
    assert hinted.cursor.candidate_digest != initial_digest


def test_diff_expansion_uses_stage_a_manifest_without_edge_request(
    tmp_path: Path,
) -> None:
    """AG3-147 diff content stays local to the Stage-A collected snapshot."""
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender(
            '{"requests":[{"type":"NEED_DIFF_EXPANSION",'
            '"target":"src/app.py","reason":"inspect changed code"}]}'
        ),
    )
    inputs = _inputs(tmp_path)
    base = coordinator.advance(inputs, None)
    assert base.cursor is not None
    _complete_base(store, base.cursor.command_id)

    dynamic = coordinator.advance(inputs, base.cursor)

    assert dynamic.cursor is not None
    assert store.records[dynamic.cursor.command_id].payload["requests"] == []
    _complete_empty_dynamic(store, dynamic.cursor.command_id)
    final = coordinator.advance(inputs, dynamic.cursor)
    assert [item.status for item in final.request_results] == ["RESOLVED"]


def test_dynamic_conflict_cannot_replace_primary_stage_a_content(
    tmp_path: Path,
) -> None:
    """A lower-authority edge result cannot overwrite Stage-A truth."""
    store = MemoryEdgeCommands()
    coordinator = VerifyEvidencePreparationCoordinator(
        edge_commands=store,  # type: ignore[arg-type]
        sender=RecordingSender(
            '{"requests":[{"type":"NEED_FILE","target":"src/app.py",'
            '"reason":"review"}]}'
        ),
    )
    inputs = _inputs(tmp_path)
    base = coordinator.advance(inputs, None)
    assert base.cursor is not None
    _complete_base(store, base.cursor.command_id)
    dynamic = coordinator.advance(inputs, base.cursor)
    assert dynamic.cursor is not None
    record = store.records[dynamic.cursor.command_id]
    payload = record.payload
    conflicting = VerifyEvidenceFile.from_content(
        repo_id="app", path="src/app.py", content="def app():\n    return 999\n"
    )
    report = VerifyEvidenceReport(
        stage="dynamic_requests",
        batch_id=str(payload["batch_id"]),
        generation=str(payload["generation"]),
        candidate_digest=str(payload["candidate_digest"]),
        request_digest=str(payload["request_digest"]),
        observations=(
            VerifyEvidenceObservation(
                request_index=0,
                status=VerifyEvidenceObservationStatus.COLLECTED,
                candidates=(conflicting,),
            ),
        ),
    )
    store.records[record.command_id] = replace(
        record,
        status="completed",
        result_type="verify_evidence_report",
        result_payload=report.model_dump(mode="json"),
    )

    final = coordinator.advance(inputs, dynamic.cursor)

    assert final.manifest is not None
    app_entry = next(
        entry
        for entry in final.manifest.entries
        if entry.repo_id == "app" and entry.path.as_posix() == "src/app.py"
    )
    assert app_entry.content == "def app():\n    return 1\n"
    assert any("EDGE_EVIDENCE_CONFLICT" in item for item in final.manifest.warnings)
