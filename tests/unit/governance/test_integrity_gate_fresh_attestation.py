"""Dim-9 fresh-attestation verification + drift tests (AG3-053, FK-35 §35.2.4a).

These pin the Closure pre-merge path where the IntegrityGate VERIFIES the FRESH
attestation the AG3-056 scan produced (``IntegrityGate.evaluate(...,
fresh_attestation=...)``) instead of re-resolving via the worktree. The fresh
path is exercised through the REAL ``verify_fresh_attestation`` /
``detect_version_drift`` (no live Sonar -- the attestation is a real
``SonarAttestation`` value object). Negative paths (stale binding, red QG,
version drift, missing config) all fail closed with ``SONAR_NOT_GREEN``.
"""

from __future__ import annotations

from agentkit.config.models import (
    SonarQubeBranchPluginConfig,
    SonarQubeConfig,
    SonarQubePluginsConfig,
)
from agentkit.governance.integrity_gate import DimensionResult, IntegrityDimension
from agentkit.governance.integrity_gate.dim9_drift import detect_version_drift
from agentkit.governance.integrity_gate.dim9_sonar import (
    SONAR_NOT_GREEN,
    FreshAttestation,
    verify_fresh_attestation,
)
from agentkit.verify_system.sonarqube_gate import (
    SonarApplicability,
    SonarGateOutcome,
)
from agentkit.verify_system.sonarqube_gate.attestation import (
    ATTESTATION_STATUS_READ,
    SonarAttestation,
)

_CANDIDATE = "1111candidatecommit1111"


def _green_outcome() -> SonarGateOutcome:
    """A FULL AG3-052 green gate outcome (the impl-phase green truth, FIX-1)."""
    return SonarGateOutcome(
        applicability=SonarApplicability.APPLICABLE,
        passed=True,
        gate_status="sonarqube_gate_passed",
    )


def _red_outcome(reason: str = "red_gate: ERROR") -> SonarGateOutcome:
    """A FULL AG3-052 red gate outcome (post-apply re-read found it not green)."""
    return SonarGateOutcome(
        applicability=SonarApplicability.APPLICABLE,
        passed=False,
        gate_status="failed",
        failure_reason=reason,
    )


def _config(
    *,
    available: bool = True,
    min_version: str = "26.4",
    plugin_min: str = "1.23.0",
    scanner_version: str | None = "5.0.1",
) -> SonarQubeConfig:
    return SonarQubeConfig(
        available=available,
        enabled=available,
        base_url="https://sonar.example" if available else None,
        token_env="SONAR_TOKEN" if available else None,
        min_version=min_version,
        plugins=SonarQubePluginsConfig(
            community_branch=SonarQubeBranchPluginConfig(min_version=plugin_min)
        ),
        scanner_version=scanner_version if available else None,
    )


def _attestation(
    *,
    commit_sha: str = _CANDIDATE,
    last_analyzed_revision: str = _CANDIDATE,
    quality_gate_status: str = "OK",
    sonarqube_version: str = "26.4",
    branch_plugin_version: str = "1.23.0",
    scanner_version: str = "5.0.1",
) -> SonarAttestation:
    return SonarAttestation(
        commit_sha=commit_sha,
        tree_hash="2222tree2222",
        analysis_id="analysis-001",
        ce_task_id="ce-001",
        quality_gate_status=quality_gate_status,
        quality_gate_hash="qg-hash",
        quality_profile_hash="qp-hash",
        analysis_scope_hash="scope-hash",
        new_code_definition="previous_version",
        exception_ledger_hash="ledger-hash",
        last_analyzed_revision=last_analyzed_revision,
        sonarqube_version=sonarqube_version,
        branch_plugin_version=branch_plugin_version,
        scanner_version=scanner_version,
        status=ATTESTATION_STATUS_READ,
    )


def _fresh(
    attestation: SonarAttestation,
    *,
    expected: str = _CANDIDATE,
    config: SonarQubeConfig | None = None,
    gate_outcome: SonarGateOutcome | None = None,
) -> FreshAttestation:
    return FreshAttestation(
        attestation=attestation,
        expected_main_revision=expected,
        config=config or _config(),
        gate_outcome=gate_outcome if gate_outcome is not None else _green_outcome(),
    )


