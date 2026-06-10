"""Guard runner -- evaluates all registered guards for an operation.

Orchestration only (ARCH-12). Business logic lives in individual guards.
The runner is fail-closed: if any guard blocks, the operation is blocked.
All guards run even if earlier ones block, so that complete violation
information is collected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from agentkit.governance.errors import LockRecordNotFoundError
from agentkit.governance.guard_system.records import GuardDecision, GuardDecisionOutcome
from agentkit.governance.hook_registration import HookId
from agentkit.governance.locks import DeactivationResult, LockRecordId
from agentkit.governance.principal_capabilities.operations import (
    WEB_FETCH,
    WEB_SEARCH,
    canonical_web_tool,
)
from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.hook_registration import HookDefinition, RegistrationResult
    from agentkit.governance.protocols import GovernanceGuard
    from agentkit.governance.repository import (
        HookRegistrationRepository,
        WorktreeRepository,
    )
    from agentkit.state_backend.store.lock_record_repository import LockRecordRepository

type HookDecision = GuardVerdict


class _GuardDecisionSink(Protocol):
    def append(self, decision: GuardDecision) -> None:
        """Append one guard decision."""
        ...

#: Canonical tool names that count as a research web call (FK-68 §68.6.1). Used at
#: the runner edge to gate the BudgetEventEmitter dispatch (fail-closed on an
#: UNRESOLVED story type) to actual WebFetch/WebSearch operations. ``_event_tool``
#: canonicalizes alias / casing forms (``web_fetch`` / ``web-search`` / ...) to
#: these BEFORE this membership check (AG3-036 FIX-2 — never a fail-open gap).
_WEB_TOOLS = frozenset({WEB_FETCH, WEB_SEARCH})

PRE_HOOK_IDS = frozenset(
    {
        # FK-30 §30.5.1 guard-hook identifiers (wortgleich) + ccag_gatekeeper
        "branch_guard",
        "orchestrator_guard",
        "integrity",
        "qa_agent_guard",
        "adversarial_guard",
        "self_protection",
        "story_creation_guard",
        "budget",
        "skill_usage_check",
        "health_monitor",
        "ccag_gatekeeper",
        # AG3-036 (FK-68 §68.3.1) FIX-1/FIX-3: the two double-role telemetry
        # guards enforce at PreToolUse so a DENY blocks BEFORE the tool runs.
        # ``review_guard`` (§2.1.5) blocks a ``git commit`` whose mandatory
        # reviewer roles are not covered; ``budget_event_emitter`` (§2.1.6)
        # blocks a research web call over the hard budget. A PostToolUse DENY
        # cannot stop an action that already ran (fail-open), so both belong in
        # the PRE phase.
        "review_guard",
        "budget_event_emitter",
    }
)
POST_HOOK_IDS = frozenset(
    {
        "telemetry",
        "budget",
        "health_monitor",
    }
)
SUPPORTED_PHASES = frozenset({"pre", "post"})
SUPPORTED_HOOK_IDS = frozenset(PRE_HOOK_IDS | POST_HOOK_IDS)


@dataclass(frozen=True)
class HookWrapperArgs:
    """Validated hook-wrapper command-line selector."""

    phase: str
    hook_id: str


class GuardRunner:
    """Runs all registered guards for an operation.

    Fail-closed semantics: if **any** guard blocks, the operation is
    blocked.  All guards are evaluated even when earlier ones already
    blocked, so that complete violation information is available.

    An empty runner (no guards registered) allows everything -- there
    are no rules to violate.
    """

    def __init__(
        self, guards: list[GovernanceGuard] | None = None,
        decision_repo: _GuardDecisionSink | None = None,
    ) -> None:
        self._guards: list[GovernanceGuard] = list(guards) if guards else []
        self._decision_repo = decision_repo

    def register(self, guard: GovernanceGuard) -> None:
        """Add a guard to the evaluation pipeline.

        Args:
            guard: A ``GovernanceGuard`` implementation to register.
        """
        self._guards.append(guard)

    def evaluate(
        self, operation: str, context: dict[str, object],
    ) -> list[GuardVerdict]:
        """Evaluate all guards. Returns list of all verdicts.

        Even if the first guard blocks, all remaining guards still run
        (to collect complete violation information).

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            List of ``GuardVerdict`` instances, one per registered guard.
        """
        verdicts = [g.evaluate(operation, context) for g in self._guards]
        self._append_guard_decisions(verdicts, context)
        return verdicts

    def is_allowed(
        self, operation: str, context: dict[str, object],
    ) -> tuple[bool, list[GuardVerdict]]:
        """Check if an operation is allowed.

        Convenience wrapper around :meth:`evaluate` that also returns a
        boolean summary.

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            A ``(allowed, verdicts)`` tuple where ``allowed`` is ``True``
            only if every guard returned ``ALLOW``.
        """
        verdicts = self.evaluate(operation, context)
        allowed = all(v.allowed for v in verdicts)
        return allowed, verdicts

    def _append_guard_decisions(
        self,
        verdicts: list[GuardVerdict],
        context: dict[str, object],
    ) -> None:
        """Append guard decisions when a state-backed audit sink is wired."""
        if self._decision_repo is None:
            return
        scope = _decision_scope(context)
        if scope is None:
            return
        project_key, story_id, run_id, flow_id, node_id = scope
        for verdict in verdicts:
            self._decision_repo.append(
                GuardDecision(
                    project_key=project_key,
                    story_id=story_id,
                    run_id=run_id,
                    flow_id=flow_id,
                    guard_decision_id=str(uuid4()),
                    guard_key=verdict.guard_name,
                    outcome=(
                        GuardDecisionOutcome.PASS
                        if verdict.allowed
                        else GuardDecisionOutcome.ERROR
                    ),
                    decided_at=datetime.now(UTC),
                    node_id=node_id,
                    reason=verdict.message,
                    evidence_ref=_evidence_ref(verdict),
                )
            )


class Governance:
    """Harness-neutral governance top surface.

    Provides three top-level surfaces:
    - ``run_hook`` (static): dispatch a named hook (pre-existing).
    - ``register_hooks``: persist hook definitions in the state backend and
      materialise harness-specific settings files (FK-30 §30.3.1).
    - ``deactivate_locks``: deactivate story locks and clean up lock exports.

    Args:
        hook_repo: Repository for hook-definition persistence.
        lock_repo: Repository for story-execution lock deactivation.
        project_key: Owning project key used for hook registration scoping.
            Required for ``register_hooks``.  Sourced from Composition Root /
            Installer context (Fix E1, AG3-031 Pass-3).
        project_root: Root directory used by harness settings writers
            (Fix E2).  Defaults to ``Path.cwd()``.  Tests pass ``tmp_path``.
        worktree_repo: Repository for resolving worktree paths per story
            (Fix E4, AG3-031 Pass-4 / E9 AG3-031 Pass-5).  Must be provided
            explicitly — use
            ``agentkit.state_backend.store.worktree_repository.StateBackendWorktreeRepository()``
            or inject a test double.  No internal fallback factory.
    """

    def __init__(
        self,
        *,
        hook_repo: HookRegistrationRepository,
        lock_repo: LockRecordRepository,
        project_key: str = "",
        project_root: Path | None = None,
        worktree_repo: WorktreeRepository,
    ) -> None:
        self._hook_repo = hook_repo
        self._lock_repo = lock_repo
        self._project_key = project_key
        self._project_root = project_root
        self._worktree_repo: WorktreeRepository = worktree_repo

    # ------------------------------------------------------------------
    # register_hooks (FK-30 §30.3.1)
    # ------------------------------------------------------------------

    def register_hooks(
        self,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Register harness-specific hook definitions in the project.

        FK-30 §30.3.1: signature is ``register_hooks(hook_definitions)`` —
        no ``project_key`` parameter.  The project key is resolved from
        ``self._project_key`` set at construction (Fix E1, AG3-031 Pass-3).

        The caller (Installer) must supply ``project_key`` to
        ``Governance.__init__`` rather than passing it per-call.

        Idempotent: repeated registration of an identical
        ``(project_key, hook_event_name, matcher)`` triple returns the
        matcher string in ``skipped`` without overwriting the existing entry
        (for identical entries).  Entries with a changed ``command`` are
        overwritten (UPSERT — Fix E3).

        Settings materialisation (Fix E2): after persisting to the backend,
        calls each registered harness adapter to write the harness-specific
        settings file (e.g. ``.claude/settings.json``).  Fail-closed: a
        broken settings file raises, not silently continues.

        Args:
            hook_definitions: Hook definitions to register.

        Returns:
            ``RegistrationResult`` with ``registered``, ``skipped``, ``errors``.

        Raises:
            Exception: On unrecoverable backend failures or broken settings
                files (FK-30 §30.3.1).
        """
        result = self._hook_repo.register(self._project_key, hook_definitions)
        # Fix E2: materialise harness-specific settings files after backend persist.
        self._materialise_harness_settings(hook_definitions)
        return result

    def _materialise_harness_settings(
        self,
        hook_definitions: list[HookDefinition],
    ) -> None:
        """Write hook definitions into harness-specific settings files.

        Calls both the Claude Code and Codex adapters to write their
        respective settings files.  Fail-closed: broken settings files
        (invalid JSON in ``.claude/settings.json``) raise ``ValueError``
        rather than continuing silently (FK-30 §30.3.1 Z.339).

        The ``project_root`` defaults to ``Path.cwd()``.  Tests that need
        to redirect to a ``tmp_path`` should configure ``project_root``
        at Governance construction time (future enhancement: inject via
        ``__init__`` or composition-root; current default is cwd).

        Args:
            hook_definitions: Hook definitions to materialise.
        """
        from agentkit.governance.harness_adapters.settings_writer import (
            ClaudeCodeSettingsWriter,
            CodexSettingsWriter,
        )

        # Write Claude Code settings (.claude/settings.json)
        ClaudeCodeSettingsWriter(self._project_root).write(hook_definitions)
        # Write Codex settings (.codex/hooks.json — FK-76 §76.5.2)
        CodexSettingsWriter(self._project_root).write(hook_definitions)

    # ------------------------------------------------------------------
    # deactivate_locks (FK-30 §30.6.0)
    # ------------------------------------------------------------------

    def deactivate_locks(self, story_id: str) -> DeactivationResult:
        """Deactivate all lock records for a story and remove lock exports.

        Called by ClosureSequence (FK-29 §29.5) after successful postflight.
        After this call, guards that depend on an active lock record
        (branch_guard, orchestrator_guard, qa_agent_guard) become inactive.

        Idempotent for already-deactivated stories (all locks INACTIVE):
        returns empty deactivated_locks without errors (but the story_id
        must be known — completely unknown story_ids raise LockRecordNotFoundError,
        surfaced in errors[]).

        Fail-closed (Fix E6, AG3-031 Pass-3):
        - Unknown story_id (no lock records at all) → LockRecordNotFoundError
          surfaced in errors[0].
        - IO errors on lock-export deletion → collected in ``errors[]``.
        - DB failures → raised immediately (not silently swallowed).

        Args:
            story_id: Canonical story identifier.

        Returns:
            ``DeactivationResult`` with ``deactivated_locks``,
            ``removed_edge_bundles``, ``removed_lock_exports``,
            ``restored_to_ai_augmented``, ``errors``.

        Raises:
            Exception: On unrecoverable DB failures.
        """
        # Fix E6: fail-closed for unknown story_id.
        # LockRecordNotFoundError is surfaced in errors[]; critical DB errors
        # (any other exception) are re-raised immediately.
        errors: list[str] = []
        deactivated: list[LockRecordId] = []
        try:
            deactivated = self._lock_repo.deactivate_locks_for_story(story_id)
        except LockRecordNotFoundError as exc:
            errors.append(str(exc))

        # Fix E4: purge the correct lock-export paths (FK-30 §30.6.0 + FK-29 §29.5)
        removed_bundles, bundle_errors = self._purge_edge_bundles(story_id)
        errors.extend(bundle_errors)

        removed_exports, export_errors = self._purge_qa_lock_export(story_id)
        errors.extend(export_errors)

        # WorktreeRepository exceptions are surfaced in errors[] (fail-closed — E4 Fix).
        try:
            restored, worktree_lock_exports, restore_errors = (
                self._restore_ai_augmented_mode(story_id)
            )
        except Exception as exc:  # noqa: BLE001
            # Fail-closed: WorktreeRepository unavailability is an error, not silently skipped.
            errors.append(
                f"WorktreeRepository.list_worktree_paths failed for story_id={story_id!r}: {exc}"
            )
            restored = False
            worktree_lock_exports = []
            restore_errors = []
        errors.extend(restore_errors)
        removed_exports = removed_exports + worktree_lock_exports

        return DeactivationResult(
            deactivated_locks=deactivated,
            removed_edge_bundles=removed_bundles,
            removed_lock_exports=removed_exports,
            restored_to_ai_augmented=restored,
            errors=errors,
        )

    def _purge_edge_bundles(
        self, story_id: str
    ) -> tuple[list[Path], list[str]]:
        """Remove legacy edge-bundle file for ``story_id``.

        Compatibility path: ``_temp/governance/{story_id}/edge-bundle.json``.
        Missing files are silently skipped (idempotent). IO errors collected.

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (removed_paths, error_messages).
        """
        removed: list[Path] = []
        errors: list[str] = []

        candidate = Path("_temp") / "governance" / story_id / "edge-bundle.json"
        if candidate.exists():
            try:
                candidate.unlink()
                removed.append(candidate)
            except OSError as exc:
                errors.append(
                    f"Failed to remove edge bundle {candidate}: {exc}"
                )

        return removed, errors

    def _purge_qa_lock_export(
        self, story_id: str
    ) -> tuple[list[Path], list[str]]:
        """Remove QA-lock export file for ``story_id`` (FK-30 §30.6.0 + FK-29 §29.5).

        Removes ``_temp/governance/locks/{story_id}/qa-lock.json``.
        Missing files are silently skipped (idempotent). IO errors collected.

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (removed_paths, error_messages).
        """
        removed: list[Path] = []
        errors: list[str] = []

        qa_lock_path = (
            Path("_temp") / "governance" / "locks" / story_id / "qa-lock.json"
        )
        if qa_lock_path.exists():
            try:
                qa_lock_path.unlink()
                removed.append(qa_lock_path)
            except OSError as exc:
                errors.append(
                    f"Failed to remove qa-lock export {qa_lock_path}: {exc}"
                )

        return removed, errors

    def _restore_ai_augmented_mode(
        self, story_id: str
    ) -> tuple[bool, list[Path], list[str]]:
        """Revert operating mode to ``ai_augmented`` for the story (FK-30 §30.6.0 Z.683).

        FK-30 §30.6.0 + FK-22 §22.7 (Fix E4, AG3-031 Pass-4/5):
        - Iterates over all worktree paths for ``story_id`` via
          ``WorktreeRepository.list_worktree_paths`` — exception propagates to
          caller (``deactivate_locks``) which appends it to ``errors[]``.
        - For each worktree: removes ``.agent-guard/lock.json`` if present,
          collecting the removed path; OSError collected in ``errors[]``.
        - For each worktree: writes ``.agent-guard/mode.json`` with the
          ``ai_augmented`` operating-mode marker; OSError collected in
          ``errors[]`` (fail-closed — CLAUDE.md FAIL-CLOSED).
        - Also writes the legacy ``_temp/governance/locks/{story_id}/mode.json``
          tombstone for backward compat (existing non-worktree consumers);
          OSError collected in ``errors[]``.

        When a worktree has no ``.agent-guard/`` directory, the write is
        skipped silently (idempotent: guard dir is created by Setup phase).

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (restored, removed_lock_exports, errors) where
            ``restored`` is True when at least one mode marker was written,
            ``removed_lock_exports`` is the list of ``.agent-guard/lock.json``
            paths that were deleted, and ``errors`` is a list of non-fatal
            IO error messages encountered (one per failed file operation).
        """
        import json

        mode_payload = json.dumps(
            {"operating_mode": "ai_augmented", "story_id": story_id}
        )
        any_written = False
        removed_lock_exports: list[Path] = []
        errors: list[str] = []

        # Per-worktree: remove lock.json + write mode.json (FK-30 §30.6.0 + FK-22 §22.7)
        # WorktreeRepository exceptions propagate to deactivate_locks (fail-closed).
        worktree_paths = self._worktree_repo.list_worktree_paths(story_id)

        for wt_path in worktree_paths:
            guard_dir = wt_path / ".agent-guard"
            if not guard_dir.exists():
                continue
            # Remove lock.json (FK-22 §22.7)
            lock_file = guard_dir / "lock.json"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    removed_lock_exports.append(lock_file)
                except OSError as exc:
                    errors.append(
                        f"failed to remove .agent-guard/lock.json at {lock_file}: {exc}"
                    )
            # Write mode.json (FK-30 §30.6.0 Z.683)
            mode_file = guard_dir / "mode.json"
            try:
                mode_file.write_text(mode_payload, encoding="utf-8")
                any_written = True
            except OSError as exc:
                errors.append(
                    f"failed to write .agent-guard/mode.json at {mode_file}: {exc}"
                )

        # Legacy tombstone (non-worktree consumers, backward compat)
        mode_dir = Path("_temp") / "governance" / "locks" / story_id
        if mode_dir.exists():
            legacy_file = mode_dir / "mode.json"
            try:
                legacy_file.write_text(mode_payload, encoding="utf-8")
                any_written = True
            except OSError as exc:
                errors.append(
                    f"failed to write legacy mode.json at {legacy_file}: {exc}"
                )

        return any_written, removed_lock_exports, errors

    # ------------------------------------------------------------------
    # run_hook (pre-existing static method — unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def run_hook(
        hook_id: str,
        event: HookEvent,
        *,
        phase: str = "pre",
        project_root: Path | None = None,
    ) -> HookDecision:
        """Dispatch a named hook against the harness-neutral event model."""
        return run_hook(
            hook_id,
            event,
            phase=phase,
            project_root=project_root,
        )


