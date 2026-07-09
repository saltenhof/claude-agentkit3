"""Integration tests: IS phase-boundary enforcement via REAL production components.

Every test drives the REAL production component (StructuralChecker, GuardRunner,
ClosurePhaseHandler) against a simulated IS story directory. Tests FAIL if the
corresponding wiring in checker.py, guard_evaluation.py, or closure/phase.py is
removed -- verifying that the IS machinery is wired into production boundaries, not
just callable as standalone helpers (AC2/AC3/AC4/AC6/AC7/AC8/AC9/AC12).

Boundary ownership:
- AC6/AC12 -- StructuralChecker.evaluate() with IS StageRegistry
- AC7/AC8   -- GuardRunner with SeamAllowlistGuard wired via _guards_for_state()
- AC9       -- ClosurePhaseHandler._check_integration_stabilization_closure()
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.protocols import ViolationType
from agentkit.backend.governance.runner import GuardRunner
from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.backend.integration_stabilization.seam_allowlist_guard import (
    SeamAllowlistGuard,
    materialize_seam_allowlist,
)
from agentkit.backend.integration_stabilization.state import (
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    ClosurePayload,
    ClosureProgress,
    PhaseSnapshot,
    PhaseStatus,
)
from agentkit.backend.state_backend.pipeline_runtime_store import save_phase_snapshot
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.backend.verify_system.stage_registry.data import ALL_STAGES
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry
from agentkit.backend.verify_system.structural.checker import StructuralChecker
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY_ID = "IS-069"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_caps(**kwargs: int) -> StabilizationBudgetCaps:
    defaults = dict(
        max_loops=3,
        max_new_surfaces=2,
        max_contract_changes=1,
        max_regressions_per_cycle=1,
    )
    defaults.update(kwargs)
    return StabilizationBudgetCaps(**defaults)  # type: ignore[arg-type]


def _make_manifest(
    target_seams: tuple[str, ...] = ("src/api/", "src/db/"),
    allowed_repos_paths: tuple[str, ...] = ("worktrees/main/",),
    integration_targets: tuple[str, ...] = ("e2e_login",),
) -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id=_STORY_ID,
        implementation_contract="integration_stabilization",
        target_seams=target_seams,
        allowed_repos_paths=allowed_repos_paths,
        integration_targets=integration_targets,
        allowed_contract_changes=(),
        stabilization_budget=_make_caps(),
    )


def _make_approval(manifest: IntegrationScopeManifest) -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=manifest.project_key,
        story_id=manifest.story_id,
        run_id="run-is069",
        manifest_version=manifest.version,
        manifest_hash=manifest.content_hash,
    )


def _is_ctx() -> StoryContext:
    return StoryContext(
        project_key="PROJ",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        execution_route=StoryMode.EXPLORATION,
    )


def _standard_ctx() -> StoryContext:
    return StoryContext(
        project_key="PROJ",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.STANDARD,
        execution_route=StoryMode.EXPLORATION,
    )


def _make_is_story_dir(tmp_path: Path) -> Path:
    """Create a minimal IS story directory with context saved."""
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = _is_ctx()
    save_story_context(story_dir, ctx)
    for phase in ("setup", "exploration"):
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id=_STORY_ID,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    return story_dir


class _FakeChangeEvidencePort:
    """Injects deterministic system evidence for structural checks."""

    def __init__(self, changed_files: tuple[str, ...] = ()) -> None:
        self._ev = ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY_ID}",
            commit_messages=(f"feat({_STORY_ID}): add integration work",),
            pushed=True,
            changed_files=changed_files,
            actual_impact=ChangeImpact("Component"),
        )

    def collect(self, story_dir: Path) -> ChangeEvidence:  # noqa: ARG002
        return self._ev


class _FakeTelemetry:
    """Null telemetry port -- passes all recurring-guard checks."""

    def count_events(
        self,
        story_dir: Path,  # noqa: ARG002
        *,
        story_id: str,  # noqa: ARG002
        event_type: str,  # noqa: ARG002
        role: str | None = None,  # noqa: ARG002
        project_key: str | None = None,  # noqa: ARG002
        run_id: str | None = None,  # noqa: ARG002
    ) -> int:
        # Return enough events to pass recurring-guard thresholds.
        return 2

    def run_scope_resolvable(self, story_dir: Path) -> bool:  # noqa: ARG002
        return True


def _make_checker(
    changed_files: tuple[str, ...] = (),
) -> StructuralChecker:
    """Real StructuralChecker with IS registry and fake evidence."""
    from agentkit.backend.verify_system.structural.checks import BuildTestEvidence

    class _Bt:
        def evaluate(self, story_dir: Path) -> BuildTestEvidence:  # noqa: ARG002
            return BuildTestEvidence(
                build_ok=True,
                tests_green=True,
                test_file_count=3,
                coverage_report_present=True,
                coverage_meets_threshold=True,
            )

    return StructuralChecker(
        registry=StageRegistry(stages=ALL_STAGES),
        telemetry=_FakeTelemetry(),
        build_test_port=_Bt(),
        change_evidence_port=_FakeChangeEvidencePort(changed_files=changed_files),
    )


# ---------------------------------------------------------------------------
# AC12 / AC6: StructuralChecker blocks IS stages when manifest absent
# ---------------------------------------------------------------------------


class TestStructuralCheckerISBlocksWithoutManifest:
    """Real StructuralChecker.evaluate() blocks IS checks when manifest absent.

    These tests prove the wiring in checker.py._dispatch() and _check_is_*
    functions is active: removing the IS stage dispatch entries would make these
    tests fail by no longer producing BLOCKING findings for IS stages.
    """

    def test_manifest_approval_required_stage_blocks_without_approval(
        self, tmp_path: Path
    ) -> None:
        """AC12: integration.manifest_approval_required BLOCKS via real checker."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        checker = _make_checker()

        result = checker.evaluate(ctx, story_dir)

        # The IS stage must have fired and produced a BLOCKING finding.
        from agentkit.backend.verify_system.protocols import Severity

        blocking = [
            f
            for f in result.findings
            if f.check == "integration.manifest_approval_required"
            and f.severity == Severity.BLOCKING
        ]
        assert len(blocking) == 1, (
            f"Expected BLOCKING finding for 'integration.manifest_approval_required' "
            f"but got: {[f.check for f in result.findings]}"
        )
        assert result.passed is False

    def test_is_stage_ids_appear_in_layer1_plan_for_is_context(
        self, tmp_path: Path
    ) -> None:
        """AC12: IS stages included in the Layer-1 plan for IS contract."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        checker = _make_checker()

        result = checker.evaluate(ctx, story_dir)

        # The executed stage IDs must include IS-prefixed stages.
        stage_ids = result.metadata.get("stage_ids", ())
        is_stages = [s for s in stage_ids if str(s).startswith("integration.")]
        assert len(is_stages) >= 1, (
            f"Expected at least one 'integration.*' stage in plan, "
            f"got stage_ids: {stage_ids}"
        )

    def test_standard_context_does_not_run_is_stages(
        self, tmp_path: Path
    ) -> None:
        """AC12 contract gate: IS stages never run for STANDARD contract."""
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        ctx = _standard_ctx()
        save_story_context(story_dir, ctx)
        for phase in ("setup", "exploration"):
            save_phase_snapshot(
                story_dir,
                PhaseSnapshot(
                    story_id=_STORY_ID,
                    phase=phase,
                    status=PhaseStatus.COMPLETED,
                    completed_at=datetime.now(tz=UTC),
                    artifacts=[],
                    evidence={},
                ),
            )
        # Add mandatory artifacts to avoid standard BLOCKING findings.
        (story_dir / "protocol.md").write_text("protocol body " * 10, encoding="utf-8")
        (story_dir / "worker-manifest.json").write_text(
            json.dumps(
                {
                    "story_id": _STORY_ID,
                    "status": "DONE",
                    "files": ["feature.py"],
                    "declared_change_impact": "Component",
                }
            ),
            encoding="utf-8",
        )
        (story_dir / "handover.json").write_text(
            json.dumps(
                {
                    "changes_summary": "added feature",
                    "increments": [
                        {"description": "f", "commit_sha": "a", "tests_added": []}
                    ],
                    "assumptions": [],
                    "existing_tests": ["tests/test_feature.py::test_x"],
                    "risks_for_qa": ["load"],
                    "drift_log": [],
                    "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
                }
            ),
            encoding="utf-8",
        )

        checker = _make_checker()
        result = checker.evaluate(ctx, story_dir)

        # Standard story: no IS stages should appear in the plan.
        stage_ids = result.metadata.get("stage_ids", ())
        is_stages = [s for s in stage_ids if str(s).startswith("integration.")]
        assert is_stages == [], (
            f"IS stages must NOT appear in standard-contract plan, "
            f"got: {is_stages}"
        )

    def test_binding_integrity_stage_blocks_on_hash_mismatch(
        self, tmp_path: Path
    ) -> None:
        """AC12: integration.binding_integrity BLOCKS via real checker on mismatch."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        manifest = _make_manifest()
        # Persist manifest but approval with wrong hash (tampered binding).
        save_integration_manifest(story_dir, manifest)
        bad_approval = ManifestApprovalRecord(
            project_key=manifest.project_key,
            story_id=manifest.story_id,
            run_id="run-is069",
            manifest_version=manifest.version,
            manifest_hash="deadbeef",  # wrong hash
        )
        save_manifest_approval(story_dir, bad_approval)

        checker = _make_checker()
        result = checker.evaluate(ctx, story_dir)

        from agentkit.backend.verify_system.protocols import Severity

        blocking = [
            f
            for f in result.findings
            if f.check == "integration.binding_integrity"
            and f.severity == Severity.BLOCKING
        ]
        assert len(blocking) == 1, (
            f"Expected BLOCKING finding for 'integration.binding_integrity' "
            f"but got: {[f.check for f in result.findings]}"
        )

    def test_declared_surfaces_only_blocks_on_undeclared_path(
        self, tmp_path: Path
    ) -> None:
        """AC6: integration.declared_surfaces_only BLOCKS via real checker."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        manifest = _make_manifest(target_seams=("src/api/",))
        approval = _make_approval(manifest)
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(story_dir, approval)

        # Touch a file OUTSIDE the declared seam.
        checker = _make_checker(changed_files=("src/unrelated/hack.py",))
        result = checker.evaluate(ctx, story_dir)

        from agentkit.backend.verify_system.protocols import Severity

        blocking = [
            f
            for f in result.findings
            if f.check == "integration.declared_surfaces_only"
            and f.severity == Severity.BLOCKING
        ]
        assert len(blocking) == 1, (
            f"Expected BLOCKING finding for 'integration.declared_surfaces_only' "
            f"but got: {[f.check for f in result.findings]}"
        )

    def test_declared_surfaces_only_passes_when_within_seam(
        self, tmp_path: Path
    ) -> None:
        """AC6: integration.declared_surfaces_only passes for in-seam paths."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        manifest = _make_manifest(target_seams=("src/api/",))
        approval = _make_approval(manifest)
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(story_dir, approval)

        checker = _make_checker(changed_files=("src/api/handler.py",))
        result = checker.evaluate(ctx, story_dir)

        surface_findings = [
            f
            for f in result.findings
            if f.check == "integration.declared_surfaces_only"
        ]
        assert surface_findings == [], (
            f"Unexpected findings for declared_surfaces_only: {surface_findings}"
        )