class TestVerifyFreshAttestation:
    def test_green_bound_no_drift_passes(self) -> None:
        result = verify_fresh_attestation(_fresh(_attestation()))
        assert isinstance(result, DimensionResult)
        assert result.dimension is IntegrityDimension.SONARQUBE_GREEN
        assert result.passed

    def test_stale_binding_fails_closed(self) -> None:
        """A green QG for a DIFFERENT analysed revision is drift scan<->merge."""
        att = _attestation(last_analyzed_revision="9999other9999")
        result = verify_fresh_attestation(_fresh(att))
        assert not result.passed
        assert result.failure_reason == SONAR_NOT_GREEN
        assert "not bound" in result.detail

    def test_red_gate_outcome_fails_closed(self) -> None:
        """FIX-1: the green verdict is the FULL AG3-052 gate outcome, not the raw
        pre-apply quality_gate_status. A red gate outcome fails closed even when
        the attestation's pre-apply ``quality_gate_status`` reads OK (the gate
        ran the post-apply re-read + Broken-Window + ledger reconcile)."""
        att = _attestation(quality_gate_status="OK")
        result = verify_fresh_attestation(
            _fresh(att, gate_outcome=_red_outcome("red_gate: overall_open_issues=3"))
        )
        assert not result.passed
        assert result.failure_reason == SONAR_NOT_GREEN
        assert "gate not green" in result.detail

    def test_missing_gate_outcome_fails_closed(self) -> None:
        """FIX-1: a supplied fresh attestation with no AG3-052 gate outcome is an
        unverifiable green -> fail-closed (no raw quality_gate_status shortcut)."""
        result = verify_fresh_attestation(
            FreshAttestation(
                attestation=_attestation(),
                expected_main_revision=_CANDIDATE,
                config=_config(),
                gate_outcome=None,
            )
        )
        assert not result.passed
        assert result.failure_reason == SONAR_NOT_GREEN
        assert "without an AG3-052 gate outcome" in result.detail

    def test_version_drift_fails_closed(self) -> None:
        """A scanner version != the FK-03 pin is config/version drift (item 5)."""
        att = _attestation(scanner_version="4.9.0")
        result = verify_fresh_attestation(_fresh(att))
        assert not result.passed
        assert result.failure_reason == SONAR_NOT_GREEN
        assert "scanner_version drift" in result.detail

    def test_missing_config_fails_closed(self) -> None:
        """A fresh attestation with no FK-03 config cannot verify drift -> FAIL."""
        result = verify_fresh_attestation(
            FreshAttestation(
                attestation=_attestation(),
                expected_main_revision=_CANDIDATE,
                config=None,
                gate_outcome=_green_outcome(),
            )
        )
        assert not result.passed
        assert result.failure_reason == SONAR_NOT_GREEN
        assert "without an FK-03 sonarqube config" in result.detail


class TestDetectVersionDrift:
    def test_no_drift_when_versions_meet_pins(self) -> None:
        drift = detect_version_drift(_attestation(), _config())
        assert not drift.drifted

    def test_sonarqube_below_minimum_drifts(self) -> None:
        drift = detect_version_drift(
            _attestation(sonarqube_version="25.1"), _config(min_version="26.4")
        )
        assert drift.drifted
        assert "sonarqube_version below minimum" in (drift.reason or "")

    def test_branch_plugin_below_minimum_drifts(self) -> None:
        drift = detect_version_drift(
            _attestation(branch_plugin_version="1.22.0"),
            _config(plugin_min="1.23.0"),
        )
        assert drift.drifted
        assert "branch_plugin_version below minimum" in (drift.reason or "")

    def test_scanner_version_exact_mismatch_drifts(self) -> None:
        drift = detect_version_drift(
            _attestation(scanner_version="5.0.2"), _config(scanner_version="5.0.1")
        )
        assert drift.drifted
        assert "scanner_version drift" in (drift.reason or "")

    def test_higher_than_minimum_is_not_drift(self) -> None:
        """A SonarQube version ABOVE the minimum is fine (minimum, not exact)."""
        drift = detect_version_drift(
            _attestation(sonarqube_version="27.0"), _config(min_version="26.4")
        )
        assert not drift.drifted

    def test_unparseable_version_fails_closed(self) -> None:
        drift = detect_version_drift(
            _attestation(sonarqube_version="not-a-version"), _config()
        )
        assert drift.drifted
        assert "unparseable" in (drift.reason or "")
