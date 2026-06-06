"""Unit tests for the Jenkins CI run orchestration (AG3-056 §3.1/§2.1.1).

The thin Jenkins HTTP client is faked (external system unavailable in tests);
the trigger -> await -> read-report-task orchestration runs for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from agentkit.verify_system.pre_merge_runner.ci_run import (
    CandidateRunCache,
    CiRunUnavailableError,
    JenkinsCiBackend,
)
from agentkit.verify_system.pre_merge_runner.contract import CandidateRef

if TYPE_CHECKING:
    from collections.abc import Mapping

_BUILT = {"lastBuiltRevision": {"SHA1": "cafe1234"}}
#: Pipeline-contributed post-scan environment value exposing the run's REAL
#: SonarScanner version (ERROR-B / WARNING-1) — an
#: ``EnvironmentContributingAction`` map, NOT a user-tweakable build parameter.
_SCANNER = {"SONAR_SCANNER_VERSION": "5.0.1"}

#: A REAL report-task.txt carries only ceTaskId/projectKey/server metadata —
#: no analysisId (ERROR-A) and NO top-level ``branch`` key (ERROR-2).
_REPORT_TASK = (
    "projectKey=proj\n"
    "serverUrl=http://sonar:9901\n"
    "serverVersion=26.4.0.1\n"
    "ceTaskId=CE-1\n"
    "ceTaskUrl=http://sonar:9901/api/ce/task?id=CE-1\n"
    "dashboardUrl=http://sonar:9901/dashboard?id=proj\n"
)


@dataclass(frozen=True)
class _Resp:
    json_body: dict[str, object] = field(default_factory=dict)
    text_body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _FakeJenkins:
    """Scriptable fake of the thin Jenkins client.

    Each queue/status poll pops the next scripted body, so a test can model
    "still building -> terminal" sequences deterministically.
    """

    queue_bodies: list[dict[str, object]] = field(default_factory=list)
    status_bodies: list[dict[str, object]] = field(default_factory=list)
    report_task: str = _REPORT_TASK
    location: str = "http://jenkins/queue/item/7/"
    triggers: list[tuple[str, Mapping[str, str]]] = field(default_factory=list)

    def trigger_build(
        self, pipeline: str, *, parameters: Mapping[str, str]
    ) -> _Resp:
        self.triggers.append((pipeline, dict(parameters)))
        return _Resp(headers={"location": self.location})

    def queue_item(self, queue_id: int) -> _Resp:
        del queue_id
        return _Resp(json_body=self.queue_bodies.pop(0))

    def build_status(self, pipeline: str, build_number: int) -> _Resp:
        del pipeline, build_number
        return _Resp(json_body=self.status_bodies.pop(0))

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> _Resp:
        del pipeline, build_number, artifact_path
        return _Resp(text_body=self.report_task)


def _backend(fake: _FakeJenkins) -> JenkinsCiBackend:
    return JenkinsCiBackend(
        client=fake,  # type: ignore[arg-type]
        pipeline="ak3-pre-merge",
        poll_timeout_seconds=5,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
    )


class TestSuccessfulRun:
    def test_trigger_await_and_read_report_task(self) -> None:
        fake = _FakeJenkins(
            queue_bodies=[
                {"cancelled": False},  # not scheduled yet
                {"executable": {"number": 42}},  # scheduled
            ],
            status_bodies=[
                {"building": True, "result": None},  # still running
                {  # terminal
                    "building": False,
                    "result": "SUCCESS",
                    "actions": [_BUILT, _SCANNER],
                },
            ],
        )
        result = _backend(fake).run_candidate(
            branch="story/AG3-056-candidate", commit_sha="cafe1234"
        )
        assert result.build_succeeded is True
        assert result.result == "SUCCESS"
        assert result.ce_task_id == "CE-1"
        # ERROR-A: the run never carries an analysisId from the artefact.
        assert result.analysis_id is None
        assert result.component == "proj"
        # ERROR-2: the run result carries no branch field (proven from Sonar).
        assert not hasattr(result, "analyzed_branch")
        # FIX-3: run identity + the commit Jenkins ACTUALLY built.
        assert result.build_number == 42
        assert result.built_commit == "cafe1234"
        # ERROR-B: the run's scanner version is sourced from the
        # pipeline-contributed post-scan env value.
        assert result.scanner_version == "5.0.1"
        # Build was parameterised with the candidate branch + commit.
        assert fake.triggers[0][1] == {
            "branch": "story/AG3-056-candidate",
            "commit_sha": "cafe1234",
        }

    def test_scanner_version_ignores_build_param(self) -> None:
        """WARNING-1 (round 5): a build PARAMETER is a user-tweakable INPUT, not
        evidence of the scanner binary that ran. When ONLY a build parameter is
        present (no pipeline-contributed env entry), the scanner version is NOT
        sourced from it — it surfaces as ``None`` so the scan runner fails
        closed (never a placeholder in a produced attestation)."""
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 3}}],
            status_bodies=[
                {
                    "building": False,
                    "result": "SUCCESS",
                    "actions": [
                        _BUILT,
                        # ONLY a user-set build parameter (NOT authoritative).
                        {
                            "parameters": [
                                {"name": "SONAR_SCANNER_VERSION", "value": "9.9.9"}
                            ]
                        },
                    ],
                }
            ],
        )
        result = _backend(fake).run_candidate(branch="b", commit_sha="cafe1234")
        assert result.scanner_version is None

    def test_built_commit_ignores_git_commit_build_param(self) -> None:
        """FIX-3 / round 6: a ``GIT_COMMIT`` build PARAMETER is a user-tweakable
        INPUT, not proof Jenkins built that commit. When the commit is exposed
        ONLY as a parameter (no git-plugin ``lastBuiltRevision.SHA1``),
        ``built_commit`` is NOT sourced from it — it surfaces as ``None`` so the
        runners fail closed (``built_commit_unknown``)."""
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 7}}],
            status_bodies=[
                {
                    "building": False,
                    "result": "SUCCESS",
                    "actions": [
                        # ONLY a user-set build parameter (NOT git-plugin evidence).
                        {"parameters": [{"name": "GIT_COMMIT", "value": "abc999"}]}
                    ],
                }
            ],
        )
        result = _backend(fake).run_candidate(branch="b", commit_sha="abc999")
        assert result.built_commit is None

    def test_no_built_revision_surfaces_as_none(self) -> None:
        """No actions => ``built_commit`` is None (runners fail closed)."""
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 1}}],
            status_bodies=[{"building": False, "result": "SUCCESS"}],
        )
        result = _backend(fake).run_candidate(branch="b", commit_sha="c")
        assert result.built_commit is None

    def test_failure_result_surfaces_as_not_succeeded(self) -> None:
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 1}}],
            status_bodies=[{"building": False, "result": "FAILURE"}],
        )
        result = _backend(fake).run_candidate(branch="b", commit_sha="c")
        assert result.build_succeeded is False
        assert result.result == "FAILURE"


class TestSingleRunPerCandidate:
    def test_run_cache_triggers_once_and_memoizes(self) -> None:
        """FIX-3: both facets observe ONE run for a candidate."""
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 5}}],
            status_bodies=[
                {"building": False, "result": "SUCCESS", "actions": [_BUILT]}
            ],
        )
        cache = CandidateRunCache(backend=_backend(fake))
        candidate = CandidateRef(
            branch="story/AG3-056-candidate", commit_sha="cafe1234", tree_hash="t"
        )
        first = cache.run_for(candidate)
        second = cache.run_for(candidate)
        assert first is second
        # Exactly ONE Jenkins build was triggered for the candidate.
        assert len(fake.triggers) == 1


class TestFailClosed:
    def test_cancelled_queue_item_fails_closed(self) -> None:
        fake = _FakeJenkins(queue_bodies=[{"cancelled": True}])
        with pytest.raises(CiRunUnavailableError, match="cancelled"):
            _backend(fake).run_candidate(branch="b", commit_sha="c")

    def test_missing_location_header_fails_closed(self) -> None:
        fake = _FakeJenkins(location="")
        with pytest.raises(CiRunUnavailableError, match="Location"):
            _backend(fake).run_candidate(branch="b", commit_sha="c")

    def test_run_without_report_task_ids_fails_closed(self) -> None:
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 9}}],
            status_bodies=[{"building": False, "result": "SUCCESS"}],
            report_task="projectKey=proj\n",  # no ceTaskId
        )
        with pytest.raises(CiRunUnavailableError, match="report-task"):
            _backend(fake).run_candidate(branch="b", commit_sha="c")

    def test_run_without_scanner_version_surfaces_none(self) -> None:
        """ERROR-B: a run that exposed no scanner version => None (the scan
        runner then fails closed; the CI run itself stays readable)."""
        fake = _FakeJenkins(
            queue_bodies=[{"executable": {"number": 9}}],
            status_bodies=[{"building": False, "result": "SUCCESS", "actions": [_BUILT]}],
        )
        result = _backend(fake).run_candidate(branch="b", commit_sha="cafe1234")
        assert result.scanner_version is None