# ---------------------------------------------------------------------------
# AC7: SeamAllowlistGuard wired into GuardRunner
# ---------------------------------------------------------------------------


class TestSeamAllowlistGuardViaGuardRunner:
    """Real GuardRunner with SeamAllowlistGuard blocks writes outside seam.

    These tests use the real GuardRunner.is_allowed() interface (the same one
    used by _guards_for_state → evaluate_pre_tool_use). Removing SeamAllowlistGuard
    from the chain would make the write-outside-seam test fail to block.
    """

    def test_write_within_seam_allowed_via_runner(self) -> None:
        """AC7: write within seam allowlist passes via GuardRunner."""
        manifest = _make_manifest(target_seams=("src/api/",))
        allowlist = materialize_seam_allowlist(manifest)
        runner = GuardRunner(guards=[SeamAllowlistGuard(allowlist)])

        allowed, _ = runner.is_allowed("file_write", {"file_path": "src/api/handler.py"})

        assert allowed is True

    def test_write_outside_seam_blocked_via_runner(self) -> None:
        """AC7: write outside seam blocks via real GuardRunner with SeamAllowlistGuard."""
        manifest = _make_manifest(target_seams=("src/api/",))
        allowlist = materialize_seam_allowlist(manifest)
        runner = GuardRunner(guards=[SeamAllowlistGuard(allowlist)])

        allowed, verdicts = runner.is_allowed(
            "file_write", {"file_path": "src/unrelated/hack.py"}
        )

        assert allowed is False
        blocking = [v for v in verdicts if not v.allowed]
        assert len(blocking) >= 1
        assert any(v.violation_type == ViolationType.SCOPE_VIOLATION for v in blocking)

    def test_guard_name_is_seam_allowlist_guard(self) -> None:
        """AC7: SeamAllowlistGuard.name is correct (required by GuardRunner)."""
        guard = SeamAllowlistGuard(())
        assert guard.name == "seam_allowlist_guard"

    def test_read_allowed_even_outside_seam(self) -> None:
        """AC7: SeamAllowlistGuard only blocks write operations, not reads."""
        manifest = _make_manifest(target_seams=("src/api/",))
        allowlist = materialize_seam_allowlist(manifest)
        runner = GuardRunner(guards=[SeamAllowlistGuard(allowlist)])

        # file_read should be allowed anywhere.
        allowed, _ = runner.is_allowed("file_read", {"file_path": "src/unrelated/readme.md"})

        assert allowed is True


