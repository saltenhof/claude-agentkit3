"""Pre-Merge-Verification-Runner capability (AG3-056).

This capability OWNS the port contract that the Closure pre-merge barrier
(AG3-053, FK-29 §29.1a.3) consumes, and provides commit-bound, CI-triggered
runners that prove their binding via Sonar/CI itself (FK-33 §33.6.3). The
dependency direction is strictly ``closure -> verify_system.pre_merge_runner``;
nothing here imports from ``agentkit.backend.closure``.

Public surface:

* the port Protocols + result/input dataclasses (``contract``);
* the binding-proof primitive (``binding``);
* the CI run orchestration seam (``ci_run``);
* the productive runners (``scan_runner`` / ``build_test_runner``);
* the per-run productive wiring (``runtime_wiring``).

Green/attestation/applicability logic is REUSED from the ``sonarqube_gate``
capability (AG3-052) — it is never rebuilt here.
"""

from __future__ import annotations

from agentkit.backend.verify_system.pre_merge_runner.binding import (
    BindingProof,
    prove_binding,
)
from agentkit.backend.verify_system.pre_merge_runner.build_test_runner import (
    CiBuildTestRunner,
)
from agentkit.backend.verify_system.pre_merge_runner.ci_run import (
    CandidateRunCache,
    CiBackend,
    CiRunResult,
    CiRunUnavailableError,
    JenkinsCiBackend,
)
from agentkit.backend.verify_system.pre_merge_runner.contract import (
    BuildTestOutcome,
    BuildTestPort,
    CandidateRef,
    PreMergeScanPort,
    ScanOutcome,
)
from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
    PreMergeRunnerUnavailableError,
    build_pre_merge_runners,
)
from agentkit.backend.verify_system.pre_merge_runner.scan_runner import (
    CiSonarScanRunner,
    GitTreeHashResolver,
    TreeHashResolver,
)

__all__ = [
    "BindingProof",
    "BuildTestOutcome",
    "BuildTestPort",
    "CandidateRef",
    "CandidateRunCache",
    "CiBackend",
    "CiBuildTestRunner",
    "CiRunResult",
    "CiRunUnavailableError",
    "CiSonarScanRunner",
    "GitTreeHashResolver",
    "JenkinsCiBackend",
    "PreMergeRunnerUnavailableError",
    "PreMergeScanPort",
    "ScanOutcome",
    "TreeHashResolver",
    "build_pre_merge_runners",
    "prove_binding",
]
