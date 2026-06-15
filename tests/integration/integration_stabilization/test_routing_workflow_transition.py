"""Integration: IS routing block at the REAL workflow transition (AG3-069 ERROR A).

AC8 / FK-05 §5.6: these tests drive the REAL engine transition evaluator
(``pipeline_engine.engine._evaluate_transitions`` over the resolved
IMPLEMENTATION workflow) -- NOT a helper predicate. They prove:

* an integration_stabilization story at ``setup`` routes to ``exploration``
  (the direct setup -> implementation transition is blocked, exploration is
  mandatory);
* ``exploration -> implementation`` is BLOCKED for IS without an approved+bound
  manifest (execution gated on the manifest);
* with an approved+bound manifest the transition advances to implementation;
* a STANDARD story still routes setup -> implementation on the EXECUTION route
  (no regression).

If the IS routing guard were reverted, the standard ``_mode_is_not_exploration``
would advance an IS story straight to implementation -- these tests would fail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.core_types import ExplorationGateStatus
from agentkit.installer.paths import story_dir as _story_dir
from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.integration_stabilization.state import (
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.pipeline_engine.engine import _evaluate_transitions
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseStatus,
)
from agentkit.process.language.definitions import resolve_workflow
from agentkit.state_backend.store import save_story_context
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY = "IS-69"
_RUN = "11111111-1111-4111-8111-111111111111"


def _is_ctx(project_root: Path | None = None) -> StoryContext:
    return StoryContext(
        project_key="PROJ",
        story_id=_STORY,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        execution_route=StoryMode.EXECUTION,  # even on EXECUTION route, IS forces exploration
        project_root=project_root,
    )


def _setup_state() -> object:
    return make_phase_state(
        story_id=_STORY, phase="setup", status=PhaseStatus.COMPLETED
    )


def _exploration_state(*, approved: bool) -> object:
    gate = (
        ExplorationGateStatus.APPROVED if approved else ExplorationGateStatus.PENDING
    )
    return make_phase_state(
        story_id=_STORY,
        phase="exploration",
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=gate),
    )


def _workflow() -> object:
    return resolve_workflow(StoryType.IMPLEMENTATION)


class TestSetupRoutingBlocksImplementationForIS:
    def test_is_story_routes_setup_to_exploration(self) -> None:
        """AC8: IS story at setup routes to exploration, NOT implementation."""
        transition = _evaluate_transitions(_workflow(), _is_ctx(), _setup_state())
        assert transition is not None
        assert transition.target == "exploration"

    def test_standard_execution_story_routes_setup_to_implementation(self) -> None:
        """No regression: STANDARD EXECUTION story routes setup -> implementation."""
        ctx = StoryContext(
            project_key="PROJ",
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            implementation_contract=ImplementationContract.STANDARD,
            execution_route=StoryMode.EXECUTION,
        )
        transition = _evaluate_transitions(_workflow(), ctx, _setup_state())
        assert transition is not None
        assert transition.target == "implementation"


class TestExplorationToImplementationGatedOnManifest:
    def _prepare_story_dir(self, tmp_path: Path, *, approved: bool) -> Path:
        s_dir = _story_dir(tmp_path, _STORY)
        s_dir.mkdir(parents=True, exist_ok=True)
        ctx = _is_ctx(tmp_path)
        save_story_context(s_dir, ctx)
        if approved:
            m = IntegrationScopeManifest(
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
            save_integration_manifest(s_dir, m)
            save_manifest_approval(
                s_dir,
                ManifestApprovalRecord(
                    project_key="PROJ",
                    story_id=_STORY,
                    run_id=_RUN,
                    manifest_version=m.version,
                    manifest_hash=m.content_hash,
                ),
            )
        return s_dir

    def test_exploration_to_implementation_blocked_without_manifest(
        self, tmp_path: Path
    ) -> None:
        """AC8: exploration -> implementation BLOCKED for IS without manifest.

        Even though the exploration gate is APPROVED, the absence of an approved
        IS manifest blocks the transition fail-closed (no transition fires).
        """
        self._prepare_story_dir(tmp_path, approved=False)
        transition = _evaluate_transitions(
            _workflow(), _is_ctx(tmp_path), _exploration_state(approved=True)
        )
        assert transition is None

    def test_exploration_to_implementation_allowed_with_approved_manifest(
        self, tmp_path: Path
    ) -> None:
        """AC8: with an approved+bound manifest the transition advances."""
        self._prepare_story_dir(tmp_path, approved=True)
        transition = _evaluate_transitions(
            _workflow(), _is_ctx(tmp_path), _exploration_state(approved=True)
        )
        assert transition is not None
        assert transition.target == "implementation"

    def test_exploration_gate_not_approved_blocks_even_with_manifest(
        self, tmp_path: Path
    ) -> None:
        """The base exploration-gate-approved guard still gates (defense in depth)."""
        self._prepare_story_dir(tmp_path, approved=True)
        transition = _evaluate_transitions(
            _workflow(), _is_ctx(tmp_path), _exploration_state(approved=False)
        )
        assert transition is None
