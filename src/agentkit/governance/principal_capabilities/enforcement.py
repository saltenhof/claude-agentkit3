"""Capability enforcement pipeline (FK-55 §55.10.3 steps 1-5 + step 7 CCAG gate).

:class:`CapabilityEnforcement` runs the normed FK-55 §55.10.3 evaluation order:

1. resolve the :class:`Principal` (fail-closed, harness-context only — §55.3a)
2. normalize the tool call to an :class:`OperationClass`
3. normalize the target(s) to :class:`PathClass` (or the unclassified sentinel)
4. consult the hard capability matrix
5. apply the conflict-freeze overlay

The evaluation engages for EVERY hook event. Absence of an active story binding
is ``normal`` mode, NOT a skip (AG3-032 ERROR 2 — never fail-open). Five-way
:class:`EnforcementOutcome`:

- ``DENY``       — hard matrix / freeze block; CCAG cannot soften it.
- ``ALLOW``      — the matrix (post-freeze) permits the operation.
- ``UNCLASSIFIED_MUTATION`` — mutating operation whose target could not be
                   classified (FK-55 §55.10.2): fail-closed BLOCK in ALL modes.
                   The §55.6.1 unknown-permission rule must never override this.
- ``UNRESOLVED`` — non-mutating event with unclassifiable target (pure read /
                   plain exec). Resolved mode-scharf (§55.6.1): in
                   ``story_execution`` a fail-closed BLOCK; elsewhere may defer.
- ``UNKNOWN_PERMISSION`` — TOOL unknown to the classifier; matrix NOT consulted
                   for ALLOW (AG3-032 ERROR C). A hard DENY still precedes this.
                   Resolved mode-scharf: ``story_execution`` ⇒ BLOCK; else defer.

Step 6 (official service paths) is rudimentary (AG3-032 §2.1.4 — out of scope).
Step 7 (CCAG, FK-30 §30.2.6) runs ONLY on ``ALLOW`` — see :meth:`should_run_ccag`.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    is_subagent_spawn,
)
from agentkit.governance.principal_capabilities.principals import Principal
from agentkit.governance.principal_capabilities.service_paths import (
    is_official_service_path,
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
    ALLOW_VIA_OFFICIAL_SERVICE_PATH = auto()
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

#: Reason emitted for the ``Agent`` sub-agent spawn (FK-31 §31.7; FK-91 §91.4
#: hook catalog). A sub-agent spawn is a control-plane orchestration operation
#: with no path target the FK-55 §55.6 matrix can adjudicate; the path matrix
#: would wrongly hard-DENY it (e.g. an ``orchestrator`` has no EXECUTE on the cwd
#: path-class), killing the dedicated ``prompt_integrity`` guard. The
#: path-matrix-bypass rationale is FK-31 §31.7 (the spawn's authority IS the
#: dedicated guard) + FK-55 §55.6 (no meaningful path-class). FK-91 §91.4 only
#: catalogues ``Agent`` under the ``ccag_gatekeeper`` matcher
#: (``Bash|Write|Edit|Read|Grep|Glob|Agent``) — it does NOT itself grant a matrix
#: exemption. The capability layer therefore passes the spawn through with an
#: ALLOW hull and lets ``prompt_integrity`` (and CCAG) be the real authority.
SUBAGENT_SPAWN_REASON = "subagent_spawn_routed_to_prompt_integrity"
_SUBAGENT_SPAWN_RULE_ID = "FK-31-31.7"

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


@dataclass(frozen=True)
class CapabilityHull:
    """Pre-computed capability hull required by CCAG (FK-42 §42.2.4).

    FK-42 §42.2.4: ``evaluate_ccag()`` may run ONLY after the capability hull has
    been computed (principal / path / operation classes + the hard matrix and
    freeze verdicts). CCAG consults this hull and must NEVER be invoked without
    it — a missing hull is a fail-closed block, not a global allow.

    Attributes:
        principal_type: The resolved technical principal (FK-55 §55.3a).
        operation_class: The normalized operation class.
        path_classes: The per-target path classes (the unclassified sentinel
            ``None`` is mapped to the literal ``"unclassified"`` so the hull is a
            plain value object CCAG can carry without the path-class enum).
        hard_capability_verdict: ``"allow"`` / ``"deny"`` — the hard matrix
            decision (post any per-target DENY short-circuit).
        freeze_verdict: ``"allow"`` / ``"deny"`` — the conflict-freeze overlay
            decision applied on top of the matrix base.
    """

    principal_type: str
    operation_class: str
    path_classes: tuple[str, ...]
    hard_capability_verdict: str
    freeze_verdict: str


class CapabilityResult:
    """Outcome of one capability evaluation (verdict + three-way classification).

    Args:
        outcome: The three-way :class:`EnforcementOutcome`.
        verdict: The originating :class:`CapabilityVerdict` (for ALLOW/DENY) or
            the synthesized fail-closed verdict for UNRESOLVED.
        hull: The pre-computed :class:`CapabilityHull` (FK-42 §42.2.4) the caller
            threads into CCAG. ``None`` only for results that never reach CCAG
            (an early fault); the runner passes the hull ONLY on an ALLOW outcome.
    """

    __slots__ = ("hull", "outcome", "verdict")

    def __init__(
        self,
        outcome: EnforcementOutcome,
        verdict: CapabilityVerdict,
        hull: CapabilityHull | None = None,
    ) -> None:
        self.outcome = outcome
        self.verdict = verdict
        self.hull = hull


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
        # FK-31 §31.7: the ``Agent`` sub-agent spawn is a KNOWN control-plane
        # operation with no path target the §55.6 matrix can adjudicate. The path
        # matrix would wrongly hard-DENY it (an orchestrator has no EXECUTE on the
        # cwd path-class), which would intercept the spawn BEFORE the dedicated
        # ``prompt_integrity`` guard — leaving that guard dead. The
        # path-matrix-bypass rationale is FK-31 §31.7 (the dedicated guard is the
        # spawn's authority) + FK-55 §55.6 (no meaningful path-class); FK-91 §91.4
        # only catalogues ``Agent`` under the ``ccag_gatekeeper`` matcher and does
        # NOT itself grant a matrix exemption. The capability layer passes it
        # through with an ALLOW matrix hull (the spawn schema / template is governed
        # by ``prompt_integrity_guard``, the spawn's real fail-closed authority).
        # The hull's ``freeze_verdict`` carries the REAL conflict-freeze state
        # (FK-42 §42.2.4 — the hull must not fabricate ``allow``; FK-55 §55.8.2 —
        # the freeze exists precisely to stop an orchestrator from spawning fresh
        # sub-agents to circumvent guard barriers after a HARD STOP, so CCAG/the
        # adjudication downstream must see the true state). This is NOT a weakening
        # of the fail-closed for genuinely-unknown tools — it is the
        # concept-modelled routing of one specific, named operation.
        if is_subagent_spawn(event.operation, event.operation_args):
            return self._subagent_spawn_result(principal, story_id or "")
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
                if _service_path_override_allowed(
                    event, principal, op_class, path_class
                ):
                    return CapabilityResult(
                        EnforcementOutcome.ALLOW_VIA_OFFICIAL_SERVICE_PATH,
                        CapabilityVerdict.allow(
                            "attested official service path",
                            rule_id="FK-55-55.10.3-step-8",
                        ),
                    )
                return CapabilityResult(EnforcementOutcome.DENY, verdict)
        # An unclassified MUTATION target is a fail-closed BLOCK in ALL modes
        # (FK-55 §55.10.2); it precedes the §55.6.1 unknown-permission rule (an
        # unclassified mutation must never be deferred). An unknown tool is never
        # a mutation (it normalizes to the inert EXECUTE), so this branch resolves
        # only the mutating-op fail-closed case.
        if unresolved and op_class in _MUTATING_OP_CLASSES:
            return self._unresolved_result(op_class)
        # FK-42 §42.2.4: the capability hull is computed for EVERY outcome that can
        # reach CCAG (ALLOW + the mode-scharf defer outcomes UNKNOWN_PERMISSION /
        # UNRESOLVED). No hard DENY fired here, so the hull's matrix/freeze
        # verdicts are ``allow`` (a DENY / UNCLASSIFIED_MUTATION already returned
        # above and never reaches CCAG). An unclassified target is recorded as the
        # literal ``"unclassified"`` path class.
        hull = CapabilityHull(
            principal_type=principal.value,
            operation_class=op_class.value,
            path_classes=tuple(
                pc.value if pc is not None else "unclassified" for pc in path_classes
            ),
            hard_capability_verdict="allow",
            freeze_verdict="allow",
        )
        # Per FK-55 §55.6.1 an UNKNOWN tool resolves to UNKNOWN_PERMISSION (the
        # matrix is NOT consulted for an ALLOW) — the caller resolves it
        # mode-scharf and may defer to CCAG.
        if not is_known:
            return CapabilityResult(
                EnforcementOutcome.UNKNOWN_PERMISSION,
                CapabilityVerdict.deny(
                    UNKNOWN_PERMISSION_REASON, rule_id=_UNKNOWN_PERMISSION_RULE_ID
                ),
                hull=hull,
            )
        # A KNOWN op with an unclassifiable NON-mutating target is a genuinely
        # non-actionable event (UNRESOLVED) the caller resolves mode-scharf (it may
        # defer to CCAG, so it carries the hull too).
        if unresolved:
            return CapabilityResult(
                EnforcementOutcome.UNRESOLVED,
                CapabilityVerdict.deny(
                    UNCLASSIFIED_TARGET_REASON, rule_id=_UNCLASSIFIED_RULE_ID
                ),
                hull=hull,
            )
        return CapabilityResult(
            EnforcementOutcome.ALLOW,
            CapabilityVerdict.allow(
                f"{principal.value}:{op_class.value} permitted by matrix",
                rule_id="FK-55-55.10.3",
            ),
            hull=hull,
        )

    def _subagent_spawn_result(
        self, principal: Principal, story_id: str
    ) -> CapabilityResult:
        """Route an ``Agent`` sub-agent spawn past the path matrix (FK-31 §31.7).

        A sub-agent spawn is a control-plane orchestration operation with no path
        target. The hard path matrix (FK-55 §55.6) cannot meaningfully adjudicate
        it and would wrongly DENY it for principals without an EXECUTE grant on the
        cwd path-class (orchestrator / llm_evaluator) — which would kill the
        dedicated ``prompt_integrity`` guard. FK-91 §91.4 only catalogues ``Agent``
        under the ``ccag_gatekeeper`` matcher; the path-matrix-bypass rationale is
        FK-31 §31.7 + FK-55 §55.6. We therefore return an ALLOW *matrix* hull so the
        dispatch proceeds to the dedicated ``prompt_integrity`` guard + CCAG, the
        spawn's real fail-closed authority.

        FK-42 §42.2.4 / FK-55 §55.8.2 (AG3-086 FIX B): the hull's
        ``freeze_verdict`` MUST report the REAL conflict-freeze state — never a
        fabricated ``"allow"``. The freeze exists precisely to stop an orchestrator
        from spawning fresh sub-agents to circumvent guard barriers after a HARD
        STOP (§55.8.2). The capability **overlay** scope per FK-55 §55.10.6 is
        ``write``/``git_mutation``/``curate``/``admin_transition`` for
        ``orchestrator`` — a control-plane spawn (EXECUTE) is OUT of that overlay
        scope, so this layer does NOT itself hard-DENY the spawn on freeze. But it
        surfaces the TRUE ``is_frozen`` state in the hull so CCAG (and the §55.8.2
        adjudication downstream) decides on a real freeze signal rather than an
        asserted ``"allow"`` for a possibly-frozen story.

        Args:
            principal: The resolved principal (recorded on the hull for the audit).
            story_id: The active story id (``""`` ⇒ ``normal`` mode, never frozen);
                used to consult the real conflict-freeze overlay state.

        Returns:
            An ``ALLOW`` :class:`CapabilityResult` carrying a hull whose matrix
            verdict is ``allow`` and whose ``freeze_verdict`` reflects the real
            ``is_frozen`` state of ``story_id``.
        """
        # The freeze overlay scope (§55.10.6) does not cover the control-plane
        # spawn op-class, so this is a pure STATE read, not an overlay application:
        # report the true freeze state without forcing a spawn-DENY here.
        frozen = bool(story_id) and self._freeze.is_frozen(story_id)
        hull = CapabilityHull(
            principal_type=principal.value,
            operation_class=OperationClass.EXECUTE.value,
            path_classes=("control_plane_spawn",),
            hard_capability_verdict="allow",
            freeze_verdict="deny" if frozen else "allow",
        )
        return CapabilityResult(
            EnforcementOutcome.ALLOW,
            CapabilityVerdict.allow(
                SUBAGENT_SPAWN_REASON, rule_id=_SUBAGENT_SPAWN_RULE_ID
            ),
            hull=hull,
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
        return result.outcome in (
            EnforcementOutcome.ALLOW,
            EnforcementOutcome.ALLOW_VIA_OFFICIAL_SERVICE_PATH,
        )

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


def _service_path_override_allowed(
    event: HookEvent,
    principal: Principal,
    op_class: OperationClass,
    path_class: PathClass,
) -> bool:
    """Whether an explicit service-path override may turn a service DENY to allow."""
    from agentkit.governance.principal_capabilities.paths import PathClass as Pc

    if principal not in {
        Principal.PIPELINE_DETERMINISTIC,
        Principal.ADMIN_SERVICE,
        Principal.HUMAN_CLI,
    }:
        return False
    if op_class not in _MUTATING_OP_CLASSES:
        return False
    if path_class not in {
        Pc.GIT_INTERNAL,
        Pc.GOVERNANCE_PLANE,
        Pc.CONTENT_PLANE,
    }:
        return False
    return is_official_service_path(event, principal)


__all__ = [
    "SUBAGENT_SPAWN_REASON",
    "UNCLASSIFIED_TARGET_REASON",
    "UNKNOWN_PERMISSION_REASON",
    "CapabilityEnforcement",
    "CapabilityResult",
    "EnforcementOutcome",
]
