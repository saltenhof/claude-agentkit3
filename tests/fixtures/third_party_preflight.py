"""Thin external-system boundary fakes for third-party mediation tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from agentkit.integration_clients.are.preflight import ArePreflightResponse
from agentkit.integration_clients.jenkins import JenkinsHttpResponse
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

if TYPE_CHECKING:
    from agentkit.backend.control_plane.third_party_models import (
        AreValidationConfig,
        CiValidationConfig,
        SonarValidationConfig,
    )
    from agentkit.integration_clients.are import ArePreflightClient
    from agentkit.integration_clients.jenkins import JenkinsClient
    from agentkit.integration_clients.sonar import SonarClient


@dataclass
class FakeThirdPartySonarClient:
    """Fake only the Sonar Web API boundary used by light and heavy logic."""

    branches: tuple[str, ...] = ("main", "ak3-selftest-branch")
    reachable: bool = True
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    issue_queries: list[dict[str, str]] = field(default_factory=list)

    def system_status(self) -> SonarHttpResponse:
        if not self.reachable:
            raise SonarApiError("sonar connection refused")
        return SonarHttpResponse(status_code=200, json_body={"version": "26.4"})

    def installed_plugins(self) -> SonarHttpResponse:
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "plugins": [
                    {"key": "communityBranchSupport", "version": "1.23.0"}
                ]
            },
        )

    def create_project(self, project_key: str, name: str) -> SonarHttpResponse:
        del name
        self.created.append(project_key)
        return SonarHttpResponse(status_code=200)

    def qualitygates_show(self, name: str) -> SonarHttpResponse:
        del name
        return SonarHttpResponse(status_code=200)

    def qualitygates_create(self, name: str) -> SonarHttpResponse:
        del name
        return SonarHttpResponse(status_code=200)

    def qualitygates_select(
        self, *, project_key: str, gate_name: str
    ) -> SonarHttpResponse:
        del project_key, gate_name
        return SonarHttpResponse(status_code=200)

    def delete_project(self, project_key: str) -> SonarHttpResponse:
        self.deleted.append(project_key)
        return SonarHttpResponse(status_code=200)

    def ce_task(self, ce_task_id: str) -> SonarHttpResponse:
        del ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={"task": {"status": "SUCCESS", "analysisId": "analysis-1"}},
        )

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200, json_body={"projectStatus": {"status": "OK"}}
        )

    def project_branches(self, project_key: str) -> SonarHttpResponse:
        del project_key
        return SonarHttpResponse(
            status_code=200,
            json_body={"branches": [{"name": branch} for branch in self.branches]},
        )

    def search_issues(self, params: dict[str, str]) -> SonarHttpResponse:
        self.issue_queries.append(params)
        branch = params.get("branch", "main")
        return SonarHttpResponse(
            status_code=200,
            json_body={"issues": [{"key": f"issue-{branch}"}]},
        )

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        del issue_key, transition
        return SonarHttpResponse(status_code=200)


@dataclass
class FakeThirdPartyJenkinsClient:
    """Fake only the Jenkins Remote API boundary used by light and heavy logic."""

    triggered: list[dict[str, str]] = field(default_factory=list)

    def whoami(self) -> JenkinsHttpResponse:
        return JenkinsHttpResponse(status_code=200, json_body={"id": "agentkit"})

    def job_exists(self, pipeline: str) -> JenkinsHttpResponse:
        return JenkinsHttpResponse(status_code=200, json_body={"name": pipeline})

    def trigger_build(
        self, pipeline: str, *, parameters: dict[str, str]
    ) -> JenkinsHttpResponse:
        del pipeline
        self.triggered.append(parameters)
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
            status_code=200,
            json_body={
                "building": False,
                "result": "SUCCESS",
                "actions": [{"SONAR_SCANNER_VERSION": "5.0.1"}],
            },
        )

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> JenkinsHttpResponse:
        del pipeline, build_number, artifact_path
        return JenkinsHttpResponse(status_code=200, text_body="ceTaskId=ce-1\n")


class FakeThirdPartyAreClient:
    """Fake only the authenticated ARE health endpoint."""

    def health(self) -> ArePreflightResponse:
        return ArePreflightResponse(status_code=200, json_body={"status": "ok"})


@dataclass
class FakeThirdPartyClientFactory:
    """Factory fake whose products remain at the external HTTP boundary."""

    sonar_client: FakeThirdPartySonarClient = field(
        default_factory=FakeThirdPartySonarClient
    )
    jenkins_client: FakeThirdPartyJenkinsClient = field(
        default_factory=FakeThirdPartyJenkinsClient
    )
    sonar_constructions: int = 0
    jenkins_constructions: int = 0

    def sonar(self, config: SonarValidationConfig, token: str) -> SonarClient:
        del config
        assert token == "backend-sonar-token"
        self.sonar_constructions += 1
        return cast("SonarClient", self.sonar_client)

    def sonar_permissions(
        self, config: SonarValidationConfig
    ) -> frozenset[str]:
        del config
        return frozenset({"Administer Issues"})

    def jenkins(self, config: CiValidationConfig, token: str) -> JenkinsClient:
        del config
        assert token == "backend-jenkins-token"
        self.jenkins_constructions += 1
        return cast("JenkinsClient", self.jenkins_client)

    def are(self, config: AreValidationConfig, token: str) -> ArePreflightClient:
        del config, token
        return cast("ArePreflightClient", FakeThirdPartyAreClient())
