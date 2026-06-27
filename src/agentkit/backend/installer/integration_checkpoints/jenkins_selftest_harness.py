"""Jenkins-backed CP 10d Branch-Plugin conformance harness.

The FK-50 CP 10d self-test must exercise the same operational scan boundary
that later produces Sonar attestations for code stories: Jenkins triggers the
scanner, archives ``.scannerwork/report-task.txt``, and AgentKit reads the
resulting Sonar analysis through the Web API. The installer therefore does not
require a local ``sonar-scanner`` binary on the operator machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.integration_clients.jenkins import JenkinsApiError
from agentkit.integration_clients.sonar import SonarApiError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
        SelfTestScan,
    )
    from agentkit.integration_clients.jenkins import JenkinsClient
    from agentkit.integration_clients.sonar import SonarClient

_ACCEPTED_RESOLUTIONS = "ACCEPTED,WONTFIX,FALSE-POSITIVE"
_REPORT_TASK_ARTIFACT = ".scannerwork/report-task.txt"
_SELFTEST_MODE = "cp10d_branch_plugin_self_test"
_CE_TERMINAL = frozenset({"SUCCESS", "FAILED", "CANCELED"})


@dataclass(frozen=True)
class JenkinsBranchPluginSelfTestHarness:
    """Productive ``ScannerHarness`` using Jenkins as scan executor.

    The Jenkins job must support the CP10d self-test mode parameters documented
    in FK-50: it scans a small fixture from the Jenkins workspace against the
    supplied Sonar ``project_key`` and ``branch`` and archives the scanner's
    ``report-task.txt``.
    """

    sonar_client: SonarClient
    jenkins_client: JenkinsClient
    pipeline: str
    poll_timeout_seconds: int = 1800
    poll_interval_seconds: int = 10
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    mode_param: str = "agentkit_mode"
    project_key_param: str = "sonar_project_key"
    branch_param: str = "sonar_branch"

    def create_project(self, project_key: str) -> None:
        """Create the throwaway mini-project via Sonar Web API."""
        self.sonar_client.create_project(
            project_key, "AK3 Branch-Plugin Conformance Self-Test"
        )

    def scan(self, project_key: str, branch: str) -> SelfTestScan:
        """Trigger Jenkins to scan ``project_key``/``branch`` and return analysis."""
        from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
            SelfTestScan,
        )

        build_number = self._trigger_and_resolve_build(project_key, branch)
        status = self._await_terminal(build_number)
        if str(status.get("result") or "") != "SUCCESS":
            raise JenkinsApiError(
                f"Jenkins CP10d self-test build {self.pipeline}#{build_number} "
                f"finished with result {status.get('result')!r}",
            )
        scanner_version = _scanner_version_from_status(status)
        if not scanner_version:
            raise JenkinsApiError(
                f"Jenkins CP10d self-test build {self.pipeline}#{build_number} "
                "exposed no SONAR_SCANNER_VERSION run evidence",
            )
        report_task = self._read_report_task(build_number)
        ce_task_id = report_task.get("ceTaskId", "")
        if not ce_task_id:
            raise JenkinsApiError(
                f"Jenkins CP10d self-test build {self.pipeline}#{build_number} "
                "archived report-task.txt without ceTaskId",
            )
        analysis_id = self._resolve_analysis_id(ce_task_id)
        return SelfTestScan(
            analysis_id=analysis_id,
            branch=branch,
            issue_keys=self._issue_keys(project_key, branch),
            scanner_version=scanner_version,
        )

    def branch_exists(self, project_key: str, branch: str) -> bool:
        """Return whether the Sonar branch analysis is visible."""
        body = self.sonar_client.project_branches(project_key).json_body
        branches = body.get("branches", [])
        if not isinstance(branches, list):
            return False
        return any(
            isinstance(entry, dict) and entry.get("name") == branch
            for entry in branches
        )

    def issue_accepted_on_branch(
        self, project_key: str, branch: str, issue_key: str
    ) -> bool:
        """Return whether ``issue_key`` reads as Accepted on ``branch``."""
        body = self.sonar_client.search_issues(
            {
                "componentKeys": project_key,
                "branch": branch,
                "issues": issue_key,
                "resolutions": _ACCEPTED_RESOLUTIONS,
                "ps": "1",
            }
        ).json_body
        issues = body.get("issues", [])
        return isinstance(issues, list) and len(issues) >= 1

    def delete_project(self, project_key: str) -> None:
        """Delete the throwaway mini-project; cleanup errors are non-fatal."""
        try:
            self.sonar_client.delete_project(project_key)
        except SonarApiError:
            return

    def _trigger_and_resolve_build(self, project_key: str, branch: str) -> int:
        response = self.jenkins_client.trigger_build(
            self.pipeline,
            parameters={
                self.mode_param: _SELFTEST_MODE,
                self.project_key_param: project_key,
                self.branch_param: branch,
            },
        )
        queue_id = _queue_id_from_location(response.headers.get("location", ""))
        if queue_id is None:
            raise JenkinsApiError(
                "Jenkins CP10d self-test trigger returned no resolvable queue "
                "Location header",
            )
        return self._await_executable(queue_id)

    def _await_executable(self, queue_id: int) -> int:
        deadline = self.monotonic() + self.poll_timeout_seconds
        while True:
            body = self.jenkins_client.queue_item(queue_id).json_body
            executable = body.get("executable")
            if isinstance(executable, dict):
                number = executable.get("number")
                if isinstance(number, int):
                    return number
            if body.get("cancelled") is True:
                raise JenkinsApiError(
                    f"Jenkins CP10d self-test queue item {queue_id} was cancelled"
                )
            if self.monotonic() >= deadline:
                raise JenkinsApiError(
                    f"Jenkins CP10d self-test queue item {queue_id} did not "
                    f"start within {self.poll_timeout_seconds}s",
                )
            self.sleep(self.poll_interval_seconds)

    def _await_terminal(self, build_number: int) -> dict[str, object]:
        deadline = self.monotonic() + self.poll_timeout_seconds
        while True:
            body = self.jenkins_client.build_status(
                self.pipeline, build_number
            ).json_body
            if body.get("building") is False and body.get("result") is not None:
                return body
            if self.monotonic() >= deadline:
                raise JenkinsApiError(
                    f"Jenkins CP10d self-test build {self.pipeline}#{build_number} "
                    f"did not terminate within {self.poll_timeout_seconds}s",
                )
            self.sleep(self.poll_interval_seconds)

    def _read_report_task(self, build_number: int) -> dict[str, str]:
        response = self.jenkins_client.build_artifact(
            self.pipeline, build_number, _REPORT_TASK_ARTIFACT
        )
        return _parse_report_task(response.text_body)

    def _resolve_analysis_id(self, ce_task_id: str) -> str:
        deadline = self.monotonic() + self.poll_timeout_seconds
        while True:
            task_body = self.sonar_client.ce_task(ce_task_id).json_body
            task = task_body.get("task")
            if isinstance(task, dict):
                status = str(task.get("status") or "")
                analysis_id = str(task.get("analysisId") or "")
                if status == "SUCCESS" and analysis_id:
                    return analysis_id
                if status in _CE_TERMINAL:
                    raise SonarApiError(
                        f"Sonar CE task {ce_task_id} ended as {status!r} "
                        "without usable analysisId",
                    )
            if self.monotonic() >= deadline:
                raise SonarApiError(
                    f"Sonar CE task {ce_task_id} did not finish within "
                    f"{self.poll_timeout_seconds}s",
                )
            self.sleep(self.poll_interval_seconds)

    def _issue_keys(self, project_key: str, branch: str) -> tuple[str, ...]:
        body = self.sonar_client.search_issues(
            {
                "componentKeys": project_key,
                "branch": branch,
                "ps": "100",
            }
        ).json_body
        issues = body.get("issues", [])
        if not isinstance(issues, list):
            return ()
        keys: list[str] = []
        for issue in issues:
            if isinstance(issue, dict):
                key = issue.get("key")
                if isinstance(key, str) and key:
                    keys.append(key)
        return tuple(keys)


def _parse_report_task(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _scanner_version_from_status(status: dict[str, object]) -> str | None:
    actions = status.get("actions")
    if not isinstance(actions, list):
        return None
    for action in actions:
        if not isinstance(action, dict):
            continue
        value = action.get("SONAR_SCANNER_VERSION")
        if isinstance(value, str) and value:
            return value
    return None


def _queue_id_from_location(location: str) -> int | None:
    parts = [part for part in location.rstrip("/").split("/") if part]
    if len(parts) < 2 or parts[-2] != "item":
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


__all__ = ["JenkinsBranchPluginSelfTestHarness"]
