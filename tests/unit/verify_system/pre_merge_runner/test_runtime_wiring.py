"""Unit tests for the pre-merge runner wiring (AG3-056 §2.1.4 applicability).

Distinguishes a deliberate declared absence (``ci.available == false`` =>
``None``, a declared skip) from configured-but-unreachable/misconfigured
(``ci.available == true`` but no resolvable endpoint/token => fail-closed
``PreMergeRunnerUnavailableError``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.backend.config.models import JenkinsConfig, SonarQubeConfig
from agentkit.backend.verify_system.pre_merge_runner.build_test_runner import CiBuildTestRunner
from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
    PreMergeRunnerUnavailableError,
    build_build_test_runner,
    build_pre_merge_runners,
)
from agentkit.backend.verify_system.pre_merge_runner.scan_runner import CiSonarScanRunner

_REPO = Path("/repo/candidate")


def _ci(*, available: bool = True) -> JenkinsConfig:
    if not available:
        return JenkinsConfig(available=False, enabled=False)
    return JenkinsConfig(
        available=True,
        enabled=True,
        base_url="http://jenkins:8080",
        token_env="JENKINS_TOKEN_TEST",
        pipeline="ak3-pre-merge",
    )


def _sonar(*, available: bool = True) -> SonarQubeConfig:
    if not available:
        return SonarQubeConfig(available=False, enabled=False)
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONAR_TOKEN_TEST",
        scanner_version="5.0.1",
    )


class TestDeclaredAbsence:
    def test_no_ci_stanza_returns_none(self) -> None:
        assert build_pre_merge_runners(None, _sonar(), _REPO) is None

    def test_ci_unavailable_returns_none(self) -> None:
        assert build_pre_merge_runners(_ci(available=False), _sonar(), _REPO) is None


class TestApplicableWiring:
    def test_available_builds_productive_runners(self) -> None:
        runners = build_pre_merge_runners(
            _ci(), _sonar(), _REPO, ci_token="jtok", sonar_token="stok"
        )
        assert runners is not None
        assert isinstance(runners.scan, CiSonarScanRunner)
        assert isinstance(runners.build_test, CiBuildTestRunner)

    def test_both_facets_share_one_run_cache(self) -> None:
        """FIX-3: scan + build/test draw from the SAME single-run cache."""
        runners = build_pre_merge_runners(
            _ci(), _sonar(), _REPO, ci_token="jtok", sonar_token="stok"
        )
        assert runners is not None
        assert isinstance(runners.scan, CiSonarScanRunner)
        assert isinstance(runners.build_test, CiBuildTestRunner)
        assert runners.scan.run_cache is runners.build_test.run_cache

    def test_reads_tokens_from_env_when_not_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JENKINS_TOKEN_TEST", "jtok")
        monkeypatch.setenv("SONAR_TOKEN_TEST", "stok")
        runners = build_pre_merge_runners(_ci(), _sonar(), _REPO)
        assert runners is not None


class TestBuildTestOnlyRunner:
    """FIX-3: a CI-present, Sonar-declared-absent project gets a Build/Test runner.

    The additive ``build_build_test_runner`` lets the Closure barrier run
    Build/Test without a Sonar scan runner (SONAR_ABSENT applicability) -- a
    deliberate Sonar absence (FK-33 §33.6.5), not a misconfiguration.
    """

    def test_ci_present_builds_build_test_runner(self) -> None:
        runner = build_build_test_runner(_ci(), _REPO, ci_token="jtok")
        assert isinstance(runner, CiBuildTestRunner)

    def test_no_ci_stanza_returns_none(self) -> None:
        assert build_build_test_runner(None, _REPO) is None

    def test_ci_unavailable_returns_none(self) -> None:
        assert build_build_test_runner(_ci(available=False), _REPO) is None

    def test_ci_present_missing_token_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JENKINS_TOKEN_TEST", raising=False)
        with pytest.raises(PreMergeRunnerUnavailableError):
            build_build_test_runner(_ci(), _REPO)


class TestFailClosed:
    def test_available_but_missing_ci_token_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JENKINS_TOKEN_TEST", raising=False)
        with pytest.raises(PreMergeRunnerUnavailableError, match="token"):
            build_pre_merge_runners(_ci(), _sonar(), _REPO, sonar_token="stok")

    def test_available_ci_but_sonar_absent_fails_closed(self) -> None:
        """A CI-present code-producing project with Sonar absent is a
        misconfiguration for the pre-merge scan runner => fail-closed."""
        with pytest.raises(PreMergeRunnerUnavailableError, match="sonarqube"):
            build_pre_merge_runners(
                _ci(), _sonar(available=False), _REPO, ci_token="jtok"
            )

    def test_available_but_missing_sonar_token_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SONAR_TOKEN_TEST", raising=False)
        with pytest.raises(PreMergeRunnerUnavailableError, match="token"):
            build_pre_merge_runners(_ci(), _sonar(), _REPO, ci_token="jtok")