def parse_hook_wrapper_args(
    argv: list[str],
    *,
    command_name: str,
) -> HookWrapperArgs:
    """Validate ``agentkit-hook-{harness} {phase} {hook_id}`` arguments."""
    if len(argv) != 2:
        raise ValueError(f"Usage: {command_name} {{pre|post}} {{hook_id}}")
    phase, hook_id = argv
    verdict = validate_hook_selector(phase=phase, hook_id=hook_id)
    if verdict is not None:
        raise ValueError(verdict.message or "Invalid hook selector")
    return HookWrapperArgs(phase=phase, hook_id=hook_id)


def validate_hook_selector(*, phase: str, hook_id: str) -> GuardVerdict | None:
    """Return a fail-closed verdict when a hook selector is invalid."""
    if phase not in SUPPORTED_PHASES:
        return GuardVerdict.block(
            "hook_dispatcher",
            ViolationType.POLICY_VIOLATION,
            f"Unknown hook phase {phase!r}; expected one of {sorted(SUPPORTED_PHASES)}",
            detail={"phase": phase, "hook_id": hook_id},
        )
    if hook_id not in _hook_ids_for_phase(phase):
        return GuardVerdict.block(
            "hook_dispatcher",
            ViolationType.POLICY_VIOLATION,
            f"Unknown hook id {hook_id!r} for phase {phase!r}",
            detail={
                "phase": phase,
                "hook_id": hook_id,
                "supported_hook_ids": sorted(_hook_ids_for_phase(phase)),
            },
        )
    return None


