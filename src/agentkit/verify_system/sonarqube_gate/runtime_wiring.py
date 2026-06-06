"""Per-run wiring of the productive ``sonarqube_gate`` port (FK-33 §33.6, E1).

This is the ONE place that turns a live run into a productive
:class:`SonarGateInputPort` at the QA-subflow gate point (the only
lifecycle anchor AG3-052 owns; Setup-green-main/Closure stay OOS §2.2).

It resolves the per-run coordinates the
:class:`ConfiguredSonarGateInputPort` needs:

* the commit-bound :class:`BoundAnalysis` from the scanner ``report-task``
  artefact (``sonar.qualitygate.wait``) plus the worktree git HEAD — never
  a bare ``projectKey`` live-read (FK-33 §33.6.3);
* the loaded accepted-exception ledger;
* the authoritative main HEAD revision (stale check).

FAIL-CLOSED (FK-33 §33.6.5 "absent != broken", Story §1/§2.1.5/AC6): when
the gate is APPLICABLE (``sonarqube.available == true`` AND ``mode != fast``
— the fast axis lives on ``StoryContext.mode``, FK-24 §24.3.3, NOT
``execution_route`` — AND code-producing story) but the coordinates are
MISSING or UNREADABLE,
this returns a port that resolves to ``APPLICABLE`` with ``attestation =
None`` — which the gate turns into a fail-closed BLOCK. It is NEVER
downgraded to a silent not-applicable skip.

When ``sonarqube.available == false`` (or there is no sonarqube stanza, or
the story is non-code-producing), this returns ``None`` so the caller wires
the absent default port (deliberate, declared absence => stage SKIP).

OUT OF SCOPE (§2.2): provisioning/running the live scanner and the
SonarQube server. This module only CONSUMES the scan artefact a prior
(OOS) scanner step produced and fails closed when it is absent.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.verify_system.sonarqube_gate.adapter import (
    BoundAnalysis,
    ConfiguredSonarGateInputPort,
)
from agentkit.verify_system.sonarqube_gate.applicability import (
    SonarApplicability,
    resolve_applicability,
)
from agentkit.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
from agentkit.verify_system.sonarqube_gate.port import (
    SonarGateInputPort,
    SonarGateInputs,
)

if TYPE_CHECKING:
    from agentkit.config.models import SonarQubeConfig
    from agentkit.integrations.sonar import SonarClient
    from agentkit.story_context_manager.models import StoryContext

logger = logging.getLogger(__name__)

#: Standard SonarScanner output, relative to the scanned repo/worktree root.
_REPORT_TASK_REL = Path(".scannerwork") / "report-task.txt"
#: Repo-relative accepted-exception ledger artefact (FK-33 §33.6.4, FK-71).
_LEDGER_REL = Path(".agentkit") / "sonar" / "accepted-exceptions.json"
#: Reference branch the gate stale-checks against (FK-33 §33.6.3).
_MAIN_BRANCH = "main"


class SonarCoordinatesUnavailableError(Exception):
    """The per-run Sonar coordinates could not be resolved (fail-closed).

    Raised internally when an APPLICABLE gate's scan artefact / ledger / git
    HEAD is missing or unreadable. The caller converts this into a
    fail-closed APPLICABLE port (``attestation = None``) — NEVER a silent
    not-applicable skip (FK-33 §33.6.5).
    """


class _FailClosedApplicablePort:
    """APPLICABLE port that always fails closed (coordinates unresolvable).

    FK-33 §33.6.5 "configured-but-unreachable stays APPLICABLE and blocks":
    a missing/unreadable scan artefact for an ``available == true`` run is a
    broken precondition, NOT a deliberate absence. Resolving APPLICABLE with
    ``attestation = None`` routes the gate directly into the terminal
    ``failed`` (``attestation_unreadable``).
    """

    __slots__ = ("_reason",)

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:
        """Return APPLICABLE inputs with no attestation (fail-closed)."""
        del story_dir
        logger.error(
            "sonarqube_gate APPLICABLE fail-closed for story=%s: %s "
            "(attestation=None; never silently not-applicable, FK-33 §33.6.5)",
            story_id,
            self._reason,
        )
        return SonarGateInputs(applicability=SonarApplicability.APPLICABLE)


class _NotApplicableFastPort:
    """Port that genuinely resolves ``NOT_APPLICABLE_FAST`` (AG3-052 E2).

    A ``mode == fast`` run is a REAL fast resolution at the anchor: the
    ``sonarqube_gate`` stage drops entirely (the caller returns ``None`` from
    ``run_sonarqube_gate_stage`` — no LayerResult, no Sonar artefact). This
    is runtime DISTINGUISHABLE from ``available == false`` (which resolves
    ``NOT_APPLICABLE_UNAVAILABLE`` via the absent default port).

    The full fast-mode QA-subflow terminal (skipping the Policy Engine via
    the Layer-1 tests-green floor) is FK-24 §24.3.4 / FK-27 §27.6a — NOT
    AG3-052. This port only carries AG3-052's own contract: the genuine fast
    DROP of the Sonar stage (AC6, state-machine fast path).
    """

    __slots__ = ()

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:
        """Return NOT_APPLICABLE_FAST inputs (stage drops at the caller)."""
        del story_id, story_dir
        return SonarGateInputs(applicability=SonarApplicability.NOT_APPLICABLE_FAST)


def build_sonar_gate_port_for_run(
    config: SonarQubeConfig | None,
    story_context: StoryContext,
    story_dir: Path,
    *,
    token: str | None = None,
) -> SonarGateInputPort | None:
    """Build the productive ``sonarqube_gate`` port for one QA-subflow run.

    Args:
        config: The resolved ``sonarqube`` config stanza (``None`` when the
            project omits it — only legal for non-code-producing projects,
            see ``ProjectConfig`` E6 rule).
        story_context: The run's :class:`StoryContext` (story type + mode +
            project root + worktree path).
        story_dir: The story working directory (state/ledger root).
        token: The resolved Sonar token (from ``config.token_env`` via the
            secret store/env). When ``None`` the env var is read here.

    Returns:
        * ``None`` when the gate is NOT applicable as a DELIBERATE,
          declared absence — no stanza, ``available == false``, or a
          non-code-producing story resolving ``NOT_APPLICABLE_UNAVAILABLE``.
          The caller then wires the absent default port (=> stage SKIP).
        * a :class:`_NotApplicableFastPort` when ``mode == fast`` (AG3-052
          E2): a GENUINE fast resolution at the anchor (stage drops), runtime
          distinguishable from ``available == false``/UNAVAILABLE.
        * a productive :class:`ConfiguredSonarGateInputPort` when the gate is
          APPLICABLE and the coordinates resolve.
        * a fail-closed APPLICABLE port (``attestation = None``) when the gate
          is APPLICABLE but the coordinates are missing/unreadable — NEVER a
          silent not-applicable (FK-33 §33.6.5).
    """
    if config is None or not config.available:
        # No stanza / declared-absent => deliberate skip; caller uses absent
        # default port (NOT_APPLICABLE_UNAVAILABLE). Note: even fast mode is
        # a declared-absent skip here (no Sonar configured at all), so there
        # is nothing to drop genuinely — the absent default already SKIPs.
        return None

    applicability = resolve_applicability(
        available=config.available,
        # Fast/standard is a SEPARATE axis (FK-24 §24.3.3) carried on
        # ``StoryContext.mode`` — NOT ``execution_route`` (the old axis bug).
        fast=story_context.mode is WireStoryMode.FAST,
        story_type=story_context.story_type,
    )
    if applicability is SonarApplicability.NOT_APPLICABLE_FAST:
        # AG3-052 E2: a Sonar-configured (available==true) project in fast
        # mode resolves GENUINELY to NOT_APPLICABLE_FAST — the stage drops at
        # the anchor (runtime distinguishable from available==false). The full
        # fast terminal (Policy-skip via tests-green floor) stays FK-24/FK-27.
        return _NotApplicableFastPort()
    if applicability is not SonarApplicability.APPLICABLE:
        # NOT_APPLICABLE_UNAVAILABLE (non-code-producing story on an
        # available==true project): deliberate skip; caller uses absent port.
        return None

    try:
        bound_analysis = _resolve_bound_analysis(story_context, story_dir, config)
        ledger = _load_ledger(story_context, story_dir)
        main_head = _resolve_main_head(story_context, story_dir)
        resolved_token = token if token is not None else _resolve_token(config)
        client = _build_client(config, resolved_token)
    except SonarCoordinatesUnavailableError as exc:
        # APPLICABLE but coordinates unresolvable => fail-closed (FK-33
        # §33.6.5). Caller MUST NOT fall back to the absent port.
        return _FailClosedApplicablePort(str(exc))

    return ConfiguredSonarGateInputPort(
        config=config,
        client=client,
        fast=story_context.mode is WireStoryMode.FAST,
        story_type=story_context.story_type,
        ledger=ledger,
        bound_analysis=bound_analysis,
        main_head_revision=main_head,
    )


def _scan_root(story_context: StoryContext, story_dir: Path) -> Path:
    """Resolve the repo/worktree root the scan artefact lives under."""
    if story_context.worktree_path is not None:
        return story_context.worktree_path
    if story_context.project_root is not None:
        return story_context.project_root
    return story_dir


def _resolve_bound_analysis(
    story_context: StoryContext, story_dir: Path, config: SonarQubeConfig
) -> BoundAnalysis:
    """Resolve the commit-bound analysis coordinates (fail-closed).

    A real ``report-task.txt`` carries only ``ceTaskId``/``projectKey`` (and
    server metadata) — NOT a top-level ``branch`` key (ERROR-2); the analysisId
    is resolved later from the Compute-Engine task (ERROR-A). The analysed
    branch is therefore taken from the worktree git itself (the branch the
    Community Branch Plugin scanned), never from a non-real report-task field.
    The scanner version is the AK3-pinned ``sonarqube.scanner_version`` (the
    scanner AK3 runs for the local branch scan — Sonar exposes none,
    FK-33 §33.6.3).
    """
    root = _scan_root(story_context, story_dir)
    report = _read_report_task(root)
    commit_sha, tree_hash = _resolve_head_commit_tree(root)
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not config.scanner_version:
        raise SonarCoordinatesUnavailableError(
            "sonarqube.scanner_version is unset on an available=true config "
            "(no authoritative scanner version for the attestation binding, "
            "FK-33 §33.6.3, fail-closed)"
        )
    return BoundAnalysis(
        ce_task_id=report.get("ceTaskId", ""),
        component=report["projectKey"],
        branch=branch,
        commit_sha=commit_sha,
        tree_hash=tree_hash,
        scanner_version=config.scanner_version,
    )


def _read_report_task(root: Path) -> dict[str, str]:
    """Parse the scanner ``report-task.txt`` properties file (fail-closed)."""
    path = root / _REPORT_TASK_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SonarCoordinatesUnavailableError(
            f"scanner report-task not found/readable at {path} "
            "(no scan artefact for this APPLICABLE run)"
        ) from exc
    props: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        props[key.strip()] = value.strip()
    if not props.get("projectKey"):
        raise SonarCoordinatesUnavailableError(
            f"scanner report-task at {path} is missing projectKey"
        )
    if not props.get("ceTaskId"):
        raise SonarCoordinatesUnavailableError(
            f"scanner report-task at {path} is missing ceTaskId "
            "(cannot resolve the analysis via ce/task, FK-33 §33.6.3)"
        )
    return props


def _resolve_head_commit_tree(root: Path) -> tuple[str, str]:
    """Resolve the worktree HEAD commit SHA and tree hash (fail-closed)."""
    commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return commit, tree


def _resolve_main_head(story_context: StoryContext, story_dir: Path) -> str:
    """Resolve the authoritative main HEAD revision (fail-closed)."""
    root = _scan_root(story_context, story_dir)
    return _git(root, "rev-parse", _MAIN_BRANCH)


def _git(root: Path, *args: str) -> str:
    """Run a read-only git command in ``root`` (fail-closed on error)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise SonarCoordinatesUnavailableError(
            f"git {' '.join(args)} failed to spawn in {root}: {exc}"
        ) from exc
    out = result.stdout.strip()
    if result.returncode != 0 or not out:
        raise SonarCoordinatesUnavailableError(
            f"git {' '.join(args)} in {root} returned no revision "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return out


def _load_ledger(
    story_context: StoryContext, story_dir: Path
) -> AcceptedExceptionLedger:
    """Load the accepted-exception ledger (fail-closed; absent == empty).

    An ABSENT ledger file is a valid empty ledger (no exceptions declared).
    A PRESENT-but-unreadable/invalid ledger is fail-closed: the gate must
    not run against a corrupt exception set.
    """
    root = _scan_root(story_context, story_dir)
    path = root / _LEDGER_REL
    if not path.is_file():
        return AcceptedExceptionLedger()
    try:
        return AcceptedExceptionLedger.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise SonarCoordinatesUnavailableError(
            f"accepted-exception ledger at {path} is unreadable/invalid: {exc}"
        ) from exc


def _resolve_token(config: SonarQubeConfig) -> str:
    """Resolve the Sonar token from the configured env key (fail-closed)."""
    if not config.token_env:
        raise SonarCoordinatesUnavailableError(
            "sonarqube.token_env is not set on an available=true config "
            "(cannot authenticate the scoped Sonar client)"
        )
    token = os.environ.get(config.token_env)
    if not token:
        raise SonarCoordinatesUnavailableError(
            f"sonarqube token env {config.token_env!r} is unset/empty "
            "(no scoped token for the Sonar client)"
        )
    return token


def _build_client(config: SonarQubeConfig, token: str) -> SonarClient:
    """Construct the thin ``integrations.sonar`` client (fail-closed)."""
    from agentkit.integrations.sonar import SonarClient

    if not config.base_url:
        raise SonarCoordinatesUnavailableError(
            "sonarqube.base_url is not set on an available=true config"
        )
    return SonarClient(config.base_url, token)


__all__ = [
    "SonarCoordinatesUnavailableError",
    "build_sonar_gate_port_for_run",
]
