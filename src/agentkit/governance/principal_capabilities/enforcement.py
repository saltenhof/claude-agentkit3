"""Capability enforcement pipeline (FK-55 §55.10.3 steps 1-5 + step 7 CCAG gate).

:class:`CapabilityEnforcement` runs the normed FK-55 §55.10.3 evaluation order
for a single hook event:

1. resolve the :class:`Principal` (fail-closed, harness-context only — §55.3a)
2. normalize the tool call to an :class:`OperationClass`
3. normalize the target(s) to :class:`PathClass` (or the unclassified sentinel)
4. consult the hard capability matrix
5. apply the conflict-freeze overlay

The evaluation engages for EVERY hook event (FK-55 §55.10.3 / formal
``evaluate-principal-operation`` is allowed in ``normal``, ``story_scoped`` and
``frozen`` status). Absence of an active story binding is ``normal`` mode, NOT a
skip (AG3-032 ERROR 2 — never fail-open). The result is a five-way
:class:`EnforcementOutcome`:

- ``DENY``       — a hard matrix / freeze block. Hard in ALL modes; CCAG must
                   not run and cannot soften it (governance-and-guards.B5 /
                   invariant ``ccag_never_elevates_hard_capabilities``).
- ``ALLOW``      — the matrix (post-freeze) permits the operation.
- ``UNCLASSIFIED_MUTATION`` — a *mutating* operation (write / git_mutation /
                   curate / admin_transition) that did not resolve to an explicit
                   matrix ALLOW because at least one target could not be
                   classified to a PathClass — INCLUDING the case where no
                   concrete target was extracted at all (missing / empty /
                   ambiguous target). Per FK-55 §55.10.2 an unclassifiable
                   mutation is a fail-closed BLOCK in ALL modes — NOT a deferral.
                   The §55.6.1 unknown-permission rule is a DIFFERENT case (it
                   applies only AFTER the capability zone is known) and must never
                   be used to wave through an unclassified mutation. The caller
                   blocks this regardless of mode (AG3-032 ERROR 2).
- ``UNRESOLVED`` — a genuinely non-actionable event: a target could not be
                   classified but the operation is NON-mutating (a pure read /
                   plain exec with no discernible file/mutation target). The
                   caller resolves this *mode-scharf* (§55.6.1): in
                   ``story_execution`` it is a fail-closed BLOCK (opening a
                   permission_request); outside a story run it may defer to the
                   mode rule / CCAG (no hard block).
- ``UNKNOWN_PERMISSION`` — the TOOL itself is unknown to the classifier (no
                   concrete operation class to grant). The matrix is NOT consulted
                   for an ALLOW (AG3-032 ERROR C — an unknown worker tool in story
                   scope must not be allowed). A hard matrix / freeze DENY still
                   PRECEDES this. The caller resolves it mode-scharf (§55.6.1):
                   ``story_execution`` ⇒ BLOCK + ``permission_request_opened``;
                   ``interactive_admin`` / ``ai_augmented`` ⇒ defer to an external
                   prompt.

Step 6 (official service paths / mode rule) is deliberately rudimentary in this
story (AG3-032 §2.1.4 — out of scope; follow-up Fast-Modus story). Because the
service-path validator is deferred, the matrix itself is fail-closed for the
dangerous service-principal cells (see ``matrix_data``). Step 7 (CCAG, FK-30
§30.2.6) runs ONLY on an ``ALLOW`` outcome — surfaced via
:meth:`should_run_ccag`.
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.principal_capabilities.matrix import (
    CapabilityDecision,
    CapabilityVerdict,
)
from agentkit.governance.principal_capabilities.operations import (
    OperationClass,
    bash_mutation_targets,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.principal_capabilities.freeze import ConflictFreezeOverlay
    from agentkit.governance.principal_capabilities.matrix import CapabilityMatrix
    from agentkit.governance.principal_capabilities.operations import (
        OperationClassifier,
    )
    from agentkit.governance.principal_capabilities.paths import (
        PathClass,
        PathClassifier,
    )
    from agentkit.governance.principal_capabilities.principals import PrincipalResolver


class EnforcementOutcome(Enum):
    """The five-way result of :meth:`CapabilityEnforcement.evaluate`.

    ``UNKNOWN_PERMISSION`` (AG3-032 ERROR C / FK-55 §55.6.1): the tool itself is
    UNKNOWN to the classifier — it has no concrete operation class the matrix can
    grant. The matrix must NOT be used to ALLOW it; the caller resolves it
    mode-scharf (``story_execution`` ⇒ BLOCK + ``permission_request_opened``;
    ``interactive_admin`` / ``ai_augmented`` ⇒ defer to an external prompt). A
    hard matrix / freeze DENY still PRECEDES this (e.g. an unknown tool aimed at
    ``.git`` is a hard DENY); the unknown-permission signal only resolves the
    otherwise-not-denied case, never softening a DENY.
    """

    ALLOW = auto()
    DENY = auto()
    UNCLASSIFIED_MUTATION = auto()
    UNRESOLVED = auto()
    UNKNOWN_PERMISSION = auto()


#: Reason emitted when a target cannot be cheaply/canonically classified and the
#: caller is in a story-scoped mode (FK-55 §55.10.2 fail-closed BLOCK).
UNCLASSIFIED_TARGET_REASON = "unclassified_target"
_UNCLASSIFIED_RULE_ID = "FK-55-55.10.2"

#: Reason emitted for an UNKNOWN tool that is not otherwise hard-denied (FK-55
#: §55.6.1). The verdict is a fail-closed DENY (the caller resolves it
#: mode-scharf: story_execution ⇒ BLOCK + permission_request; else defer).
UNKNOWN_PERMISSION_REASON = "unknown_permission"
_UNKNOWN_PERMISSION_RULE_ID = "FK-55-55.6.1"

#: Operation classes that *mutate* state. An unclassifiable target combined with
#: one of these is a fail-closed BLOCK in ALL modes (FK-55 §55.10.2 — an
#: unclassified MUTATION target must never be deferred via the §55.6.1
#: unknown-permission rule, which only applies AFTER the capability zone is
#: known). ``EXECUTE`` is deliberately excluded: a plain exec (e.g. ``pytest``)
#: with no discernible file target is non-actionable, not a mutation — Bash file
#: mutations are already normalized to ``WRITE`` by the OperationClassifier.
_MUTATING_OP_CLASSES: frozenset[OperationClass] = frozenset(
    {
        OperationClass.WRITE,
        OperationClass.GIT_MUTATION,
        OperationClass.CURATE,
        OperationClass.ADMIN_TRANSITION,
    }
)


class CapabilityResult:
    """Outcome of one capability evaluation (verdict + three-way classification).

    Args:
        outcome: The three-way :class:`EnforcementOutcome`.
        verdict: The originating :class:`CapabilityVerdict` (for ALLOW/DENY) or
            the synthesized fail-closed verdict for UNRESOLVED.
    """

    __slots__ = ("outcome", "verdict")

    def __init__(self, outcome: EnforcementOutcome, verdict: CapabilityVerdict) -> None:
        self.outcome = outcome
        self.verdict = verdict


class CapabilityEnforcement:
    """Runs FK-55 §55.10.3 steps 1-5 and gates CCAG (step 7).

    Args:
        principal_resolver: Resolves the principal from the event (§55.3a).
        path_classifier: Normalizes targets to path classes.
        op_classifier: Normalizes the tool call to an operation class.
        matrix: The hard capability matrix.
        freeze: The conflict-freeze overlay.
    """

    def __init__(
        self,
        principal_resolver: PrincipalResolver,
        path_classifier: PathClassifier,
        op_classifier: OperationClassifier,
        matrix: CapabilityMatrix,
        freeze: ConflictFreezeOverlay,
    ) -> None:
        self._principal_resolver = principal_resolver
        self._path_classifier = path_classifier
        self._op_classifier = op_classifier
        self._matrix = matrix
        self._freeze = freeze

    def evaluate(
        self,
        event: HookEvent,
        *,
        project_root: Path | None = None,
        story_id: str | None = None,
        story_scope_roots: Sequence[str] | None = None,
    ) -> CapabilityResult:
        """Evaluate the capability decision for ``event`` (steps 1-5).

        Args:
            event: Harness-neutral hook event.
            project_root: Project root for path classification. Defaults to the
                event ``cwd`` (then to ``Path.cwd()``).
            story_id: The active story id (for story-scope path classification).
                ``None`` ⇒ ``normal`` mode.
            story_scope_roots: The FK-55 §55.7.1 story-scope roots (worktree /
                participating-repo roots, registered sandboxes).

        Returns:
            A :class:`CapabilityResult`. A ``DENY`` outcome is hard — the caller
            must NOT run CCAG (see :meth:`should_run_ccag`). An
            ``UNCLASSIFIED_MUTATION`` outcome is a mutating operation that did
            not resolve to an explicit ALLOW (unclassifiable target, including a
            missing / empty / ambiguous target): the caller blocks it in ALL
            modes (FK-55 §55.10.2). An ``UNRESOLVED`` outcome is an
            unclassifiable target on a non-mutating operation: the caller decides
            mode-scharf (story-scoped ⇒ block; otherwise defer to CCAG).
        """
        root = project_root or Path(event.cwd or ".")
        # Step 1: resolve principal (fail-closed, harness-context only).
        principal = self._principal_resolver.resolve(event)
        # Step 2: normalize operation class. An UNKNOWN tool (no positive
        # classifier rule) is flagged here: it must never be force-fit to a
        # matrix-matching ALLOW (AG3-032 ERROR C). ``classify`` still yields the
        # inert EXECUTE, but ``is_known`` is the explicit unknown-permission
        # signal resolved AFTER the hard matrix / freeze DENY checks.
        op_class = self._op_classifier.classify(event.operation, event.operation_args)
        is_known = self._op_classifier.is_known(event.operation, event.operation_args)
        # Step 3: normalize target path classes (may include the unclassified
        # sentinel `None`). A target-less event falls back to the event ``cwd``
        # so the matrix still receives a concrete target; if that too is
        # unclassifiable the mutating-op rule (§55.10.2) fail-closes regardless
        # (AG3-032 ERROR 2 — a mutation with no extractable target still BLOCKs).
        path_classes = self._classify_targets(
            event, root, story_id, story_scope_roots
        )
        # Step 4 + 5: hard matrix then freeze overlay, per target. First DENY
        # wins; an unclassified target is resolved after the loop — as an
        # UNCLASSIFIED_MUTATION (block-all-modes) for ANY mutating op, else an
        # UNRESOLVED (mode-scharf) non-mutating event.
        unresolved = False
        for path_class in path_classes:
            if path_class is None:
                unresolved = True
                continue
            base = self._matrix.is_allowed(principal, op_class, path_class)
            verdict = self._freeze.apply(base, principal, story_id or "", op_class)
            if verdict.decision is CapabilityDecision.DENY:
                return CapabilityResult(EnforcementOutcome.DENY, verdict)
        # An unclassified MUTATION target is a fail-closed BLOCK in ALL modes
        # (FK-55 §55.10.2); it precedes the §55.6.1 unknown-permission rule (an
        # unclassified mutation must never be deferred). An unknown tool is never
        # a mutation (it normalizes to the inert EXECUTE), so this branch resolves
        # only the mutating-op fail-closed case.
        if unresolved and op_class in _MUTATING_OP_CLASSES:
            return self._unresolved_result(op_class)
        # No hard DENY and no unclassified mutation. Per FK-55 §55.6.1 an UNKNOWN
        # tool now resolves to UNKNOWN_PERMISSION (the matrix is NOT consulted for
        # an ALLOW) — the caller resolves it mode-scharf. AG3-032 ERROR C: this is
        # the fix for "a worker's unknown tool in story scope is ALLOWED".
        if not is_known:
            return CapabilityResult(
                EnforcementOutcome.UNKNOWN_PERMISSION,
                CapabilityVerdict.deny(
                    UNKNOWN_PERMISSION_REASON, rule_id=_UNKNOWN_PERMISSION_RULE_ID
                ),
            )
        # A KNOWN op with an unclassifiable NON-mutating target is a genuinely
        # non-actionable event (UNRESOLVED) the caller resolves mode-scharf.
        if unresolved:
            return self._unresolved_result(op_class)
        return CapabilityResult(
            EnforcementOutcome.ALLOW,
            CapabilityVerdict.allow(
                f"{principal.value}:{op_class.value} permitted by matrix",
                rule_id="FK-55-55.10.3",
            ),
        )

    @staticmethod
    def _unresolved_result(op_class: OperationClass) -> CapabilityResult:
        """Resolve an unclassifiable target into the correct fail-closed outcome.

        FK-55 §55.10.2: a *mutating* operation (write / git_mutation / curate /
        admin_transition) that does not resolve to an explicit matrix ALLOW is a
        hard BLOCK in ALL modes (``UNCLASSIFIED_MUTATION``) — REGARDLESS of
        whether a concrete target was extracted. A mutation with a missing /
        empty / ambiguous target is exactly the case §55.10.2 fail-closes ("Kann
        ein Ziel nicht billig und kanonisch aufgeloest werden, ist die
        Entscheidung fail-closed BLOCK"); the §55.6.1 unknown-permission deferral
        must never apply to it (the `has_concrete_target` precondition was the
        AG3-032 ERROR 2 fail-open hole). Only a genuinely NON-mutating, target-less
        op (READ, or EXECUTE with no protected-zone indication) remains a
        non-actionable event the caller resolves mode-scharf (``UNRESOLVED``).
        Both carry the same fail-closed ``unclassified_target`` DENY verdict; the
        outcome differs so the caller knows whether deferral is admissible.
        """
        verdict = CapabilityVerdict.deny(
            UNCLASSIFIED_TARGET_REASON, rule_id=_UNCLASSIFIED_RULE_ID
        )
        if op_class in _MUTATING_OP_CLASSES:
            return CapabilityResult(
                EnforcementOutcome.UNCLASSIFIED_MUTATION, verdict
            )
        return CapabilityResult(EnforcementOutcome.UNRESOLVED, verdict)

    @staticmethod
    def should_run_ccag(result: CapabilityResult) -> bool:
        """Step 7 gate: CCAG runs ONLY on an ALLOW outcome.

        FK-30 §30.2.6 / FK-55 §55.10.3 step 10: CCAG is consulted last and only
        within the already-permitted capability zone. A hard DENY and an
        UNCLASSIFIED_MUTATION are final blocks; an UNRESOLVED outcome and an
        UNKNOWN_PERMISSION outcome are resolved mode-scharf by the caller, not by
        this gate (the caller may still dispatch CCAG on the defer path).
        """
        return result.outcome is EnforcementOutcome.ALLOW

    def _classify_targets(
        self,
        event: HookEvent,
        project_root: Path,
        story_id: str | None,
        story_scope_roots: Sequence[str] | None,
    ) -> list[PathClass | None]:
        """Normalize all affected targets to path classes (§55.10.3 step 5).

        Pulls candidate target paths from the operation args cheaply (FK-55
        §55.10.2 — no semantic shell interpretation), INCLUDING Bash file
        mutation targets (redirects / ``rm``/``mv``/``cp``/``tee`` / git
        mutations) so a ``.git`` / ``_temp/governance`` / content-plane mutation
        is recognised directly even without a structured ``file_path`` arg
        (FK-55 §55.10.2). When no target path is discernible, falls back to the
        event ``cwd`` so the matrix still receives a concrete target. The
        target-less case is no longer treated specially: a mutating op whose
        cwd fallback is also unclassifiable still fail-closes via the mutating-op
        rule in :meth:`_unresolved_result` (AG3-032 ERROR 2).

        Returns:
            The per-target path classes (each may be the ``None`` sentinel).
        """
        concrete = _candidate_paths(event)
        targets = concrete if concrete else [event.cwd or "."]
        return [
            self._path_classifier.classify(
                target, project_root, story_id, story_scope_roots
            )
            for target in targets
        ]


def _candidate_paths(event: HookEvent) -> list[str]:
    """Extract cheap candidate target paths from the event args.

    Inspects the well-known structured keys (``file_path``, ``path``,
    ``notebook_path``) AND — for Bash — the file-mutation targets parsed from the
    command string (FK-55 §55.10.2: Bash file mutations under ``.git/**`` /
    ``_temp/governance/**`` / content-plane must be recognised directly). No
    expensive semantic shell interpretation — cheap token scan only.
    """
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


__all__ = [
    "UNCLASSIFIED_TARGET_REASON",
    "UNKNOWN_PERMISSION_REASON",
    "CapabilityEnforcement",
    "CapabilityResult",
    "EnforcementOutcome",
]
