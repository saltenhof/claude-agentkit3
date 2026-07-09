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

import uuid
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.core_types import ExplorationGateStatus
from agentkit.backend.installer.paths import story_dir as _story_dir
from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.backend.integration_stabilization.state import (
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.backend.pipeline_engine.engine import _evaluate_transitions
from agentkit.backend.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseStatus,
)
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

# Static story id used only by tests that do NOT persist story context to the
# database (TestSetupRoutingBlocksImplementationForIS). Tests that DO write to
# the shared Postgres ``story_contexts`` table use the per-test ``unique_story_id``
# fixture below to avoid UniqueViolation on ``story_contexts_story_id_idx``.
_STORY = "IS-69"
_RUN = "11111111-1111-4111-8111-111111111111"


@pytest.fixture()
def unique_story_id() -> str:
    """Return a per-test-unique story id to prevent Postgres unique-index collisions.

    The shared Postgres DB carries a standalone UNIQUE index on ``story_id``
    (``story_contexts_story_id_idx``).  Tests that persist a story context must
    use a story id that is unique across ALL integration tests in the session;
    otherwise a previously inserted row from a different test file or a prior
    test run causes a UniqueViolation even when the ``(project_key, story_id)``
    pair would be distinct.

    The id uses a large numeric suffix derived from a UUID so it satisfies the
    ``^[A-Z][A-Z0-9]{1,9}-\\d+$`` pattern and the ``story_number >= 1`` invariant
    while being statistically unique across parallel Jenkins workers.
    """
    # Take the low 9 digits of the uuid int; always >= 1 (floor at 1 if 0).
    n = uuid.uuid4().int % 1_000_000_000 or 1
    return f"IS-{n}"


def _is_ctx(story_id: str, project_root: Path | None = None) -> StoryContext:
    return StoryContext(
        project_key="PROJ",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        execution_route=StoryMode.EXECUTION,  # even on EXECUTION route, IS forces exploration
        project_root=project_root,
    )


def _setup_state(story_id: str) -> object:
    return make_phase_state(
        story_id=story_id, phase="setup", status=PhaseStatus.COMPLETED
    )


def _exploration_state(story_id: str, *, approved: bool) -> object:
    gate = (
        ExplorationGateStatus.APPROVED if approved else ExplorationGateStatus.PENDING
    )
    return make_phase_state(
        story_id=story_id,
        phase="exploration",
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=gate),
    )


def _workflow() -> object:
    return resolve_workflow(StoryType.IMPLEMENTATION)


class TestSetupRoutingBlocksImplementationForIS:
    def test_is_story_routes_setup_to_exploration(self) -> None:
        """AC8: IS story at setup routes to exploration, NOT implementation."""
        transition = _evaluate_transitions(
            _workflow(), _is_ctx(_STORY), _setup_state(_STORY)
        )
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
        transition = _evaluate_transitions(_workflow(), ctx, _setup_state(_STORY))
        assert transition is not None
        assert transition.target == "implementation"


class TestExplorationToImplementationGatedOnManifest:
    def _prepare_story_dir(
        self, tmp_path: Path, story_id: str, *, approved: bool
    ) -> Path:
        s_dir = _story_dir(tmp_path, story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        ctx = _is_ctx(story_id, tmp_path)
        save_story_context(s_dir, ctx)
        if approved:
            m = IntegrationScopeManifest(
                version=1,
                project_key="PROJ",
                story_id=story_id,
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
                    story_id=story_id,
                    run_id=_RUN,
                    manifest_version=m.version,
                    manifest_hash=m.content_hash,
                ),
            )
        return s_dir

    def test_exploration_to_implementation_blocked_without_manifest(
        self, tmp_path: Path, unique_story_id: str
    ) -> None:
        """AC8: exploration -> implementation BLOCKED for IS without manifest.

        Even though the exploration gate is APPROVED, the absence of an approved
        IS manifest blocks the transition fail-closed (no transition fires).
        """
        self._prepare_story_dir(tmp_path, unique_story_id, approved=False)
        transition = _evaluate_transitions(
            _workflow(),
            _is_ctx(unique_story_id, tmp_path),
            _exploration_state(unique_story_id, approved=True),
        )
        assert transition is None

    def test_exploration_to_implementation_allowed_with_approved_manifest(
        self, tmp_path: Path, unique_story_id: str
    ) -> None:
        """AC8: with an approved+bound manifest the transition advances."""
        self._prepare_story_dir(tmp_path, unique_story_id, approved=True)
        transition = _evaluate_transitions(
            _workflow(),
            _is_ctx(unique_story_id, tmp_path),
            _exploration_state(unique_story_id, approved=True),
        )
        assert transition is not None
        assert transition.target == "implementation"

    def test_exploration_gate_not_approved_blocks_even_with_manifest(
        self, tmp_path: Path, unique_story_id: str
    ) -> None:
        """The base exploration-gate-approved guard still gates (defense in depth)."""
        self._prepare_story_dir(tmp_path, unique_story_id, approved=True)
        transition = _evaluate_transitions(
            _workflow(),
            _is_ctx(unique_story_id, tmp_path),
            _exploration_state(unique_story_id, approved=False),
        )
        assert transition is None
