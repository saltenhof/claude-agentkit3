"""CI run orchestration seam for the pre-merge runner (AG3-056).

This module owns the capability-side orchestration of a single CI run for an
integrated candidate: trigger -> await terminal -> read the run's build
result + the run's OWN Sonar analysis reference (``report-task.txt``). It
depends only on a thin ``CiBackend`` Protocol so the runners can be unit/
integration tested against a fake (the HTTP boundary stubbed, MOCKS
exception), while the productive :class:`JenkinsCiBackend` drives the thin
``integrations.jenkins`` client.

The orchestration logic (poll loop, terminal detection, artefact parsing)
is business logic and therefore lives in ``verify_system``, NOT in the thin
``integrations`` adapter (CLAUDE.md: integrations = thin adapters).

FAIL-CLOSED (AG3-056 §2.1.4): unreachable CI, a missing/aborted run, a
timeout, or a run that emitted no ``report-task.txt`` all surface as a typed
:class:`CiRunUnavailableError`; the runners convert this into a
not-produced / not-green outcome. The analysis reference is ALWAYS read from
the build's archived artefact — never from a local ``.scannerwork/``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef

#: Standard SonarScanner output path, archived by the Jenkins build.
REPORT_TASK_ARTIFACT = ".scannerwork/report-task.txt"


class CiRunUnavailableError(Exception):
    """A CI run could not be triggered/awaited/read (fail-closed).

    Raised by the CI backend or the orchestration on any unreachable CI,
    missing/aborted run, timeout, or missing run artefact. The runners
    convert this into a not-produced / not-green outcome (AG3-056 §2.1.4) —
    NEVER fail-open.
    """


@dataclass(frozen=True)
class CiRunResult:
    """Terminal result of one CI run for an integrated candidate.

    A SINGLE run is triggered per candidate and shared across BOTH the
    build/test and the scan facet (FIX-3): the same immutable result backs
    both outcomes, so they can never reflect two different commits.

    Attributes:
        build_succeeded: Whether the build+test of the run passed
            (``result == "SUCCESS"``).
        result: The raw CI build result (e.g. ``SUCCESS``/``FAILURE``/
            ``ABORTED``).
        analysis_id: The Sonar analysis id emitted by THIS run's
            ``report-task.txt`` (``None`` when the run produced none).
        ce_task_id: The Sonar Compute-Engine task id from the run's
            ``report-task.txt`` (``None`` when none).
        component: The Sonar component/project key the run analysed.
        build_number: The CI build number of the triggered run (run
            identity; the same number backs both port facets).
        built_commit: The commit Jenkins ACTUALLY checked out and built,
            sourced ONLY from git-plugin EVIDENCE (``lastBuiltRevision.SHA1``)
            — never from a ``GIT_COMMIT`` build parameter (a tweakable input,
            not proof). The runners require
            ``built_commit == candidate.commit_sha`` (FIX-3) so a job that
            silently builds branch-tip cannot report green for a foreign
            commit. ``None`` when Jenkins exposed no built revision (the
            runners fail closed).
        scanner_version: The SonarScanner version of THIS run's analysis,
            contributed by the pipeline AFTER the scan as an environment value
            (``SONAR_SCANNER_VERSION``, an ``EnvironmentContributingAction``
            entry — NOT a user-tweakable build parameter). Sonar carries no
            authoritative scanner version for an analysis (``project_status``/
            ``ce/task`` do not), so it is sourced from the producing CI run as a
            documented pipeline contract (FK-33 §33.6.3, ERROR-B). ``None`` when
            the run contributed none (the scan runner fails closed — never a
            placeholder in a produced attestation).
    """

    build_succeeded: bool
    result: str
    analysis_id: str | None
    ce_task_id: str | None
    component: str | None
    build_number: int
    built_commit: str | None
    scanner_version: str | None


class CiBackend(Protocol):
    """Thin seam over the CI system for one integrated-candidate run.

    Fakeable so the runners cover positive AND negative paths without a live
    CI. The productive implementation is :class:`JenkinsCiBackend`.
    """

    def run_candidate(self, *, branch: str, commit_sha: str) -> CiRunResult:
        """Trigger a build for ``branch``/``commit_sha``, await it, return it.

        Args:
            branch: The integrated-candidate branch.
            commit_sha: The exact candidate commit to build/test/scan.

        Returns:
            The terminal :class:`CiRunResult` for the run.

        Raises:
            CiRunUnavailableError: On unreachable CI, missing/aborted run,
                timeout, or a run without a Sonar analysis reference.
        """
        ...


@dataclass
class CandidateRunCache:
    """Triggers EXACTLY ONE CI run per candidate and memoizes its result.

    The build/test facet and the scan facet of the pre-merge runner MUST
    observe the SAME run for a given candidate (FIX-3): two separate triggers
    could build/scan two different commits. This cache funnels both facets
    through a single ``backend.run_candidate`` call, keyed by the candidate's
    ``(branch, commit_sha)`` identity, and serves the immutable
    :class:`CiRunResult` to both.

    The cache is per-runner (one runner instance verifies one candidate at a
    time in the closure barrier); the key still guards against an accidental
    cross-candidate reuse.

    Attributes:
        backend: The CI backend that triggers/awaits the candidate run.
        _runs: Memo of ``(branch, commit_sha) -> CiRunResult``.
    """

    backend: CiBackend
    _runs: dict[tuple[str, str], CiRunResult] = field(default_factory=dict)

    def run_for(self, candidate: CandidateRef) -> CiRunResult:
        """Return the (memoized) single run for ``candidate``.

        Args:
            candidate: The integrated-candidate commit to build/test/scan.

        Returns:
            The terminal :class:`CiRunResult` for the one triggered run.

        Raises:
            CiRunUnavailableError: Propagated from the backend (fail-closed).
        """
        key = (candidate.branch, candidate.commit_sha)
        cached = self._runs.get(key)
        if cached is not None:
            return cached
        result = self.backend.run_candidate(
            branch=candidate.branch, commit_sha=candidate.commit_sha
        )
        self._runs[key] = result
        return result


def _parse_report_task(text: str) -> dict[str, str]:
    """Parse a ``report-task.txt`` properties file into a dict."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        props[key.strip()] = value.strip()
    return props


