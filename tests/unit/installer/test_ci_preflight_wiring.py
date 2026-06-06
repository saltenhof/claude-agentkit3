"""Tests for the AG3-056 CI (Jenkins) preflight wiring in the installer (FIX-5).

Mirrors the CP 10d wiring discipline. Proves SKIPPED / FAILED / PASS are
actually exercised THROUGH the installer runner (``_run_ci_preflight``):

* the installer writes an EXPLICIT ``ci`` stanza (available:true) for a
  code-producing project, and an explicit ``available: false`` for the
  conscious opt-out;
* ``available: false`` => SKIPPED (declared not-applicable);
* ``available: true`` without a ``ci_client`` => InstallationError (fail-closed,
  no escape hatch — a real CI trigger must not be promised against an
  unverified Jenkins);
* ``available: true`` with a failing probe => InstallationError (abort);
* ``available: true`` with a working client => PASS.

Only the thin Jenkins HTTP client is stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agentkit.exceptions import InstallationError
from agentkit.installer.integration_checkpoints.ci_preflight import (
    CheckpointStatus,
    CiPreflightResult,
)
from agentkit.installer.registration import CheckpointStatus as RegCheckpointStatus
from agentkit.installer.runner import (
    _CI_CHECKPOINT_ID,
    InstallConfig,
    _build_project_yaml,
    _ci_cp_to_checkpoint_result,
    _run_ci_preflight,
)


def _config(root: Path, **kwargs: object) -> InstallConfig:
    return InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=root,
        **kwargs,  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class _Resp:
    json_body: dict[str, object]


@dataclass
class _StubJenkins:
    whoami_body: dict[str, object] = field(default_factory=lambda: {"id": "ak3"})
    job_body: dict[str, object] = field(default_factory=lambda: {"name": "ak3"})
    raise_on: str | None = None

    def whoami(self) -> _Resp:
        if self.raise_on == "whoami":
            from agentkit.integrations.jenkins import JenkinsApiError

            raise JenkinsApiError("unreachable")
        return _Resp(self.whoami_body)

    def job_exists(self, pipeline: str) -> _Resp:
        del pipeline
        return _Resp(self.job_body)


def _available_true_yaml() -> dict[str, object]:
    return {
        "pipeline": {
            "ci": {
                "available": True,
                "enabled": True,
                "base_url": "http://jenkins:8080",
                "token_env": "JENKINS_TOKEN",
                "pipeline": "ak3-pre-merge",
            }
        }
    }


def test_built_yaml_has_explicit_ci_stanza() -> None:
    """A code-producing scaffold writes an EXPLICIT available:true ci stanza."""
    data = _build_project_yaml(_config(Path("/tmp")))
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    ci = pipeline["ci"]
    assert isinstance(ci, dict)
    assert ci["available"] is True
    assert ci["enabled"] is True
    assert ci["base_url"] == "http://localhost:8080"
    assert ci["token_env"] == "JENKINS_TOKEN"
    assert ci["pipeline"] == "ak3-pre-merge"


def test_built_yaml_conscious_optout_writes_available_false() -> None:
    config = _config(Path("/tmp"), ci_available=False)
    data = _build_project_yaml(config)
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    ci = pipeline["ci"]
    assert isinstance(ci, dict)
    assert ci["available"] is False
    assert ci["enabled"] is False
    assert "base_url" not in ci
    assert "pipeline" not in ci


def test_ci_preflight_skipped_when_available_false(tmp_path: Path) -> None:
    yaml_data = {"pipeline": {"ci": {"available": False, "enabled": False}}}
    result = _run_ci_preflight(_config(tmp_path), yaml_data)
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_ci_preflight_skipped_when_conscious_optout_scaffold(tmp_path: Path) -> None:
    config = _config(tmp_path, ci_available=False)
    yaml_data = _build_project_yaml(config)
    result = _run_ci_preflight(config, yaml_data)
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_ci_preflight_skipped_when_no_stanza(tmp_path: Path) -> None:
    result = _run_ci_preflight(_config(tmp_path), {"pipeline": {}})
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_ci_preflight_aborts_when_available_true_without_client(tmp_path: Path) -> None:
    """available:true but NO ci_client => FAIL-CLOSED abort (no escape)."""
    with pytest.raises(InstallationError, match="CI .Jenkins. precondition FAILED"):
        _run_ci_preflight(_config(tmp_path), _available_true_yaml())


def test_ci_preflight_aborts_when_scaffold_default_without_jenkins(
    tmp_path: Path,
) -> None:
    """The scaffold default (ci.available:true) with no client => abort."""
    config = _config(tmp_path)  # default ci_available=True, no ci_client
    yaml_data = _build_project_yaml(config)
    with pytest.raises(InstallationError, match="CI .Jenkins. precondition FAILED"):
        _run_ci_preflight(config, yaml_data)


def test_ci_preflight_aborts_when_probe_fails(tmp_path: Path) -> None:
    config = _config(tmp_path, ci_client=_StubJenkins(raise_on="whoami"))
    with pytest.raises(InstallationError, match="CI .Jenkins. precondition FAILED"):
        _run_ci_preflight(config, _available_true_yaml())


def test_ci_preflight_passes_when_available_true_and_probes_ok(tmp_path: Path) -> None:
    config = _config(tmp_path, ci_client=_StubJenkins())
    result = _run_ci_preflight(config, _available_true_yaml())
    assert result.status == CheckpointStatus.PASS


class TestCiCheckpointRecording:
    """AG3-056 WARNING-2: the CI preflight result is recorded in
    ``checkpoint_results`` for ALL three states (PASS / SKIPPED / FAILED),
    mirroring the Sonar CP recording."""

    def test_pass_is_recorded_as_pass_checkpoint(self) -> None:
        cp = _ci_cp_to_checkpoint_result(
            CiPreflightResult(
                status=CheckpointStatus.PASS,
                details=("reachable; token authenticated; pipeline exists",),
            )
        )
        assert cp.checkpoint == _CI_CHECKPOINT_ID
        assert cp.status is RegCheckpointStatus.PASS
        assert cp.detail is not None

    def test_skipped_is_recorded_with_reason(self) -> None:
        cp = _ci_cp_to_checkpoint_result(
            CiPreflightResult(
                status=CheckpointStatus.SKIPPED, reason="not_applicable"
            )
        )
        assert cp.checkpoint == _CI_CHECKPOINT_ID
        assert cp.status is RegCheckpointStatus.SKIPPED
        # FK-50 §50.4: SKIPPED carries a machine-readable reason.
        assert cp.reason == "not_applicable"

    def test_failed_is_recorded_with_reason(self) -> None:
        cp = _ci_cp_to_checkpoint_result(
            CiPreflightResult(
                status=CheckpointStatus.FAILED,
                reason="unreachable",
                details=("jenkins down",),
            )
        )
        assert cp.checkpoint == _CI_CHECKPOINT_ID
        assert cp.status is RegCheckpointStatus.FAILED
        assert cp.reason == "unreachable"
        assert cp.detail == "jenkins down"