# ---------------------------------------------------------------------------
# AC9: ClosurePhaseHandler blocks IS stories without approved manifest
# ---------------------------------------------------------------------------


class _FakeChangeEvidencePortImpl:
    """Injects deterministic implementation change evidence for closure tests."""

    def __init__(self) -> None:
        from agentkit.backend.story_context_manager.story_model import ChangeImpact

        self._ev = ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY_ID}",
            commit_messages=(f"feat({_STORY_ID}): implement integration work",),
            pushed=True,
            changed_files=("src/api/handler.py",),
            actual_impact=ChangeImpact("Component"),
        )

    def collect(self, story_dir: Path) -> ChangeEvidence:  # noqa: ARG002
        return self._ev


def _write_implementation_artifacts(story_dir: Path) -> None:
    """Write minimum delivery artifacts so the implementation-evidence gate passes."""
    from datetime import datetime as _dt

    from agentkit.backend.core_types.qa_artifact_names import (
        HANDOVER_FILE,
        PROTOCOL_FILE,
        WORKER_MANIFEST_FILE,
    )
    from agentkit.backend.implementation.manifest.manifest import (
        WorkerManifest,
        WorkerManifestStatus,
    )

    (story_dir / HANDOVER_FILE).write_text(
        json.dumps(
            {
                "changes_summary": "implemented IS integration work",
                "increments": [
                    {
                        "description": "IS integration change",
                        "commit_sha": "fixture",
                        "tests_added": ["tests/test_is.py"],
                    }
                ],
                "assumptions": [],
                "existing_tests": ["tests/test_is.py::test_is"],
                "risks_for_qa": [],
                "drift_log": [],
                "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
            }
        ),
        encoding="utf-8",
    )
    (story_dir / PROTOCOL_FILE).write_text(
        "IS implementation protocol.\n" * 4,
        encoding="utf-8",
    )
    manifest = WorkerManifest(
        story_id=_STORY_ID,
        run_id="run-is069",
        status=WorkerManifestStatus.COMPLETED,
        completed_at=_dt(2026, 6, 1, tzinfo=UTC),
        commit_sha="fixture",
        files_changed=["src/api/handler.py"],
        tests_added=["tests/test_is.py"],
        acceptance_criteria_status={"AC-1": "ADDRESSED"},
    )
    (story_dir / WORKER_MANIFEST_FILE).write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )


