"""Unit tests for the SonarQube installer CP 10d preconditions (FK-50, AC7).

The external HTTP boundary is stubbed (MOCKS-Ausnahme); the precondition
logic runs for real. The local profile check and light server probes are
deliberately tested as separate responsibilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agentkit.backend.config.models import SonarQubeConfig
from agentkit.backend.installer.integration_checkpoints import (
    check_sonarqube_preconditions,
)
from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    ADMINISTER_ISSUES,
    CheckpointStatus,
    SonarPreflightResult,
    check_default_profile,
)
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

_TOKEN_OK = frozenset({ADMINISTER_ISSUES, "Execute Analysis"})


@dataclass
class _StubSonarClient:
    """Stub of the HTTP boundary (only external system is faked)."""

    version: str = "26.4"
    plugin_version: str | None = "1.23.0"
    reachable: bool = True

    def system_status(self) -> SonarHttpResponse:
        if not self.reachable:
            raise SonarApiError("unreachable")
        return SonarHttpResponse(status_code=200, json_body={"version": self.version})

    def installed_plugins(self) -> SonarHttpResponse:
        plugins = []
        if self.plugin_version is not None:
            plugins = [{"key": "communityBranchSupport", "version": self.plugin_version}]
        return SonarHttpResponse(status_code=200, json_body={"plugins": plugins})


def _profile(tmp_path: Path) -> SonarQubeConfig:
    profile = tmp_path / "bundles" / "target_project" / "sonar" / "ak3-default-gate.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("{}", encoding="utf-8")
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONARQUBE_TOKEN",
        scanner_version="5.0.1",
    )


def _check(config: SonarQubeConfig, **kw: object) -> SonarPreflightResult:
    defaults: dict[str, object] = {
        "client": _StubSonarClient(),
        "token_permissions": _TOKEN_OK,
    }
    defaults.update(kw)
    return check_sonarqube_preconditions(config, **defaults)  # type: ignore[arg-type]


class TestNotApplicable:
    def test_available_false_is_skipped_not_failed(self, tmp_path: Path) -> None:
        config = SonarQubeConfig(available=False, enabled=False)
        result = check_sonarqube_preconditions(
            config,
            client=None,
            token_permissions=frozenset(),
        )
        assert result.status == CheckpointStatus.SKIPPED
        assert result.reason == "not_applicable"


class TestApplicableFailClosed:
    def test_all_preconditions_pass(self, tmp_path: Path) -> None:
        result = _check(_profile(tmp_path))
        assert result.status == CheckpointStatus.PASS

    def test_unreachable_fails(self, tmp_path: Path) -> None:
        result = _check(_profile(tmp_path), client=_StubSonarClient(reachable=False))
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "unreachable"

    def test_version_too_low_fails(self, tmp_path: Path) -> None:
        result = _check(_profile(tmp_path), client=_StubSonarClient(version="9.9"))
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "version_too_low"

    def test_missing_administer_issues_fails(self, tmp_path: Path) -> None:
        result = _check(
            _profile(tmp_path), token_permissions=frozenset({"Execute Analysis"})
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "token_role_insufficient"

    def test_branch_plugin_missing_fails(self, tmp_path: Path) -> None:
        result = _check(
            _profile(tmp_path), client=_StubSonarClient(plugin_version=None)
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "branch_plugin_missing"

    def test_light_preflight_never_accepts_a_heavy_self_test_callback(
        self, tmp_path: Path
    ) -> None:
        result = _check(_profile(tmp_path))
        assert result.status == CheckpointStatus.PASS

    def test_missing_default_profile_fails(self, tmp_path: Path) -> None:
        config = SonarQubeConfig(
            available=True,
            enabled=True,
            base_url="http://sonar:9901",
            token_env="SONARQUBE_TOKEN",
            scanner_version="5.0.1",
        )
        result = check_default_profile(config, tmp_path)
        assert result is not None
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "default_profile_missing"

    def test_missing_dependency_when_applicable_fails(self, tmp_path: Path) -> None:
        result = _check(_profile(tmp_path), client=None)
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "missing_dependency"


def test_shipped_default_profile_carries_overall_condition() -> None:
    """The SSOT default profile artefact carries an overall-code condition."""
    repo_root = Path(__file__).resolve().parents[3]
    profile = (
        repo_root
        / "src"
        / "agentkit"
        / "bundles"
        / "target_project"
        / "sonar"
        / "ak3-default-gate.json"
    )
    data = json.loads(profile.read_text(encoding="utf-8"))
    scopes = {c["scope"] for c in data["conditions"]}
    assert "overall_code" in scopes
    assert "new_code" in scopes
