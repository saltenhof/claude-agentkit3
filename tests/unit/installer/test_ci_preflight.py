"""Unit tests for the CI (Jenkins) installer preflight (AG3-056 §4.2 / AC7).

Proves SKIPPED (declared absence) vs FAILED (configured-but-unreachable /
misconfigured) vs PASS. Only the thin Jenkins HTTP client is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.backend.config.models import JenkinsConfig
from agentkit.backend.installer.integration_checkpoints.ci_preflight import (
    CheckpointStatus,
    check_ci_preconditions,
)
from agentkit.integration_clients.jenkins import JenkinsApiError


@dataclass
class _FakeJenkins:
    whoami_body: dict[str, object] = field(default_factory=lambda: {"id": "ak3"})
    job_body: dict[str, object] = field(default_factory=lambda: {"name": "ak3"})
    raise_on: str | None = None

    def whoami(self) -> _Resp:
        if self.raise_on == "whoami":
            raise JenkinsApiError("unreachable")
        return _Resp(self.whoami_body)

    def job_exists(self, pipeline: str) -> _Resp:
        del pipeline
        if self.raise_on == "job_exists":
            raise JenkinsApiError("HTTP 404")
        return _Resp(self.job_body)


@dataclass(frozen=True)
class _Resp:
    json_body: dict[str, object]


def _available_ci() -> JenkinsConfig:
    return JenkinsConfig(
        available=True,
        enabled=True,
        base_url="http://jenkins:8080",
        token_env="JENKINS_TOKEN",
        pipeline="ak3-pre-merge",
    )


class TestApplicability:
    def test_unavailable_skips(self) -> None:
        cfg = JenkinsConfig(available=False, enabled=False)
        result = check_ci_preconditions(cfg, client=None)
        assert result.status == CheckpointStatus.SKIPPED
        assert result.reason == "not_applicable"

    def test_available_without_client_fails(self) -> None:
        result = check_ci_preconditions(_available_ci(), client=None)
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "missing_dependency"


class TestApplicableProbes:
    def test_all_green_passes(self) -> None:
        result = check_ci_preconditions(
            _available_ci(),
            client=_FakeJenkins(),  # type: ignore[arg-type]
        )
        assert result.status == CheckpointStatus.PASS

    def test_unreachable_fails_closed(self) -> None:
        result = check_ci_preconditions(
            _available_ci(),
            client=_FakeJenkins(raise_on="whoami"),  # type: ignore[arg-type]
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "unreachable"

    def test_invalid_token_fails(self) -> None:
        result = check_ci_preconditions(
            _available_ci(),
            client=_FakeJenkins(whoami_body={}),  # type: ignore[arg-type]
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "token_invalid"

    def test_missing_pipeline_fails(self) -> None:
        result = check_ci_preconditions(
            _available_ci(),
            client=_FakeJenkins(job_body={}),  # type: ignore[arg-type]
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "pipeline_missing"

    def test_pipeline_404_fails_closed(self) -> None:
        result = check_ci_preconditions(
            _available_ci(),
            client=_FakeJenkins(raise_on="job_exists"),  # type: ignore[arg-type]
        )
        assert result.status == CheckpointStatus.FAILED
        assert result.reason == "unreachable"
