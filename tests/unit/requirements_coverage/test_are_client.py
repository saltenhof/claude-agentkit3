"""Unit tests for AreClient skeleton (AG3-030)."""

from __future__ import annotations

import inspect

import pytest

from agentkit.requirements_coverage.are_client import AreClient
from agentkit.requirements_coverage.contract import EvidenceType

# ---------------------------------------------------------------------------
# NotImplementedError on all five methods
# ---------------------------------------------------------------------------

class TestAreClientNotImplemented:
    """Every AreClient method must raise NotImplementedError with 'follow-up'."""

    def setup_method(self) -> None:
        self.client = AreClient(base_url="https://are.example.com", auth_token=None)

    def test_list_requirements_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up"):
            self.client.list_requirements(story_id="s-1", scope="backend")

    def test_get_recurring_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up"):
            self.client.get_recurring(scope="backend", story_type="implementation")

    def test_load_context_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up"):
            self.client.load_context(story_id="s-1")

    def test_submit_evidence_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up"):
            self.client.submit_evidence(
                story_id="s-1",
                requirement_id="REQ-1",
                evidence_type=EvidenceType.TEST_REPORT,
                evidence_ref="tests/test_x.py::test_y",
            )

    def test_check_gate_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up"):
            self.client.check_gate(story_id="s-1")


# ---------------------------------------------------------------------------
# Signature pinning via inspect.signature
# ---------------------------------------------------------------------------

class TestAreClientSignatures:
    """Signatures must match FK-40 §40.4.1 exactly."""

    def test_list_requirements_signature(self) -> None:
        sig = inspect.signature(AreClient.list_requirements)
        params = list(sig.parameters)
        assert params == ["self", "story_id", "scope"]

    def test_get_recurring_signature(self) -> None:
        sig = inspect.signature(AreClient.get_recurring)
        params = list(sig.parameters)
        assert params == ["self", "scope", "story_type"]

    def test_load_context_signature(self) -> None:
        sig = inspect.signature(AreClient.load_context)
        params = list(sig.parameters)
        assert params == ["self", "story_id"]

    def test_submit_evidence_signature(self) -> None:
        sig = inspect.signature(AreClient.submit_evidence)
        params = list(sig.parameters)
        assert params == [
            "self",
            "story_id",
            "requirement_id",
            "evidence_type",
            "evidence_ref",
        ]

    def test_check_gate_signature(self) -> None:
        sig = inspect.signature(AreClient.check_gate)
        params = list(sig.parameters)
        assert params == ["self", "story_id"]

    def test_init_signature(self) -> None:
        sig = inspect.signature(AreClient.__init__)
        params = list(sig.parameters)
        assert params == ["self", "base_url", "auth_token"]
        # auth_token must have a default of None
        assert sig.parameters["auth_token"].default is None
