"""Harness-neutral guard evaluation for project-local governance hooks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter

from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.protocols import (
    GovernanceGuard,
    GuardVerdict,
    ViolationType,
)
from agentkit.governance.runner import GuardRunner
from agentkit.installer.paths import qa_story_dir
from agentkit.projectedge.runtime import (
    FreshnessClass,
    ProjectEdgeResolver,
    ResolvedEdgeState,
    read_change_frame_freeze_state,
)
from agentkit.story_context_manager.operating_mode_resolver import (
    resolve_operating_mode,
)

Operation = Literal[
    "bash_command",
    "file_write",
    "file_edit",
    "file_read",
    "unknown_tool",
]
PrincipalKind = Literal["main", "subagent"]


class HookEvent(BaseModel):
    """Harness-neutral event consumed by the guard evaluation core."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Operation
    operation_args: dict[str, object] = {}
    freshness_class: FreshnessClass
    cwd: str = ""
    session_id: str | None = None
    # AG3-032 (FK-55 §55.3a): harness-context fields the PrincipalResolver reads
    # to attest the technical principal. NEVER prompt content. Default None; the
    # resolver then falls back to the context default principal. Deliberately a
    # minimal extension — no full HookEvent overhaul (AG3-032 §2.2).
    parent_session_id: str | None = None
    cli_args: list[str] | None = None
    principal_kind: PrincipalKind = "main"
    # Harness-neutral PostToolUse outcome payload. Harness-specific adapters own
    # filling it; the worker-health engine validates it against PostToolOutcome.
    post_tool_outcome: dict[str, object] | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, value: object) -> object:
        if isinstance(value, dict) and "cwd" not in value:
            updated = dict(value)
            updated["cwd"] = str(Path.cwd())
            return updated
        return value

    @field_validator("cwd", mode="before")
    @classmethod
    def _default_cwd(cls, value: object) -> str:
        if isinstance(value, str) and value:
            return value
        return str(Path.cwd())

    @field_validator("session_id", "parent_session_id", mode="before")
    @classmethod
    def _coerce_session_id(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None

    @field_validator("cli_args", mode="before")
    @classmethod
    def _coerce_cli_args(cls, value: object) -> list[str] | None:
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
        return None


def evaluate_pre_tool_use(event: HookEvent, *, project_root: Path) -> GuardVerdict:
    """Evaluate one harness-neutral pre-tool event against mode-aware guards."""
    operation, context, freshness_class = _normalize_event(event)
    resolver = ProjectEdgeResolver(project_root=project_root)
    resolved = resolver.resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=freshness_class,
    )
    context.update(_guard_context(event, resolved, project_root=project_root))

    operating_mode = resolve_operating_mode(resolved)
    if operating_mode == "binding_invalid" and freshness_class == "mutation":
        return GuardVerdict.block(
            "operating_mode_guard",
            ViolationType.POLICY_VIOLATION,
            "Mutating operation blocked because the local story binding is invalid",
            detail={"reason": resolved.block_reason},
        )

    runner = GuardRunner(guards=_guards_for_state(resolved, project_root=project_root))
    allowed, verdicts = runner.is_allowed(operation, context)
    if allowed:
        return GuardVerdict.allow("guard_evaluation")
    for verdict in verdicts:
        if not verdict.allowed:
            return verdict
    return GuardVerdict.allow("guard_evaluation")


def _normalize_event(
    event: HookEvent,
) -> tuple[str, dict[str, object], FreshnessClass]:
    return event.operation, dict(event.operation_args), event.freshness_class


