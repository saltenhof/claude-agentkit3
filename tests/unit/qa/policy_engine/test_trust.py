"""Tests for trust classification and effective severity computation."""

from __future__ import annotations

from agentkit.qa.policy_engine.trust import TRUST_WEIGHT, effective_severity
from agentkit.qa.protocols import Finding, Severity, TrustClass


class TestTrustWeight:
    """TRUST_WEIGHT mapping values."""

    def test_system_has_highest_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.SYSTEM] == 3

    def test_verified_llm_has_middle_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.VERIFIED_LLM] == 2

    def test_worker_assertion_has_lowest_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.WORKER_ASSERTION] == 1

    def test_system_weight_greater_than_worker(self) -> None:
        assert TRUST_WEIGHT[TrustClass.SYSTEM] > TRUST_WEIGHT[TrustClass.WORKER_ASSERTION]


class TestEffectiveSeverity:
    """effective_severity computation tests."""

    def test_critical_system_scores_highest(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.CRITICAL,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        assert effective_severity(f) == 100 * 3  # 300

    def test_critical_worker_scores_lower_than_critical_system(self) -> None:
        system = Finding(
            layer="s", check="a", severity=Severity.CRITICAL,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        worker = Finding(
            layer="s", check="a", severity=Severity.CRITICAL,
            message="msg", trust_class=TrustClass.WORKER_ASSERTION,
        )
        assert effective_severity(system) > effective_severity(worker)

    def test_high_system_scores_higher_than_high_worker(self) -> None:
        system = Finding(
            layer="s", check="a", severity=Severity.HIGH,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        worker = Finding(
            layer="s", check="a", severity=Severity.HIGH,
            message="msg", trust_class=TrustClass.WORKER_ASSERTION,
        )
        assert effective_severity(system) > effective_severity(worker)

    def test_info_severity_scores_zero(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.INFO,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        assert effective_severity(f) == 0

    def test_medium_verified_llm_score(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.MEDIUM,
            message="msg", trust_class=TrustClass.VERIFIED_LLM,
        )
        assert effective_severity(f) == 50 * 2  # 100
