"""Integration: pre-merge runners end-to-end against stubbed HTTP boundaries.

AG3-056 §2.1.7 / AC6. The real runner + binding + CI-run orchestration runs;
only the external HTTP boundaries (the thin Jenkins client + the thin Sonar
client) are stubbed — exactly the MOCKS exception in CLAUDE.md (external
system unavailable in test). The full chain trigger -> await -> read-run-
report-task -> read Sonar attestation -> prove binding is exercised.

Proves:
* POSITIVE: a triggered run green + Sonar reports the candidate revision ->
  ScanOutcome.produced=True (commit/tree bound) AND BuildTestOutcome.green=True;
* NEGATIVES: run red; run aborted; stale/foreign analysis (revision mismatch);
  Jenkins unreachable; timeout -> each a fail-closed outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from agentkit.config.models import SonarQubeConfig
from agentkit.verify_system.pre_merge_runner.build_test_runner import CiBuildTestRunner
from agentkit.verify_system.pre_merge_runner.ci_run import (
    CandidateRunCache,
    JenkinsCiBackend,
)
from agentkit.verify_system.pre_merge_runner.contract import CandidateRef
from agentkit.verify_system.pre_merge_runner.scan_runner import CiSonarScanRunner
from agentkit.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger

if TYPE_CHECKING:
    from collections.abc import Mapping

_SHA = "cafe1234deadbeef"
_BRANCH = "story/AG3-056-candidate"
_TREE = "treehash9999"


@dataclass(frozen=True)
class _JenkinsResp:
    json_body: dict[str, object] = field(default_factory=dict)
    text_body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _StubJenkinsClient:
    """Stub of the thin Jenkins HTTP client (trigger/poll/artefact)."""

    build_result: str = "SUCCESS"
    report_task: str | None = None
    unreachable: bool = False
    never_terminal: bool = False
    built_commit: str = _SHA
    trigger_calls: int = 0

    def trigger_build(
        self, pipeline: str, *, parameters: Mapping[str, str]
    ) -> _JenkinsResp:
        del pipeline, parameters
        self.trigger_calls += 1
        if self.unreachable:
            from agentkit.integrations.jenkins import JenkinsApiError

            raise JenkinsApiError("jenkins unreachable")
        return _JenkinsResp(headers={"location": "http://jenkins/queue/item/3/"})

    def queue_item(self, queue_id: int) -> _JenkinsResp:
        del queue_id
        return _JenkinsResp(json_body={"executable": {"number": 11}})

    def build_status(self, pipeline: str, build_number: int) -> _JenkinsResp:
        del pipeline, build_number
        if self.never_terminal:
            return _JenkinsResp(json_body={"building": True, "result": None})
        return _JenkinsResp(
            json_body={
                "building": False,
                "result": self.build_result,
                "actions": [
                    {"lastBuiltRevision": {"SHA1": self.built_commit}},
                    # Pipeline-contributed post-scan env value (real scanner
                    # binary evidence), NOT a user-tweakable build parameter
                    # (WARNING-1 / round 5).
                    {"SONAR_SCANNER_VERSION": "5.0.1"},
                ],
            }
        )

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> _JenkinsResp:
        del pipeline, build_number, artifact_path
        text = self.report_task
        if text is None:
            # A REAL report-task.txt carries only ceTaskId/projectKey/server
            # metadata — no analysisId (ERROR-A) and NO branch (ERROR-2).
            text = (
                "projectKey=proj\n"
                "serverUrl=http://sonar:9901\n"
                "serverVersion=26.4.0.1\n"
                "ceTaskId=CE-9\n"
                "ceTaskUrl=http://sonar:9901/api/ce/task?id=CE-9\n"
                "dashboardUrl=http://sonar:9901/dashboard?id=proj\n"
            )
        return _JenkinsResp(text_body=text)


@dataclass(frozen=True)
class _SonarResp:
    json_body: dict[str, Any]


@dataclass
class _StubSonarClient:
    """Stub of the thin Sonar HTTP client mirroring the REAL Web-API shapes.

    ``ce/task`` resolves the analysisId (the report-task carries only ceTaskId,
    ERROR-A); ``project_status`` carries ONLY status/conditions/periods (no
    invented hash fields); the integrity hashes come from the qualitygates /
    qualityprofiles / settings endpoints (ERROR-B).
    """

    analyzed_revision: str = _SHA
    quality_gate_status: str = "OK"
    analysis_id: str = "AX-9"
    #: The branch under which the analysis exists (ERROR-2 branch proof). A
    #: project_analyses search scoped to a different branch finds nothing.
    analyses_branch: str = _BRANCH

    def ce_task(self, ce_task_id: str) -> _SonarResp:
        del ce_task_id
        return _SonarResp(
            {"task": {"id": "CE-9", "status": "SUCCESS", "analysisId": self.analysis_id}}
        )

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> _SonarResp:
        del analysis_id, ce_task_id
        return _SonarResp(
            {
                "projectStatus": {
                    "status": self.quality_gate_status,
                    "conditions": [],
                    "periods": [{"mode": "PREVIOUS_VERSION"}],
                }
            }
        )

    def project_analyses_search(
        self, project: str, *, branch: str | None = None
    ) -> _SonarResp:
        del project
        # ERROR-2: the analysis only exists under its real branch; a search
        # scoped to a different branch returns nothing (the branch proof).
        if branch != self.analyses_branch:
            return _SonarResp({"analyses": []})
        return _SonarResp(
            {"analyses": [{"key": self.analysis_id, "revision": self.analyzed_revision}]}
        )

    def system_status(self) -> _SonarResp:
        return _SonarResp({"id": "srv-1", "version": "26.4", "status": "UP"})

    def qualitygates_get_by_project(self, project: str) -> _SonarResp:
        del project
        return _SonarResp({"qualityGate": {"id": "1", "name": "AK3 Way"}})

    def qualitygates_show(self, name: str) -> _SonarResp:
        del name
        return _SonarResp(
            {
                "id": "1",
                "name": "AK3 Way",
                "conditions": [
                    {"id": 1, "metric": "new_violations", "op": "GT", "error": "0"}
                ],
            }
        )

    def qualityprofiles_search(self, project: str) -> _SonarResp:
        del project
        return _SonarResp(
            {
                "profiles": [
                    {
                        "key": "py-1",
                        "name": "Sonar way",
                        "language": "py",
                        "rulesUpdatedAt": "2026-01-01T00:00:00+0000",
                        "lastUsed": "2026-06-01T00:00:00+0000",
                    }
                ]
            }
        )

    def settings_values(
        self, *, component: str, keys: tuple[str, ...] = ()
    ) -> _SonarResp:
        del component, keys
        return _SonarResp({"settings": [{"key": "sonar.sources", "value": "src"}]})

    def search_issues(self, params: object) -> _SonarResp:
        # FIX-1: the runner runs the FULL AG3-052 gate over the run's analysis.
        # An empty open-issue set + OK post-apply QG = green (no open findings).
        del params
        return _SonarResp({"issues": []})

    def transition_issue(self, issue_key: str, transition: str) -> _SonarResp:
        del issue_key, transition
        return _SonarResp({})

    def set_issue_tags(self, issue_key: str, tags: str) -> _SonarResp:
        del issue_key, tags
        return _SonarResp({})


def _sonar_config() -> SonarQubeConfig:
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONAR_TOKEN",
        scanner_version="5.0.1",
    )


def _backend(jenkins: _StubJenkinsClient) -> JenkinsCiBackend:
    # A monotonic clock that advances 1s per call makes the bounded poll
    # timeout deterministic and instant (no real wall-clock spin).
    ticks = iter(range(0, 10_000))
    return JenkinsCiBackend(
        client=jenkins,  # type: ignore[arg-type]
        pipeline="ak3-pre-merge",
        poll_timeout_seconds=2,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=lambda: float(next(ticks)),
    )


def _cache(jenkins: _StubJenkinsClient) -> CandidateRunCache:
    return CandidateRunCache(backend=_backend(jenkins))


def _candidate() -> CandidateRef:
    return CandidateRef(branch=_BRANCH, commit_sha=_SHA, tree_hash=_TREE)


def _fake_tree(commit_sha: str) -> str:
    del commit_sha
    return _TREE


def _scan_runner(
    cache: CandidateRunCache, sonar: _StubSonarClient
) -> CiSonarScanRunner:
    return CiSonarScanRunner(
        run_cache=cache,
        client=sonar,  # type: ignore[arg-type]
        config=_sonar_config(),
        ledger=AcceptedExceptionLedger(),
        tree_resolver=_fake_tree,
    )


@pytest.mark.integration
class TestPositivePath:
    def test_green_run_and_bound_analysis_produces_outcome(self) -> None:
        # Full REAL-shaped chain: report-task with ONLY ceTaskId/projectKey/
        # server metadata (NO branch, NO analysisId) => ce/task SUCCESS +
        # analysisId => project_analyses(branch=candidate) revision==candidate
        # => project_status periods[] => computed hashes => run-sourced scanner
        # version => complete attestation, every mandatory field non-empty.
        jenkins = _StubJenkinsClient(build_result="SUCCESS")
        sonar = _StubSonarClient(analyzed_revision=_SHA)
        # ONE shared cache for both facets => ONE triggered run (FIX-3).
        cache = _cache(jenkins)
        scan = _scan_runner(cache, sonar).produce_attestation(_candidate())
        assert scan.produced is True
        assert scan.commit_sha == _SHA
        assert scan.tree_hash == _TREE
        # FIX-1/FIX-4/ERROR-A/ERROR-B: a fresh, complete attestation is
        # surfaced; analysisId resolved via ce/task; integrity hashes COMPUTED
        # (non-empty sha256, not invented fields); scanner version run-sourced.
        att = scan.attestation
        assert att is not None
        assert att.last_analyzed_revision == _SHA
        assert att.tree_hash == _TREE
        assert att.quality_gate_status == "OK"
        assert att.analysis_id == "AX-9"
        assert len(att.quality_gate_hash) == 64
        assert len(att.quality_profile_hash) == 64
        assert len(att.analysis_scope_hash) == 64
        assert att.scanner_version == "5.0.1"
        # FIX-1: the FULL AG3-052 gate ran over the run's analysis and is green.
        assert scan.gate_outcome is not None
        assert scan.gate_outcome.passed is True
        # ERROR-1: EVERY mandatory FK-33 §33.6.3 binding is non-empty.
        for field_name in (
            "commit_sha",
            "tree_hash",
            "analysis_id",
            "ce_task_id",
            "quality_gate_status",
            "quality_gate_hash",
            "quality_profile_hash",
            "analysis_scope_hash",
            "exception_ledger_hash",
            "last_analyzed_revision",
            "sonarqube_version",
            "branch_plugin_version",
            "scanner_version",
        ):
            assert str(getattr(att, field_name)).strip()

        build_test = CiBuildTestRunner(run_cache=cache).run(_candidate())
        assert build_test.green is True
        # Both facets shared the SAME single run: exactly ONE trigger (FIX-3).
        assert jenkins.trigger_calls == 1


@pytest.mark.integration
class TestNegativePaths:
    def test_red_run_build_test_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(build_result="FAILURE")
        outcome = CiBuildTestRunner(run_cache=_cache(jenkins)).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None

    def test_aborted_run_build_test_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(build_result="ABORTED")
        outcome = CiBuildTestRunner(run_cache=_cache(jenkins)).run(_candidate())
        assert outcome.green is False

    def test_stale_foreign_analysis_revision_mismatch_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(build_result="SUCCESS")
        sonar = _StubSonarClient(analyzed_revision="0000foreign0000")
        scan = _scan_runner(_cache(jenkins), sonar).produce_attestation(_candidate())
        assert scan.produced is False
        assert scan.reason is not None
        assert "revision_mismatch" in scan.reason

    def test_built_commit_mismatch_fails_closed(self) -> None:
        """FIX-3: Jenkins built branch-tip (foreign commit) => fail closed."""
        jenkins = _StubJenkinsClient(build_result="SUCCESS", built_commit="0ther99")
        sonar = _StubSonarClient(analyzed_revision=_SHA)
        scan = _scan_runner(_cache(jenkins), sonar).produce_attestation(_candidate())
        assert scan.produced is False
        assert scan.reason is not None
        assert "built_commit_mismatch" in scan.reason

    def test_analysis_only_under_different_branch_fails_closed(self) -> None:
        """ERROR-2: the analysis exists only under a DIFFERENT branch. The
        candidate-branch-scoped project_analyses/search finds nothing => the
        revision read misses => fail closed (the branch is proven by Sonar,
        not by a non-real report-task field)."""
        jenkins = _StubJenkinsClient(build_result="SUCCESS")
        sonar = _StubSonarClient(analyzed_revision=_SHA, analyses_branch="main")
        scan = _scan_runner(_cache(jenkins), sonar).produce_attestation(_candidate())
        assert scan.produced is False
        assert scan.reason is not None
        # No analysis on the candidate branch => Sonar revision read fails.
        assert "sonar_unreachable" in scan.reason

    def test_run_without_report_task_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(report_task="projectKey=proj\n")
        sonar = _StubSonarClient(analyzed_revision=_SHA)
        scan = _scan_runner(_cache(jenkins), sonar).produce_attestation(_candidate())
        assert scan.produced is False
        assert scan.reason is not None
        assert "ci_run_unavailable" in scan.reason

    def test_jenkins_unreachable_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(unreachable=True)
        sonar = _StubSonarClient(analyzed_revision=_SHA)
        scan = _scan_runner(_cache(jenkins), sonar).produce_attestation(_candidate())
        assert scan.produced is False
        assert scan.reason is not None
        assert "ci_run_unavailable" in scan.reason

    def test_build_never_terminal_times_out_fails_closed(self) -> None:
        jenkins = _StubJenkinsClient(never_terminal=True)
        outcome = CiBuildTestRunner(run_cache=_cache(jenkins)).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "ci_run_unavailable" in outcome.reason
