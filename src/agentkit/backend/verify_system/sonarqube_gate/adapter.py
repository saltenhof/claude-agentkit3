"""Productive ``SonarGateInputPort`` adapter (FK-33 §33.6, AG3-052 E1/E4).

Translates the live environment (FK-03 config + ``integrations.sonar``
client + accepted-exception ledger + scanner report-task + git HEAD) into
:class:`SonarGateInputs` for an APPLICABLE QA-subflow run, and supplies the
deterministic reconciler's ``Administer Issues`` applier so a single-matched
exception is ACTUALLY transitioned to ``Accepted`` in Sonar (E4) — the
worker never holds issue-admin rights; the scoped token lives only here.

Fail-closed (FK-33 §33.6.5, "absent != broken"): when the gate is
APPLICABLE (``sonarqube.available == true`` AND ``fast is False`` AND the
story is code-producing), ANY read failure — unreachable API, unreadable
attestation, missing report-task, ledger load error — resolves to an
APPLICABLE input with ``attestation = None``, which the gate turns into a
fail-closed BLOCK. It is NEVER downgraded to not-applicable. A deliberately
absent Sonar (``available == false``) is resolved not-applicable by the
composition-root builder, which then wires the absent default port instead
of this adapter.

The thin HTTP boundary stays in ``integrations.sonar`` (CLAUDE.md:
integrations = thin adapters). This module is capability orchestration and
lives in ``verify_system``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentkit.backend.verify_system.sonarqube_gate.applicability import (
    SonarApplicability,
    resolve_applicability,
)
from agentkit.backend.verify_system.sonarqube_gate.attestation import SonarAttestation
from agentkit.backend.verify_system.sonarqube_gate.errors import ReconcilerApplyError
from agentkit.backend.verify_system.sonarqube_gate.integrity_hashes import (
    compute_analysis_scope_hash,
    compute_quality_gate_hash,
    compute_quality_profile_hash,
)
from agentkit.backend.verify_system.sonarqube_gate.port import (
    PostApplyGateState,
    SonarGateInputs,
)
from agentkit.backend.verify_system.sonarqube_gate.reconciler import SonarIssue
from agentkit.integration_clients.sonar import SonarApiError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
    from agentkit.integration_clients.sonar import SonarClient

logger = logging.getLogger(__name__)

#: Sonar transition that moves an issue into the ``Accepted`` resolution.
_ACCEPT_TRANSITION = "accept"
#: Tag attached to issues accepted via the deterministic ledger reconciler.
_LEDGER_TAG = "ak3-accepted-ledger"


@dataclass(frozen=True)
class BoundAnalysis:
    """The commit-bound analysis coordinates for the final branch scan.

    Resolved from the scanner ``report-task.txt`` (``sonar.qualitygate.wait``)
    plus git — never a bare ``projectKey`` live-read (FK-33 §33.6.3). A real
    ``report-task.txt`` carries only ``ceTaskId`` (plus projectKey/branch/...),
    NOT an ``analysisId``: the analysisId is a property of the Compute-Engine
    task and is resolved at attestation time via ``api/ce/task`` (ERROR-A).

    Attributes:
        ce_task_id: Compute-Engine task identifier (from ``report-task.txt``;
            the authoritative key to resolve the analysisId).
        component: Sonar component/project key for issue search.
        branch: Branch name measured by the Community Branch Plugin.
        commit_sha: Git commit the scan was bound to.
        tree_hash: Git tree hash the scan was bound to.
        scanner_version: SonarScanner version of the run that produced this
            analysis. Sonar exposes NO authoritative scanner version for an
            analysis (``project_status``/``ce/task`` do not carry it), so it is
            carried authoritatively from the run that produced the analysis
            (FK-33 §33.6.3 names it; ERROR-B). Empty when the producer could
            not supply it — the attestation build then fails closed.
    """

    ce_task_id: str
    component: str
    branch: str
    commit_sha: str
    tree_hash: str
    scanner_version: str


@dataclass(frozen=True)
class ConfiguredSonarGateInputPort:
    """Productive ``SonarGateInputPort`` for an ``available == true`` project.

    Attributes:
        config: The resolved ``sonarqube`` config stanza.
        client: Thin ``integrations.sonar`` HTTP client (scoped token).
        fast: Whether the run is in ``fast`` mode (FK-24 §24.3.3) — the
            SEPARATE fast/standard axis, NOT ``execution_route``. A genuine
            ``fast`` run resolves NOT_APPLICABLE_FAST (stage drops); the
            builder normally routes fast away before this adapter is built.
        story_type: Resolved story type.
        ledger: The loaded accepted-exception ledger.
        bound_analysis: The commit-bound analysis coordinates.
        main_head_revision: Authoritative current main HEAD (stale-check).
    """

    config: SonarQubeConfig
    client: SonarClient
    fast: bool
    story_type: StoryType
    ledger: AcceptedExceptionLedger
    bound_analysis: BoundAnalysis
    main_head_revision: str

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:
        """Resolve the gate inputs for the QA-subflow run (fail-closed)."""
        del story_dir  # Coordinates were resolved at construction time.
        applicability = resolve_applicability(
            available=self.config.available,
            fast=self.fast,
            story_type=self.story_type,
        )
        if applicability is not SonarApplicability.APPLICABLE:
            # available==false / fast=True / non-code-producing: not this adapter's
            # job to fail-closed. (The builder wires the absent port for
            # available==false; fast/non-code-producing simply skip/drop.)
            return SonarGateInputs(applicability=applicability)
        try:
            return self._resolve_applicable_inputs()
        except (SonarApiError, OSError, KeyError, ValueError) as exc:
            # Configured-but-unreachable => fail-closed (attestation=None),
            # NEVER not-applicable (FK-33 §33.6.5 "absent != broken").
            logger.error(
                "sonarqube_gate inputs unreadable for story=%s; APPLICABLE "
                "fail-closed (attestation=None): %s",
                story_id,
                exc,
            )
            return SonarGateInputs(applicability=SonarApplicability.APPLICABLE)

    def _resolve_applicable_inputs(self) -> SonarGateInputs:
        attestation = self._read_attestation()
        issues = self._read_open_issues()
        # E4: the gate matches the ledger against the PRE-apply ``issues`` and
        # then RE-READS the post-apply quality gate + open count via
        # ``post_apply_reader`` (NO AK subtraction). Sonar recomputes the gate
        # after the accepts; AK only reads the new verdict.
        return SonarGateInputs(
            applicability=SonarApplicability.APPLICABLE,
            attestation=attestation,
            main_head_revision=self.main_head_revision,
            ledger_entries=self.ledger.entries,
            current_issues=issues,
            issue_applier=self._apply_accepted_issue,
            post_apply_reader=self._read_post_apply_state,
        )

    def _read_post_apply_state(self) -> PostApplyGateState:
        """RE-READ the post-apply quality gate + open count (AG3-052 E4).

        Called by the gate AFTER the reconciler transitioned the
        single-matched issues to ``Accepted``. SonarQube has recomputed the
        quality gate itself (Accepted issues no longer count); this re-reads
        the NEW verdict (``project_status`` per ``analysisId``/``ceTaskId``)
        and the NEW open-non-accepted count (``issues/search?resolved=false``)
        so the gate evaluates green against the real post-apply state. AK
        interprets no individual QG rules.

        Returns:
            The :class:`PostApplyGateState` (fresh QG status + open count).

        Raises:
            ValueError: When the post-apply re-read against Sonar fails
                (configured-but-unreachable). Surfaced as ``ValueError`` so
                the gate's fail-closed boundary handles it without importing
                ``integrations.sonar`` (the gate catches ``OSError/ValueError``
                from the re-read => terminal ``failed``).
        """
        return read_post_apply_state(self.client, self.bound_analysis)

    def _read_attestation(self) -> SonarAttestation:
        return read_commit_bound_attestation(
            self.client,
            self.config,
            self.bound_analysis,
            exception_ledger_hash=self.ledger.content_hash(),
        )

    def _read_open_issues(self) -> tuple[SonarIssue, ...]:
        return read_open_issues(self.client, self.bound_analysis)

    def _apply_accepted_issue(self, issue_key: str) -> None:
        """Transition a single-matched issue to ``Accepted`` (scoped token).

        FK-33 §33.6.4: the deterministic reconciler — not the worker —
        applies the exception. A failed transition is fail-closed.
        """
        build_issue_applier(self.client)(issue_key)


def read_open_issues(
    client: SonarClient, analysis: BoundAnalysis
) -> tuple[SonarIssue, ...]:
    """Read the current open (non-accepted) issues for a bound analysis.

    Reused by AG3-052's gate-input adapter and the AG3-056 pre-merge scan
    runner so there is ONE ``issues/search`` truth (no second Sonar truth).
    The query is scoped to the analysis ``component`` + ``branch`` and to
    ``resolved=false`` (the pre-apply scan view the reconciler matches the
    ledger against, and — re-read post-apply — the open-non-accepted count).

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        analysis: The commit-bound analysis coordinates.

    Returns:
        The current open issues as transport-neutral :class:`SonarIssue`.

    Raises:
        SonarApiError: On an unreachable API or a malformed ``issues`` body.
    """
    body = client.search_issues(
        {
            "componentKeys": analysis.component,
            "branch": analysis.branch,
            "resolved": "false",
            "ps": "500",
        }
    ).json_body
    raw_issues = body.get("issues", [])
    if not isinstance(raw_issues, list):
        raise SonarApiError("issues/search returned a non-list 'issues' body")
    return tuple(_to_sonar_issue(entry) for entry in raw_issues)


def read_post_apply_state(
    client: SonarClient, analysis: BoundAnalysis
) -> PostApplyGateState:
    """RE-READ the post-apply quality gate + open count (AG3-052 E4).

    Reused by AG3-052's gate-input adapter and the AG3-056 pre-merge scan
    runner so the post-apply re-read is ONE truth. Resolves the analysisId,
    reads the recomputed ``project_status`` verdict and the fresh
    open-non-accepted count.

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        analysis: The commit-bound analysis coordinates.

    Returns:
        The :class:`PostApplyGateState` (fresh QG status + open count).

    Raises:
        ValueError: When the post-apply re-read against Sonar fails
            (configured-but-unreachable). Surfaced as ``ValueError`` so the
            gate's fail-closed boundary handles it without importing
            ``integrations.sonar``.
    """
    try:
        analysis_id = resolve_analysis_id(client, analysis.ce_task_id)
        status_body = client.project_status(analysis_id=analysis_id).json_body
        open_issues = read_open_issues(client, analysis)
    except SonarApiError as exc:
        raise ValueError(f"post-apply Sonar re-read failed: {exc}") from exc
    return PostApplyGateState(
        quality_gate_status=_quality_gate_status(status_body),
        overall_open_issue_count=len(open_issues),
    )


def _quality_gate_status(status_body: dict[str, Any]) -> str:
    project_status = status_body.get("projectStatus")
    if isinstance(project_status, dict):
        status = project_status.get("status")
        if isinstance(status, str) and status:
            return status
    raise SonarApiError("qualitygates/project_status returned no projectStatus.status")


#: Terminal Compute-Engine task status that carries a usable ``analysisId``.
_CE_TASK_SUCCESS = "SUCCESS"


def resolve_analysis_id(client: SonarClient, ce_task_id: str) -> str:
    """Resolve the real ``analysisId`` from a ``ceTaskId`` (ERROR-A, fail-closed).

    A real SonarScanner ``report-task.txt`` carries only ``ceTaskId`` — the
    ``analysisId`` is a property of the Compute-Engine task and only exists once
    the task has terminated successfully. This calls ``api/ce/task`` and returns
    the analysisId ONLY when the task reached terminal ``SUCCESS`` and carries a
    non-empty ``analysisId``. A pending / in-progress / failed / canceled task,
    or a successful task without an analysisId, fails closed.

    Shared by AG3-052's gate adapter and the AG3-056 pre-merge scan runner so
    there is ONE analysisId-resolution truth (no second Sonar truth).

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        ce_task_id: The Compute-Engine task id from ``report-task.txt``.

    Returns:
        The non-empty Sonar ``analysisId`` of the successful analysis.

    Raises:
        SonarApiError: When ``ce_task_id`` is empty, the task is not terminal
            SUCCESS, or it carries no analysisId (fail-closed; no shortcut that
            treats the ceTaskId itself as an analysisId).
    """
    if not ce_task_id:
        raise SonarApiError(
            "cannot resolve an analysisId without a ceTaskId "
            "(FK-33 §33.6.3, fail-closed)"
        )
    task = client.ce_task(ce_task_id).json_body.get("task")
    if not isinstance(task, dict):
        raise SonarApiError(
            f"ce/task returned no task object for ceTaskId={ce_task_id!r} "
            "(fail-closed)"
        )
    status = task.get("status")
    if status != _CE_TASK_SUCCESS:
        raise SonarApiError(
            f"ce/task for ceTaskId={ce_task_id!r} is not terminal SUCCESS "
            f"(status={status!r}); the analysis is not gatable (fail-closed)"
        )
    analysis_id = task.get("analysisId")
    if not isinstance(analysis_id, str) or not analysis_id:
        raise SonarApiError(
            f"ce/task SUCCESS for ceTaskId={ce_task_id!r} carried no analysisId "
            "(cannot bind the analysis; fail-closed)"
        )
    return analysis_id


def read_last_analyzed_revision(
    client: SonarClient, analysis: BoundAnalysis, analysis_id: str
) -> str:
    """Read the git revision SONAR reports for a bound analysis (FK-33 §33.6.3).

    Authoritative source: the revision the analysis actually measured, read
    from Sonar via ``api/project_analyses/search`` and matched STRICTLY by the
    analysis ``key == analysis_id`` — NEVER the project-version string, NEVER a
    single-entry fallback, and NEVER a local fabrication (ERROR-A).

    Shared by AG3-052's gate-input adapter and the AG3-056 pre-merge scan
    runner so there is ONE revision-binding truth (no second Sonar truth).

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        analysis: The commit-bound analysis coordinates.
        analysis_id: The REAL analysisId (resolved via :func:`resolve_analysis_id`).

    Returns:
        The git revision the analysis measured.

    Raises:
        SonarApiError: When Sonar reports no analysis whose ``key`` matches
            ``analysis_id``, or no revision (fail-closed — no local
            ``commit_sha`` fallback, FIX-2; no single-entry fallback, ERROR-A).
    """
    body = client.project_analyses_search(
        analysis.component, branch=analysis.branch
    ).json_body
    revision = _revision_for_analysis(body, analysis_id)
    if not revision:
        raise SonarApiError(
            "project_analyses/search reported no revision for "
            f"analysisId={analysis_id!r} on branch "
            f"{analysis.branch!r}; cannot prove the commit binding "
            "(FK-33 §33.6.3, fail-closed — strict key match, no fallback)"
        )
    return revision


def read_commit_bound_attestation(
    client: SonarClient,
    config: SonarQubeConfig,
    analysis: BoundAnalysis,
    *,
    exception_ledger_hash: str,
) -> SonarAttestation:
    """Build a COMPLETE commit-bound ``SonarAttestation`` (FK-33 §33.6.3).

    The single attestation-construction truth reused by both AG3-052's gate
    adapter and the AG3-056 pre-merge scan runner (FIX-4 / ERROR-A / ERROR-B —
    no hand-rolled partial attestation, no second Sonar truth). Every field is
    sourced authoritatively from where Sonar actually exposes it:

    * ``analysis_id`` resolved from ``analysis.ce_task_id`` via ``api/ce/task``
      (terminal SUCCESS + non-empty analysisId, :func:`resolve_analysis_id`);
    * ``quality_gate_status`` / ``new_code_definition`` from
      ``api/qualitygates/project_status`` (by the resolved ``analysisId``);
    * ``quality_gate_hash`` / ``quality_profile_hash`` / ``analysis_scope_hash``
      COMPUTED deterministically from ``api/qualitygates/get_by_project`` +
      ``show`` / ``api/qualityprofiles/search`` / ``api/settings/values``
      (the ``project_status`` response carries NO such fields, ERROR-B);
    * ``last_analyzed_revision`` from ``api/project_analyses/search``
      (:func:`read_last_analyzed_revision`, strict-match, fail-closed);
    * ``sonarqube_version`` from ``api/system/status``;
    * ``branch_plugin_version`` from config;
    * ``scanner_version`` from the run that produced the analysis
      (``analysis.scanner_version``; Sonar exposes none — ERROR-B);
    * ``commit_sha`` / ``tree_hash`` from the (already proven) bound analysis;
    * ``exception_ledger_hash`` from the ledger actually used.

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        config: The resolved ``sonarqube`` config stanza.
        analysis: The commit-bound analysis coordinates (``commit_sha`` and
            ``tree_hash`` MUST already be proven by the caller; ``ce_task_id``
            and ``scanner_version`` come from the producing run).
        exception_ledger_hash: Content hash of the accepted-exception ledger
            actually used for this analysis.

    Returns:
        A complete :class:`SonarAttestation` (``status="READ"``).

    Raises:
        SonarApiError: On any unreachable/malformed Sonar read, a non-terminal
            CE task, a missing revision, or an unsourceable required field
            (fail-closed; never empty-string-stamped).
    """
    if not analysis.scanner_version:
        raise SonarApiError(
            "no authoritative scanner_version for the analysis of "
            f"ceTaskId={analysis.ce_task_id!r}; Sonar exposes none and the "
            "producing run supplied none (FK-33 §33.6.3, fail-closed — never "
            "a placeholder scanner version in a produced attestation)"
        )
    analysis_id = resolve_analysis_id(client, analysis.ce_task_id)
    status_body = client.project_status(analysis_id=analysis_id).json_body
    revision = read_last_analyzed_revision(client, analysis, analysis_id)
    server_version = _required_server_version(client)
    return SonarAttestation(
        commit_sha=analysis.commit_sha,
        tree_hash=analysis.tree_hash,
        analysis_id=analysis_id,
        ce_task_id=analysis.ce_task_id,
        quality_gate_status=_quality_gate_status(status_body),
        quality_gate_hash=compute_quality_gate_hash(client, analysis.component),
        quality_profile_hash=compute_quality_profile_hash(client, analysis.component),
        analysis_scope_hash=compute_analysis_scope_hash(client, analysis.component),
        new_code_definition=_new_code_definition(status_body),
        exception_ledger_hash=exception_ledger_hash,
        last_analyzed_revision=revision,
        sonarqube_version=server_version,
        branch_plugin_version=config.plugins.community_branch.min_version,
        scanner_version=analysis.scanner_version,
        status="READ",
    )


def _revision_for_analysis(body: dict[str, Any], analysis_id: str) -> str:
    """Return the git revision the given analysis measured (FK-33 §33.6.3).

    Matches the analysis STRICTLY by ``key == analysis_id`` in an
    ``api/project_analyses/search`` body and returns its ``revision``. There is
    NO single-entry fallback (ERROR-A: against real Sonar the analyses list may
    carry many entries and the binding proof must be exact). Returns the empty
    string when no entry's key matches so the caller fails closed.
    """
    analyses = body.get("analyses")
    if not isinstance(analyses, list):
        return ""
    for entry in analyses:
        if isinstance(entry, dict) and entry.get("key") == analysis_id:
            revision = entry.get("revision")
            return revision if isinstance(revision, str) else ""
    return ""


def _new_code_definition(status_body: dict[str, Any]) -> str:
    """Read the new-code-definition mode from a REAL ``project_status`` body.

    The real SonarQube ``api/qualitygates/project_status`` response carries the
    new-code reference as ``projectStatus.periods`` — an ARRAY of
    ``{index, mode, date, parameter}`` entries (newer servers; the first entry
    describes the active new-code period). Older servers (<= 6.x) expose a
    SINGLE ``projectStatus.period`` object of the same shape, which is still
    accepted. The ``mode`` (e.g. ``PREVIOUS_VERSION`` / ``NUMBER_OF_DAYS`` /
    ``REFERENCE_BRANCH``) is the new-code definition.

    ``new_code_definition`` is a first-class attribute of the formal
    ``deterministic-checks.entity.sonar-attestation`` entity and a MANDATORY
    READ binding (see ``attestation._MANDATORY_READ_FIELDS``). A code-producing
    project under the Sonar gate always has an active new-code period, so when
    neither the real ``periods[]`` array nor the legacy ``period`` dict yields
    a non-empty ``mode`` this fails closed rather than stamping ``""`` — the
    absence is a broken precondition, not a silent empty (ERROR-1).

    Raises:
        SonarApiError: When no non-empty new-code ``mode`` can be sourced from
            ``projectStatus.periods`` (or the legacy ``period``); fail-closed.
    """
    project_status = status_body.get("projectStatus")
    if isinstance(project_status, dict):
        mode = _new_code_mode_from_project_status(project_status)
        if mode:
            return mode
    raise SonarApiError(
        "qualitygates/project_status carried no new-code period mode "
        "(neither projectStatus.periods[] nor the legacy projectStatus.period "
        "yielded a non-empty mode); cannot bind new_code_definition "
        "(FK-33 §33.6.3, fail-closed — ERROR-1)"
    )


def _new_code_mode_from_project_status(project_status: dict[str, Any]) -> str:
    """Return the new-code mode from current or legacy project-status shapes."""
    return _mode_from_periods(project_status.get("periods")) or _mode_from_period(
        project_status.get("period")
    )


def _mode_from_periods(periods: object) -> str:
    """Return the first non-empty mode from a Sonar ``periods`` array."""
    if not isinstance(periods, list):
        return ""
    for entry in periods:
        mode = _mode_from_period(entry)
        if mode:
            return mode
    return ""


def _mode_from_period(period: object) -> str:
    """Return a non-empty Sonar period mode, or ``""`` when absent/malformed."""
    if not isinstance(period, dict):
        return ""
    mode = period.get("mode")
    return mode if isinstance(mode, str) and mode else ""


def _required_server_version(client: SonarClient) -> str:
    """Read the SonarQube server version, failing closed when absent (ERROR-1).

    ``sonarqube_version`` is a mandatory FK-33 §33.6.3 binding. The real
    ``api/system/status`` response carries ``{id, version, status}``; a body
    with no non-empty ``version`` cannot back a complete attestation, so this
    raises rather than stamping ``""`` (which would otherwise pass silently).
    """
    version = client.system_status().json_body.get("version")
    if not isinstance(version, str) or not version:
        raise SonarApiError(
            "api/system/status carried no version; cannot bind "
            "sonarqube_version (FK-33 §33.6.3, fail-closed — ERROR-1)"
        )
    return version


def _str(body: dict[str, Any], key: str) -> str:
    value = body.get(key, "")
    return value if isinstance(value, str) else str(value)


def _to_sonar_issue(entry: object) -> SonarIssue:
    if not isinstance(entry, dict):
        raise SonarApiError("issues/search entry is not an object")
    return SonarIssue(
        issue_key=_str(entry, "key"),
        rule_key=_str(entry, "rule"),
        normalized_code_fingerprint=_str(entry, "hash"),
        message=_str(entry, "message"),
    )


def build_issue_applier(client: SonarClient) -> Callable[[str], None]:
    """Build a standalone ``Administer Issues`` applier (for consumers).

    AG3-034 / Closure (AC8) can reuse the same scoped-token transition
    without reconstructing the full adapter.

    Args:
        client: Thin ``integrations.sonar`` client with a scoped token.

    Returns:
        A callable transitioning one issue to ``Accepted`` (fail-closed).
    """

    def _apply(issue_key: str) -> None:
        try:
            client.transition_issue(issue_key, _ACCEPT_TRANSITION)
            client.set_issue_tags(issue_key, _LEDGER_TAG)
        except SonarApiError as exc:
            raise ReconcilerApplyError(
                f"could not transition issue {issue_key!r} to Accepted: {exc}"
            ) from exc

    return _apply


__all__ = [
    "BoundAnalysis",
    "ConfiguredSonarGateInputPort",
    "build_issue_applier",
    "read_commit_bound_attestation",
    "read_last_analyzed_revision",
    "read_open_issues",
    "read_post_apply_state",
    "resolve_analysis_id",
]
