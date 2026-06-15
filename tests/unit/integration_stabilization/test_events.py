"""Unit tests for integration-stabilization telemetry events (AC11)."""

from __future__ import annotations

from agentkit.integration_stabilization.events import (
    INTEGRATION_MANIFEST_APPROVED,
    STABILITY_GATE_PASSED,
    STABILIZATION_BUDGET_EXHAUSTED,
    UNDECLARED_SURFACE_DETECTED,
    emit_integration_manifest_approved,
    emit_stability_gate_passed,
    emit_stabilization_budget_exhausted,
    emit_undeclared_surface_detected,
)
from agentkit.telemetry.events import Event


class TestEventWireKeys:
    """AC11/AC13: wire keys are English, match formal-spec events.md."""

    def test_integration_manifest_approved_wire_key(self) -> None:
        assert INTEGRATION_MANIFEST_APPROVED == "integration_manifest_approved"

    def test_undeclared_surface_detected_wire_key(self) -> None:
        assert UNDECLARED_SURFACE_DETECTED == "undeclared_surface_detected"

    def test_stabilization_budget_exhausted_wire_key(self) -> None:
        assert STABILIZATION_BUDGET_EXHAUSTED == "stabilization_budget_exhausted"

    def test_stability_gate_passed_wire_key(self) -> None:
        assert STABILITY_GATE_PASSED == "stability_gate_passed"


class TestEmitIntegrationManifestApproved:
    """AC11: integration_manifest_approved event."""

    def test_produces_event_with_correct_payload(self) -> None:
        event = emit_integration_manifest_approved(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            manifest_version=1,
            manifest_hash="abc123",
        )
        assert isinstance(event, Event)
        assert event.story_id == "PROJ-42"
        assert event.project_key == "PROJ"
        assert event.run_id == "run-001"
        assert event.payload["event_name"] == INTEGRATION_MANIFEST_APPROVED
        assert event.payload["manifest_version"] == 1
        assert event.payload["manifest_hash"] == "abc123"

    def test_producer_is_human_cli(self) -> None:
        event = emit_integration_manifest_approved(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            manifest_version=1,
            manifest_hash="abc123",
        )
        assert event.source_component == "human_cli"


class TestEmitUndeclaredSurfaceDetected:
    """AC11: undeclared_surface_detected event."""

    def test_produces_event_with_surface_path(self) -> None:
        event = emit_undeclared_surface_detected(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            surface_path="src/undeclared/module.py",
        )
        assert isinstance(event, Event)
        assert event.payload["event_name"] == UNDECLARED_SURFACE_DETECTED
        assert event.payload["surface_path"] == "src/undeclared/module.py"

    def test_producer_is_guard_system(self) -> None:
        event = emit_undeclared_surface_detected(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            surface_path="src/other.py",
        )
        assert event.source_component == "guard_system"

    def test_default_check_layer(self) -> None:
        event = emit_undeclared_surface_detected(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            surface_path="src/other.py",
        )
        assert event.payload["check_layer"] == "layer_1_structural"


class TestEmitStabilizationBudgetExhausted:
    """AC11: stabilization_budget_exhausted event."""

    def test_produces_event_with_exhausted_caps(self) -> None:
        event = emit_stabilization_budget_exhausted(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            exhausted_caps=["loops", "regressions_per_cycle"],
        )
        assert isinstance(event, Event)
        assert event.payload["event_name"] == STABILIZATION_BUDGET_EXHAUSTED
        assert "loops" in event.payload["exhausted_caps"]

    def test_producer_is_guard_system(self) -> None:
        event = emit_stabilization_budget_exhausted(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            exhausted_caps=["loops"],
        )
        assert event.source_component == "guard_system"


class TestEmitStabilityGatePassed:
    """AC11: stability_gate_passed event."""

    def test_produces_event_with_achieved_targets(self) -> None:
        event = emit_stability_gate_passed(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            achieved_targets=["e2e_login", "e2e_checkout"],
        )
        assert isinstance(event, Event)
        assert event.payload["event_name"] == STABILITY_GATE_PASSED
        assert "e2e_login" in event.payload["achieved_targets"]

    def test_producer_is_pipeline_deterministic(self) -> None:
        event = emit_stability_gate_passed(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            achieved_targets=["e2e_login"],
        )
        assert event.source_component == "pipeline_deterministic"


