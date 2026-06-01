"""Guard runner -- evaluates all registered guards for an operation.

Orchestration only (ARCH-12). Business logic lives in individual guards.
The runner is fail-closed: if any guard blocks, the operation is blocked.
All guards run even if earlier ones block, so that complete violation
information is collected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.errors import LockRecordNotFoundError
from agentkit.governance.locks import DeactivationResult, LockRecordId
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
    }
)
POST_HOOK_IDS = frozenset(
    {
        "telemetry",
        "review_guard",
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
    ) -> None:
        self._guards: list[GovernanceGuard] = list(guards) if guards else []

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
        return [g.evaluate(operation, context) for g in self._guards]

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
        return GuardVerdict.allow(hook_id)

    # CCAG is the last PreToolUse hook — dispatched separately (FK-42 §42.5.2)
    if hook_id == "ccag_gatekeeper":
        return _run_ccag_hook(event)

    from agentkit.governance.guard_evaluation import evaluate_pre_tool_use

    return evaluate_pre_tool_use(event, project_root=project_root or Path.cwd())


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