def _guard_context(
    event: HookEvent,
    resolved: ResolvedEdgeState,
    *,
    project_root: Path,
) -> dict[str, object]:
    story_id = ""
    context_project_key = ""
    context_run_id = ""
    principal_type = ""
    qa_lock_active = False
    qa_lock_known = False
    if resolved.bundle is not None and resolved.bundle.session is not None:
        story_id = resolved.bundle.session.story_id
        context_project_key = resolved.bundle.session.project_key
        context_run_id = resolved.bundle.session.run_id
        principal_type = resolved.bundle.session.principal_type
        qa_lock_known = resolved.bundle.qa_lock is not None
        qa_lock_active = (
            resolved.bundle.qa_lock is not None
            and resolved.bundle.qa_lock.status == "ACTIVE"
        )
    context: dict[str, object] = {
        "operating_mode": resolve_operating_mode(resolved),
        "principal_kind": event.principal_kind,
        "active_story_id": story_id,
        "project_key": context_project_key if story_id else "",
        "run_id": context_run_id if story_id else "",
        "principal_type": principal_type,
        "qa_artifact_lock_known": qa_lock_known,
        "qa_artifact_lock_active": qa_lock_active,
    }
    context.update(
        _change_frame_freeze_signals(story_id, project_root=project_root)
    )
    return context


def _change_frame_freeze_signals(
    story_id: str,
    *,
    project_root: Path,
) -> dict[str, object]:
    """Resolve the persisted change-frame freeze signals (FK-23 §23.4.3, AG3-047).

    The ``ArtifactGuard`` keys the exploration change-frame protection on two
    guard-context signals (``change_frame_frozen`` / ``change_frame_freeze_known``).
    The productive guard-context builder feeds them from the PERSISTED
    ``_temp/qa/{story_id}/change_frame.json`` freeze state via the ``projectedge``
    R-boundary read (this A-core owns the path policy, the boundary owns the FS
    read). Fail-closed semantics (AG3-047):

    * no file yet OR an explicitly NOT-frozen file -> ``freeze_known=True`` +
      ``frozen=False`` (the legitimate pre-freeze editable draft is allowed,
      FK-25 §25.4.2);
    * a frozen file -> ``freeze_known=True`` + ``frozen=True`` (the write is
      blocked);
    * an UNREADABLE file (error, not absence) -> ``freeze_known`` is LEFT UNSET
      so the guard blocks fail-closed (the unknown freeze state is never read as
      "not frozen", ARCH-48 default deny).

    Args:
        story_id: The active story display id (empty outside story execution).
        project_root: The project root resolving ``_temp/qa/{story_id}/``.

    Returns:
        The freeze guard-context signals (possibly empty when no story scope or
        when the state is unreadable).
    """
    if not story_id:
        return {}
    change_frame_path = qa_story_dir(project_root, story_id) / CHANGE_FRAME_FILE
    state = read_change_frame_freeze_state(change_frame_path)
    if state == "unreadable":
        # Unknown freeze state -> leave freeze_known unset -> guard blocks.
        return {}
    return {
        "change_frame_freeze_known": True,
        "change_frame_frozen": state == "frozen",
    }


def _guards_for_state(
    resolved: ResolvedEdgeState,
    *,
    project_root: Path,
) -> list[GovernanceGuard]:
    guards: list[GovernanceGuard] = [BranchGuard()]
    if (
        resolve_operating_mode(resolved) == "story_execution"
        and resolved.bundle is not None
        and resolved.bundle.session is not None
    ):
        session = resolved.bundle.session
        allowed_paths = list(session.worktree_roots)
        allowed_paths.append(
            str(qa_story_dir(project_root, session.story_id)),
        )
        guards.append(
            ScopeGuard(allowed_paths=allowed_paths),
        )
        guards.append(ArtifactGuard())

        # AG3-069 (FK-05 §5.12): wire the SeamAllowlistGuard and
        # StabilizationBudgetGuard for integration_stabilization stories.
        # These guards are ONLY active when the story uses the IS contract
        # — they must never widen or alter the guard chain for standard
        # stories (CORE PRINCIPLE: gate every IS enforcement on contract).
        # Fail-CLOSED: when the story IS an IS story but the guard cannot be
        # built (manifest/approval absent/unreadable/unbound), a FailClosed
        # stand-in BLOCKS — a missing/broken IS guard must never silently skip.
        seam_guard = _maybe_seam_guard(
            project_root,
            story_id=session.story_id,
            project_key=session.project_key,
            run_id=session.run_id,
            worktree_roots=tuple(session.worktree_roots),
        )
        if seam_guard is not None:
            guards.append(seam_guard)
        budget_guard = _maybe_budget_guard(
            project_root,
            story_id=session.story_id,
            project_key=session.project_key,
            run_id=session.run_id,
        )
        if budget_guard is not None:
            guards.append(budget_guard)

    return guards