def run_hook(
    hook_id: str,
    event: HookEvent,
    *,
    phase: str = "pre",
    project_root: Path | None = None,
) -> HookDecision:
    """Run a named governance hook, fail-closed on unknown selectors.

    For ``phase="pre"`` and ``hook_id="ccag_gatekeeper"``, delegates to
    :class:`~agentkit.governance.ccag.runtime.CcagPermissionRuntime` which
    implements FK-42 §42.1.  All other pre-hooks are dispatched to the
    general :func:`~agentkit.governance.guard_evaluation.evaluate_pre_tool_use`
    guard evaluation chain.

    Args:
        hook_id: The registered hook identifier (see PRE_HOOK_IDS / POST_HOOK_IDS).
        event: Harness-neutral hook event.
        phase: ``"pre"`` or ``"post"``.
        project_root: Project root for guard context resolution.

    Returns:
        A :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    invalid = validate_hook_selector(phase=phase, hook_id=hook_id)
    if invalid is not None:
        return invalid
    if phase == "post":
        # AG3-036 (FK-68 §68.3.1) FIX-1: ReviewGuard/BudgetEventEmitter moved
        # to PreToolUse. Every post hook is observational only.
        if hook_id == "health_monitor":
            return _run_health_monitor_post(event, project_root=project_root or Path.cwd())
        return GuardVerdict.allow(hook_id)

    return _dispatch_pre_hook(hook_id, event, project_root=project_root or Path.cwd())


def _dispatch_pre_hook(
    hook_id: str,
    event: HookEvent,
    *,
    project_root: Path,
) -> HookDecision:
    """Dispatch a validated pre-hook through the FK-55 enforcement chain.

    Ordering (FK-55 §55.10.3 / governance-and-guards.B5):
    1. Capability enforcement (hard DENY — CCAG never softens it).
    2. Dedicated pre-hooks (review_guard, budget_event_emitter, health_monitor,
       self_protection, story_creation_guard).
    3. CCAG gatekeeper (FK-42 §42.5.2 — last pre-hook).
    4. Generic guard evaluation chain (all other hooks).
    """
    # Step 1: hard capability matrix + freeze overlay (FK-55 §55.10.3).
    capability_block = _run_capability_enforcement(event, project_root=project_root)
    if capability_block is not None:
        return capability_block

    # Step 2: dedicated hooks (AG3-036 FIX-1/FIX-3 — run after capability check).
    if hook_id == "review_guard":
        return _run_review_guard(event, project_root=project_root)
    if hook_id == "budget_event_emitter":
        return _run_budget_event_emitter(event, project_root=project_root)
    if hook_id == "health_monitor":
        return _run_health_monitor_pre(event, project_root=project_root)

    # Step 2b: dedicated guard modules (AG3-033 / governance-and-guards.C5).
    if hook_id == HookId.SELF_PROTECTION.value:
        return _run_self_protection_guard(event)
    if hook_id == HookId.STORY_CREATION_GUARD.value:
        return _run_story_creation_guard(event)

    # Step 3: CCAG — last pre-hook (FK-42 §42.5.2).
    if hook_id == "ccag_gatekeeper":
        return _run_ccag_hook(event)

    # Step 4: generic guard evaluation chain.
    from agentkit.governance.guard_evaluation import evaluate_pre_tool_use

    return evaluate_pre_tool_use(event, project_root=project_root)


def _run_health_monitor_post(event: HookEvent, *, project_root: Path) -> HookDecision:
    """Dispatch the PostToolUse health monitor."""

    story_id = _health_story_id(event)
    if story_id == "":
        return GuardVerdict.allow("health_monitor")
    if event.post_tool_outcome is None:
        return GuardVerdict.allow("health_monitor")
    from agentkit.implementation.worker_health import PostToolOutcome, apply_post_tool_use
    from agentkit.state_backend.store.worker_health_repository import (
        StateBackendWorkerHealthRepository,
    )

    outcome = PostToolOutcome.model_validate(event.post_tool_outcome)
    repository = StateBackendWorkerHealthRepository(project_root)
    apply_post_tool_use(
        event=event,
        outcome=outcome,
        repository=repository,
        project_root=project_root,
        story_id=story_id,
        worker_id=_health_worker_id(event),
    )
    return GuardVerdict.allow("health_monitor")


def _run_health_monitor_pre(event: HookEvent, *, project_root: Path) -> HookDecision:
    """Dispatch the PreToolUse health intervention gate."""

    story_id = _health_story_id(event)
    if story_id == "":
        return GuardVerdict.allow("health_monitor")
    from agentkit.implementation.worker_health.interventions import (
        intervention_decision_result,
    )
    from agentkit.state_backend.store.worker_health_repository import (
        StateBackendWorkerHealthRepository,
    )

    repository = StateBackendWorkerHealthRepository(project_root)
    state = repository.load(story_id=story_id, worker_id=_health_worker_id(event))
    if state is None:
        return GuardVerdict.allow("health_monitor")
    result = intervention_decision_result(state)
    repository.save(result.state)
    if result.exit_code == 0:
        return GuardVerdict.allow("health_monitor")
    return GuardVerdict.block(
        "health_monitor",
        ViolationType.POLICY_VIOLATION,
        result.message,
        detail={
            "story_id": state.story_id,
            "worker_id": state.worker_id,
            "score": state.total_score,
        },
    )


def _health_story_id(event: HookEvent) -> str:
    value = event.operation_args.get("story_id")
    if isinstance(value, str) and value:
        return value
    return os.environ.get("AGENTKIT_STORY_ID", "")


def _health_worker_id(event: HookEvent) -> str:
    value = event.operation_args.get("worker_id")
    if isinstance(value, str) and value:
        return value
    return (
        os.environ.get("AGENTKIT_WORKER_ID", "")
        or event.session_id
        or "worker"
    )


def _run_review_guard(event: HookEvent, *, project_root: Path) -> HookDecision:
    """Dispatch the ``review_guard`` pre-hook to the double-role ReviewGuard.

    AG3-036 (FK-68 §68.3.1) FIX-1/FIX-2: builds the telemetry
    :class:`~agentkit.telemetry.hooks.review_guard.ReviewGuard` over the canonical
    :class:`~agentkit.telemetry.storage.StateBackendEmitter` bound to the active
    story directory (story binding resolved from the LOCAL edge bundle, same
    source as the capability enforcement). On a missing reviewer role the guard
    returns a fail-closed DENY (blocking the PreToolUse ``git commit`` BEFORE it
    runs) and emits ``review_guard_intervention``; otherwise it allows the commit
    and emits nothing.

    The mandatory reviewer roles are resolved AUTHORITATIVELY at this runner edge
    from ``pipeline.review.required_roles`` (FK-68 §68.3.1 / §2.1.5) — NOT from a
    forgeable ``operation_args`` payload. The runner MAY import config; the hook
    still receives the roles as injected plain values, preserving the hook import
    boundary (AC10).

    Fail-closed (FIX-2): when no story binding is resolvable, the pre-tool
    capability chain has already run; this guard stays observational (allow).
    When a binding IS active but the authoritative ``required_roles`` config is
    unavailable for a code-producing story, the commit is DENIED (never a silent
    guard-skip).

    Args:
        event: Harness-neutral hook event.
        project_root: Project root for binding + config resolution.

    Returns:
        The guard's :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.projectedge.runtime import ProjectEdgeResolver
    from agentkit.telemetry.hooks.base import HookContext, HookTrigger
    from agentkit.telemetry.hooks.review_guard import ReviewGuard
    from agentkit.telemetry.storage import StateBackendEmitter

    resolved = ProjectEdgeResolver(project_root=project_root).resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=event.freshness_class,
    )
    if resolved.bundle is None or resolved.bundle.session is None:
        return GuardVerdict.allow("review_guard")
    session = resolved.bundle.session
    story_id = session.story_id
    run_id = session.run_id
    if not story_id or not run_id:
        return GuardVerdict.allow("review_guard")

    story_dir = project_root / "stories" / story_id

    # FIX-C: branch on the TYPED authoritative outcome. The UNRESOLVED story type,
    # a config fault, AND an empty required_roles for a code story are all
    # fail-closed blocks here; only a RESOLVED non-code story takes the allow path
    # (distinct from UNRESOLVED — they do NOT share one path).
    roles_outcome = _authoritative_required_roles(
        project_root=project_root, story_id=story_id
    )
    if roles_outcome.block is not None:
        return roles_outcome.block
    if roles_outcome.non_code_story:
        # RESOLVED non-code story: ReviewGuard is not applicable (non_code_story,
        # explicitly NOT the story_type_unresolved path).
        return GuardVerdict.allow("review_guard")
    required_roles = roles_outcome.roles

    guard = ReviewGuard(
        StateBackendEmitter(story_dir, default_project_key=session.project_key),
        required_roles=required_roles,
    )
    context = HookContext(
        trigger=HookTrigger.PRE_TOOL_USE,
        story_id=story_id,
        run_id=run_id,
        project_key=session.project_key,
        principal=event.principal_kind,
        tool="Bash",
        command=_event_command(event),
    )
    result = guard.evaluate(context)
    guard.emit(result)
    if result.verdict is not None:
        return result.verdict
    return GuardVerdict.allow("review_guard")