class TestMandatoryPayloadContract:
    """AC11/ERROR G: the four IS events carry registered mandatory payload keys."""

    def test_all_four_events_have_mandatory_fields(self) -> None:
        from agentkit.telemetry.events import MANDATORY_PAYLOAD_FIELDS, EventType

        for event_type in (
            EventType.INTEGRATION_MANIFEST_APPROVED,
            EventType.UNDECLARED_SURFACE_DETECTED,
            EventType.STABILIZATION_BUDGET_EXHAUSTED,
            EventType.STABILITY_GATE_PASSED,
        ):
            assert event_type in MANDATORY_PAYLOAD_FIELDS
            assert MANDATORY_PAYLOAD_FIELDS[event_type]

    def test_missing_mandatory_field_fails_closed(self) -> None:
        import pytest

        from agentkit.telemetry.events import (
            EventPayloadContractError,
            EventType,
            validate_event_payload,
        )

        with pytest.raises(EventPayloadContractError):
            validate_event_payload(
                EventType.UNDECLARED_SURFACE_DETECTED,
                {"event_name": "undeclared_surface_detected"},  # missing surface_path
            )

    def test_emitted_events_pass_validation(self) -> None:
        from agentkit.telemetry.events import EventType, validate_event_payload

        event = emit_stabilization_budget_exhausted(
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
            exhausted_caps=["loops"],
        )
        # Must not raise (the factory already validated on build).
        validate_event_payload(EventType.STABILIZATION_BUDGET_EXHAUSTED, event.payload)


class TestGuardsEmitAtBoundaryViaRealEmitter:
    """AC11/ERROR G: guards EMIT through the real emitter at their boundary."""

    def _manifest(self) -> object:
        from agentkit.integration_stabilization.models import (
            IntegrationScopeManifest,
            StabilizationBudgetCaps,
        )

        return IntegrationScopeManifest(
            version=1,
            project_key="PROJ",
            story_id="PROJ-42",
            implementation_contract="integration_stabilization",
            target_seams=("src/api/",),
            allowed_repos_paths=(),
            integration_targets=("e2e_login",),
            allowed_contract_changes=(),
            stabilization_budget=StabilizationBudgetCaps(
                max_loops=1,
                max_new_surfaces=0,
                max_contract_changes=0,
                max_regressions_per_cycle=0,
            ),
        )

    def test_seam_guard_emits_undeclared_surface_on_block(self) -> None:
        from agentkit.integration_stabilization.seam_allowlist_guard import (
            SeamAllowlistGuard,
        )
        from agentkit.telemetry.emitters import MemoryEmitter
        from agentkit.telemetry.events import EventType

        emitter = MemoryEmitter()
        guard = SeamAllowlistGuard(
            ("src/api/",),
            emitter=emitter,
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
        )
        verdict = guard.evaluate("file_write", {"file_path": "src/other/hack.py"})
        assert verdict.allowed is False
        events = emitter.query("PROJ-42", EventType.UNDECLARED_SURFACE_DETECTED)
        assert len(events) == 1
        assert events[0].payload["surface_path"].endswith("hack.py")

    def test_budget_guard_emits_budget_exhausted_on_block(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        import json

        from agentkit.integration_stabilization.budget_guard import (
            StabilizationBudgetGuard,
        )
        from agentkit.telemetry.emitters import MemoryEmitter
        from agentkit.telemetry.events import EventType

        story_dir = tmp_path / "PROJ-42"
        story_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "integration_budget.json").write_text(
            json.dumps({"loops_used": 1}), encoding="utf-8"
        )
        emitter = MemoryEmitter()
        guard = StabilizationBudgetGuard(
            manifest=self._manifest(),  # type: ignore[arg-type]
            story_dir=story_dir,
            emitter=emitter,
            story_id="PROJ-42",
            project_key="PROJ",
            run_id="run-001",
        )
        verdict = guard.evaluate("file_write", {"file_path": "src/api/x.py"})
        assert verdict.allowed is False
        events = emitter.query("PROJ-42", EventType.STABILIZATION_BUDGET_EXHAUSTED)
        assert len(events) == 1
