"""Integration: the REAL standard->IS reclassification boundary (AG3-069 ERROR E).

AC10 / FK-05 §5.7/§5.13: these tests drive the REAL reclassification production
path (``reclassify_standard_to_integration_stabilization``) and the REAL
structural checker, proving:

* reclassifying a standard story to integration_stabilization persists the IS
  contract, creates a fresh evidence_epoch, and PERSISTS the pre-snapshot
  cross-scope deltas as quarantine state (no retroactive legalization);
* a pre-snapshot delta stays QUARANTINED: touching it in a later diff is a
  BLOCKING declared_surfaces_only finding through the real StructuralChecker
  EVEN WHEN the path falls within a declared seam (the invariant
  ``reclassification_may_not_legalize_pre_manifest_cross_scope_delta``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.integration_stabilization.reclassification import (
    reclassify_standard_to_integration_stabilization,
)
from agentkit.integration_stabilization.state import (
    read_quarantine_state,
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.state_backend.store import load_story_context, save_story_context
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import ChangeImpact
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.verify_system.protocols import Severity
from agentkit.verify_system.stage_registry.data import ALL_STAGES
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.structural.checker import StructuralChecker
from agentkit.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY = "IS-69"
_RUN = "run-is69"
_DELTA = "src/api/legacy_delta.py"  # a pre-snapshot delta INSIDE a declared seam


def _standard_ctx() -> StoryContext:
    return StoryContext(
        project_key="PROJ",
        story_id=_STORY,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.STANDARD,
        execution_route=StoryMode.EXPLORATION,
    )


def _manifest() -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id=_STORY,
        implementation_contract="integration_stabilization",
        target_seams=("src/api/",),
        allowed_repos_paths=("src/api/",),
        integration_targets=("e2e_login",),
        allowed_contract_changes=(),
        stabilization_budget=StabilizationBudgetCaps(
            max_loops=3,
            max_new_surfaces=2,
            max_contract_changes=1,
            max_regressions_per_cycle=1,
        ),
    )


class _FakeChangeEvidencePort:
    def __init__(self, changed_files: tuple[str, ...]) -> None:
        self._ev = ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY}",
            commit_messages=(f"feat({_STORY}): work",),
            pushed=True,
            changed_files=changed_files,
            actual_impact=ChangeImpact("Component"),
        )

    def collect(self, story_dir: Path) -> ChangeEvidence:  # noqa: ARG002
        return self._ev


class _FakeTelemetry:
    def count_events(self, *a: object, **k: object) -> int:  # noqa: ARG002
        return 2

    def run_scope_resolvable(self, *a: object, **k: object) -> bool:  # noqa: ARG002
        return True


def _checker(changed_files: tuple[str, ...]) -> StructuralChecker:
    from agentkit.verify_system.structural.checks import BuildTestEvidence

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
        change_evidence_port=_FakeChangeEvidencePort(changed_files),
    )


def _reclassified_is_story(tmp_path: Path) -> Path:
    """Reclassify a standard story to IS with a pre-snapshot delta quarantined."""
    story_dir = tmp_path / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    save_story_context(story_dir, _standard_ctx())
    for phase in ("setup", "exploration"):
        from agentkit.pipeline_engine.phase_executor import (
            PhaseSnapshot,
            PhaseStatus,
        )
        from agentkit.state_backend.store import save_phase_snapshot

        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id=_STORY,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    # The REAL reclassification boundary (standard -> IS). The state-backend
    # save_story_context is the allowed AC003 mutation surface (injected).
    result = reclassify_standard_to_integration_stabilization(
        story_dir,
        _standard_ctx(),
        pre_snapshot_deltas=(_DELTA,),
        context_writer=save_story_context,
    )
    assert result.legalization_blocked is True
    assert _DELTA in result.quarantined_deltas
    # Approve the manifest so the other IS checks do not mask the delta finding.
    m = _manifest()
    save_integration_manifest(story_dir, m)
    save_manifest_approval(
        story_dir,
        ManifestApprovalRecord(
            project_key="PROJ",
            story_id=_STORY,
            run_id=_RUN,
            manifest_version=m.version,
            manifest_hash=m.content_hash,
        ),
    )
    return story_dir


class TestReclassificationBoundary:
    def test_reclassification_persists_is_contract(self, tmp_path: Path) -> None:
        story_dir = _reclassified_is_story(tmp_path)
        ctx = load_story_context(story_dir)
        assert ctx is not None
        assert (
            ctx.implementation_contract
            is ImplementationContract.INTEGRATION_STABILIZATION
        )

    def test_pre_snapshot_delta_is_persisted_quarantined(
        self, tmp_path: Path
    ) -> None:
        story_dir = _reclassified_is_story(tmp_path)
        assert _DELTA in read_quarantine_state(story_dir)

    def test_pre_snapshot_delta_stays_quarantined_via_real_checker(
        self, tmp_path: Path
    ) -> None:
        """ERROR E: touching the quarantined pre-snapshot delta BLOCKS.

        The delta path is INSIDE the declared seam src/api/, yet it is BLOCKING
        because it is a quarantined pre-manifest delta (not legalized). This
        drives the REAL StructuralChecker, which reads the persisted quarantine.
        """
        story_dir = _reclassified_is_story(tmp_path)
        # The IS context is now persisted; build the IS ctx for the checker.
        ctx = load_story_context(story_dir)
        assert ctx is not None

        checker = _checker(changed_files=(_DELTA,))
        result = checker.evaluate(ctx, story_dir)

        blocking = [
            f
            for f in result.findings
            if f.check == "integration.declared_surfaces_only"
            and f.severity == Severity.BLOCKING
            and "quarantin" in f.message.lower()
        ]
        assert len(blocking) == 1, (
            f"Expected a quarantined-delta BLOCKING finding, got: "
            f"{[(f.check, f.message[:40]) for f in result.findings]}"
        )

    def test_declared_in_seam_non_quarantined_path_passes(
        self, tmp_path: Path
    ) -> None:
        """A normal in-seam path (not quarantined) does NOT trigger the block."""
        story_dir = _reclassified_is_story(tmp_path)
        ctx = load_story_context(story_dir)
        assert ctx is not None

        checker = _checker(changed_files=("src/api/handler.py",))
        result = checker.evaluate(ctx, story_dir)

        surface_findings = [
            f
            for f in result.findings
            if f.check == "integration.declared_surfaces_only"
        ]
        assert surface_findings == []