@dataclass(frozen=True)
class _RequiredRolesOutcome:
    """Resolved authoritative reviewer roles, or a fail-closed block.

    Attributes:
        roles: The authoritative ``pipeline.review.required_roles`` for a RESOLVED
            code-producing story (always non-empty when ``block`` is ``None`` and
            the story is code-producing).
        block: A fail-closed blocking verdict; ``None`` on a clean resolution.
        non_code_story: ``True`` when the authoritative story type is RESOLVED and
            NOT code-producing — the ReviewGuard does not apply and the commit is
            allowed. This is distinct from the UNRESOLVED case (which yields a
            ``block``); the two must NOT share the allow path (AG3-036 FIX-C).
    """

    roles: tuple[str, ...] = ()
    block: GuardVerdict | None = None
    non_code_story: bool = False


def _authoritative_required_roles(
    *, project_root: Path, story_id: str
) -> _RequiredRolesOutcome:
    """Resolve mandatory reviewer roles from the authoritative pipeline config.

    FK-68 §68.3.1 / AG3-036 §2.1.5 (FIX-C): the runner — NOT a forgeable harness
    payload — owns the authority. Branches on the TYPED story-type outcome and
    fail-closes on every non-compliant authoritative state:

    - UNRESOLVED story type (backend fault OR missing record) → block
      ``story_type_unresolved`` (NOT downgraded to non-code — the two error cases
      must not reach the non-code allow path);
    - RESOLVED non-code story → ``non_code_story`` allow (ReviewGuard N/A);
    - RESOLVED code story + config unavailable → block ``review_config_unavailable``;
    - RESOLVED code story + ``required_roles`` EMPTY → block
      ``review_required_roles_empty`` (empty coverage defeats §2.1.5 / the
      Integrity-Gate Dim 5 mandatory-reviewer rule — empty is NOT "fully
      compliant");
    - RESOLVED code story + non-empty roles → return the roles.

    Args:
        project_root: Project root for config + story-store resolution.
        story_id: Canonical story display id for the authoritative story type.

    Returns:
        A :class:`_RequiredRolesOutcome` carrying the roles, a block, or the
        ``non_code_story`` allow signal.
    """
    from agentkit.config.loader import load_project_config

    resolution = _resolve_local_story_type(story_id, store_dir=project_root)
    if not resolution.resolved:
        # UNRESOLVED (backend fault OR missing record): fail-closed. Must NOT
        # downgrade to non-code (which would share the allow path).
        return _RequiredRolesOutcome(
            block=GuardVerdict.block(
                "review_guard",
                ViolationType.POLICY_VIOLATION,
                "story_type_unresolved: the authoritative story type could not "
                "be resolved fail-closed (backend fault or missing record)",
                detail={"story_id": story_id},
            ),
        )
    if not resolution.is_code_producing:
        # RESOLVED non-code story: ReviewGuard does not apply (distinct from the
        # UNRESOLVED block above — these must NOT share one path).
        return _RequiredRolesOutcome(non_code_story=True)

    try:
        config = load_project_config(project_root)
    except Exception as exc:  # noqa: BLE001 -- fail-closed mapping of any config/backend fault to a review_config_unavailable BLOCK
        return _RequiredRolesOutcome(
            block=GuardVerdict.block(
                "review_guard",
                ViolationType.POLICY_VIOLATION,
                "review_config_unavailable: pipeline.review.required_roles "
                f"could not be resolved fail-closed ({exc})",
                detail={"fault_class": type(exc).__name__},
            ),
        )
    roles = tuple(config.pipeline.review.required_roles)
    if not roles:
        # RESOLVED code story with EMPTY required_roles: empty coverage provides
        # NO protection and must NOT be treated as fully compliant (FIX-C).
        return _RequiredRolesOutcome(
            block=GuardVerdict.block(
                "review_guard",
                ViolationType.POLICY_VIOLATION,
                "review_required_roles_empty: a code-producing story requires a "
                "non-empty pipeline.review.required_roles (empty coverage defeats "
                "the mandatory-reviewer rule, §2.1.5 / Integrity-Gate Dim 5)",
                detail={"story_id": story_id},
            ),
        )
    return _RequiredRolesOutcome(roles=roles)