@dataclass(frozen=True)
class JenkinsCiBackend:
    """Productive :class:`CiBackend` driving the thin Jenkins client.

    Triggers a parameterised build, polls it to a terminal state within a
    bounded timeout, then reads the run's archived ``report-task.txt`` to
    obtain the Sonar analysis reference THIS build emitted (never a stale
    local file). All failure modes fail closed via
    :class:`CiRunUnavailableError`.

    Attributes:
        client: The thin ``integrations.jenkins`` HTTP client (scoped token).
        pipeline: The Jenkins job/pipeline name to trigger.
        poll_timeout_seconds: Bounded wait for the build to reach terminal.
        poll_interval_seconds: Delay between status polls.
        branch_param: Build parameter name carrying the candidate branch.
        commit_param: Build parameter name carrying the candidate commit.
        sleep: Injected sleep (defaults to ``time.sleep``; tests pass a
            no-op to keep the poll loop instant).
        monotonic: Injected monotonic clock (defaults to ``time.monotonic``;
            tests pass a fake to drive the bounded timeout deterministically).
    """

    client: _JenkinsClientLike
    pipeline: str
    poll_timeout_seconds: int = 1800
    poll_interval_seconds: int = 10
    branch_param: str = "branch"
    commit_param: str = "commit_sha"
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    def run_candidate(self, *, branch: str, commit_sha: str) -> CiRunResult:
        """Trigger, await and read one candidate run (fail-closed)."""
        from agentkit.integration_clients.jenkins import JenkinsApiError

        try:
            build_number = self._trigger_and_resolve_build(
                branch=branch, commit_sha=commit_sha
            )
            status = self._await_terminal(build_number)
            report = self._read_run_report_task(build_number)
        except JenkinsApiError as exc:
            raise CiRunUnavailableError(
                f"Jenkins run for {branch}@{commit_sha} unavailable: {exc}"
            ) from exc
        result = str(status.get("result") or "")
        return CiRunResult(
            build_succeeded=result == "SUCCESS",
            result=result,
            # ERROR-A: a real report-task.txt carries only ceTaskId (NOT an
            # analysisId); the analysisId is resolved later via ce/task. We
            # never pretend to have an analysisId from the artefact.
            analysis_id=None,
            ce_task_id=report.get("ceTaskId") or None,
            component=report.get("projectKey") or None,
            # ERROR-2: a real report-task.txt has NO top-level ``branch`` key;
            # the analysed branch is proven from Sonar (the candidate-branch
            # scoped project_analyses/search), never read from the artefact.
            build_number=build_number,
            built_commit=_built_commit_from_status(status),
            scanner_version=_scanner_version_from_status(status),
        )

    def _trigger_and_resolve_build(self, *, branch: str, commit_sha: str) -> int:
        response = self.client.trigger_build(
            self.pipeline,
            parameters={self.branch_param: branch, self.commit_param: commit_sha},
        )
        location = response.headers.get("location", "")
        queue_id = _queue_id_from_location(location)
        if queue_id is None:
            raise CiRunUnavailableError(
                "Jenkins trigger returned no resolvable queue Location header"
            )
        return self._await_executable(queue_id)

    def _await_executable(self, queue_id: int) -> int:
        deadline = self.monotonic() + self.poll_timeout_seconds
        while True:
            body = self.client.queue_item(queue_id).json_body
            executable = body.get("executable")
            if isinstance(executable, dict):
                number = executable.get("number")
                if isinstance(number, int):
                    return number
            if body.get("cancelled") is True:
                raise CiRunUnavailableError(
                    f"Jenkins queue item {queue_id} was cancelled before start"
                )
            if self.monotonic() >= deadline:
                raise CiRunUnavailableError(
                    f"Jenkins queue item {queue_id} did not start within "
                    f"{self.poll_timeout_seconds}s (fail-closed timeout)"
                )
            self.sleep(self.poll_interval_seconds)

    def _await_terminal(self, build_number: int) -> Mapping[str, object]:
        deadline = self.monotonic() + self.poll_timeout_seconds
        while True:
            body = self.client.build_status(self.pipeline, build_number).json_body
            building = body.get("building")
            result = body.get("result")
            if building is False and result is not None:
                return body
            if self.monotonic() >= deadline:
                raise CiRunUnavailableError(
                    f"Jenkins build {self.pipeline}#{build_number} did not reach "
                    f"a terminal state within {self.poll_timeout_seconds}s "
                    "(fail-closed timeout)"
                )
            self.sleep(self.poll_interval_seconds)

    def _read_run_report_task(self, build_number: int) -> dict[str, str]:
        response = self.client.build_artifact(
            self.pipeline, build_number, REPORT_TASK_ARTIFACT
        )
        props = _parse_report_task(response.text_body)
        if not props.get("ceTaskId"):
            raise CiRunUnavailableError(
                f"Jenkins build {self.pipeline}#{build_number} archived no "
                "report-task with ceTaskId (no scan from this run, AG3-056 AC1)"
            )
        return props


