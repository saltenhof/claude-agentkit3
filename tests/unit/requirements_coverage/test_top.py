"""Unit tests for RequirementsCoverage top-surface (AG3-030)."""

from __future__ import annotations

import pytest

from agentkit.config.models import Features, PipelineConfig
from agentkit.requirements_coverage.are_client import AreClient
from agentkit.requirements_coverage.contract import (
    AreDockpointStatus,
    AreEvidence,
    EvidenceProducer,
    EvidenceType,
)
from agentkit.requirements_coverage.errors import (
    AreCapabilityNotImplementedError,
    AreConfigurationError,
)
from agentkit.requirements_coverage.top import RequirementsCoverage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(are_enabled: bool = False) -> PipelineConfig:
    return PipelineConfig(features=Features(are=are_enabled))


def _evidence() -> AreEvidence:
    return AreEvidence(
        requirement_id="REQ-1",
        evidence_type=EvidenceType.TEST_REPORT,
        evidence_ref="tests/test_foo.py::test_bar",
        produced_by=EvidenceProducer.WORKER,
    )


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------

class TestIsEnabled:
    """`is_enabled` reflects ``features.are`` only; the AreClient presence is a
    separate fail-closed precondition checked per dock-point method (AK6)."""

    def test_disabled_config_no_client(self) -> None:
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(False))
        assert rc.is_enabled is False

    def test_disabled_config_with_client(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(False))
        assert rc.is_enabled is False

    def test_enabled_config_no_client_is_still_enabled(self) -> None:
        # AK6 / FAIL-CLOSED: features.are=True activates the BC. Missing
        # client surfaces as AreConfigurationError on dock-point invocation.
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(True))
        assert rc.is_enabled is True

    def test_enabled_config_with_client(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(True))
        assert rc.is_enabled is True


# ---------------------------------------------------------------------------
# link_requirements
# ---------------------------------------------------------------------------

class TestLinkRequirements:
    def test_disabled_returns_skipped(self) -> None:
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(False))
        result = rc.link_requirements("story-1", "proj-a")
        assert result.status == AreDockpointStatus.SKIPPED
        assert result.reason == "feature_disabled"

    def test_enabled_no_client_raises_configuration_error(self) -> None:
        # AK6 / FAIL-CLOSED: features.are=True but no AreClient -> AreConfigurationError.
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(True))
        with pytest.raises(AreConfigurationError):
            rc.link_requirements("story-1", "proj-a")

    def test_enabled_with_client_raises_not_implemented(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(True))
        with pytest.raises(AreCapabilityNotImplementedError):
            rc.link_requirements("story-1", "proj-a")


# ---------------------------------------------------------------------------
# load_context
# ---------------------------------------------------------------------------

class TestLoadContext:
    def test_disabled_returns_skipped(self) -> None:
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(False))
        result = rc.load_context("story-1", "proj-a", "run-42")
        assert result.status == AreDockpointStatus.SKIPPED
        assert result.are_bundle_ref is None

    def test_enabled_no_client_raises_configuration_error(self) -> None:
        # AK6 / FAIL-CLOSED: features.are=True but no AreClient -> AreConfigurationError.
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(True))
        with pytest.raises(AreConfigurationError):
            rc.load_context("story-1", "proj-a", "run-42")

    def test_enabled_with_client_raises_not_implemented(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(True))
        with pytest.raises(AreCapabilityNotImplementedError):
            rc.load_context("story-1", "proj-a", "run-42")


# ---------------------------------------------------------------------------
# submit_evidence
# ---------------------------------------------------------------------------

class TestSubmitEvidence:
    def test_disabled_returns_skipped(self) -> None:
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(False))
        result = rc.submit_evidence("story-1", _evidence())
        assert result.status == AreDockpointStatus.SKIPPED

    def test_enabled_no_client_raises_configuration_error(self) -> None:
        # AK6 / FAIL-CLOSED: features.are=True but no AreClient -> AreConfigurationError.
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(True))
        with pytest.raises(AreConfigurationError):
            rc.submit_evidence("story-1", _evidence())

    def test_enabled_with_client_raises_not_implemented(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(True))
        with pytest.raises(AreCapabilityNotImplementedError):
            rc.submit_evidence("story-1", _evidence())


# ---------------------------------------------------------------------------
# check_gate
# ---------------------------------------------------------------------------

class TestCheckGate:
    def test_disabled_returns_skipped(self) -> None:
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(False))
        result = rc.check_gate("story-1", "proj-a")
        assert result.status == AreDockpointStatus.SKIPPED
        assert result.verdict is None

    def test_enabled_no_client_raises_configuration_error(self) -> None:
        # AK6 / FAIL-CLOSED: features.are=True but no AreClient -> AreConfigurationError.
        rc = RequirementsCoverage(are_client=None, pipeline_config=_config(True))
        with pytest.raises(AreConfigurationError):
            rc.check_gate("story-1", "proj-a")

    def test_enabled_with_client_raises_not_implemented(self) -> None:
        client = AreClient(base_url="https://are.example.com")
        rc = RequirementsCoverage(are_client=client, pipeline_config=_config(True))
        with pytest.raises(AreCapabilityNotImplementedError):
            rc.check_gate("story-1", "proj-a")