_CODE_PRODUCING_STORY_TYPES = frozenset({"implementation", "bugfix"})


@dataclass(frozen=True)
class _StoryTypeResolution:
    """Typed outcome of the authoritative story-type resolution (AG3-036 FIX-A).

    Distinguishes EXACTLY two states; the UNRESOLVED state must NOT be collapsed
    into a story-type string (an empty string previously conflated a backend
    fault and a missing record with a real non-research / non-code story, which
    fails OPEN at the dispatch sites):

    - ``RESOLVED``   — the canonical story store was read AND the record was found;
      ``story_type`` carries the authoritative value (e.g. ``"research"``).
    - ``UNRESOLVED`` — a backend fault OR a missing record. Both downstream
      dispatch sites (ReviewGuard, BudgetEventEmitter) fail-closed on this state
      rather than downgrading it to "not research" / "not code-producing".

    Attributes:
        resolved: ``True`` only for the ``RESOLVED`` state.
        story_type: The authoritative story-type string when ``resolved`` is
            ``True``; an empty string when ``resolved`` is ``False`` (never read
            as a story type — callers must branch on ``resolved`` first).
    """

    resolved: bool
    story_type: str = ""

    @classmethod
    def of(cls, story_type: str) -> _StoryTypeResolution:
        """Return a ``RESOLVED`` outcome carrying *story_type*."""
        return cls(resolved=True, story_type=story_type)

    @classmethod
    def unresolved(cls) -> _StoryTypeResolution:
        """Return the ``UNRESOLVED`` outcome (backend fault OR missing record)."""
        return cls(resolved=False)

    @property
    def is_code_producing(self) -> bool:
        """Whether a RESOLVED story type is code-producing (implementation/bugfix).

        Only meaningful for the ``RESOLVED`` state; an ``UNRESOLVED`` outcome
        returns ``False`` here, but callers must check :attr:`resolved` first and
        fail-closed on UNRESOLVED — they must NOT use this ``False`` as a
        non-code allow path.
        """
        return self.resolved and self.story_type in _CODE_PRODUCING_STORY_TYPES


def _resolve_local_story_type(
    story_id: str, *, store_dir: Path
) -> _StoryTypeResolution:
    """Resolve the authoritative story type as a TYPED outcome (AG3-036 FIX-A).

    FK-24 §24.3.2: the story type is read from the CANONICAL story master data
    (the state-backend ``stories`` table via
    :class:`~agentkit.state_backend.store.story_repository.StateBackendStoryRepository`)
    — NOT from a forgeable ``operation_args`` payload and NOT from a file-based
    export loader (the truth-boundary contract forbids governance modules reading
    story export json / calling ``load_story_context``; the DB store is the
    canonical truth).

    Returns a :class:`_StoryTypeResolution` distinguishing exactly RESOLVED
    (store read + record found) from UNRESOLVED (backend fault OR missing record).
    The two error cases are deliberately NOT collapsed into a story-type string:
    an UNRESOLVED outcome must fail-closed at the dispatch sites instead of
    silently downgrading to "not research" / "not code-producing".

    Args:
        story_id: Canonical story display id.
        store_dir: Base store directory for the SQLite backend (project root).

    Returns:
        A RESOLVED outcome with the story-type string, or the UNRESOLVED outcome.
    """
    from agentkit.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )

    try:
        story = StateBackendStoryRepository(store_dir).get_by_display_id(story_id)
    except Exception:  # noqa: BLE001 -- fail-closed mapping of any backend/store fault to UNRESOLVED (never a story type)
        # Backend fault: UNRESOLVED (fail-closed downstream), never a story type.
        return _StoryTypeResolution.unresolved()
    if story is None:
        # Missing record: UNRESOLVED (fail-closed downstream), never a story type.
        return _StoryTypeResolution.unresolved()
    return _StoryTypeResolution.of(str(story.story_type.value))


def _is_code_producing_story(story_id: str, *, store_dir: Path) -> bool:
    """Return whether a RESOLVED story is code-producing (implementation/bugfix).

    Thin convenience over :func:`_resolve_local_story_type`. An UNRESOLVED outcome
    (backend fault OR missing record) returns ``False`` here; callers that must
    fail-closed on UNRESOLVED branch on the typed
    :class:`_StoryTypeResolution` directly (see :func:`_authoritative_required_roles`
    and :func:`_run_budget_event_emitter`) — they do NOT use this boolean as an
    allow path.

    Args:
        story_id: Canonical story display id.
        store_dir: Base store directory for the SQLite backend (project root).

    Returns:
        ``True`` only for a RESOLVED implementation/bugfix story.
    """
    return _resolve_local_story_type(story_id, store_dir=store_dir).is_code_producing


