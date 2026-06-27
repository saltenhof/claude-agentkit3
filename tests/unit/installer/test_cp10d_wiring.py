"""Tests for the FK-50 CP 10d wiring in the installer (AG3-052 E5/E6).

Covers:
* the installer writes an EXPLICIT ``sonarqube`` stanza (available:true) for a
  code-producing project (E6 — no silent disable by omission);
* ``_run_cp10d_sonarqube`` is applicability-conditional and FAIL-CLOSED:
  available:false => SKIPPED; available:true without a working verification =>
  InstallationError (NO ``verification_deferred`` escape, E5); available:true
  with a failing probe => InstallationError (fail-closed abort);
* the PRODUCTIVE ``SonarClientScannerHarness`` is assembled from a
  ``sonar_client`` + ``sonar_scan_runner`` and drives the conformance steps.

Only the external HTTP boundary (``SonarClient``) and the operational scanner
runner are stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.integration_checkpoints import SelfTestScan
from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    ADMINISTER_ISSUES,
    CheckpointStatus,
)
from agentkit.backend.installer.runner import (
    InstallConfig,
    _build_project_yaml,
    _run_cp10d_sonarqube,
)
from agentkit.integration_clients.jenkins import JenkinsHttpResponse
from agentkit.integration_clients.sonar import SonarHttpResponse


def _config(root: Path) -> InstallConfig:
    return InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=root,
    )


def test_built_yaml_has_explicit_sonarqube_stanza() -> None:
    """E6 + Design-Decision: code-producing scaffold writes an EXPLICIT stanza.

    AG3-052 Design-Decision (FK-03 §3): the scaffold DEFAULT for a
    code-producing project is ``available: true`` (+ endpoint) — the green
    gate is a mandatory runtime dependency, not auto-disabled. ``available:
    false`` is a CONSCIOUS opt-out (``sonarqube_available=False``), never the
    install default. The stanza is always PRESENT and explicit (E6).
    """
    data = _build_project_yaml(_config(Path("/tmp")))
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    sonar = pipeline["sonarqube"]
    assert isinstance(sonar, dict)
    assert "available" in sonar  # explicit, not omitted (E6)
    # Design-Decision: default is available:true (FK-03 §3), with endpoint.
    assert sonar["available"] is True
    assert sonar["enabled"] is True
    assert sonar["base_url"] == "http://localhost:9901"
    assert sonar["token_env"] == "SONARQUBE_TOKEN"
    # ERROR-B: scanner_version is a mandatory attestation binding (FK-33 §33.6.3).
    assert sonar["scanner_version"] == "5.0.1"


def test_built_yaml_conscious_optout_writes_available_false() -> None:
    """The conscious opt-out (``sonarqube_available=False``) is explicit false.

    FK-03 §3: ``available: false`` is a deliberate operator decision (gate
    not applicable). The cross-field rule needs no base_url/token_env then, so
    the explicit opt-out omits the endpoint keys.
    """
    config = InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=Path("/tmp"),
        sonarqube_available=False,
    )
    data = _build_project_yaml(config)
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    sonar = pipeline["sonarqube"]
    assert isinstance(sonar, dict)
    assert sonar["available"] is False
    assert sonar["enabled"] is False
    assert "base_url" not in sonar
    assert "token_env" not in sonar


def test_cp10d_skipped_when_available_false(tmp_path: Path) -> None:
    config = _config(tmp_path)
    yaml_data = {"pipeline": {"sonarqube": {"available": False, "enabled": False}}}
    result = _run_cp10d_sonarqube(config, tmp_path, yaml_data)
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def _available_true_yaml() -> dict[str, object]:
    """A project.yaml with an EXPLICIT available:true sonarqube stanza."""
    return {
        "pipeline": {
            "sonarqube": {
                "available": True,
                "enabled": True,
                "base_url": "http://sonar:9901",
                "token_env": "SONARQUBE_TOKEN",
                "scanner_version": "5.0.1",
                "quality_gate": {"default_profile": "sonar/ak3-default-gate.json"},
            }
        }
    }


def test_cp10d_skipped_when_conscious_optout_scaffold(tmp_path: Path) -> None:
    """A conscious opt-out scaffold (available:false) => CP 10d SKIPPED.

    AG3-052 Design-Decision: ``available: false`` is a deliberate operator
    opt-out (``sonarqube_available=False``); CP 10d then SKIPs (declared
    not-applicable), no Sonar collaborators required.
    """
    config = InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=tmp_path,
        sonarqube_available=False,
    )
    yaml_data = _build_project_yaml(config)
    result = _run_cp10d_sonarqube(config, tmp_path, yaml_data)
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_cp10d_aborts_when_scaffold_default_available_true_without_sonar(
    tmp_path: Path,
) -> None:
    """The scaffold DEFAULT (available:true) with no reachable Sonar => abort.

    AG3-052 Design-Decision (accepted consequence, FAIL-CLOSED): a fresh
    code-producing install declares ``available: true`` (FK-03 §3); with no
    injected ``sonar_client`` CP 10d FAILs closed and aborts — the GEWOLLTE
    prompt to provision Sonar OR consciously set ``available: false``.
    """
    config = _config(tmp_path)  # default sonarqube_available=True, no client
    yaml_data = _build_project_yaml(config)
    with pytest.raises(InstallationError, match="CP 10d"):
        _run_cp10d_sonarqube(config, tmp_path, yaml_data)


def test_cp10d_aborts_when_available_true_without_client(tmp_path: Path) -> None:
    """E5: available:true but NO Sonar client => FAIL-CLOSED abort (no defer)."""
    config = _config(tmp_path)  # no sonar_client injected
    with pytest.raises(InstallationError, match="CP 10d"):
        _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())


@dataclass
class _StubClient:
    """Stub HTTP boundary for CP 10d probes + the productive harness ops."""

    version: str = "26.4"
    branches: tuple[str, ...] = ("main", "ak3-selftest-branch")
    accepted_issue_keys: tuple[str, ...] = ()
    gate_status: str = "OK"
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    transitioned: list[tuple[str, str]] = field(default_factory=list)

    def system_status(self) -> SonarHttpResponse:
        return SonarHttpResponse(status_code=200, json_body={"version": self.version})

    def installed_plugins(self) -> SonarHttpResponse:
        return SonarHttpResponse(
            status_code=200,
            json_body={"plugins": [{"key": "communityBranchPlugin", "version": "26.5.0"}]},
        )

    def create_project(self, project_key: str, name: str) -> SonarHttpResponse:
        del name
        self.created.append(project_key)
        return SonarHttpResponse(status_code=200, json_body={})

    def delete_project(self, project_key: str) -> SonarHttpResponse:
        self.deleted.append(project_key)
        return SonarHttpResponse(status_code=200, json_body={})

    def project_branches(self, project_key: str) -> SonarHttpResponse:
        del project_key
        return SonarHttpResponse(
            status_code=200,
            json_body={"branches": [{"name": n} for n in self.branches]},
        )

    def search_issues(self, params: object) -> SonarHttpResponse:
        # The harness only queries Accepted issues; return the canned set.
        issues = [{"key": k} for k in self.accepted_issue_keys]
        return SonarHttpResponse(status_code=200, json_body={"issues": issues})

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200, json_body={"projectStatus": {"status": self.gate_status}}
        )

    def ce_task(self, ce_task_id: str) -> SonarHttpResponse:
        del ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={"task": {"status": "SUCCESS", "analysisId": "AX-CI"}},
        )

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        self.transitioned.append((issue_key, transition))
        return SonarHttpResponse(status_code=200, json_body={})


def _green_scan_runner(project_key: str, branch: str) -> SelfTestScan:
    """Stubbed operational scanner: a green scan with no issues (OOS boundary)."""
    del project_key
    return SelfTestScan(analysis_id=f"AX-{branch}", branch=branch, issue_keys=())


@dataclass
class _StubJenkins:
    def trigger_build(
        self, pipeline: str, *, parameters: dict[str, str]
    ) -> JenkinsHttpResponse:
        del pipeline, parameters
        return JenkinsHttpResponse(
            status_code=201,
            headers={"location": "http://jenkins/queue/item/7/"},
        )

    def queue_item(self, queue_id: int) -> JenkinsHttpResponse:
        del queue_id
        return JenkinsHttpResponse(
            status_code=200, json_body={"executable": {"number": 11}}
        )

    def build_status(self, pipeline: str, build_number: int) -> JenkinsHttpResponse:
        del pipeline, build_number
        return JenkinsHttpResponse(
            status_code=200, json_body={"building": False, "result": "SUCCESS"}
        )

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> JenkinsHttpResponse:
        del pipeline, build_number, artifact_path
        return JenkinsHttpResponse(
            status_code=200,
            text_body="projectKey=ak3-selftest\nceTaskId=ce-1\n",
        )


def _profile(root: Path) -> None:
    profile = root / "sonar" / "ak3-default-gate.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("{}", encoding="utf-8")


def test_cp10d_passes_when_available_true_and_probes_ok(tmp_path: Path) -> None:
    _profile(tmp_path)
    config = InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=tmp_path,
        sonar_client=_StubClient(),  # type: ignore[arg-type]
        sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
        sonar_branch_plugin_self_test=lambda _client: True,
    )
    result = _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())
    assert result.status == CheckpointStatus.PASS


def test_cp10d_aborts_install_when_applicable_check_fails(tmp_path: Path) -> None:
    _profile(tmp_path)
    config = InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=tmp_path,
        sonar_client=_StubClient(version="9.9"),  # too low => FAILED
        sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
        sonar_branch_plugin_self_test=lambda _client: True,
    )
    with pytest.raises(InstallationError, match="CP 10d"):
        _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())


def test_cp10d_skipped_when_no_stanza(tmp_path: Path) -> None:
    """A non-code-producing scaffold (no sonarqube stanza) => SKIP."""
    result = _run_cp10d_sonarqube(_config(tmp_path), tmp_path, {"pipeline": {}})
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


class TestProductiveHarnessWiring:
    """E5: the productive CP10d self-test harness is assembled + driven."""

    def test_cp10d_passes_via_jenkins_harness(self, tmp_path: Path) -> None:
        """client + ci_client => CP10d uses Jenkins, not a local scanner."""
        _profile(tmp_path)
        client = _StubClient()
        config = InstallConfig(
            project_key="acme",
            project_name="Acme",
            project_root=tmp_path,
            sonar_client=client,  # type: ignore[arg-type]
            sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
            ci_client=_StubJenkins(),  # type: ignore[arg-type]
            ci_pipeline="ak3-pre-merge",
        )
        result = _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())
        assert result.status == CheckpointStatus.PASS

    def test_cp10d_passes_via_productive_harness(self, tmp_path: Path) -> None:
        """Explicit scan_runner remains a dev/test fallback."""
        _profile(tmp_path)
        client = _StubClient()
        config = InstallConfig(
            project_key="acme",
            project_name="Acme",
            project_root=tmp_path,
            sonar_client=client,  # type: ignore[arg-type]
            sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
            sonar_scan_runner=_green_scan_runner,
            # NO sonar_branch_plugin_self_test: the installer must assemble the
            # productive SonarClientScannerHarness from client + scan_runner.
        )
        result = _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())
        assert result.status == CheckpointStatus.PASS
        # The productive harness actually provisioned + cleaned up the project.
        assert client.created == ["ak3-branch-plugin-conformance-selftest"]
        assert client.deleted == ["ak3-branch-plugin-conformance-selftest"]

    def test_cp10d_aborts_when_harness_branch_invisible(self, tmp_path: Path) -> None:
        """A non-conformant plugin (branch not visible) => fail-closed abort."""
        _profile(tmp_path)
        client = _StubClient(branches=("main",))  # branch scan not visible
        config = InstallConfig(
            project_key="acme",
            project_name="Acme",
            project_root=tmp_path,
            sonar_client=client,  # type: ignore[arg-type]
            sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
            sonar_scan_runner=_green_scan_runner,
        )
        with pytest.raises(InstallationError, match="CP 10d"):
            _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())

    def test_cp10d_aborts_when_only_client_without_scan_runner(
        self, tmp_path: Path
    ) -> None:
        """client but no scan_runner and no self-test => cannot verify => abort."""
        _profile(tmp_path)
        config = InstallConfig(
            project_key="acme",
            project_name="Acme",
            project_root=tmp_path,
            sonar_client=_StubClient(),  # type: ignore[arg-type]
            sonar_token_permissions=frozenset({ADMINISTER_ISSUES}),
            # no scan_runner, no pre-built self-test
        )
        with pytest.raises(InstallationError, match="CP 10d"):
            _run_cp10d_sonarqube(config, tmp_path, _available_true_yaml())
