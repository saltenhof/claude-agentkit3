"""Shared fakes for the pre-merge runner tests (HTTP boundary stubbed only).

These fakes stand in for the external CI + Sonar systems that are not
available in unit/integration tests (the MOCKS exception in CLAUDE.md:
isolated test of an external system). The runner/binding logic runs for
real against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentkit.integrations.sonar import SonarApiError
from agentkit.verify_system.pre_merge_runner.ci_run import (
    CandidateRunCache,
    CiRunResult,
    CiRunUnavailableError,
)
from agentkit.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger

#: Default tree hash a fake :func:`fake_tree_resolver` returns for any commit.
FAKE_TREE_HASH = "tree9999"


@dataclass
class FakeCiBackend:
    """Fake :class:`CiBackend` returning a preset terminal run result.

    Attributes:
        result: The :class:`CiRunResult` to return, or ``None`` to raise.
        error: When set, ``run_candidate`` raises this instead of returning.
        calls: Records ``(branch, commit_sha)`` per invocation.
    """

    result: CiRunResult | None = None
    error: CiRunUnavailableError | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def run_candidate(self, *, branch: str, commit_sha: str) -> CiRunResult:
        self.calls.append((branch, commit_sha))
        if self.error is not None:
            raise self.error
        assert self.result is not None  # noqa: S101 (test fake invariant)
        return self.result


@dataclass
class FakeSonarClient:
    """Fake Sonar HTTP boundary mirroring the REAL Web-API response shapes.

    Every body mirrors what real SonarQube returns (ERROR-A/ERROR-B):
    ``ce/task`` resolves the analysisId; ``project_status`` carries ONLY
    ``projectStatus.{status,periods}`` (NO invented hash fields); the integrity
    hashes come from the qualitygates / qualityprofiles / settings endpoints.

    Attributes:
        analyzed_revision: The revision ``project_analyses_search`` reports for
            the run's analysis (the authoritative binding source, FIX-2).
        quality_gate_status: The gate status ``project_status`` reports.
        version: The server version ``system_status`` reports.
        raise_on: When set to an operation name, that call raises
            ``SonarApiError`` (configured-but-unreachable simulation).
        analysis_id: The analysisId ``ce/task`` resolves and the
            ``project_analyses`` entry is keyed on (the REAL analysisId).
        ce_status: The ``ce/task`` terminal status (``SUCCESS`` for the
            positive path; negatives drive PENDING/FAILED/no-analysisId).
        ce_carries_analysis_id: Whether the SUCCESS ce/task carries an
            analysisId (a SUCCESS without one fails closed).
        analyses_key: The ``key`` the ``project_analyses`` entry carries; when
            ``None`` it equals ``analysis_id`` (matching). Set it to a
            DIFFERENT id to exercise the strict no-match fail-closed path.
        analyses_branch: When set, ``project_analyses_search`` only returns the
            analysis entry for THIS branch (the candidate-branch proof,
            ERROR-2). A request scoped to a different branch returns an empty
            ``analyses`` array, so the revision read misses => fail-closed.
            ``None`` means branch-agnostic (the analysis is returned regardless
            of the branch the search was scoped to).
        version: The server version ``system_status`` reports; set to ``None``
            to drop the ``version`` field entirely (real absence => fail-closed,
            ERROR-1).
    """

    analyzed_revision: str = ""
    quality_gate_status: str = "OK"
    version: str | None = "26.4"
    raise_on: str | None = None
    analysis_id: str = "AX-1"
    ce_status: str = "SUCCESS"
    ce_carries_analysis_id: bool = True
    analyses_key: str | None = None
    analyses_branch: str | None = None

    def ce_task(self, ce_task_id: str) -> _Body:
        del ce_task_id
        self._maybe_raise("ce_task")
        task: dict[str, Any] = {"id": "CE-1", "type": "REPORT", "status": self.ce_status}
        if self.ce_status == "SUCCESS" and self.ce_carries_analysis_id:
            task["analysisId"] = self.analysis_id
        return _Body({"task": task})

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> _Body:
        del analysis_id, ce_task_id
        self._maybe_raise("project_status")
        return _Body(
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
    ) -> _Body:
        del project
        self._maybe_raise("project_analyses_search")
        # ERROR-2: the analysis only exists under its real branch; a search
        # scoped to a different branch returns nothing (the branch proof).
        if self.analyses_branch is not None and branch != self.analyses_branch:
            return _Body({"analyses": []})
        key = self.analyses_key if self.analyses_key is not None else self.analysis_id
        return _Body(
            {"analyses": [{"key": key, "revision": self.analyzed_revision}]}
        )

    def system_status(self) -> _Body:
        self._maybe_raise("system_status")
        body: dict[str, Any] = {"id": "srv-1", "status": "UP"}
        if self.version is not None:
            body["version"] = self.version
        return _Body(body)

    def qualitygates_get_by_project(self, project: str) -> _Body:
        del project
        self._maybe_raise("qualitygates_get_by_project")
        return _Body({"qualityGate": {"id": "1", "name": "AK3 Way", "default": True}})

    def qualitygates_show(self, name: str) -> _Body:
        del name
        self._maybe_raise("qualitygates_show")
        return _Body(
            {
                "id": "1",
                "name": "AK3 Way",
                "conditions": [
                    {"id": 1, "metric": "new_violations", "op": "GT", "error": "0"}
                ],
            }
        )

    def qualityprofiles_search(self, project: str) -> _Body:
        del project
        self._maybe_raise("qualityprofiles_search")
        return _Body(
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
    ) -> _Body:
        del component, keys
        self._maybe_raise("settings_values")
        return _Body(
            {
                "settings": [
                    {"key": "sonar.sources", "value": "src"},
                    {"key": "sonar.tests", "value": "tests"},
                ]
            }
        )

    def _maybe_raise(self, op: str) -> None:
        if self.raise_on == op:
            raise SonarApiError(f"fake sonar unreachable on {op}")


@dataclass(frozen=True)
class _Body:
    """Minimal stand-in carrying a ``json_body`` like ``SonarHttpResponse``."""

    json_body: dict[str, Any]


def fake_tree_resolver(commit_sha: str) -> str:
    """Deterministic :class:`TreeHashResolver` for tests (no git subprocess)."""
    del commit_sha
    return FAKE_TREE_HASH


def empty_ledger() -> AcceptedExceptionLedger:
    """Return an empty accepted-exception ledger for tests."""
    return AcceptedExceptionLedger()


def run_cache(backend: FakeCiBackend) -> CandidateRunCache:
    """Wrap a fake backend in the shared single-run cache."""
    return CandidateRunCache(backend=backend)  # type: ignore[arg-type]


def make_ci_result(
    *,
    build_succeeded: bool = True,
    result: str = "SUCCESS",
    ce_task_id: str | None = "CE-1",
    component: str | None = "proj",
    build_number: int = 11,
    built_commit: str | None = "cafe1234",
    scanner_version: str | None = "5.0.1",
) -> CiRunResult:
    """Build a :class:`CiRunResult` with sensible positive-path defaults.

    A real ``report-task.txt`` carries only ``ceTaskId`` (no analysisId,
    ERROR-A; no branch, ERROR-2), so ``analysis_id`` is always ``None`` on a CI
    run result and there is no ``analyzed_branch`` field; the branch is proven
    from Sonar and the scanner version is sourced from the run (ERROR-B).
    """
    return CiRunResult(
        build_succeeded=build_succeeded,
        result=result,
        analysis_id=None,
        ce_task_id=ce_task_id,
        component=component,
        build_number=build_number,
        built_commit=built_commit,
        scanner_version=scanner_version,
    )