def _run_budget_event_emitter(
    event: HookEvent, *, project_root: Path
) -> HookDecision:
    """Dispatch the ``budget_event_emitter`` pre-hook (FK-68 §68.6, AG3-036 FIX-3).

    Builds the :class:`~agentkit.telemetry.hooks.budget_event_emitter.BudgetEventEmitter`
    over the canonical :class:`~agentkit.telemetry.storage.StateBackendEmitter`
    for the active story. Only research stories are budget-gated; the
    authoritative story type is resolved at this runner edge from the LOCAL
    story context (FK-24 §24.3.2) — never from a forgeable ``operation_args``
    payload. A research web call over the hard budget emits ``web_call`` and
    returns a fail-closed DENY (blocking the PreToolUse WebFetch/WebSearch BEFORE
    it runs); a non-research story is allowed (no limit).

    Args:
        event: Harness-neutral hook event.
        project_root: Project root for binding + story-type resolution.

    Returns:
        The hook's :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.projectedge.runtime import ProjectEdgeResolver
    from agentkit.telemetry.hooks.base import HookContext, HookTrigger
    from agentkit.telemetry.hooks.budget_event_emitter import BudgetEventEmitter
    from agentkit.telemetry.storage import StateBackendEmitter

    resolved = ProjectEdgeResolver(project_root=project_root).resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=event.freshness_class,
    )
    if resolved.bundle is None or resolved.bundle.session is None:
        return GuardVerdict.allow("budget_event_emitter")
    session = resolved.bundle.session
    story_id = session.story_id
    run_id = session.run_id
    if not story_id or not run_id:
        return GuardVerdict.allow("budget_event_emitter")

    story_dir = project_root / "stories" / story_id

    # FIX-B: branch on the TYPED authoritative outcome BEFORE building the hook
    # context. UNRESOLVED (backend fault OR missing record) for an active binding
    # whose web call we cannot classify is an inconsistent state → fail-closed
    # DENY; we must NOT downgrade it to non-research. The web tool gate (so we
    # only block actual WebFetch/WebSearch) is applied here too.
    tool = _event_tool(event)
    resolution = _resolve_local_story_type(story_id, store_dir=project_root)
    if not resolution.resolved and tool in _WEB_TOOLS:
        return GuardVerdict.block(
            "budget_event_emitter",
            ViolationType.POLICY_VIOLATION,
            "story_type_unresolved: cannot confirm the active story is "
            "non-research or within budget (backend fault or missing record)",
            detail={"story_id": story_id, "tool": tool},
        )

    guard = BudgetEventEmitter(
        StateBackendEmitter(story_dir, default_project_key=session.project_key),
    )
    context = HookContext(
        trigger=HookTrigger.PRE_TOOL_USE,
        story_id=story_id,
        run_id=run_id,
        project_key=session.project_key,
        principal=event.principal_kind,
        tool=tool,
        story_type=resolution.story_type,
        story_type_resolved=resolution.resolved,
    )
    result = guard.evaluate(context)
    guard.emit(result)
    if result.verdict is not None:
        return result.verdict
    return GuardVerdict.allow("budget_event_emitter")


def _event_command(event: HookEvent) -> str:
    """Extract the bash command string from the event operation args.

    Args:
        event: Harness-neutral hook event.

    Returns:
        The command string, or an empty string when absent.
    """
    command = event.operation_args.get("command")
    return command if isinstance(command, str) else ""


#: Maps the harness-neutral ``operation`` back to the canonical tool name. Web
#: tools have no dedicated ``operation`` and arrive as ``unknown_tool`` carrying
#: an explicit ``operation_args["tool_name"]`` (e.g. ``"WebFetch"``).
_OPERATION_TO_TOOL: dict[str, str] = {
    "bash_command": "Bash",
    "file_write": "Write",
    "file_edit": "Edit",
    "file_read": "Read",
}


def _event_tool(event: HookEvent) -> str:
    """Derive the canonical tool name from the harness-neutral event.

    Prefers an explicit ``operation_args["tool_name"]`` (how WebFetch/WebSearch
    arrive, since the HookEvent ``operation`` is ``unknown_tool`` for them);
    otherwise maps the ``operation`` back to the canonical tool name. Mirrors
    ``CcagPermissionRuntime._tool_name_from_event`` (single convention).

    AG3-036 FIX-2: a web-tool name is canonicalized (``web_fetch`` /
    ``web-search`` / ``WEBFETCH`` / ... → ``WebFetch`` / ``WebSearch``) BEFORE it
    is returned, so EVERY alias / casing form resolves to the canonical value the
    ``_WEB_TOOLS`` gate and the BudgetEventEmitter compare against. A
    casing/alias gap here would let an over-budget / unresolved research web call
    slip past the budget guard (fail-open) — the exact hole FIX-2 closes.

    Args:
        event: Harness-neutral hook event.

    Returns:
        The canonical tool name string (e.g. ``"WebFetch"``).
    """
    explicit = event.operation_args.get("tool_name")
    if isinstance(explicit, str) and explicit:
        return canonical_web_tool(explicit) or explicit
    canonical = _OPERATION_TO_TOOL.get(event.operation, event.operation)
    return canonical_web_tool(canonical) or canonical


def _run_self_protection_guard(event: HookEvent) -> HookDecision:
    """Dispatch the ``self_protection`` hook to :class:`SelfProtectionGuard`.

    FK-30 §30.5.4: always active. Wires the real PrincipalResolver /
    PathClassifier / OperationClassifier (no fabricated state — the same
    components the capability enforcement uses).

    Args:
        event: Harness-neutral hook event.

    Returns:
        The guard's :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.governance.guards.self_protection_guard import SelfProtectionGuard
    from agentkit.governance.principal_capabilities import (
        OperationClassifier,
        PathClassifier,
        PrincipalResolver,
    )

    return SelfProtectionGuard(
        principal_resolver=PrincipalResolver(),
        path_classifier=PathClassifier(),
        op_classifier=OperationClassifier(),
    ).evaluate(event)