def _is_integration_stabilization_story(
    project_root: Path, story_id: str
) -> bool:
    """Return whether the active story is an integration_stabilization campaign.

    Truth-boundary discipline (TB003): ``agentkit.governance`` is a protected
    module and MUST NOT read AK3 story export json nor call the ``load_story_context``
    export loader. The IS contract is therefore detected from the presence of the
    persisted IntegrationScopeManifest artifact (``integration_manifest.json``),
    whose ``implementation_contract`` is INTEGRATION_STABILIZATION by construction
    (model-validated). A standard story never produces this manifest. An IS story
    BEFORE manifest approval has no manifest here — its execution is blocked at the
    workflow transition (AC8) and the implementation worker-spawn (AC2); the
    PreToolUse guard enforces the seam/budget overlay once a manifest exists and
    fail-closes when the manifest is present but broken/unbound (ERROR D).

    Args:
        project_root: Project root for path resolution.
        story_id: The active story identifier.

    Returns:
        ``True`` iff a persisted IntegrationScopeManifest is present.
    """
    from agentkit.installer.paths import story_dir as _story_dir
    from agentkit.integration_stabilization.state import IS_MANIFEST_FILE

    s_dir = _story_dir(project_root, story_id)
    return (s_dir / IS_MANIFEST_FILE).exists()


def _maybe_seam_guard(
    project_root: Path,
    *,
    story_id: str,
    project_key: str,
    run_id: str,
    worktree_roots: tuple[str, ...],
) -> GovernanceGuard | None:
    """Build the IS SeamAllowlistGuard; fail-CLOSED for a broken IS guard (ERROR D).

    For a standard story returns ``None`` (no guard added — standard stories
    unaffected). For an integration_stabilization story the guard is built ONLY
    when an APPROVED + BOUND manifest is present; otherwise a
    :class:`~agentkit.integration_stabilization.seam_allowlist_guard.FailClosedSeamGuard`
    is returned that BLOCKS every mutation (a missing/broken IS guard must never
    silently skip — the prior fail-OPEN behaviour was the AC7 bug).

    The allowlist is materialized to ``<worktree_root>/.agent-guard/
    seam_allowlist.json`` and the guard READS it (concept-conform, FK-05 §5.14).

    Args:
        project_root: Project root for path resolution.
        story_id: The active story identifier.
        project_key: The active project key (for emitted telemetry).
        run_id: The active run id (binding-integrity + telemetry).
        worktree_roots: The bound worktree roots (materialization target +
            allowlist read source).

    Returns:
        A seam guard (production or fail-closed) for IS stories, else ``None``.
    """
    from agentkit.installer.paths import story_dir as _story_dir
    from agentkit.integration_stabilization.preconditions import (
        check_approval_present,
        check_binding_integrity,
    )
    from agentkit.integration_stabilization.seam_allowlist_guard import (
        FailClosedSeamGuard,
        SeamAllowlistGuard,
        materialize_seam_allowlist_file,
        read_seam_allowlist_file,
    )
    from agentkit.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )

    if not _is_integration_stabilization_story(project_root, story_id):
        return None

    s_dir = _story_dir(project_root, story_id)
    try:
        manifest = load_integration_manifest(s_dir)
        approval = load_manifest_approval(s_dir)
        if manifest is None:
            return FailClosedSeamGuard("no approved IntegrationScopeManifest present")
        if not check_approval_present(approval).approved:
            return FailClosedSeamGuard("no approved ManifestApprovalRecord present")
        assert approval is not None  # noqa: S101 -- guaranteed by check above
        binding = check_binding_integrity(
            manifest, approval, current_run_id=run_id
        )
        if not binding.binding_valid:
            return FailClosedSeamGuard(f"manifest binding invalid: {binding.reason}")

        # Materialize the allowlist to the concept-conform guard file in every
        # bound worktree root, then READ it back (the file is authoritative).
        allowlist: tuple[str, ...] | None = None
        for root in worktree_roots:
            written = materialize_seam_allowlist_file(manifest, Path(root))
            allowlist = read_seam_allowlist_file(written.parent.parent)
        if allowlist is None:
            # No worktree root present or the materialized allowlist file could
            # not be read back.  This is a broken IS guard state (ERROR D fix):
            # do NOT fall back to the in-memory manifest allowlist -- that was a
            # residual fail-OPEN.  Return FailClosedSeamGuard so every mutation
            # is blocked until the guard can be properly materialized.
            return FailClosedSeamGuard(
                "seam allowlist could not be materialized: no worktree root "
                "available or the allowlist file was unreadable after write "
                "(FK-05 §5.14, fail-closed)"
            )
    # A broken IS guard must BLOCK, not skip (fail-closed, FK-05 §5.14).
    except Exception as exc:  # noqa: BLE001
        return FailClosedSeamGuard(f"seam guard construction error: {exc}")

    emitter = _is_event_emitter(s_dir, project_key)
    return SeamAllowlistGuard(
        allowlist,
        emitter=emitter,
        story_id=story_id,
        project_key=project_key,
        run_id=run_id,
    )