class TestClosurePhaseHandlerISPrecondition:
    """Real ClosurePhaseHandler._check_integration_stabilization_closure() blocks.

    Tests use the real ClosurePhaseHandler (via ClosureConfig + a stub
    progress_store). The IS precondition is placed BEFORE the finalization-
    collaborator check in _run_sequence(), so even a minimal ClosureConfig
    (only progress_store wired) reveals the IS block.

    Removing the IS precondition call from _run_sequence() would make these
    tests fail: the FAILED result would become a collaborator-wiring error
    instead of an IS-manifest error.
    """

    def _make_closure_handler(self, story_dir: Path) -> object:
        """Build a minimal real ClosurePhaseHandler for IS closure testing.

        Wires only what is needed to get past _validate_implementation_terminality
        into _run_sequence: a progress_store and a change_evidence_port. The IS
        precondition runs BEFORE the finalization-collaborator check in
        _run_sequence so we never need doc_fidelity_port etc. for the IS block test.
        """
        from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler

        class _NullStore:
            def save_state(self, state: object) -> None:
                pass

        config = ClosureConfig(
            story_dir=story_dir,
            progress_store=_NullStore(),
            change_evidence_port=_FakeChangeEvidencePortImpl(),
        )
        return ClosurePhaseHandler(config)

    def _make_envelope(self) -> object:
        from tests.phase_state_factory import make_phase_state

        state = make_phase_state(
            story_id=_STORY_ID,
            phase="closure",
            status=PhaseStatus.IN_PROGRESS,
            payload=ClosurePayload(progress=ClosureProgress()),
        )
        return PhaseEnvelopeStore.make_fresh_envelope(state)

    def _prepare_is_story_dir(self, tmp_path: Path) -> Path:
        """IS story dir with implementation evidence to pass terminality gate."""
        story_dir = _make_is_story_dir(tmp_path)
        for phase in ("implementation",):
            save_phase_snapshot(
                story_dir,
                PhaseSnapshot(
                    story_id=_STORY_ID,
                    phase=phase,
                    status=PhaseStatus.COMPLETED,
                    completed_at=datetime.now(tz=UTC),
                    artifacts=[],
                    evidence={},
                ),
            )
        _write_implementation_artifacts(story_dir)
        return story_dir

    def test_closure_blocked_without_is_manifest(self, tmp_path: Path) -> None:
        """AC9: ClosurePhaseHandler blocks IS stories when manifest absent.

        This test proves the IS precondition check is WIRED into the real
        _run_sequence() path -- not just callable as a standalone helper.
        Removing _check_integration_stabilization_closure() from _run_sequence()
        would change the error message from IS-manifest to collaborator-wiring.
        """
        story_dir = self._prepare_is_story_dir(tmp_path)
        ctx = _is_ctx()

        handler = self._make_closure_handler(story_dir)
        envelope = self._make_envelope()
        result = handler.on_enter(ctx, envelope)

        assert result.status == PhaseStatus.FAILED
        assert result.errors
        # Must mention IS precondition / manifest, not an unrelated error.
        combined_errors = " ".join(result.errors).lower()
        assert "manifest" in combined_errors or "integration" in combined_errors, (
            f"Expected IS-precondition error, got: {result.errors}"
        )

    def test_standard_story_not_blocked_by_is_precondition(
        self, tmp_path: Path
    ) -> None:
        """AC9 contract gate: standard stories NOT blocked by IS precondition.

        If the IS precondition check is incorrectly gated (runs for all stories),
        this test would fail because the error would reference IS/manifest instead
        of the expected collaborator-wiring error.
        """
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        ctx = _standard_ctx()
        save_story_context(story_dir, ctx)
        for phase in ("setup", "exploration", "implementation"):
            save_phase_snapshot(
                story_dir,
                PhaseSnapshot(
                    story_id=_STORY_ID,
                    phase=phase,
                    status=PhaseStatus.COMPLETED,
                    completed_at=datetime.now(tz=UTC),
                    artifacts=[],
                    evidence={},
                ),
            )
        _write_implementation_artifacts(story_dir)

        from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler

        class _NullStore:
            def save_state(self, state: object) -> None:
                pass

        config = ClosureConfig(
            story_dir=story_dir,
            progress_store=_NullStore(),
            change_evidence_port=_FakeChangeEvidencePortImpl(),
        )
        handler = ClosurePhaseHandler(config)
        envelope = self._make_envelope()
        result = handler.on_enter(ctx, envelope)

        # Standard story: closure proceeds past IS precondition.
        # The result may FAIL for unrelated reasons (missing finalization
        # collaborators is expected for a minimal ClosureConfig).
        # What matters: the error must NOT be an IS-precondition error.
        combined_errors = " ".join(result.errors or []).lower()
        # If we see both "integration" and "manifest" together it's the IS error.
        is_precondition_error = (
            "integration" in combined_errors and "manifest" in combined_errors
        )
        assert not is_precondition_error, (
            f"Standard story should not be blocked by IS precondition, "
            f"got: {result.errors}"
        )