class _JenkinsClientLike(Protocol):
    """Structural subset of ``integrations.jenkins.JenkinsClient`` used here.

    Declared so the productive backend depends on a Protocol (not the
    concrete client), keeping it unit-testable with a fake while the real
    wiring passes the genuine thin client.
    """

    def trigger_build(
        self, pipeline: str, *, parameters: Mapping[str, str]
    ) -> _HttpResponseLike:
        """Trigger a parameterised build; ``headers['location']`` => queue."""
        ...

    def queue_item(self, queue_id: int) -> _HttpResponseLike:
        """Read a queue item (``executable.number`` once scheduled)."""
        ...

    def build_status(self, pipeline: str, build_number: int) -> _HttpResponseLike:
        """Read a build's status (``building``/``result``)."""
        ...

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> _HttpResponseLike:
        """Fetch an archived artefact as raw ``text_body``."""
        ...


class _HttpResponseLike(Protocol):
    """Structural subset of ``JenkinsHttpResponse`` used by the backend."""

    @property
    def json_body(self) -> dict[str, object]:
        """Parsed JSON body."""
        ...

    @property
    def text_body(self) -> str:
        """Raw decoded text body."""
        ...

    @property
    def headers(self) -> dict[str, str]:
        """Lower-cased response headers."""
        ...


