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

from agentkit.integrations.sonar import SonarApiError
from agentkit.verify_system.sonarqube_gate.applicability import (
    SonarApplicability,
    resolve_applicability,
)
from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation
from agentkit.verify_system.sonarqube_gate.errors import ReconcilerApplyError
from agentkit.verify_system.sonarqube_gate.port import (
    PostApplyGateState,
    SonarGateInputs,
)
from agentkit.verify_system.sonarqube_gate.reconciler import SonarIssue

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.config.models import SonarQubeConfig
    from agentkit.integrations.sonar import SonarClient
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger

logger = logging.getLogger(__name__)

#: Sonar transition that moves an issue into the ``Accepted`` resolution.
_ACCEPT_TRANSITION = "accept"
#: Tag attached to issues accepted via the deterministic ledger reconciler.
_LEDGER_TAG = "ak3-accepted-ledger"


@dataclass(frozen=True)
class BoundAnalysis:
    """The commit-bound analysis coordinates for the final branch scan.

    Resolved from the scanner ``report-task.txt`` (``sonar.qualitygate.wait``)
    plus git — never a bare ``projectKey`` live-read (FK-33 §33.6.3).

    Attributes:
        analysis_id: SonarQube analysis identifier (preferred binding key).
        ce_task_id: Compute-Engine task identifier.
        component: Sonar component/project key for issue search.
        branch: Branch name measured by the Community Branch Plugin.
        commit_sha: Git commit the scan was bound to.
        tree_hash: Git tree hash the scan was bound to.
    """

    analysis_id: str
    ce_task_id: str
    component: str
    branch: str
    commit_sha: str
    tree_hash: str


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
        analysis = self.bound_analysis
        try:
            status_body = self.client.project_status(
                analysis_id=analysis.analysis_id, ce_task_id=analysis.ce_task_id
            ).json_body
            open_issues = self._read_open_issues()
        except SonarApiError as exc:
            raise ValueError(f"post-apply Sonar re-read failed: {exc}") from exc
        return PostApplyGateState(
            quality_gate_status=_quality_gate_status(status_body),
            overall_open_issue_count=len(open_issues),
        )

    def _read_attestation(self) -> SonarAttestation:
        analysis = self.bound_analysis
        status_body = self.client.project_status(
            analysis_id=analysis.analysis_id, ce_task_id=analysis.ce_task_id
        ).json_body
        revision = self._read_last_analyzed_revision(analysis)
        plugin_version = self.config.plugins.community_branch.min_version
        return SonarAttestation(
            commit_sha=analysis.commit_sha,
            tree_hash=analysis.tree_hash,
            analysis_id=analysis.analysis_id,
            ce_task_id=analysis.ce_task_id,
            quality_gate_status=_quality_gate_status(status_body),
            quality_gate_hash=_str(status_body, "qualityGateHash"),
            quality_profile_hash=_str(status_body, "qualityProfileHash"),
            analysis_scope_hash=_str(status_body, "analysisScopeHash"),
            new_code_definition=_new_code_definition(status_body),
            exception_ledger_hash=self.ledger.content_hash(),
            last_analyzed_revision=revision,
            sonarqube_version=self._read_server_version(),
            branch_plugin_version=plugin_version,
            scanner_version=_str(status_body, "scannerVersion"),
            status="READ",
        )

    def _read_last_analyzed_revision(self, analysis: BoundAnalysis) -> str:
        body = self.client.component_revision(
            analysis.component, branch=analysis.branch
        ).json_body
        component = body.get("component")
        if isinstance(component, dict):
            value = component.get("analysisRevision") or component.get("version")
            if isinstance(value, str) and value:
                return value
        # Fail-closed: an absent revision must not silently pass the stale
        # check; bind to the scan's commit so the gate compares it to HEAD.
        return analysis.commit_sha

    def _read_server_version(self) -> str:
        body = self.client.system_status().json_body
        return _str(body, "version")

    def _read_open_issues(self) -> tuple[SonarIssue, ...]:
        analysis = self.bound_analysis
        body = self.client.search_issues(
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

    def _apply_accepted_issue(self, issue_key: str) -> None:
        """Transition a single-matched issue to ``Accepted`` (scoped token).

        FK-33 §33.6.4: the deterministic reconciler — not the worker —
        applies the exception. A failed transition is fail-closed.
        """
        try:
            self.client.transition_issue(issue_key, _ACCEPT_TRANSITION)
            self.client.set_issue_tags(issue_key, _LEDGER_TAG)
        except SonarApiError as exc:
            raise ReconcilerApplyError(
                f"could not transition issue {issue_key!r} to Accepted "
                f"(FK-33 §33.6.4): {exc}"
            ) from exc


def _quality_gate_status(status_body: dict[str, Any]) -> str:
    project_status = status_body.get("projectStatus")
    if isinstance(project_status, dict):
        status = project_status.get("status")
        if isinstance(status, str) and status:
            return status
    raise SonarApiError("qualitygates/project_status returned no projectStatus.status")


def _new_code_definition(status_body: dict[str, Any]) -> str:
    project_status = status_body.get("projectStatus")
    if isinstance(project_status, dict):
        period = project_status.get("period") or project_status.get("periods")
        if isinstance(period, dict):
            mode = period.get("mode")
            if isinstance(mode, str):
                return mode
    return ""


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
]
