"""Tests for trust classification and effective severity computation."""

from __future__ import annotations

from agentkit.backend.verify_system.policy_engine.trust import TRUST_WEIGHT, effective_severity
from agentkit.backend.verify_system.protocols import Finding, Severity, TrustClass


class TestTrustWeight:
    """TRUST_WEIGHT mapping values."""

    def test_system_has_highest_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.SYSTEM] == 3

    def test_verified_llm_has_middle_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.VERIFIED_LLM] == 2

    def test_worker_assertion_has_lowest_weight(self) -> None:
        assert TRUST_WEIGHT[TrustClass.WORKER_ASSERTION] == 1

    def test_system_weight_greater_than_worker(self) -> None:
        assert (
            TRUST_WEIGHT[TrustClass.SYSTEM]
            > TRUST_WEIGHT[TrustClass.WORKER_ASSERTION]
        )


class TestEffectiveSeverity:
    """effective_severity computation tests using BLOCKING/MAJOR/MINOR."""

    def test_blocking_system_scores_highest(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.BLOCKING,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        assert effective_severity(f) == 100 * 3  # 300

    def test_blocking_worker_scores_lower_than_blocking_system(self) -> None:
        system = Finding(
            layer="s", check="a", severity=Severity.BLOCKING,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        worker = Finding(
            layer="s", check="a", severity=Severity.BLOCKING,
            message="msg", trust_class=TrustClass.WORKER_ASSERTION,
        )
        assert effective_severity(system) > effective_severity(worker)

    def test_major_system_scores_higher_than_major_worker(self) -> None:
        system = Finding(
            layer="s", check="a", severity=Severity.MAJOR,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        worker = Finding(
            layer="s", check="a", severity=Severity.MAJOR,
            message="msg", trust_class=TrustClass.WORKER_ASSERTION,
        )
        assert effective_severity(system) > effective_severity(worker)

    def test_minor_score(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.MINOR,
            message="msg", trust_class=TrustClass.SYSTEM,
        )
        # MINOR score = 20, trust SYSTEM weight = 3, total = 60.
        assert effective_severity(f) == 60

    def test_major_verified_llm_score(self) -> None:
        f = Finding(
            layer="s", check="a", severity=Severity.MAJOR,
            message="msg", trust_class=TrustClass.VERIFIED_LLM,
        )
        # MAJOR score = 50, VERIFIED_LLM weight = 2, total = 100.
        assert effective_severity(f) == 100