def _built_commit_from_status(status: Mapping[str, object]) -> str | None:
    """Read the commit Jenkins ACTUALLY built from a build-status body (FIX-3).

    Sourced ONLY from git-plugin EVIDENCE: ``actions[].lastBuiltRevision.SHA1``
    — the git plugin's record of the revision it actually checked out. A
    ``GIT_COMMIT`` build PARAMETER (``ParametersAction``/``parameters``) is a
    user-tweakable INPUT, not proof Jenkins built that commit, so it is
    deliberately NOT consulted (same evidence-not-input discipline as
    ``scanner_version``, round 5/6). Returns ``None`` when Jenkins exposed no
    built revision, so the runners fail closed (``built_commit_unknown``) rather
    than trusting the commit the build was *asked* to use.
    """
    actions = status.get("actions")
    if not isinstance(actions, list):
        return None
    for action in actions:
        if not isinstance(action, dict):
            continue
        sha = _last_built_sha(action)
        if sha:
            return sha
    return None


def _last_built_sha(action: Mapping[str, object]) -> str | None:
    last_built = action.get("lastBuiltRevision")
    if isinstance(last_built, dict):
        sha = last_built.get("SHA1")
        if isinstance(sha, str) and sha:
            return sha
    return None


def _scanner_version_from_status(status: Mapping[str, object]) -> str | None:
    """Read the run's SonarScanner version from a build-status body (ERROR-B).

    WARNING-1 / web-research residual: there is NO authoritative post-scan
    artifact carrying the scanner version. A real ``report-task.txt`` exposes
    only ``projectKey``/``serverUrl``/``serverVersion``/``ceTaskId``/
    ``ceTaskUrl`` — not the scanner version — and the SonarQube Web API
    (``project_status``/``ce/task``/``project_analyses``) exposes no scanner
    version for an analysis either. The scanner prints its version ONLY to the
    console log at scan start (``INFO: SonarScanner X.Y.Z``).

    Therefore the scanner version is sourced ONLY from the pipeline-CONTRIBUTED
    post-scan environment value, as a DOCUMENTED PIPELINE CONTRACT (never a
    user-tweakable input): the AK3 Jenkins pipeline MUST capture the REAL
    scanner version of the binary it invoked (e.g. parsed from the scanner log
    it just ran) and contribute it as the ``SONAR_SCANNER_VERSION`` environment
    entry AFTER the scan (an ``EnvironmentContributingAction`` map) — NOT as a
    build *parameter* the triggerer can set. A build PARAMETER is a tweakable
    INPUT, not evidence of the scanner binary that actually ran, so it is
    deliberately NOT consulted here. Sonar carries no authoritative scanner
    version, so this contributed run value IS the authoritative scanner version
    of the analysis (FK-33 §33.6.3). Returns ``None`` when the run contributed
    none, so the scan runner fails closed (never a placeholder in a produced
    attestation) — the residual risk that a misconfigured pipeline contributes
    a wrong value is a pipeline-contract concern, not an AK3 fail-open.
    """
    actions = status.get("actions")
    if not isinstance(actions, list):
        return None
    # ONLY the pipeline-contributed environment value (archived post-scan
    # evidence). A build PARAMETER (user-tweakable input) is intentionally NOT
    # accepted as scanner-binary evidence.
    return _env_value(actions, "SONAR_SCANNER_VERSION")


def _env_value(actions: list[object], name: str) -> str | None:
    """Read ``name`` from a Jenkins action's contributed environment map."""
    for action in actions:
        if isinstance(action, dict):
            direct = action.get(name)
            if isinstance(direct, str) and direct:
                return direct
    return None


def _queue_id_from_location(location: str) -> int | None:
    """Extract the trailing queue id from a Jenkins ``Location`` header."""
    if not location:
        return None
    parts = [part for part in location.rstrip("/").split("/") if part]
    if not parts:
        return None
    tail = parts[-1]
    return int(tail) if tail.isdigit() else None


__all__ = [
    "REPORT_TASK_ARTIFACT",
    "CandidateRunCache",
    "CiBackend",
    "CiRunResult",
    "CiRunUnavailableError",
    "JenkinsCiBackend",
]