def _run_story_creation_guard(event: HookEvent) -> HookDecision:
    """Dispatch the ``story_creation_guard`` hook to :class:`StoryCreationGuard`.

    FK-31 §31.5 / FK-21 §21.13: always active.

    Args:
        event: Harness-neutral hook event.

    Returns:
        The guard's :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.governance.guards.story_creation_guard import StoryCreationGuard
    from agentkit.governance.principal_capabilities import (
        OperationClassifier,
        PrincipalResolver,
    )

    return StoryCreationGuard(
        principal_resolver=PrincipalResolver(),
        op_classifier=OperationClassifier(),
    ).evaluate(event)


def _run_capability_enforcement(
    event: HookEvent,
    *,
    project_root: Path,
) -> HookDecision | None:
    """Run FK-55 §55.10.3 steps 1-5 before the legacy guard chain / CCAG.

    Engages for EVERY hook event (FK-55 §55.10.3 / formal
    ``evaluate-principal-operation`` is allowed in ``normal``, ``story_scoped``
    and ``frozen`` status). Absence of an active story binding is ``normal``
    mode, NOT a skip (AG3-032 ERROR 2 — never fail-open).

    Returns a blocking :class:`GuardVerdict` on:

    - a hard capability DENY (matrix / freeze) — in ALL modes; or
    - an UNCLASSIFIED_MUTATION target — in ALL modes. A target that cannot be
      classified to a PathClass while the operation MUTATES (write /
      git_mutation / curate / admin_transition) is a fail-closed BLOCK
      regardless of mode (FK-55 §55.10.2). ``normal`` mode is NOT a fail-open
      escape for unclassified mutations (AG3-032 ERROR 2); the §55.6.1
      unknown-permission rule is a different case that only applies AFTER the
      capability zone is known and must not be used to defer an unclassified
      mutation; or
    - an UNRESOLVED (non-mutating, target-less) event WHEN a story-execution
      binding is active (FK-55 §55.10.2 fail-closed BLOCK; §55.6.1 mode-scharf).
    - a capability-layer evaluation fault (e.g. a corrupt / stale dual freeze
      export) — mapped to a hard BLOCK rather than an escaping runtime fault
      (FK-55 §55.10.5 / FK-31 §31.2.7, AG3-032 ERROR 6).

    Returns ``None`` when the operation is matrix-permitted (ALLOW — proceed to
    CCAG, step 7) OR when a NON-mutating target is unclassifiable OUTSIDE a story
    run (the §55.6.1 unknown-permission rule is mode-scharf: in
    interactive/ai_augmented mode the unknown non-mutating target defers to the
    legacy guards / CCAG / external prompt rather than hard-blocking generic
    interactive work). The deferred step 6 mode-rule (B3 / AG3-018) is what would
    later open a permission request here.
    """
    from agentkit.governance.principal_capabilities import (
        CapabilityEnforcement,
        CapabilityMatrix,
        ConflictFreezeOverlay,
        EnforcementOutcome,
        OperationClassifier,
        PathClassifier,
        PrincipalResolver,
    )
    from agentkit.state_backend.store.freeze_repository import (
        FreezeRepository,
        LocalFreezeJsonExport,
    )

    enforcement = CapabilityEnforcement(
        principal_resolver=PrincipalResolver(),
        path_classifier=PathClassifier(),
        op_classifier=OperationClassifier(),
        matrix=CapabilityMatrix(),
        freeze=ConflictFreezeOverlay(
            FreezeRepository(project_root),
            local_export=LocalFreezeJsonExport(project_root),
        ),
    )
    # FK-55 §55.10.3 step 2: derive execution_mode (and the story binding) from
    # the LOCAL lock/run exports — NOT from operation_args (AG3-032 ERROR C). The
    # ProjectEdgeResolver is the single local source of both the operating mode
    # and the story_scope_binding (same source as guard_evaluation).
    context = _resolve_capability_context(event, project_root=project_root)
    story_id = context.story_id
    scope_roots = context.scope_roots
    try:
        result = enforcement.evaluate(
            event,
            project_root=project_root,
            story_id=story_id,
            story_scope_roots=scope_roots,
        )
    except Exception as exc:  # noqa: BLE001
        # AG3-032 ERROR 6 + ERROR D / FK-55 §55.10.5 / FK-31 §31.2.7 / FAIL-CLOSED:
        # ANY capability-layer evaluation fault must FAIL-CLOSED as a deterministic
        # BLOCK, never escape as a runtime fault. This is the capability-layer
        # boundary: a typed ``PrincipalCapabilityError`` (e.g. a corrupt/stale dual
        # freeze export, FreezePersistenceError) AND an untyped backend fault from
        # the injected FreezeRepository (e.g. a disabled-SQLite / missing-Postgres-
        # URL ``RuntimeError`` raised inside the freeze read) are both mapped here.
        # The concrete fault class is recorded in ``detail`` for the audit trail.
        return _capability_fault_block(exc)
    if result.outcome is EnforcementOutcome.DENY:
        return _capability_block(result.verdict)
    if result.outcome is EnforcementOutcome.UNCLASSIFIED_MUTATION:
        # ALL modes: an unclassified MUTATION target is a fail-closed BLOCK
        # (FK-55 §55.10.2). normal mode is NOT a fail-open escape (ERROR 2).
        return _capability_block(result.verdict)
    if result.outcome is EnforcementOutcome.UNKNOWN_PERMISSION:
        # FK-55 §55.6.1 mode-scharf (AG3-032 ERROR C / FK-55 §55.10.1/§55.10.4):
        # an UNKNOWN tool resolves by the THREE locally-derived mode buckets.
        return _resolve_mode_scoped_block(context, event, result.verdict, project_root)
    if result.outcome is EnforcementOutcome.UNRESOLVED:
        # A non-mutating unclassifiable / target-less event resolves by the SAME
        # three mode buckets (FK-55 §55.10.2 / §55.6.1 mode-scharf): a binding-
        # invalid edge must fail-closed here too — it must NOT defer to CCAG.
        return _resolve_mode_scoped_block(context, event, result.verdict, project_root)
    return None


def _resolve_mode_scoped_block(
    context: _CapabilityContext,
    event: HookEvent,
    verdict: object,
    project_root: Path,
) -> HookDecision | None:
    """Resolve an UNKNOWN_PERMISSION / UNRESOLVED outcome by execution-mode bucket.

    FK-55 §55.6.1 mode-scharf with the §55.10.1/§55.10.4 fail-closed correction
    for inconsistent bindings. Three exhaustive buckets:

    - ``story_execution``: a coherent autonomous run. Open a GRANTABLE
      ``permission_request`` AND return a blocking verdict (no native prompt may
      hang a run). Unchanged behaviour.
    - ``binding_invalid``: a story-execution lock/session EXISTS but is
      inconsistent (session mismatch / inactive lock / worktree-root mismatch).
      A broken binding must NOT degrade to free mode and is NOT a grantable
      in-story permission — it is a fail-closed HARD BLOCK carrying the resolver
      ``block_reason`` (FK-55 §55.10.1/§55.10.4, FK-56 §51, FK-59 §175).
    - genuine ``ai_augmented`` (no lock/session at all): defer (return ``None``).
      This is the ONLY bucket that may defer to CCAG / an external prompt.
    """
    if context.is_story_execution:
        return _block_with_permission_request(event, verdict, project_root)
    if context.is_binding_invalid:
        return _binding_invalid_block(context.block_reason)
    return None


def _binding_invalid_block(reason: str | None) -> HookDecision:
    """Fail-closed HARD BLOCK for an inconsistent story-execution binding.

    FK-55 §55.10.1/§55.10.4 (FK-56 §51 "broken binding must not degrade to free
    mode", FK-59 §175 "binding_invalid is not a normal third mode"): when a
    story-execution lock/session exists but is inconsistent, an unknown /
    unresolved permission must NOT open a grantable in-story permission_request
    and must NOT defer to CCAG. It is a deterministic ``principal_capability``
    BLOCK whose ``detail`` carries the specific resolver ``block_reason``.

    Args:
        reason: The ``ProjectEdgeResolver`` block reason (e.g.
            ``worktree_root_mismatch``), or ``None`` if not available.

    Returns:
        A blocking :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        f"operating_mode binding_invalid: {reason or 'inconsistent_story_binding'}",
        detail={
            "capability_rule_id": "FK-55-55.10.1/55.10.4",
            "operating_mode": "binding_invalid",
            "block_reason": reason,
        },
    )


def _block_with_permission_request(
    event: HookEvent,
    verdict: object,
    project_root: Path,
) -> HookDecision:
    """Open a permission_request (story_execution) and return a blocking verdict.

    FK-55 §55.6.1 / formal ``open-permission-request``: in ``story_execution`` an
    unknown / non-actionable permission must not hang on a native host prompt —
    the hook blocks AND emits an auditable ``permission_request_opened`` (AG3-032
    ERROR C). Request creation is owned by the CCAG runtime (the single owner of
    permission requests); the runner only triggers it with the locally-derived
    mode. A failure to persist the request must not turn the fail-closed BLOCK
    into a fault that escapes — it stays a deterministic BLOCK.
    """
    from agentkit.governance.ccag.runtime import CcagPermissionRuntime

    request_id: str | None = None
    try:
        request = CcagPermissionRuntime(
            request_db_path=project_root / ".agentkit" / "ccag" / "ccag_requests.db"
        ).open_permission_request(event)
        request_id = request.request_id
    except Exception:  # noqa: BLE001
        # FAIL-CLOSED: persisting the audit request is best-effort; the block
        # stands regardless. The block reason already carries the rule id.
        request_id = None
    reason = getattr(verdict, "reason", "capability denied")
    rule_id = getattr(verdict, "rule_id", None)
    detail: dict[str, object] = {
        "capability_rule_id": rule_id,
        "permission_request_opened": request_id is not None,
    }
    if request_id is not None:
        detail["permission_request_id"] = request_id
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        reason,
        detail=detail,
    )


