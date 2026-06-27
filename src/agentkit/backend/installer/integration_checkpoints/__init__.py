"""Installer integration checkpoints (FK-50 §50.3).

Currently hosts the SonarQube CP 10d precondition checks (FK-50 CP 10d,
applicability-conditional). The CP10d config-drift-against-CP7 handling is
out of scope (AG3-052 §2.2; owner Installer/AG3-039).
"""

from __future__ import annotations

from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
    ScannerHarness,
    SelfTestScan,
    run_branch_plugin_conformance_self_test,
)
from agentkit.backend.installer.integration_checkpoints.ci_preflight import (
    CiPreflightResult,
    check_ci_preconditions,
)
from agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness import (
    JenkinsBranchPluginSelfTestHarness,
)
from agentkit.backend.installer.integration_checkpoints.scanner_harness import (
    ScanRunner,
    SonarClientScannerHarness,
)
from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    SonarPreflightResult,
    check_sonarqube_preconditions,
)

__all__ = [
    "CiPreflightResult",
    "JenkinsBranchPluginSelfTestHarness",
    "ScanRunner",
    "ScannerHarness",
    "SelfTestScan",
    "SonarClientScannerHarness",
    "SonarPreflightResult",
    "check_ci_preconditions",
    "check_sonarqube_preconditions",
    "run_branch_plugin_conformance_self_test",
]
