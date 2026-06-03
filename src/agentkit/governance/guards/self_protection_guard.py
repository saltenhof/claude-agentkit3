"""Governance self-protection guard (FK-30 §30.5.4 / FK-15 §15.7.1).

The :class:`SelfProtectionGuard` blocks a mutation of the governance
infrastructure by a principal the concept does not grant for the targeted zone.
It is **always active**, independent of the operating mode (FK-30 §30.5.4
"Dieser Hook ist immer aktiv"). It is a Schicht-A (threat-level-1+2) guard: it
acts on the structured target keys and on the *visible* Bash mutation targets
(FK-55 §55.10.2); active obfuscation (Schicht B) is out of scope.

Protected targets come exclusively from the ``SELF_PROTECTION_*`` registry in
:mod:`agentkit.governance.guard_system.protected_paths` (SINGLE SOURCE OF TRUTH;
no protected-path literals live here — CLAUDE.md) plus the
``GOVERNANCE_PLANE`` / ``GIT_INTERNAL`` :class:`PathClass` zones already owned by
the :class:`PathClassifier` (lock-records, edge-bundle / freeze exports,
``.agent-guard``, git internals — FK-55 §55.4). They fall into two policy zones
(see :data:`SelfProtectionGuard._ZONE_POLICY`):

- **harness zone** — harness hook-settings + CCAG-/skill-symlink dirs. Only the
  Installer (Zone-2 deterministic, FK-30 §30.3.1) materialises these binding
  points; FK-15 §15.4.1 grants no other writer → fail-closed to the most
  restrictive grounded principal: :attr:`Principal.PIPELINE_DETERMINISTIC` only.
- **governance zone** — governance config / installer manifest plus the
  governance-plane and git internals. FK-15 §15.4.1 / §15.7.3 + FK-30 §30.3.3
  ground :attr:`Principal.PIPELINE_DETERMINISTIC` (Zone-2 scripts),
  :attr:`Principal.ADMIN_SERVICE` (official reset/split/resolve) and
  :attr:`Principal.HUMAN_CLI` (the FK-15 §15.4.1 "Mensch über Admin/CLI" path).

Runtime dispatch is wired in
:func:`agentkit.governance.runner._run_self_protection_guard` for the
``self_protection`` hook id; the install-time PreToolUse matcher
(``Write|Edit|Bash``) is owned by the Installer / harness adapters (FK-30
§30.3.1 / FK-76 §76.5) and pinned by the guard-registration contract test.
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


class SelfProtectionGuard:
    """Blocks a non-granted mutation of the governance infrastructure.

    FK-30 §30.5.4: always active. A mutating operation (``write`` /
    ``git_mutation`` / ``curate`` / ``admin_transition``) whose target is a
    protected governance path is a hard DENY unless the resolved principal is in
    the concept-grounded whitelist for that target's protection zone (see the
    module docstring / :data:`_ZONE_POLICY`).
    """

    #: Protection zones (AG3-033 per-zone whitelist, FK-30 §30.5.4 / FK-15 §15.7.x).
    _ZONE_HARNESS = "harness"
    _ZONE_GOVERNANCE = "governance"

    #: harness zone — only the Installer (Zone-2 deterministic) writes these
    #: binding points. Concept silent on any other writer → fail-closed to the
    #: most restrictive grounded principal (FK-15 §15.7.3 floor): pipeline only.
    _HARNESS_PRINCIPALS: frozenset[Principal] = frozenset(
        {
            Principal.PIPELINE_DETERMINISTIC,
        }
    )

    #: governance zone — lock-records / governance config / manifest / git.
    #: FK-15 §15.4.1 ("Lock-Record erstellen/beenden": Pipeline-Skript ✅, Mensch
    #: ✅ über Admin/CLI) + FK-30 §30.3.3 (official reset/split service path).
    _GOVERNANCE_PRINCIPALS: frozenset[Principal] = frozenset(
        {
            Principal.PIPELINE_DETERMINISTIC,
            Principal.ADMIN_SERVICE,
            Principal.HUMAN_CLI,
        }
    )

    #: Zone → allowed-principal policy. A mutation of a protected target is a hard
    #: DENY unless the resolved principal is in the policy set for that zone.
    _ZONE_POLICY: dict[str, frozenset[Principal]] = {
        _ZONE_HARNESS: _HARNESS_PRINCIPALS,
        _ZONE_GOVERNANCE: _GOVERNANCE_PRINCIPALS,
    }

    #: Operation classes that mutate state (FK-55 §55.10.2). A non-mutating op is
    #: never blocked by self-protection (read/inspect a governance file is
    #: allowed; the hard capability matrix governs read access separately).
    _MUTATING_OPS: frozenset[OperationClass] = frozenset(
        {
            OperationClass.WRITE,
            OperationClass.GIT_MUTATION,
            OperationClass.CURATE,
            OperationClass.ADMIN_TRANSITION,
        }
    )

    #: PathClasses the PathClassifier already resolves that belong to the
    #: governance-truth zone (FK-55 §55.4): the governance plane (lock-records,
    #: edge-bundle exports, freeze export, ``.agent-guard``) and git internals.
    _GOVERNANCE_PATH_CLASSES: frozenset[PathClass] = frozenset(
        {
            PathClass.GOVERNANCE_PLANE,
            PathClass.GIT_INTERNAL,
        }
    )

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
        if op_class not in self._MUTATING_OPS:
            return GuardVerdict.allow(self.name)

        hit = self._protected_target(event)
        if hit is None:
            return GuardVerdict.allow(self.name)
        target, zone = hit

        principal = self._principal_resolver.resolve(event)
        if principal in self._ZONE_POLICY[zone]:
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
            return self._ZONE_HARNESS
        if _under_dir(segments, SELF_PROTECTION_HARNESS_DIR_PARTS):
            return self._ZONE_HARNESS
        # governance zone: config / manifest files.
        if _matches_file(segments, SELF_PROTECTION_GOVERNANCE_FILE_PARTS):
            return self._ZONE_GOVERNANCE
        # governance zone: governance-plane / git-internal (owned by the
        # PathClassifier — lock-records, edge-bundle / freeze exports, ``.git``).
        # project_root is irrelevant for these prefix/segment-based classes.
        path_class = self._path_classifier.classify(target, project_root=".")
        if path_class in self._GOVERNANCE_PATH_CLASSES:
            return self._ZONE_GOVERNANCE
        return None


def _segments(path: str) -> list[str]:
    """Split ``path`` into non-empty POSIX/Windows-tolerant segments."""
    raw = path.replace("\\", "/")
    return [seg for seg in raw.split("/") if seg not in ("", ".")]


def _matches_file(segments: list[str], file_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` ends with one of the exact protected file tuples."""
    return any(len(parts) <= len(segments) and parts == tuple(segments[-len(parts) :]) for parts in file_parts)


def _under_dir(segments: list[str], dir_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` contains one of the protected dir tuples as a run."""
    return any(_run_matches(segments, parts) for parts in dir_parts)


def _run_matches(segments: list[str], parts: tuple[str, ...]) -> bool:
    """Whether ``parts`` appears as a contiguous run within ``segments``."""
    width = len(parts)
    return any(parts == tuple(segments[start : start + width]) for start in range(len(segments) - width + 1))


__all__ = [
    "GUARD_NAME",
    "RULE_ID",
    "SelfProtectionGuard",
]