def _capability_block(verdict: object) -> HookDecision:
    """Translate a capability DENY verdict into a blocking GuardVerdict."""
    reason = getattr(verdict, "reason", "capability denied")
    rule_id = getattr(verdict, "rule_id", None)
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        reason,
        detail={"capability_rule_id": rule_id},
    )


def _capability_fault_block(exc: Exception) -> HookDecision:
    """Map a capability-layer fault to a hard fail-closed BLOCK (ERROR 6).

    FK-55 §55.10.5 / FK-31 §31.2.7: a stale / missing / corrupt dual freeze
    context (or any other capability-layer wiring fault) must surface as a
    deterministic ``principal_capability`` BLOCK, not as an escaping runtime
    exception. The fault class is recorded in ``detail`` for the audit trail.
    """
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        f"capability evaluation failed fail-closed: {exc}",
        detail={
            "capability_rule_id": "FK-55-55.10.5",
            "fault_class": type(exc).__name__,
        },
    )


@dataclass(frozen=True)
class _CapabilityContext:
    """Locally-derived capability context (FK-55 §55.10.3 steps 2 + 4).

    Attributes:
        execution_mode: The execution mode derived from the LOCAL lock/run
            exports (``ProjectEdgeResolver.operating_mode`` — one of
            ``"story_execution"`` / ``"ai_augmented"`` / ``"binding_invalid"``).
            NOT read from ``operation_args`` (AG3-032 ERROR C / §55.10.3 step 2).
        story_id: The active story id, or ``None`` when no story binding is
            published (``normal`` mode — enforcement still engages).
        scope_roots: The §55.7.1 story-scope roots (worktree roots), or ``None``.
        block_reason: The ``ProjectEdgeResolver`` block reason that accompanies a
            ``binding_invalid`` mode (one of ``session_binding_mismatch`` /
            ``inactive_story_execution_lock`` / ``worktree_root_mismatch``), or
            ``None`` for a coherent ``story_execution`` / ``ai_augmented`` mode.
    """

    execution_mode: str
    story_id: str | None
    scope_roots: list[str] | None
    block_reason: str | None = None

    @property
    def is_story_execution(self) -> bool:
        """Whether the locally-derived mode is the autonomous ``story_execution``.

        Only this mode hard-blocks an unknown / non-actionable permission and
        opens a GRANTABLE permission_request (FK-55 §55.6.1); genuine
        ``ai_augmented`` (no lock/session at all) defers to an external prompt.
        """
        return self.execution_mode == "story_execution"

    @property
    def is_binding_invalid(self) -> bool:
        """Whether the locally-derived mode is the INCONSISTENT ``binding_invalid``.

        FK-55 §55.10.1/§55.10.4 (and FK-56 §51, FK-59 §175): a story-execution
        lock/session EXISTS but is inconsistent (session mismatch, inactive lock,
        worktree-root mismatch). A broken binding must NOT degrade to free mode
        and must NOT open a grantable in-story permission — it is a fail-closed
        HARD BLOCK. ``binding_invalid`` is not a normal third mode.
        """
        return self.execution_mode == "binding_invalid"


def _resolve_capability_context(
    event: HookEvent,
    *,
    project_root: Path,
) -> _CapabilityContext:
    """Resolve the execution mode + story binding from the LOCAL edge bundle.

    FK-55 §55.10.3 step 2 + step 4 / §55.7.1: both the ``execution_mode`` and the
    ``story_scope_binding`` (story id + participating-repo / worktree roots) are
    read from the locally materialized run context (the lock/run exports), NOT
    from prompt content or ``operation_args``. Mirrors the source used by
    ``guard_evaluation``. When no active story binding is published the mode is
    whatever the resolver derives (``ai_augmented`` with no lock; ``binding_invalid``
    on a mismatched lock) and the story fields are ``None`` (``normal`` mode —
    enforcement still engages; story paths simply have no in-scope root).
    """
    from agentkit.projectedge.runtime import ProjectEdgeResolver

    resolved = ProjectEdgeResolver(project_root=project_root).resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=event.freshness_class,
    )
    if resolved.bundle is None or resolved.bundle.session is None:
        return _CapabilityContext(
            execution_mode=resolved.operating_mode,
            story_id=None,
            scope_roots=None,
            block_reason=resolved.block_reason,
        )
    session = resolved.bundle.session
    return _CapabilityContext(
        execution_mode=resolved.operating_mode,
        story_id=session.story_id,
        scope_roots=list(session.worktree_roots),
        block_reason=resolved.block_reason,
    )


def _run_ccag_hook(event: HookEvent) -> HookDecision:
    """Dispatch to CcagPermissionRuntime and translate decision to GuardVerdict.

    The CCAG runtime returns a :class:`~agentkit.governance.ccag.runtime.CcagDecision`
    which we map to the :class:`~agentkit.governance.protocols.GuardVerdict`
    type used by the hook chain.

    Translation:
        ``allow``              → ``GuardVerdict.allow("ccag_gatekeeper")``
        ``unknown_permission`` → ``GuardVerdict.allow("ccag_gatekeeper")``
            (unknown → adapter decides; in story_execution the request is
             persisted and the CLI exits 2 via the standalone path)
        ``block_by_rule``      → ``GuardVerdict.block("ccag_gatekeeper", ...)``

    Args:
        event: Harness-neutral hook event.

    Returns:
        A :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.governance.ccag.runtime import CcagDecisionKind, CcagPermissionRuntime

    runtime = CcagPermissionRuntime()
    decision = runtime.evaluate(event)

    if decision.kind == CcagDecisionKind.BLOCK_BY_RULE:
        return GuardVerdict.block(
            "ccag_gatekeeper",
            ViolationType.UNAUTHORIZED_OPERATION,
            decision.reason or "Blocked by CCAG deny rule",
            detail={
                "ccag_decision": decision.kind.value,
                "matched_rule_id": decision.matched_rule_id,
            },
        )

    # allow or unknown_permission → allow at the GuardVerdict level
    # For unknown_permission in story_execution, the PermissionRequest was
    # already created by CcagPermissionRuntime._handle_unknown(); the CLI
    # entry points can inspect the decision.kind for exit code decisions.
    return GuardVerdict.allow("ccag_gatekeeper")


def _hook_ids_for_phase(phase: str) -> frozenset[str]:
    if phase == "pre":
        return PRE_HOOK_IDS
    if phase == "post":
        return POST_HOOK_IDS
    return frozenset()


def _decision_scope(
    context: dict[str, object],
) -> tuple[str, str, str, str, str | None] | None:
    project_key = context.get("project_key")
    story_id = context.get("active_story_id") or context.get("story_id")
    run_id = context.get("run_id")
    if not (
        isinstance(project_key, str)
        and isinstance(story_id, str)
        and isinstance(run_id, str)
        and project_key
        and story_id
        and run_id
    ):
        return None
    flow_id = context.get("flow_id")
    node_id = context.get("node_id")
    return (
        project_key,
        story_id,
        run_id,
        flow_id if isinstance(flow_id, str) and flow_id else "hook",
        node_id if isinstance(node_id, str) and node_id else None,
    )


def _evidence_ref(verdict: GuardVerdict) -> str | None:
    detail = verdict.detail or {}
    ref = detail.get("evidence_ref")
    return ref if isinstance(ref, str) else None


__all__ = [
    "Governance",
    "GuardRunner",
    "HookDecision",
    "HookWrapperArgs",
    "POST_HOOK_IDS",
    "PRE_HOOK_IDS",
    "SUPPORTED_HOOK_IDS",
    "SUPPORTED_PHASES",
    "parse_hook_wrapper_args",
    "run_hook",
    "validate_hook_selector",
]

# DeactivationResult and LockRecordId are imported at the top of the file
# and live in governance.locks; re-exported here for convenience.
