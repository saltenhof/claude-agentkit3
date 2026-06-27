"""Productive SonarScanner CLI runner for installer CP 10d self-tests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
    SelfTestScan,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_POLL_INTERVAL_SECONDS = 2
_POLL_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class SonarScannerCliRunner:
    """Run ``sonar-scanner`` for the branch-plugin conformance mini-project."""

    base_url: str
    token: str
    user: str = ""

    def __call__(self, project_key: str, branch: str) -> SelfTestScan:
        scanner = shutil.which("sonar-scanner")
        if scanner is None:
            raise InstallationError(
                "sonar-scanner executable not found in PATH; CP 10d cannot run "
                "the branch-plugin conformance self-test.",
                detail={"cause": "SonarScannerMissing"},
            )
        with tempfile.TemporaryDirectory(prefix="ak3-sonar-selftest-") as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "Main.java").write_text(
                "final class Main { int answer() { return 42; } }\n",
                encoding="utf-8",
            )
            self._run_scanner(scanner, root, project_key, branch)
            report = _read_report_task(root)
            analysis_id = self._resolve_analysis_id(report)
        return SelfTestScan(analysis_id=analysis_id, branch=branch, issue_keys=())

    def _run_scanner(
        self, scanner: str, root: Path, project_key: str, branch: str
    ) -> None:
        args = [
            scanner,
            f"-Dsonar.projectKey={project_key}",
            "-Dsonar.projectName=AK3 Branch Plugin Conformance Self-Test",
            "-Dsonar.sources=src",
            f"-Dsonar.host.url={self.base_url}",
            f"-Dsonar.branch.name={branch}",
            "-Dsonar.qualitygate.wait=true",
        ]
        if self.user:
            args.extend([f"-Dsonar.login={self.user}", f"-Dsonar.password={self.token}"])
        else:
            args.append(f"-Dsonar.token={self.token}")
        completed = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            raise InstallationError(
                "sonar-scanner failed during CP 10d branch-plugin self-test.",
                detail={
                    "cause": "SonarScannerFailed",
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-4000:],
                    "stdout": completed.stdout[-4000:],
                },
            )

    def _resolve_analysis_id(self, report: Mapping[str, str]) -> str:
        ce_task_id = report.get("ceTaskId")
        if not ce_task_id:
            raise InstallationError(
                "sonar-scanner report-task.txt did not contain ceTaskId.",
                detail={"cause": "SonarScannerReportIncomplete"},
            )
        from agentkit.integration_clients.sonar import SonarClient

        client = SonarClient(self.base_url, self.token, user=self.user)
        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            body = client.ce_task(ce_task_id).json_body
            task = body.get("task")
            if isinstance(task, dict):
                status = str(task.get("status", ""))
                analysis_id = str(task.get("analysisId", ""))
                if status == "SUCCESS" and analysis_id:
                    return analysis_id
                if status in {"FAILED", "CANCELED"}:
                    raise InstallationError(
                        "Sonar compute-engine task failed during CP 10d self-test.",
                        detail={"cause": "SonarComputeEngineFailed", "status": status},
                    )
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise InstallationError(
            "Timed out waiting for Sonar compute-engine analysisId.",
            detail={"cause": "SonarComputeEngineTimeout", "ceTaskId": ce_task_id},
        )


def _read_report_task(root: Path) -> dict[str, str]:
    path = root / ".scannerwork" / "report-task.txt"
    if not path.is_file():
        raise InstallationError(
            "sonar-scanner did not produce .scannerwork/report-task.txt.",
            detail={"cause": "SonarScannerReportMissing"},
        )
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


__all__ = ["SonarScannerCliRunner"]
