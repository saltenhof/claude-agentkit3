"""Governance self-protection guard (FK-30 §30.5.4 / FK-15 §15.7.1).

The :class:`SelfProtectionGuard` protects the governance infrastructure itself
against mutation by a principal the concept does not grant for the targeted
zone. It is **always active**, independent of the operating mode (AI-Augmented
or Story-Execution) — FK-30 §30.5.4 "Dieser Hook ist immer aktiv".

Protected targets are sourced exclusively from the
``SELF_PROTECTION_*`` registry in
:mod:`agentkit.governance.guard_system.protected_paths` (SINGLE SOURCE OF TRUTH;
no protected-path literals live in this module — CLAUDE.md) plus the
:class:`~agentkit.governance.principal_capabilities.paths.PathClass`
``GOVERNANCE_PLANE`` / ``GIT_INTERNAL`` zones already owned by the
:class:`~agentkit.governance.principal_capabilities.paths.PathClassifier`
(lock-records, edge-bundle exports, freeze export, ``.agent-guard``, git
internals — FK-55 §55.4). They fall into two policy ZONES (see
``_ZONE_POLICY`` below): the harness-binding zone and the governance-truth zone.

Per-zone whitelist (FK-30 §30.5.4 / FK-15 §15.7.3, AG3-033 narrowing — replaces
the former flat privileged trio):

- **harness zone** — harness hook-settings + CCAG-/skill-symlink dirs. These
  binding points are materialised ONLY by the Installer (FK-30 §30.3.1
  "Aufrufer: Installer" → ``Governance.register_hooks`` → the settings writers;
  FK-50 CP 9), a deterministic Zone-2 process. FK-15 §15.4.1 has no row granting
  any agent or human-CLI a direct write here, so the concept is effectively
  silent on a non-installer writer → fail-closed to the most restrictive
  grounded principal: :attr:`Principal.PIPELINE_DETERMINISTIC` only. Neither
  ``admin_service`` (reset/split, FK-30 §30.3.3) nor ``human_cli`` writes hook
  settings at runtime; both are excluded.
- **governance zone** — governance config / installer manifest, plus the
  governance-plane (lock-records, edge-bundle / freeze exports, ``.agent-guard``)
  and git internals. FK-15 §15.4.1 grants "Lock-Record erstellen/beenden" and
  "Zentralen Workflow-State mutieren" to Pipeline-Skript (✅) and Mensch (✅, via
  Admin/CLI), and FK-30 §30.3.3 grants the official ``StoryReset``/``StorySplit``
  service path; FK-15 §15.7.3 "Nur Pipeline-Skripte (Zone 2) schreiben
  Lock-Records" is the floor. Mapped onto the FK-55 §55.3 principals:
  :attr:`Principal.PIPELINE_DETERMINISTIC` (Zone-2 scripts),
  :attr:`Principal.ADMIN_SERVICE` (official reset/split/resolve services) and
  :attr:`Principal.HUMAN_CLI` (the FK-15 §15.4.1 "Mensch über Admin/CLI" path,
  FK-30 §30.3.3 pt. 5 "ausdrueckliche menschliche CLI-Ausfuehrung").

Always-active registration nexus (AG3-033 WARNING D — documented dependency):
this guard's *runtime* dispatch is wired in
:func:`agentkit.governance.runner._run_self_protection_guard` for the
``self_protection`` hook id, ahead of the generic chain (capability enforcement
still runs first). The install-time *materialisation* that makes the hook fire
for the FK-30 §30.3.1 PreToolUse matchers ``Write|Edit|Bash`` is owned by the
Installer / harness adapters (FK-30 §30.3.1 / FK-76 §76.5 — settings writers),
NOT by AG3-033. The normative matcher is pinned by the guard-registration
contract test; the install-time wiring is the Installer's responsibility.

Type-name reconciliation against the delivered AG3-032 model (the AG3-033
story.md predates AG3-032 and names types that do not exist):

- ``FILE_WRITE`` / ``FILE_EDIT`` / ``SHELL_EXEC`` of the story sketch are not real
  ``OperationClass`` members. A structured write tool and a shell file mutation
  both normalize to :attr:`OperationClass.WRITE`; a destructive shell command
  (``rm`` / ``del`` / ``mv`` on a protected target) is likewise surfaced as a
  ``WRITE`` over its mutation targets by the :class:`OperationClassifier`
  (FK-55 §55.10.2 ``bash_mutation_targets``). A non-mutating ``execute`` /
  ``read`` is never blocked by this guard.
- ``PathClass.PROTECTED_GOVERNANCE_LOCK`` of the story sketch does not exist; the
  delivered model classifies governance artifacts as
  :attr:`PathClass.GOVERNANCE_PLANE` (plus :attr:`PathClass.GIT_INTERNAL`).
- ``INSTALLER`` / ``RECOVERY`` principals of the story sketch do not exist; they
  reconcile onto the FK-55 §55.3 principals named per-zone above.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.guard_system.protected_paths import (
    SELF_PROTECTION_GOVERNANCE_FILE_PARTS,
    SELF_PROTECTION_HARNESS_DIR_PARTS,
    SELF_PROTECTION_HARNESS_FILE_PARTS,
)
from agentkit.governance.principal_capabilities.operations import (
    OperationClass,
    bash_mutation_targets,
)
from agentkit.governance.principal_capabilities.paths import PathClass
from agentkit.governance.principal_capabilities.principals import Principal
from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.principal_capabilities.operations import (
        OperationClassifier,
    )
    from agentkit.governance.principal_capabilities.paths import PathClassifier
    from agentkit.governance.principal_capabilities.principals import PrincipalResolver

#: FK-30 §30.5.4 rule id surfaced on a self-protection block.
RULE_ID = "FK-30 §30.5.4"

#: Guard identifier (matches the FK-30 §30.5.1 hook id ``self_protection``).
GUARD_NAME = "self_protection"

#: Protection zones (AG3-033 per-zone whitelist, FK-30 §30.5.4 / FK-15 §15.7.x).
_ZONE_HARNESS = "harness"
_ZONE_GOVERNANCE = "governance"

#: harness zone — only the Installer (Zone-2 deterministic) writes these
#: binding points. Concept silent on any other writer → fail-closed to the most
#: restrictive grounded principal (FK-15 §15.7.3 floor): pipeline only.
_HARNESS_PRINCIPALS: frozenset[Principal] = frozenset(
    {
        Principal.PIPELINE_DETERMINISTIC,
    }
)

#: governance zone — lock-records / governance config / manifest / git.
#: FK-15 §15.4.1 ("Lock-Record erstellen/beenden": Pipeline-Skript ✅, Mensch ✅
#: über Admin/CLI) + FK-30 §30.3.3 (official reset/split service path).
_GOVERNANCE_PRINCIPALS: frozenset[Principal] = frozenset(
    {
        Principal.PIPELINE_DETERMINISTIC,
        Principal.ADMIN_SERVICE,
        Principal.HUMAN_CLI,
    }
)

#: Zone → allowed-principal policy. A mutation of a protected target is a hard
#: DENY unless the resolved principal is in the policy set for the target's zone.
_ZONE_POLICY: dict[str, frozenset[Principal]] = {
    _ZONE_HARNESS: _HARNESS_PRINCIPALS,
    _ZONE_GOVERNANCE: _GOVERNANCE_PRINCIPALS,
}

#: Operation classes that mutate state (FK-55 §55.10.2). A non-mutating op is
#: never blocked by self-protection (read/inspect a governance file is allowed;
#: the hard capability matrix governs read access separately).
_MUTATING_OPS: frozenset[OperationClass] = frozenset(
    {
        OperationClass.WRITE,
        OperationClass.GIT_MUTATION,
        OperationClass.CURATE,
        OperationClass.ADMIN_TRANSITION,
    }
)

#: PathClasses that the PathClassifier already resolves and that belong to the
#: governance-truth zone (FK-55 §55.4): the governance plane (lock-records,
#: edge-bundle exports, freeze export, ``.agent-guard``) and the git internals.
_GOVERNANCE_PATH_CLASSES: frozenset[PathClass] = frozenset(
    {
        PathClass.GOVERNANCE_PLANE,
        PathClass.GIT_INTERNAL,
    }
)


class SelfProtectionGuard:
    """Blocks a non-granted mutation of the governance infrastructure.

    FK-30 §30.5.4: always active. A mutating operation (``write`` /
    ``git_mutation`` / ``curate`` / ``admin_transition``) whose target is a
    protected governance path is a hard DENY unless the resolved principal is in
    the concept-grounded whitelist for that target's protection zone (see the
    module docstring / ``_ZONE_POLICY``).
    """

    def __init__(
        self,
        principal_resolver: PrincipalResolver,
        path_classifier: PathClassifier,
        op_classifier: OperationClassifier,
    ) -> None:
        """Create the guard.

        Args:
            principal_resolver: Resolves the technical principal from the
                harness/event context (FK-55 §55.3a).
            path_classifier: Classifies a target path to a :class:`PathClass`
                (used for the governance-plane / git-internal zones).
            op_classifier: Normalizes the tool call to an
                :class:`OperationClass`.
        """
        self._principal_resolver = principal_resolver
        self._path_classifier = path_classifier
        self._op_classifier = op_classifier

    @property
    def name(self) -> str:
        """Short identifier for this guard (FK-30 §30.5.1 hook id)."""
        return GUARD_NAME

    def evaluate(self, event: HookEvent) -> GuardVerdict:
        """Evaluate ``event`` against the self-protection rules.

        Args:
            event: Harness-neutral hook event.

        Returns:
            A blocking :class:`GuardVerdict` when a principal that is not
            whitelisted for the target's protection zone mutates a protected
            governance path; otherwise an allow verdict.
        """
        op_class = self._op_classifier.classify(event.operation, event.operation_args)
        if op_class not in _MUTATING_OPS:
            return GuardVerdict.allow(self.name)

        hit = self._protected_target(event)
        if hit is None:
            return GuardVerdict.allow(self.name)
        target, zone = hit

        principal = self._principal_resolver.resolve(event)
        if principal in _ZONE_POLICY[zone]:
            return GuardVerdict.allow(self.name)

        return GuardVerdict.block(
            self.name,
            ViolationType.UNAUTHORIZED_OPERATION,
            "Mutation of protected governance infrastructure is forbidden",
            detail={
                "rule_id": RULE_ID,
                "protected_target": target,
                "protection_zone": zone,
                "principal": principal.value,
                "operation_class": op_class.value,
            },
        )

    def _protected_target(self, event: HookEvent) -> tuple[str, str] | None:
        """Return the first protected ``(target, zone)`` of ``event``, or ``None``.

        Inspects the structured target keys (``file_path`` / ``path`` /
        ``notebook_path``) and — for a shell command — the visible Bash mutation
        targets (FK-55 §55.10.2 ``bash_mutation_targets``). A target is protected
        when it matches the self-protection registry (harness hook settings /
        symlink dirs → harness zone; config / manifest → governance zone) OR
        classifies as ``governance_plane`` / ``git_internal`` → governance zone
        (FK-55 §55.4).
        """
        for target in self._candidate_targets(event):
            zone = self._zone_of(target)
            if zone is not None:
                return target, zone
        return None

    @staticmethod
    def _candidate_targets(event: HookEvent) -> list[str]:
        """Extract cheap candidate target paths from the event args."""
        args = event.operation_args
        candidates: list[str] = []
        for key in ("file_path", "path", "notebook_path"):
            value = args.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
        command = args.get("command")
        if command is None:
            command = args.get("cmd")
        if isinstance(command, str) and command:
            candidates.extend(bash_mutation_targets(command))
        return candidates

    def _zone_of(self, target: str) -> str | None:
        """Return the protection zone of ``target``, or ``None`` if unprotected."""
        segments = _segments(target)
        if not segments:
            return None
        # harness zone: exact hook-settings files + CCAG-/skill-symlink dirs.
        if _matches_file(segments, SELF_PROTECTION_HARNESS_FILE_PARTS):
            return _ZONE_HARNESS
        if _under_dir(segments, SELF_PROTECTION_HARNESS_DIR_PARTS):
            return _ZONE_HARNESS
        # governance zone: config / manifest files.
        if _matches_file(segments, SELF_PROTECTION_GOVERNANCE_FILE_PARTS):
            return _ZONE_GOVERNANCE
        # governance zone: governance-plane / git-internal (owned by the
        # PathClassifier — lock-records, edge-bundle / freeze exports, ``.git``).
        # project_root is irrelevant for these prefix/segment-based classes.
        path_class = self._path_classifier.classify(target, project_root=".")
        if path_class in _GOVERNANCE_PATH_CLASSES:
            return _ZONE_GOVERNANCE
        return None


def _segments(path: str) -> list[str]:
    """Split ``path`` into non-empty POSIX/Windows-tolerant segments."""
    raw = path.replace("\\", "/")
    return [seg for seg in raw.split("/") if seg not in ("", ".")]


def _matches_file(segments: list[str], file_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` ends with one of the exact protected file tuples."""
    return any(
        len(parts) <= len(segments) and parts == tuple(segments[-len(parts) :])
        for parts in file_parts
    )


def _under_dir(segments: list[str], dir_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` contains one of the protected dir tuples as a run."""
    return any(_run_matches(segments, parts) for parts in dir_parts)


def _run_matches(segments: list[str], parts: tuple[str, ...]) -> bool:
    """Whether ``parts`` appears as a contiguous run within ``segments``."""
    width = len(parts)
    return any(
        parts == tuple(segments[start : start + width])
        for start in range(len(segments) - width + 1)
    )


__all__ = [
    "GUARD_NAME",
    "RULE_ID",
    "SelfProtectionGuard",
]
