"""Contract tests: artifact envelope/schema stability and telemetry event keys.

Pinned schemas and wire keys that must not change without a new major version
(ARCH-55 / telemetry contract / artifact envelope stability).
"""

from __future__ import annotations

from agentkit.backend.core_types.qa_artifact_names import STABILITY_GATE_PRODUCER
from agentkit.backend.integration_stabilization.events import (
    INTEGRATION_MANIFEST_APPROVED,
    INTEGRATION_VERIFY_FAILED,
    INTEGRATION_VERIFY_PASSED,
    MANIFEST_AMENDMENT_REQUESTED,
    STABILITY_GATE_PASSED,
    STABILIZATION_BUDGET_EXHAUSTED,
    STABILIZATION_CAMPAIGN_STARTED,
    UNDECLARED_SURFACE_DETECTED,
)
from agentkit.backend.integration_stabilization.fk37_checks import FK37CheckName
from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudget,
    StabilizationBudgetCaps,
)

# ---------------------------------------------------------------------------
# AC13: Wire-key stability (ARCH-55 English, pinned)
# ---------------------------------------------------------------------------


class TestTelemetryEventWireKeyContract:
    """Pinned wire keys — must not change (AC11/AC13)."""

    def test_integration_manifest_approved_key(self) -> None:
        assert INTEGRATION_MANIFEST_APPROVED == "integration_manifest_approved"

    def test_undeclared_surface_detected_key(self) -> None:
        assert UNDECLARED_SURFACE_DETECTED == "undeclared_surface_detected"

    def test_stabilization_budget_exhausted_key(self) -> None:
        assert STABILIZATION_BUDGET_EXHAUSTED == "stabilization_budget_exhausted"

    def test_stability_gate_passed_key(self) -> None:
        assert STABILITY_GATE_PASSED == "stability_gate_passed"

    def test_stabilization_campaign_started_key(self) -> None:
        assert STABILIZATION_CAMPAIGN_STARTED == "stabilization_campaign_started"

    def test_integration_verify_passed_key(self) -> None:
        assert INTEGRATION_VERIFY_PASSED == "integration_verify_passed"

    def test_integration_verify_failed_key(self) -> None:
        assert INTEGRATION_VERIFY_FAILED == "integration_verify_failed"

    def test_manifest_amendment_requested_key(self) -> None:
        assert MANIFEST_AMENDMENT_REQUESTED == "manifest_amendment_requested"


class TestFK37CheckNameContract:
    """Pinned FK-37 §37.1.3 check name wire keys (AC12/AC13)."""

    def test_integration_target_matrix_passed(self) -> None:
        assert FK37CheckName.INTEGRATION_TARGET_MATRIX_PASSED == "integration_target_matrix_passed"

    def test_declared_surfaces_only(self) -> None:
        assert FK37CheckName.DECLARED_SURFACES_ONLY == "declared_surfaces_only"

    def test_stabilization_budget_not_exhausted(self) -> None:
        assert FK37CheckName.STABILIZATION_BUDGET_NOT_EXHAUSTED == "stabilization_budget_not_exhausted"

    def test_stability_gate(self) -> None:
        assert FK37CheckName.STABILITY_GATE == "stability_gate"

    def test_manifest_approval_required(self) -> None:
        assert FK37CheckName.MANIFEST_APPROVAL_REQUIRED == "manifest_approval_required"

    def test_binding_integrity(self) -> None:
        assert FK37CheckName.BINDING_INTEGRITY == "binding_integrity"


class TestStabilityGateProducerContract:
    """Pinned producer name for stability_gate (AC11/AC13)."""

    def test_stability_gate_producer_wire_key(self) -> None:
        assert STABILITY_GATE_PRODUCER == "verify-system.stability-gate"


# ---------------------------------------------------------------------------
# Manifest schema stability (AC1)
# ---------------------------------------------------------------------------


class TestManifestSchemaStability:
    """Pinned FK-05 §5.5.2 field names — must be present in the schema."""

    def test_all_fk05_mandatory_fields_in_model_schema(self) -> None:
        fields = set(IntegrationScopeManifest.model_fields.keys())
        # FK-05 §5.5.2 mandatory fieldset:
        expected = {
            "project_key",
            "story_id",
            "implementation_contract",
            "target_seams",
            "allowed_repos_paths",
            "integration_targets",
            "allowed_contract_changes",
            "stabilization_budget",
            "out_of_contract_examples",
            "version",
            "content_hash",
        }
        missing = expected - fields
        assert not missing, f"Missing FK-05 §5.5.2 fields: {missing}"

    def test_all_fk05_approval_fields_in_model_schema(self) -> None:
        fields = set(ManifestApprovalRecord.model_fields.keys())
        expected = {
            "project_key",
            "story_id",
            "run_id",
            "manifest_version",
            "manifest_hash",
            "approved_by",
        }
        missing = expected - fields
        assert not missing, f"Missing FK-05 §5.5.4 fields: {missing}"

    def test_budget_caps_fields_in_model_schema(self) -> None:
        fields = set(StabilizationBudgetCaps.model_fields.keys())
        expected = {
            "max_loops",
            "max_new_surfaces",
            "max_contract_changes",
            "max_regressions_per_cycle",
        }
        missing = expected - fields
        assert not missing, f"Missing FK-05 §5.9 budget cap fields: {missing}"

    def test_manifest_is_frozen(self) -> None:
        assert IntegrationScopeManifest.model_config.get("frozen") is True

    def test_approval_record_is_frozen(self) -> None:
        assert ManifestApprovalRecord.model_config.get("frozen") is True

    def test_stabilization_budget_is_frozen(self) -> None:
        assert StabilizationBudget.model_config.get("frozen") is True

    def test_budget_caps_is_frozen(self) -> None:
        assert StabilizationBudgetCaps.model_config.get("frozen") is True
