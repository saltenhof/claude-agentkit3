"""Integration: setup-move is edge-commissioned end-to-end (AG3-145 AC5).

Drives the REAL ``SetupPhaseHandler`` through its staged pause/resume flow against
a REAL Postgres Edge-Command-Queue and a REAL local git repo executed by the REAL
edge command executor (``harness_client.projectedge.command_executor``):

* the first ``on_enter`` commissions ``preflight_probe`` per participating repo and
  PAUSES fail-closed (``AWAITING_EDGE_PROVISIONING``) -- setup does NOT complete
  without a reported result;
* after the edge reports the probe, resume commissions ``provision_worktree`` per
  repo and PAUSES again;
* after the edge provisions the worktree (creating it + materializing the
  ``.agentkit-story.json`` marker dev-locally) and reports the ``worktree_report``,
  resume populates ``StoryContext.worktree_map`` from the REPORTED path and
  COMPLETES.

``run_preflight`` / ``build_story_context`` are stubbed (AC6 / context-build are
separate concerns) so this test isolates the AC5 provisioning truth: the
worktree_map is the edge-reported path, produced through the real dispatch.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from agentkit.backend.bootstrap.edge_provisioning_adapter import (
    SetupEdgeProvisioningCoordinator,
)
from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CompareEvidenceResult,
    RefProtectionResult,
    RefReadResult,
    RepoProbeResult,
    StoryRefWriteCredentialClass,
    StoryRefWriteCredentialResult,
)
from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.control_plane.edge_commands import edge_command_id
from agentkit.backend.control_plane.models import EdgeCommandView
from agentkit.backend.control_plane.ownership import OwnershipAcquisition, OwnershipStatus
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    RunOwnershipRecord,
)
from agentkit.backend.control_plane.repository import (
    EdgeCommandRepository,
    RunOwnershipRepository,
    TakeoverTransferRepository,
)
from agentkit.backend.core_types import PauseReason
from agentkit.backend.governance.setup_preflight_gate.phase import (
    SetupConfig,
    SetupPhaseHandler,
)
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.state_backend.store import (
    commit_edge_command_result_global,
    insert_run_ownership_record_global,
    list_and_ack_open_edge_command_records_global,
    list_ref_protection_degradation_findings_global,
    load_edge_command_record_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.harness_client.projectedge.command_executor import execute_command

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_PROJECT = "proj"
_STORY = "AG3-900"
_RUN = "11111111-1111-4111-8111-111111111111"
_SESSION = "sess-owner"
_REPO = "repo"
_NOW = datetime(2026, 7, 5, tzinfo=UTC)


class _CapableCodeBackend:
    def repo_probe(self) -> RepoProbeResult:
        return RepoProbeResult(reachable=True, detail="ok")

    def ref_read(self, ref: str) -> RefReadResult:
        return RefReadResult(ref=ref, resolved=False, head_sha=None, detail="none")

    def read_compare_evidence(
        self, base_ref: str, head_ref: str
    ) -> CompareEvidenceResult:
        return CompareEvidenceResult(base_ref=base_ref, head_ref=head_ref, available=False)

    def resolve_story_ref_write_credential(self) -> StoryRefWriteCredentialResult:
        return StoryRefWriteCredentialResult(
            resolved=True,
            credential_class=StoryRefWriteCredentialClass.SERVICE_IDENTITY,
            credential_ref="env:AGENTKIT_GITHUB_SERVICE_TOKEN",
            detail="service",
        )

    def administer_ref_protection(self, ref_pattern: str) -> RefProtectionResult:
        return RefProtectionResult(
            ref_pattern=ref_pattern,
            administered=True,
            blocks_direct_developer_push=True,
            blocks_fast_forward=True,
            detail="protected",
        )

    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        return capability is CodeBackendCapability.REF_PROTECTION_ADMINISTRATION


class _CapabilityLessCodeBackend(_CapableCodeBackend):
    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        del capability
        return False

    def administer_ref_protection(self, ref_pattern: str) -> RefProtectionResult:
        return RefProtectionResult(
            ref_pattern=ref_pattern,
            administered=False,
            blocks_direct_developer_push=False,
            blocks_fast_forward=False,
            detail="not backed",
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(project_root: Path) -> Path:
    repo = project_root / _REPO
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "README.md").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _project_config(project_root: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key=_PROJECT,
        project_name="P",
        repositories=[RepositoryConfig(name=_REPO, path=project_root / _REPO)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


class _RecordingRepo:
    def __init__(self) -> None:
        self.saved: list[StoryContext] = []

    def save(self, story_dir: Path, ctx: StoryContext) -> None:
        del story_dir
        self.saved.append(ctx)


class _StubService:
    """Authoritative StoryService stub: records the real story type + repos.

    ``get_story`` is the SAME authoritative source ``_resolve_worktree_plan``
    consults to classify the story (Codex r1 fix). ``story_type`` defaults to
    IMPLEMENTATION (a worktree story) with a real participating repo.
    """

    def __init__(
        self,
        story_type: WireStoryType = WireStoryType.IMPLEMENTATION,
        *,
        begin_should_fail: bool = False,
    ) -> None:
        self.begin_calls: list[str] = []
        self._story_type = story_type
        self._begin_should_fail = begin_should_fail

    def get_story(self, story_display_id: str) -> object:
        del story_display_id
        wire_type = self._story_type

        class _Story:
            participating_repos = [_REPO]
            story_type = wire_type

        return _Story()

    def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
        del correlation_id
        self.begin_calls.append(story_id)
        if self._begin_should_fail:
            raise RuntimeError("injected begin_progress failure")
        return object()


def _seed_active_ownership() -> None:
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            owner_session_id=_SESSION,
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="audit:x",
        )
    )


def _play_edge(project_config: ProjectConfig, project_root: Path) -> int:
    """Act as the Project Edge: fetch open commands, execute, report. Returns count."""
    open_commands = list_and_ack_open_edge_command_records_global(
        project_key=_PROJECT, run_id=_RUN, session_id=_SESSION, delivered_at=_NOW,
    )
    for record in open_commands:
        view = EdgeCommandView(
            command_id=record.command_id,
            command_kind=record.command_kind,
            payload=record.payload,
            status="delivered",
            created_at=record.created_at,
        )
        result = execute_command(
            view, project_config=project_config, project_root=project_root
        )
        op = ControlPlaneOperationRecord(
            op_id=f"op-{record.command_id}",
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            session_id=_SESSION,
            operation_kind="edge_command_result",
            phase=None,
            status="committed",
            response_payload={"command_id": record.command_id},
            created_at=_NOW,
            updated_at=_NOW,
        )
        commit_edge_command_result_global(
            op,
            command_id=record.command_id,
            result_status="completed",
            completed_at=_NOW,
            result_op_id=op.op_id,
            result_type=result.result_type,
            result_payload=result.model_dump(mode="json"),
            expected_ownership_epoch=1,
        )
    return len(open_commands)


def _handler(project_root: Path, service: _StubService) -> SetupPhaseHandler:
    coordinator = SetupEdgeProvisioningCoordinator(
        edge_commands=EdgeCommandRepository(),
        ownership_repo=RunOwnershipRepository(),
        transfer_repo=TakeoverTransferRepository(),
        remote_head_reader=lambda _repo, _branch: None,
        code_backend_port=lambda _repo: _CapableCodeBackend(),
    )
    cfg = SetupConfig(
        project_root=project_root,
        story_id=_STORY,
        create_worktree=True,
        story_service=service,  # type: ignore[arg-type]
    )
    return SetupPhaseHandler(
        cfg,
        context_repository=_RecordingRepo(),  # type: ignore[arg-type]
        residue_probe=lambda _root, _sid: False,
        edge_provisioning_coordinator=coordinator,
    )


def test_ref_protection_degradation_warning_is_persisted(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    _seed_active_ownership()
    store = EdgeCommandRepository()
    coordinator = SetupEdgeProvisioningCoordinator(
        edge_commands=store,
        ownership_repo=RunOwnershipRepository(),
        transfer_repo=TakeoverTransferRepository(),
        remote_head_reader=lambda _repo, _branch: None,
        code_backend_port=lambda _repo: _CapabilityLessCodeBackend(),
    )

    outcome = coordinator.ensure_preflight_probes(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        repos=(_REPO,),
        branch=f"story/{_STORY}",
    )

    assert outcome.pending is True
    rows = list_ref_protection_degradation_findings_global(_PROJECT, _STORY)
    assert len(rows) == 1
    row = rows[0]
    assert row["repo_id"] == _REPO
    assert row["severity"] == "warning"
    assert row["finding_code"] == "ref_protection_capability_unavailable"


def _ctx(project_root: Path) -> StoryContext:
    return StoryContext(
        project_key=_PROJECT,
        story_id=_STORY,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Edge provisioning",
        project_root=project_root,
        participating_repos=[_REPO],
    )


def _sparse_ctx(project_root: Path) -> StoryContext:
    """A stale/sparse incoming context: misclassified CONCEPT, no repos.

    Mirrors the Codex r1 dispatch scenario -- the incoming ``StoryContext`` is
    sparse/stale (``story_type=CONCEPT``, no participating repos) while the
    AUTHORITATIVE StoryService record for the SAME story is IMPLEMENTATION with
    participating repos.
    """
    return StoryContext(
        project_key=_PROJECT,
        story_id=_STORY,
        story_type=StoryType.CONCEPT,
        execution_route=None,
        title="Stale sparse context",
        project_root=project_root,
        participating_repos=[],
    )


def test_setup_is_edge_commissioned_end_to_end(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    repo = _init_repo(tmp_path)
    project_config = _project_config(tmp_path)
    _seed_active_ownership()
    service = _StubService()
    handler = _handler(tmp_path, service)
    ctx = _ctx(tmp_path)
    enriched = _ctx(tmp_path)

    from tests.phase_state_factory import make_phase_state

    state = make_phase_state(story_id=_STORY, run_id=_RUN, status="pending")
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    with (
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
            return_value=_pass(),
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
            return_value=enriched,
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
            return_value=project_config,
        ),
    ):
        # 1. First entry: probe commissioned, PAUSED fail-closed (no completion).
        r1 = handler.on_enter(ctx, envelope)
        assert r1.status is PhaseStatus.PAUSED
        probe_id = edge_command_id(_RUN, "preflight_probe", _REPO)
        assert load_edge_command_record_global(probe_id) is not None
        # No provision command exists yet, and no worktree_map is populated.
        assert (
            load_edge_command_record_global(
                edge_command_id(_RUN, "provision_worktree", _REPO)
            )
            is None
        )

        # 2. Edge executes the probe (clean repo).
        assert _play_edge(project_config, tmp_path) == 1

        # 3. Resume: probe ready -> provision commissioned per repo -> PAUSED.
        r2 = handler.on_resume(ctx, envelope, "edge_report_received")
        assert r2.status is PhaseStatus.PAUSED
        provision_id = edge_command_id(_RUN, "provision_worktree", _REPO)
        provision_command = load_edge_command_record_global(provision_id)
        assert provision_command is not None
        assert provision_command.command_kind == "provision_worktree"

        # 4. Edge provisions the worktree + materializes the marker dev-locally.
        assert _play_edge(project_config, tmp_path) == 1

        # 5. Resume: worktree_map populated from the REPORTED path -> COMPLETED.
        r3 = handler.on_resume(ctx, envelope, "edge_report_received")

    assert r3.status is PhaseStatus.COMPLETED, r3.errors
    assert r3.updated_context is not None
    expected_root = repo / "worktrees" / _STORY
    assert r3.updated_context.worktree_map == {_REPO: expected_root}
    # The marker was materialized dev-locally by the edge executor + reported.
    assert (expected_root / ".agentkit-story.json").is_file()
    reported = load_edge_command_record_global(
        edge_command_id(_RUN, "provision_worktree", _REPO)
    )
    assert reported is not None
    assert reported.result_type == "worktree_report"
    assert reported.result_payload is not None
    assert reported.result_payload["marker_present"] is True
    assert reported.result_payload["worktree_root"] == str(expected_root)
    # begin_progress ran only on completion.
    assert service.begin_calls == [_STORY]


def test_sparse_concept_ctx_does_not_bypass_edge_for_authoritative_worktree_story(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    """Codex r1 CRITICAL (fail-open): a sparse/misclassified incoming context must
    NOT let an authoritatively-worktree story complete setup with no edge report.

    The incoming ``StoryContext`` is stale/sparse (``story_type=CONCEPT``, no
    participating repos) while the AUTHORITATIVE StoryService record is
    IMPLEMENTATION with participating repos. Setup must derive the worktree
    classification from the authoritative record (``_resolve_worktree_plan``):
    it commissions the ``preflight_probe`` and PAUSES fail-closed
    (``AWAITING_EDGE_PROVISIONING``); it must NOT optimistically COMPLETE and
    Checks 7/8 never optimistically PASS (they only run AFTER the probe reports).
    Driven through the REAL edge-command dispatch (no hand-assembled state).

    Pre-fix, the plan was classified from ``ctx.story_type=CONCEPT`` -> the edge
    was skipped entirely and the first ``on_enter`` returned COMPLETED with no
    probe command, which this test's PAUSED + probe-commissioned assertions
    catch.
    """
    del postgres_isolated_schema
    repo = _init_repo(tmp_path)
    project_config = _project_config(tmp_path)
    _seed_active_ownership()
    # Authoritative record = IMPLEMENTATION + [_REPO]; the incoming ctx is sparse.
    service = _StubService(story_type=WireStoryType.IMPLEMENTATION)
    handler = _handler(tmp_path, service)
    sparse_ctx = _sparse_ctx(tmp_path)
    enriched = _ctx(tmp_path)  # the authoritative enriched context

    from tests.phase_state_factory import make_phase_state

    state = make_phase_state(story_id=_STORY, run_id=_RUN, status="pending")
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    with (
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
            return_value=_pass(),
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
            return_value=enriched,
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
            return_value=project_config,
        ),
    ):
        # 1. Fail-closed: the sparse CONCEPT ctx must NOT bypass the edge. The
        #    authoritative IMPLEMENTATION record commissions the probe + PAUSES.
        r1 = handler.on_enter(sparse_ctx, envelope)
        assert r1.status is PhaseStatus.PAUSED, r1
        assert r1.yield_status == PauseReason.AWAITING_EDGE_PROVISIONING.value
        probe_id = edge_command_id(_RUN, "preflight_probe", _REPO)
        assert load_edge_command_record_global(probe_id) is not None
        # Setup did NOT complete: begin_progress never ran, no provision yet.
        assert service.begin_calls == []
        assert (
            load_edge_command_record_global(
                edge_command_id(_RUN, "provision_worktree", _REPO)
            )
            is None
        )

        # 2. Drive the rest to prove the authoritatively-worktree story still
        #    provisions correctly even from a sparse incoming context.
        assert _play_edge(project_config, tmp_path) == 1
        r2 = handler.on_resume(sparse_ctx, envelope, "edge_report_received")
        assert r2.status is PhaseStatus.PAUSED
        assert (
            load_edge_command_record_global(
                edge_command_id(_RUN, "provision_worktree", _REPO)
            )
            is not None
        )
        assert _play_edge(project_config, tmp_path) == 1
        r3 = handler.on_resume(sparse_ctx, envelope, "edge_report_received")

    assert r3.status is PhaseStatus.COMPLETED, r3.errors
    assert r3.updated_context is not None
    assert r3.updated_context.worktree_map == {_REPO: repo / "worktrees" / _STORY}
    assert service.begin_calls == [_STORY]


def test_setup_failure_after_provision_commissions_teardown(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    """AG3-145 D (AC7): a setup failure AFTER provisioning commissions teardown.

    Drives the REAL setup dispatch to a post-provisioning failure
    (``begin_progress`` raises) and asserts a ``teardown_worktree`` edge command
    was commissioned in the REAL Postgres queue -- the worktree the edge already
    created is NOT silently leaked (the C->D teardown gap). No hand-assembled
    state: the command is produced through the real phase dispatch + real edge.
    """
    del postgres_isolated_schema
    repo = _init_repo(tmp_path)
    project_config = _project_config(tmp_path)
    _seed_active_ownership()
    service = _StubService(begin_should_fail=True)
    handler = _handler(tmp_path, service)
    ctx = _ctx(tmp_path)
    enriched = _ctx(tmp_path)

    from tests.phase_state_factory import make_phase_state

    state = make_phase_state(story_id=_STORY, run_id=_RUN, status="pending")
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)
    teardown_id = edge_command_id(_RUN, "teardown_worktree", _REPO)

    with (
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
            return_value=_pass(),
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
            return_value=enriched,
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
            return_value=project_config,
        ),
    ):
        handler.on_enter(ctx, envelope)  # probe pause
        assert _play_edge(project_config, tmp_path) == 1
        handler.on_resume(ctx, envelope, "edge_report_received")  # provision pause
        assert _play_edge(project_config, tmp_path) == 1  # edge provisions worktree
        # No teardown yet -- only the failing resume commissions it.
        assert load_edge_command_record_global(teardown_id) is None
        r3 = handler.on_resume(ctx, envelope, "edge_report_received")

    # The provisioned worktree exists; the failed setup commissioned its teardown.
    assert r3.status is PhaseStatus.FAILED, r3
    assert "begin_progress failed" in r3.errors[0]
    assert (repo / "worktrees" / _STORY / ".agentkit-story.json").is_file()
    teardown = load_edge_command_record_global(teardown_id)
    assert teardown is not None
    assert teardown.command_kind == "teardown_worktree"
    assert teardown.status == "created"
    assert teardown.payload["repo_id"] == _REPO
    assert teardown.payload["branch"] == f"story/{_STORY}"

    # Idempotent: a re-entered failing resume does not duplicate the command.
    with (
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
            return_value=_pass(),
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
            return_value=enriched,
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
            return_value=project_config,
        ),
    ):
        handler.on_resume(ctx, envelope, "edge_report_received")
    assert load_edge_command_record_global(teardown_id) is not None
    # The edge executes the teardown idempotently (worktree removed => torn_down).
    assert _play_edge(project_config, tmp_path) == 1
    done = load_edge_command_record_global(teardown_id)
    assert done is not None
    assert done.result_type == "worktree_report"
    assert done.result_payload is not None
    assert done.result_payload["outcome"] == "torn_down"


def test_authoritative_concept_story_skips_edge_stages(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    """Positive non-worktree case: an authoritatively CONCEPT story skips the edge.

    Guards the other direction of the Codex r1 fix -- when the AUTHORITATIVE
    StoryService record is genuinely non-worktree (CONCEPT), setup commissions NO
    edge command (probe/provision), Checks 7/8 correctly no-op, and it COMPLETES.
    Driven through the same real dispatch harness.
    """
    del postgres_isolated_schema
    _init_repo(tmp_path)
    project_config = _project_config(tmp_path)
    _seed_active_ownership()
    # Authoritative record = CONCEPT (non-worktree), even though create_worktree=True.
    service = _StubService(story_type=WireStoryType.CONCEPT)
    handler = _handler(tmp_path, service)
    ctx = _sparse_ctx(tmp_path)
    enriched = _sparse_ctx(tmp_path)  # authoritative CONCEPT context

    from tests.phase_state_factory import make_phase_state

    state = make_phase_state(story_id=_STORY, run_id=_RUN, status="pending")
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    with (
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
            return_value=_pass(),
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
            return_value=enriched,
        ),
        patch(
            "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
            return_value=project_config,
        ),
    ):
        result = handler.on_enter(ctx, envelope)

    assert result.status is PhaseStatus.COMPLETED, result.errors
    # No edge command was commissioned for the non-worktree story.
    assert (
        load_edge_command_record_global(
            edge_command_id(_RUN, "preflight_probe", _REPO)
        )
        is None
    )
    assert (
        load_edge_command_record_global(
            edge_command_id(_RUN, "provision_worktree", _REPO)
        )
        is None
    )
    assert service.begin_calls == [_STORY]


def _pass() -> object:
    class _Result:
        passed = True
        checks: list[object] = []

    return _Result()