def _maybe_budget_guard(
    project_root: Path,
    *,
    story_id: str,
    project_key: str,
    run_id: str,
) -> GovernanceGuard | None:
    """Build the IS StabilizationBudgetGuard; fail-CLOSED for a broken IS guard.

    Returns ``None`` for standard stories. For an integration_stabilization
    story the budget guard is built ONLY with an APPROVED + BOUND manifest;
    otherwise a fail-closed stand-in BLOCKS every mutation (AC4, FK-05 §5.9 —
    a missing/broken IS guard must never silently skip).

    Args:
        project_root: Project root for path resolution.
        story_id: The active story identifier.
        project_key: The active project key (for emitted telemetry).
        run_id: The active run id (binding-integrity + telemetry).

    Returns:
        A budget guard (production or fail-closed) for IS stories, else ``None``.
    """
    from agentkit.installer.paths import story_dir as _story_dir
    from agentkit.integration_stabilization.budget_guard import (
        StabilizationBudgetGuard,
    )
    from agentkit.integration_stabilization.preconditions import (
        check_approval_present,
        check_binding_integrity,
    )
    from agentkit.integration_stabilization.seam_allowlist_guard import (
        FailClosedSeamGuard,
    )
    from agentkit.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )

    if not _is_integration_stabilization_story(project_root, story_id):
        return None

    s_dir = _story_dir(project_root, story_id)
    try:
        manifest = load_integration_manifest(s_dir)
        approval = load_manifest_approval(s_dir)
        if manifest is None:
            return FailClosedSeamGuard("no approved IntegrationScopeManifest present")
        if not check_approval_present(approval).approved:
            return FailClosedSeamGuard("no approved ManifestApprovalRecord present")
        assert approval is not None  # noqa: S101 -- guaranteed by check above
        binding = check_binding_integrity(
            manifest, approval, current_run_id=run_id
        )
        if not binding.binding_valid:
            return FailClosedSeamGuard(f"manifest binding invalid: {binding.reason}")
    # A broken IS guard must BLOCK, not skip (fail-closed, FK-05 §5.9).
    except Exception as exc:  # noqa: BLE001
        return FailClosedSeamGuard(f"budget guard construction error: {exc}")

    emitter = _is_event_emitter(s_dir, project_key)
    return StabilizationBudgetGuard(
        manifest=manifest,
        story_dir=s_dir,
        emitter=emitter,
        story_id=story_id,
        project_key=project_key,
        run_id=run_id,
    )


def _is_event_emitter(story_dir: Path, project_key: str) -> EventEmitter | None:
    """Build the state-backed telemetry emitter for IS guard events, or ``None``.

    A telemetry-construction fault must NOT make the guard fail-open; the guard
    still enforces and simply skips emission when no emitter is available.
    """
    try:
        from agentkit.telemetry.storage import StateBackendEmitter

        return StateBackendEmitter(story_dir, default_project_key=project_key)
    except Exception:  # noqa: BLE001 -- emission is best-effort; the guard still blocks
        return None


__all__ = [
    "HookEvent",
    "evaluate_pre_tool_use",
]