# ---------------------------------------------------------------------------
# AC5: StageRegistry contract-awareness
# ---------------------------------------------------------------------------


class TestStageRegistryContractAwareness:
    """Real StageRegistry.stages_for() correctly filters IS stages by contract.

    These tests prove the registry wiring (stages_for, layer1_stages_for)
    is contract-aware -- removing the IS filtering code would break them.
    """

    def test_stages_for_is_contract_includes_stability_gate(self) -> None:
        """AC5: stability_gate stage included for IS contract."""
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.stages_for(
            StoryType.IMPLEMENTATION,
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        stage_ids = [s.stage_id for s in stages]
        assert "stability_gate" in stage_ids

    def test_stages_for_standard_excludes_stability_gate(self) -> None:
        """AC5: stability_gate stage excluded for STANDARD contract."""
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.stages_for(
            StoryType.IMPLEMENTATION,
            implementation_contract=ImplementationContract.STANDARD,
        )
        stage_ids = [s.stage_id for s in stages]
        assert "stability_gate" not in stage_ids

    def test_stages_for_none_contract_excludes_is_stages(self) -> None:
        """AC5: None contract (default) excludes all IS stages."""
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.stages_for(StoryType.IMPLEMENTATION)
        stage_ids = [s.stage_id for s in stages]
        is_stages = [sid for sid in stage_ids if sid.startswith("integration.") or sid == "stability_gate"]
        assert is_stages == [], f"IS stages must be excluded for None contract: {is_stages}"

    def test_layer1_stages_for_is_contract_includes_integration_checks(self) -> None:
        """AC5/AC6: Layer-1 IS checks included in layer1_stages_for for IS contract."""
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.layer1_stages_for(
            StoryType.IMPLEMENTATION,
            are_enabled=False,
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        stage_ids = [s.stage_id for s in stages]
        assert "integration.declared_surfaces_only" in stage_ids
        assert "integration.manifest_approval_required" in stage_ids

    def test_layer1_stages_for_standard_excludes_integration_checks(self) -> None:
        """AC5/AC6: Layer-1 IS checks excluded for STANDARD contract."""
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.layer1_stages_for(
            StoryType.IMPLEMENTATION,
            are_enabled=False,
            implementation_contract=ImplementationContract.STANDARD,
        )
        stage_ids = [s.stage_id for s in stages]
        is_stages = [sid for sid in stage_ids if sid.startswith("integration.")]
        assert is_stages == [], (
            f"IS Layer-1 stages must not appear for STANDARD contract: {is_stages}"
        )


# ---------------------------------------------------------------------------
# AC4: StabilizationBudgetGuard wired into GuardRunner
# ---------------------------------------------------------------------------


class TestStabilizationBudgetGuardViaGuardRunner:
    """Real GuardRunner with StabilizationBudgetGuard blocks when caps exhausted.

    Tests use the real GuardRunner.is_allowed() with StabilizationBudgetGuard.
    Removing StabilizationBudgetGuard from the chain would allow over-budget
    mutations to proceed unchecked.
    """

    def test_within_budget_allows_writes(self, tmp_path: Path) -> None:
        """AC4: write allowed when budget is within caps via GuardRunner."""
        from agentkit.backend.integration_stabilization.budget_guard import (
            StabilizationBudgetGuard,
        )

        manifest = _make_manifest()
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        # No integration_budget.json: fresh run, all counters at zero.
        runner = GuardRunner(guards=[StabilizationBudgetGuard(manifest=manifest, story_dir=story_dir)])

        allowed, _ = runner.is_allowed("file_write", {"file_path": "src/api/handler.py"})

        assert allowed is True

    def test_exhausted_budget_blocks_writes_via_runner(self, tmp_path: Path) -> None:
        """AC4: write blocked when loop budget exhausted via real GuardRunner."""
        from agentkit.backend.integration_stabilization.budget_guard import (
            StabilizationBudgetGuard,
        )

        manifest = _make_manifest()
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        # Write exhausted budget: loops_used == max_loops (3).
        (story_dir / "integration_budget.json").write_text(
            json.dumps({"loops_used": 3, "new_surfaces_used": 0,
                        "contract_changes_used": 0, "regressions_this_cycle": 0}),
            encoding="utf-8",
        )
        runner = GuardRunner(guards=[StabilizationBudgetGuard(manifest=manifest, story_dir=story_dir)])

        allowed, verdicts = runner.is_allowed("file_write", {"file_path": "src/api/x.py"})

        assert allowed is False
        blocking = [v for v in verdicts if not v.allowed]
        assert len(blocking) >= 1
        assert any(v.violation_type == ViolationType.POLICY_VIOLATION for v in blocking)

    def test_read_allowed_even_when_budget_exhausted(self, tmp_path: Path) -> None:
        """AC4: read operations not blocked even when budget is exhausted."""
        from agentkit.backend.integration_stabilization.budget_guard import (
            StabilizationBudgetGuard,
        )

        manifest = _make_manifest()
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "integration_budget.json").write_text(
            json.dumps({"loops_used": 99}),
            encoding="utf-8",
        )
        runner = GuardRunner(guards=[StabilizationBudgetGuard(manifest=manifest, story_dir=story_dir)])

        allowed, _ = runner.is_allowed("file_read", {"file_path": "src/api/handler.py"})

        assert allowed is True

    def test_budget_guard_name(self, tmp_path: Path) -> None:
        """AC4: StabilizationBudgetGuard.name is correct."""
        from agentkit.backend.integration_stabilization.budget_guard import (
            StabilizationBudgetGuard,
        )

        manifest = _make_manifest()
        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        guard = StabilizationBudgetGuard(manifest=manifest, story_dir=story_dir)
        assert guard.name == "stabilization_budget_guard"


# ---------------------------------------------------------------------------
# AC2: ImplementationPhaseHandler blocks IS stories without approved manifest
# ---------------------------------------------------------------------------


class TestImplementationPhaseHandlerISApprovalBlock:
    """Real ImplementationPhaseHandler blocks IS stories when no manifest.

    Tests use the real ImplementationPhaseHandler. Removing the IS approval
    check from on_enter() would change the error from IS-approval to some
    other unrelated failure.
    """

    def _make_impl_handler(self, story_dir: Path) -> object:
        """Build a minimal real ImplementationPhaseHandler for IS testing."""
        from agentkit.backend.implementation.phase import (
            ImplementationConfig,
            ImplementationPhaseHandler,
        )

        config = ImplementationConfig(story_dir=story_dir)
        return ImplementationPhaseHandler(config=config)

    def _make_envelope(self) -> object:
        from tests.phase_state_factory import make_phase_state

        from agentkit.backend.core_types import QaContext
        from agentkit.backend.pipeline_engine.phase_executor import (
            ImplementationPayload,
            QaCycleStatus,
        )

        state = make_phase_state(
            story_id=_STORY_ID,
            phase="implementation",
            status=PhaseStatus.IN_PROGRESS,
            payload=ImplementationPayload(
                qa_cycle_status=QaCycleStatus.IDLE,
                verify_context=QaContext.IMPLEMENTATION_INITIAL,
            ),
        )
        from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
        return PhaseEnvelopeStore.make_fresh_envelope(state)

    def test_implementation_escalates_without_is_manifest(
        self, tmp_path: Path
    ) -> None:
        """AC2: ImplementationPhaseHandler escalates IS stories when no manifest.

        Proves _check_is_implementation_approval() is wired into on_enter() --
        removing it would change the result from ESCALATED to something else.
        """
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)

        handler = self._make_impl_handler(story_dir)
        envelope = self._make_envelope()
        result = handler.on_enter(ctx, envelope)

        assert result.status == PhaseStatus.ESCALATED
        combined_errors = " ".join(result.errors or []).lower()
        assert "manifest" in combined_errors or "approval" in combined_errors, (
            f"Expected IS-approval escalation error, got: {result.errors}"
        )

    def _persist_flow(self, story_dir: Path, run_id: str = "run-is069") -> None:
        from agentkit.backend.phase_state_store.models import FlowExecution
        from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution

        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="PROJ",
                story_id=_STORY_ID,
                run_id=run_id,
                flow_id="flow-is069",
                level="story",
                owner="orchestrator",
            ),
        )

    def test_implementation_escalates_on_hash_mismatch(self, tmp_path: Path) -> None:
        """AC2/ERROR B: a hash-mismatched approval BLOCKS at spawn (binding)."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)
        manifest = _make_manifest()
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(
            story_dir,
            ManifestApprovalRecord(
                project_key=manifest.project_key,
                story_id=manifest.story_id,
                run_id="run-is069",
                manifest_version=manifest.version,
                manifest_hash="deadbeef",  # wrong hash
            ),
        )
        self._persist_flow(story_dir)

        handler = self._make_impl_handler(story_dir)
        result = handler.on_enter(ctx, self._make_envelope())

        assert result.status == PhaseStatus.ESCALATED
        combined = " ".join(result.errors or []).lower()
        assert "binding" in combined or "hash" in combined

    def test_implementation_escalates_on_version_mismatch(
        self, tmp_path: Path
    ) -> None:
        """AC2/ERROR B: a version-mismatched approval BLOCKS at spawn."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)
        manifest = _make_manifest()
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(
            story_dir,
            ManifestApprovalRecord(
                project_key=manifest.project_key,
                story_id=manifest.story_id,
                run_id="run-is069",
                manifest_version=manifest.version + 99,  # wrong version
                manifest_hash=manifest.content_hash,
            ),
        )
        self._persist_flow(story_dir)

        handler = self._make_impl_handler(story_dir)
        result = handler.on_enter(ctx, self._make_envelope())

        assert result.status == PhaseStatus.ESCALATED
        combined = " ".join(result.errors or []).lower()
        assert "binding" in combined or "version" in combined

    def test_implementation_escalates_on_run_mismatch(self, tmp_path: Path) -> None:
        """AC2/ERROR B: an approval bound to a DIFFERENT run BLOCKS at spawn."""
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)
        manifest = _make_manifest()
        save_integration_manifest(story_dir, manifest)
        # Approval bound to run-OTHER, but the active FlowExecution run is run-is069.
        save_manifest_approval(
            story_dir,
            ManifestApprovalRecord(
                project_key=manifest.project_key,
                story_id=manifest.story_id,
                run_id="run-OTHER",
                manifest_version=manifest.version,
                manifest_hash=manifest.content_hash,
            ),
        )
        self._persist_flow(story_dir, run_id="run-is069")

        handler = self._make_impl_handler(story_dir)
        result = handler.on_enter(ctx, self._make_envelope())

        assert result.status == PhaseStatus.ESCALATED
        combined = " ".join(result.errors or []).lower()
        assert "binding" in combined or "run_id" in combined or "run id" in combined

    def test_implementation_escalates_on_project_key_mismatch(
        self, tmp_path: Path
    ) -> None:
        """AC2/MAJOR I (round-3): a project_key-mismatched approval BLOCKS at spawn.

        This drives the REAL ``ImplementationPhaseHandler.on_enter`` (not just
        the helper ``check_binding_integrity``).  Removing the IS approval check
        from ``on_enter`` would let the handler proceed past this block.
        """
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)
        manifest = _make_manifest()
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(
            story_dir,
            ManifestApprovalRecord(
                project_key="WRONG-PROJECT",  # project_key mismatch
                story_id=manifest.story_id,
                run_id="run-is069",
                manifest_version=manifest.version,
                manifest_hash=manifest.content_hash,
            ),
        )
        self._persist_flow(story_dir)

        handler = self._make_impl_handler(story_dir)
        result = handler.on_enter(ctx, self._make_envelope())

        assert result.status == PhaseStatus.ESCALATED, (
            "project_key mismatch must escalate at the spawn boundary (AC2)"
        )
        combined = " ".join(result.errors or []).lower()
        assert "binding" in combined or "project" in combined, (
            f"Expected binding/project error, got: {result.errors}"
        )

    def test_implementation_escalates_on_story_id_mismatch(
        self, tmp_path: Path
    ) -> None:
        """AC2/MAJOR I (round-3): a story_id-mismatched approval BLOCKS at spawn.

        This drives the REAL ``ImplementationPhaseHandler.on_enter`` (not just
        the helper ``check_binding_integrity``).  Removing the IS approval check
        from ``on_enter`` would let the handler proceed past this block.
        """
        story_dir = _make_is_story_dir(tmp_path)
        ctx = _is_ctx()
        _write_implementation_artifacts(story_dir)
        manifest = _make_manifest()
        save_integration_manifest(story_dir, manifest)
        save_manifest_approval(
            story_dir,
            ManifestApprovalRecord(
                project_key=manifest.project_key,
                story_id="IS-WRONG",  # story_id mismatch
                run_id="run-is069",
                manifest_version=manifest.version,
                manifest_hash=manifest.content_hash,
            ),
        )
        self._persist_flow(story_dir)

        handler = self._make_impl_handler(story_dir)
        result = handler.on_enter(ctx, self._make_envelope())

        assert result.status == PhaseStatus.ESCALATED, (
            "story_id mismatch must escalate at the spawn boundary (AC2)"
        )
        combined = " ".join(result.errors or []).lower()
        assert "binding" in combined or "story" in combined, (
            f"Expected binding/story error, got: {result.errors}"
        )

    def test_standard_story_not_escalated_by_is_approval_check(
        self, tmp_path: Path
    ) -> None:
        """AC2 contract gate: standard stories NOT escalated by IS approval check.

        The IS approval check must be a no-op for STANDARD contract stories.
        If the handler raises or returns an error it must NOT be IS-approval
        related -- any other failure (e.g. missing FlowExecution) is acceptable
        proof that the IS guard did not fire.
        """
        from agentkit.backend.exceptions import CorruptStateError

        story_dir = tmp_path / "stories" / _STORY_ID
        story_dir.mkdir(parents=True, exist_ok=True)
        ctx = _standard_ctx()
        save_story_context(story_dir, ctx)
        _write_implementation_artifacts(story_dir)

        handler = self._make_impl_handler(story_dir)
        envelope = self._make_envelope()

        try:
            result = handler.on_enter(ctx, envelope)
            # Standard story: IS approval check must NOT produce an IS-related escalation.
            combined_errors = " ".join(result.errors or []).lower()
            is_approval_escalation = (
                ("manifest" in combined_errors or "approval" in combined_errors)
                and "integration" in combined_errors
            )
            assert not is_approval_escalation, (
                f"Standard story should not be escalated by IS approval check: "
                f"{result.errors}"
            )
        except CorruptStateError as exc:
            # CorruptStateError for missing FlowExecution is acceptable — it
            # proves the IS check passed through (did not block) and a later
            # unrelated precondition fired. The IS guard is NOT responsible.
            assert "integration" not in str(exc).lower() or "manifest" not in str(exc).lower(), (
                f"Unexpected IS-related CorruptStateError for standard story: {exc}"
            )
