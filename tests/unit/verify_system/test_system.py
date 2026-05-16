"""Tests for the VerifySystem Capability-A-Top-Komponente.

The facade is the sole entry point for cross-BC callers
(``concept/_meta/bc-cut-decisions.md`` §"BC 2: verify-system",
FK-07 §7.4.2, FK-27). These tests cover construction and pure-delegation
behaviour for the operations consumed by ``agentkit.implementation``.

Wertebereich seit AG3-021: ``Severity`` ist BLOCKING/MAJOR/MINOR und
``PolicyVerdict`` ist PASS/FAIL.
"""

from __future__ import annotations

from agentkit.verify_system import VerifySystem
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    QALayer,
    Severity,
    TrustClass,
)


class TestVerifySystemFacade:
    """Construction and delegation behaviour of VerifySystem."""

    def test_create_default_returns_configured_facade(self) -> None:
        verify_system = VerifySystem.create_default()
        assert isinstance(verify_system, VerifySystem)
        assert isinstance(verify_system.policy_engine, PolicyEngine)
        assert isinstance(
            verify_system.adversarial_challenger, AdversarialChallenger
        )

    def test_create_default_propagates_max_major_findings(self) -> None:
        verify_system = VerifySystem.create_default(max_major_findings=2)
        # Two MAJOR findings remain non-blocking, three flip to blocking.
        non_blocking = LayerResult(
            layer="probe",
            passed=True,
            findings=(
                Finding(
                    layer="probe",
                    check="c1",
                    severity=Severity.MAJOR,
                    message="m1",
                    trust_class=TrustClass.VERIFIED_LLM,
                ),
                Finding(
                    layer="probe",
                    check="c2",
                    severity=Severity.MAJOR,
                    message="m2",
                    trust_class=TrustClass.VERIFIED_LLM,
                ),
            ),
        )
        decision_non_blocking = verify_system.policy_decision([non_blocking])
        assert decision_non_blocking.passed is True
        assert decision_non_blocking.blocking_findings == ()

        blocking = LayerResult(
            layer="probe",
            passed=True,
            findings=(
                *non_blocking.findings,
                Finding(
                    layer="probe",
                    check="c3",
                    severity=Severity.MAJOR,
                    message="m3",
                    trust_class=TrustClass.VERIFIED_LLM,
                ),
            ),
        )
        decision_blocking = verify_system.policy_decision([blocking])
        assert decision_blocking.passed is False
        assert len(decision_blocking.blocking_findings) == 3

    def test_facade_is_frozen_dataclass(self) -> None:
        """The facade must be immutable (FrozenInstanceError on assignment)."""
        verify_system = VerifySystem.create_default()
        try:
            verify_system.policy_engine = PolicyEngine()  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 -- dataclasses.FrozenInstanceError
            assert "frozen" in str(exc).lower() or exc.__class__.__name__ == (
                "FrozenInstanceError"
            )
        else:
            msg = "VerifySystem must be a frozen dataclass"
            raise AssertionError(msg)

    def test_policy_decision_pass_without_findings(self) -> None:
        verify_system = VerifySystem.create_default()
        decision = verify_system.policy_decision(
            [LayerResult(layer="probe", passed=True, findings=())],
        )
        assert decision.passed is True
        assert decision.status == "PASS"
        assert decision.blocking_findings == ()

    def test_policy_decision_fail_on_system_blocking(self) -> None:
        verify_system = VerifySystem.create_default()
        result = LayerResult(
            layer="structural",
            passed=False,
            findings=(
                Finding(
                    layer="structural",
                    check="missing",
                    severity=Severity.BLOCKING,
                    message="blocking finding",
                    trust_class=TrustClass.SYSTEM,
                ),
            ),
        )
        decision = verify_system.policy_decision([result])
        assert decision.passed is False
        assert decision.status == "FAIL"
        assert len(decision.blocking_findings) == 1

    def test_adversarial_layer_returns_qa_layer_protocol(self) -> None:
        verify_system = VerifySystem.create_default()
        layer = verify_system.adversarial_layer()
        assert isinstance(layer, QALayer)
        assert layer.name == "adversarial"

    def test_adversarial_layer_returns_facade_owned_instance(self) -> None:
        verify_system = VerifySystem.create_default()
        # Pure delegation: facade exposes the instance it holds.
        assert verify_system.adversarial_layer() is verify_system.adversarial_challenger
