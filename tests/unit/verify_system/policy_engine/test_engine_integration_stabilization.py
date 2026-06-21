"""PolicyEngine integration_stabilization contract-threading tests (AG3-069 ERROR C).

FK-37 §37.1.3 / AC12: when ``implementation_contract == integration_stabilization``
is threaded into ``PolicyEngine.decide``, the registry-bound fail-closed
missing-stage check REQUIRES the IS Layer-4 stages (``stability_gate`` and
``integration.integration_target_matrix_passed``). A normal QA PASS (all standard
stages produced) is therefore NOT sufficient for IS closure — the IS gate result
MUST be produced. These tests drive the REAL PolicyEngine.decide and would fail if
the ``implementation_contract`` threading were reverted.

AG3-069 ERROR C (round-3): the real-producer path (``produce_stability_gate_layer_result``)
must emit stage ids that match the registry verbatim.  A wrong id (e.g. the unprefixed
``integration_target_matrix_passed`` instead of
``integration.integration_target_matrix_passed``) would leave the Layer-4 stage
unsatisfied and cause ``TestRealProducerToEngine`` to fail.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PolicyVerdict

if TYPE_CHECKING:
    from pathlib import Path
from agentkit.backend.story_context_manager.types import ImplementationContract, StoryType
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
from agentkit.backend.verify_system.protocols import LayerResult
from agentkit.backend.verify_system.stage_registry import StageRegistry

_IS = ImplementationContract.INTEGRATION_STABILIZATION


def _structural_with_is_layer1() -> LayerResult:
    """Structural Layer-1 result whose stage_ids include the IS Layer-1 stages."""
    registry = StageRegistry()
    stage_ids = tuple(
        s.stage_id
        for s in registry.layer1_stages_for(
            StoryType.IMPLEMENTATION,
            are_enabled=False,
            implementation_contract=_IS,
        )
    )
    return LayerResult(
        layer="structural",
        passed=True,
        findings=(),
        metadata={"stage_ids": stage_ids},
    )


def _sonarqube() -> LayerResult:
    return LayerResult(layer="sonarqube_gate", passed=True)


def _stability_gate_result() -> LayerResult:
    """The produced IS Layer-4 gate result (stability_gate + target matrix)."""
    return LayerResult(
        layer="stability_gate",
        passed=True,
        findings=(),
        metadata={
            "stage_ids": (
                "stability_gate",
                "integration.integration_target_matrix_passed",
            )
        },
    )


# Traversed layers for an IS implementation QA run: Layer-1 deterministic +
# Layer-4 policy/gate (Layer 2/3 omitted to isolate the IS Layer-4 crux).
_TRAVERSED = frozenset({1, 4})


class TestISContractRequiresStabilityGate:
    def test_is_qa_fails_without_stability_gate_result(self) -> None:
        """ERROR C: normal QA PASS is NOT enough for IS — the gate must be produced."""
        engine = PolicyEngine()
        result = engine.decide(
            [_structural_with_is_layer1(), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=_TRAVERSED,
            implementation_contract=_IS,
        )
        assert result.verdict is PolicyVerdict.FAIL
        missing_checks = {f.check for f in result.all_findings if f.layer == "policy"}
        # The IS Layer-4 stages are reported missing fail-closed.
        assert "stability_gate" in missing_checks
        assert "integration.integration_target_matrix_passed" in missing_checks

    def test_is_qa_passes_when_stability_gate_produced(self) -> None:
        """With the produced IS gate result the IS Layer-4 stages are satisfied."""
        engine = PolicyEngine()
        result = engine.decide(
            [
                _structural_with_is_layer1(),
                _sonarqube(),
                _stability_gate_result(),
            ],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=_TRAVERSED,
            implementation_contract=_IS,
        )
        missing_checks = {f.check for f in result.all_findings if f.layer == "policy"}
        assert "stability_gate" not in missing_checks
        assert "integration.integration_target_matrix_passed" not in missing_checks

    def test_standard_contract_does_not_require_is_stages(self) -> None:
        """Contract gate: a STANDARD story never requires the IS Layer-4 stages."""
        engine = PolicyEngine()
        registry = StageRegistry()
        std_layer1 = LayerResult(
            layer="structural",
            passed=True,
            metadata={
                "stage_ids": tuple(
                    s.stage_id
                    for s in registry.layer1_stages_for(
                        StoryType.IMPLEMENTATION, are_enabled=False
                    )
                )
            },
        )
        result = engine.decide(
            [std_layer1, _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=_TRAVERSED,
            implementation_contract=ImplementationContract.STANDARD,
        )
        missing_checks = {f.check for f in result.all_findings if f.layer == "policy"}
        assert "stability_gate" not in missing_checks
        assert "integration.integration_target_matrix_passed" not in missing_checks

    def test_none_contract_does_not_require_is_stages(self) -> None:
        """No contract threaded => IS stages excluded (unchanged standard behaviour)."""
        engine = PolicyEngine()
        registry = StageRegistry()
        std_layer1 = LayerResult(
            layer="structural",
            passed=True,
            metadata={
                "stage_ids": tuple(
                    s.stage_id
                    for s in registry.layer1_stages_for(
                        StoryType.IMPLEMENTATION, are_enabled=False
                    )
                )
            },
        )
        result = engine.decide(
            [std_layer1, _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=_TRAVERSED,
        )
        missing_checks = {f.check for f in result.all_findings if f.layer == "policy"}
        assert "stability_gate" not in missing_checks


# ---------------------------------------------------------------------------
# ERROR C (round-3): real producer -> real PolicyEngine path
# ---------------------------------------------------------------------------


def _make_approved_story_dir(tmp_path: Path) -> Path:
    """Set up a minimal IS story directory with an approved manifest.

    Returns the story_dir ready for ``produce_stability_gate_layer_result``.
    """
    from agentkit.backend.integration_stabilization.models import (
        IntegrationScopeManifest,
        ManifestApprovalRecord,
        StabilizationBudgetCaps,
    )
    from agentkit.backend.integration_stabilization.stability_gate_producer import (
        IS_TARGETS_FILE,
    )
    from agentkit.backend.integration_stabilization.state import (
        save_integration_manifest,
        save_manifest_approval,
    )

    manifest = IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id="IS-069",
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
    approval = ManifestApprovalRecord(
        project_key="PROJ",
        story_id="IS-069",
        run_id="run-c-test",
        manifest_version=manifest.version,
        manifest_hash=manifest.content_hash,
    )
    story_dir = tmp_path / "stories" / "IS-069"
    story_dir.mkdir(parents=True)
    save_integration_manifest(story_dir, manifest)
    save_manifest_approval(story_dir, approval)
    # All declared integration targets are achieved so the gate can PASS.
    (story_dir / IS_TARGETS_FILE).write_text(
        json.dumps({"achieved_targets": ["e2e_login"]}),
        encoding="utf-8",
    )
    return story_dir


class TestRealProducerToEngine:
    """ERROR C (round-3): real ``produce_stability_gate_layer_result`` -> real engine.

    This test calls the real producer and feeds its output directly into the
    real ``PolicyEngine.decide``.  It verifies two invariants:

    1. The producer emits stage ids that match the registry verbatim so the
       PolicyEngine regards the IS Layer-4 stages as produced (not missing).
    2. If the producer were to emit the wrong id (unprefixed
       ``integration_target_matrix_passed``), the engine would report the
       stage missing and this test would fail -- ensuring the test regresses
       when the ERROR C fix is reverted.
    """

    def test_real_producer_satisfies_is_layer4_in_policy_engine(
        self, tmp_path: Path
    ) -> None:
        """Real producer output satisfies both IS Layer-4 stages in PolicyEngine.

        Drives ``produce_stability_gate_layer_result`` with a fully-approved
        IS story dir, then passes the real LayerResult to the real
        ``PolicyEngine.decide``.  The IS Layer-4 stages must NOT appear in
        ``missing_checks`` -- proving the producer emits the correct prefixed
        stage id for ``integration.integration_target_matrix_passed``.
        """
        from agentkit.backend.integration_stabilization.stability_gate_producer import (
            produce_stability_gate_layer_result,
        )

        story_dir = _make_approved_story_dir(tmp_path)
        layer_result = produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id="run-c-test",
            touched_paths=("src/api/handler.py",),
            story_id="IS-069",
            project_key="PROJ",
        )

        # Verify the producer emits both IS Layer-4 stage ids verbatim.
        emitted_ids = layer_result.metadata.get("stage_ids", ())
        assert "stability_gate" in emitted_ids, (
            "Producer must emit 'stability_gate' (exact registry id)"
        )
        assert "integration.integration_target_matrix_passed" in emitted_ids, (
            "Producer must emit 'integration.integration_target_matrix_passed' "
            "(exact registry id including the 'integration.' prefix); "
            "a bare 'integration_target_matrix_passed' is wrong"
        )

        # Feed the real producer output into the real PolicyEngine.
        registry = StageRegistry()
        stage_ids = tuple(
            s.stage_id
            for s in registry.layer1_stages_for(
                StoryType.IMPLEMENTATION,
                are_enabled=False,
                implementation_contract=_IS,
            )
        )
        structural = LayerResult(
            layer="structural",
            passed=True,
            findings=(),
            metadata={"stage_ids": stage_ids},
        )
        sonarqube = LayerResult(layer="sonarqube_gate", passed=True)
        engine = PolicyEngine()
        result = engine.decide(
            [structural, sonarqube, layer_result],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
            implementation_contract=_IS,
        )
        missing_checks = {f.check for f in result.all_findings if f.layer == "policy"}
        assert "stability_gate" not in missing_checks, (
            "stability_gate stage must not be missing when real producer ran"
        )
        assert "integration.integration_target_matrix_passed" not in missing_checks, (
            "integration.integration_target_matrix_passed stage must not be missing "
            "when real producer ran -- if it is, the producer is emitting the wrong id"
        )
