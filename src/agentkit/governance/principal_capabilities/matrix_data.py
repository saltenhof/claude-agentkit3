"""Canonical FK-55 §55.6 hard-capability-matrix transcription (single source).

This module is the **single source of truth** for the hard capability matrix
(SINGLE SOURCE OF TRUTH guardrail). It transcribes the per-principal capability
rules of FK-55 §55.7 (Worker/QA/Adversarial/Orchestrator), the principal short
matrix of FK-55 §31.2.8, the freeze/least-privilege invariants of
``formal.principal-capabilities.invariants`` and the privileged-service rules of
FK-55 §55.9 into an *explicit and complete* mapping over the full cross product
``Principal × OperationClass × PathClass`` (9 × 6 × 8 = 432 cells).

Every cell is materialized explicitly (no implicit gaps): each principal is
described by the exact set of ``(operation_class, path_class)`` pairs it is
ALLOWED; every other pair for that principal is an explicit ``DENY``. The matrix
loader (:class:`~agentkit.governance.principal_capabilities.matrix.CapabilityMatrix`)
additionally treats any *absent* triple as a fail-closed ``DENY`` — but with the
explicit completion here, the matrix never relies on that fallback for the nine
canonical principals.

FAIL-CLOSED service principals (FK-55 §55.9 / §55.10.7 / §31.2.8): the dangerous
mutations of ``pipeline_deterministic`` / ``human_cli`` / ``admin_service`` on
``git_internal`` / ``governance_plane`` / ``content_plane`` are privileged ONLY
through an OFFICIAL SERVICE PATH (the §55.10.3 step-8 / FK-30 §30.2.6 step-7
service-path validation). That validation is a follow-up story (AG3-032 §2.2 —
step 6 deferred). Until it lands the matrix itself must be restrictive: these
dangerous service-principal cells are DENY here, so deferring the service-path
validator can never let an over-grant slip through (scope reconciliation,
AG3-032 — deferring step 6 is safe only because the matrix is fail-closed for
these cells). Read access to those zones stays ALLOW (service principals must
still inspect them).

No own interpretation: where the concept is silent for a principal/plane (e.g.
``llm_evaluator`` having *no* local filesystem capability per
``principal-capabilities.invariant.llm_evaluator_has_no_local_filesystem_capability``)
the cell is DENY.
"""

from __future__ import annotations

from agentkit.governance.principal_capabilities.matrix import (
    CapabilityVerdict,
    MatrixKey,
)
from agentkit.governance.principal_capabilities.operations import OperationClass as Op
from agentkit.governance.principal_capabilities.paths import PathClass as Pc
from agentkit.governance.principal_capabilities.principals import Principal as Pr

#: Reason string for an explicit default-deny cell (Sonar S1192 — single literal).
_REASON_NOT_GRANTED = "principal lacks this capability on this path class"

#: Rule id for an explicit default-deny cell (FK-55 §55.6 fail-closed).
_RULE_DEFAULT_DENY = "FK-55-55.6-default_deny"


def _grant(
    ops: tuple[Op, ...],
    paths: tuple[Pc, ...],
) -> frozenset[tuple[Op, Pc]]:
    """Cartesian helper: every ``op`` on every ``path`` is granted."""
    return frozenset((op, path) for op in ops for path in paths)


def _build_allow_sets() -> dict[Pr, tuple[frozenset[tuple[Op, Pc]], str]]:
    """Build the per-principal allow-set + rule-id table (single source).

    Each entry is the EXACT allow-set for that principal; all complementary
    cells become explicit DENY in :func:`build_matrix`. Concept anchors are in
    the inline comments. Rule-id and reason literals live here (function body) so
    the module top level stays thin (project LOC linter).

    Returns:
        Mapping of each :class:`Principal` to its ``(allow_set, rule_id)`` pair.
    """
    rule_worker = "FK-55-55.7.2"
    rule_qa = "FK-55-55.7.3"
    rule_adversarial = "FK-55-55.7.4"
    rule_orchestrator = "FK-55-55.7.5"
    rule_llm_eval = "FK-55-inv-llm_evaluator_no_local_fs"
    rule_pipeline = "FK-55-55.9"
    rule_human_cli = "FK-55-31.2.8"
    rule_admin = "FK-55-55.9-admin_service"
    rule_interactive = "FK-55-55.3-interactive_agent"

    # worker (FK-55 §55.7.2 + §31.2.8): read/write/execute in story scope;
    # read-only on control- and content-plane; nothing on git/governance/sandbox/
    # out-of-scope/repo-admin; no curate/admin.
    worker_allow = _grant((Op.READ, Op.WRITE, Op.EXECUTE), (Pc.CODEBASE_STORY_SCOPE,)) | _grant(
        (Op.READ,), (Pc.CONTENT_PLANE, Pc.CONTROL_PLANE)
    )

    # qa_reader (FK-55 §55.7.3 + §31.2.8): read + execute in story scope;
    # read-only on the QA contexts it needs (content/control plane); no
    # productive write; no sandbox; no git/governance/admin.
    qa_reader_allow = _grant((Op.READ, Op.EXECUTE), (Pc.CODEBASE_STORY_SCOPE,)) | _grant(
        (Op.READ,), (Pc.CONTENT_PLANE, Pc.CONTROL_PLANE)
    )

    # adversarial_writer (FK-55 §55.7.4 + §31.2.8): read story scope; read/write/
    # execute ONLY in the qa_sandbox; no direct promotion into productive paths.
    adversarial_allow = _grant((Op.READ,), (Pc.CODEBASE_STORY_SCOPE,)) | _grant((Op.READ, Op.WRITE, Op.EXECUTE), (Pc.QA_SANDBOX,))

    # orchestrator (FK-55 §55.7.5 + §31.2.8): read control-plane signals ONLY.
    # No content read/write, no story-scope write, no git/governance write, no
    # curate, no admin_transition (without a privileged path — out of scope).
    orchestrator_allow = _grant((Op.READ,), (Pc.CONTROL_PLANE,))

    # llm_evaluator (invariant llm_evaluator_has_no_local_filesystem_capability):
    # no local filesystem or shell capability at all → empty allow set.
    llm_evaluator_allow: frozenset[tuple[Op, Pc]] = frozenset()

    # interactive_agent (FK-55 §55.3): free human-guided work OUTSIDE a run. No
    # active story scope; restricted to non-mutating inspection of the productive
    # codebase. No mutation, no protected planes, no git, no admin (fail-closed —
    # the interactive principal must not be a backdoor into story-scoped mutation).
    interactive_allow = _grant(
        (Op.READ, Op.EXECUTE),
        (Pc.CODEBASE_OUT_OF_SCOPE, Pc.CODEBASE_STORY_SCOPE, Pc.CONTROL_PLANE),
    )

    # pipeline_deterministic (FK-55 §55.7 "deterministische AgentKit-Skripte mit
    # offizieller Mutationshoheit" + §31.2.8): official mutation authority over
    # the planes it owns — BUT the dangerous git_internal mutations are only
    # privileged via an official service path (§31.2.8 ".git: nur ueber
    # deklarierte AgentKit-Pfade"; §55.10.7). The service-path validator is
    # deferred (AG3-032 §2.2), so git_internal MUTATIONS are DENY here
    # (fail-closed); git_internal READ stays allowed.
    pipeline_allow = (
        _grant(
            _ALL_OPS,
            (
                Pc.CODEBASE_STORY_SCOPE,
                Pc.QA_SANDBOX,
                Pc.CONTROL_PLANE,
                Pc.CONTENT_PLANE,
                Pc.GOVERNANCE_PLANE,
                Pc.REPO_ADMIN_SURFACE,
            ),
        )
        | _grant((Op.READ, Op.EXECUTE), (Pc.CODEBASE_OUT_OF_SCOPE,))
        | _grant((Op.READ,), (Pc.GIT_INTERNAL,))
    )

    # human_cli (FK-55 §31.2.8 / §55.9): acts via OFFICIAL COMMANDS, not via free
    # direct mutation. §31.2.8 ".git: nie frei, sondern nur ueber AgentKit-
    # Kommandos"; governance/content/git mutations therefore require the official
    # service path (deferred — AG3-032 §2.2). Until then the matrix DENIES those
    # direct mutations (fail-closed) while keeping: admin_transition on the
    # repo_admin_surface (that IS the official-command surface), full authority
    # over story-scope, qa_sandbox and control_plane, and read everywhere.
    human_cli_allow = (
        _grant(
            _ALL_OPS,
            (
                Pc.CODEBASE_STORY_SCOPE,
                Pc.QA_SANDBOX,
                Pc.CONTROL_PLANE,
                Pc.REPO_ADMIN_SURFACE,
            ),
        )
        | _grant((Op.READ, Op.EXECUTE), (Pc.CODEBASE_OUT_OF_SCOPE,))
        | _grant((Op.READ,), (Pc.CONTENT_PLANE, Pc.GOVERNANCE_PLANE, Pc.GIT_INTERNAL))
    )

    # admin_service (FK-55 §55.3 + §55.9): official administrative service path
    # (StoryResetService, StorySplitService, resolve-conflict). Authority over
    # the admin/governance/control surface and the story scope it must repair;
    # read/execute elsewhere. NOT a free productive worker on out-of-scope code.
    # Its git_internal MUTATION is only privileged via an official service path
    # (§55.10.7) which is deferred — so git_internal mutation is DENY here
    # (fail-closed); git_internal READ stays allowed.
    admin_service_allow = (
        _grant(
            _ALL_OPS,
            (
                Pc.REPO_ADMIN_SURFACE,
                Pc.GOVERNANCE_PLANE,
                Pc.CONTROL_PLANE,
                Pc.CODEBASE_STORY_SCOPE,
            ),
        )
        | _grant((Op.READ,), (Pc.CONTENT_PLANE,))
        | _grant((Op.READ, Op.EXECUTE), (Pc.CODEBASE_OUT_OF_SCOPE,))
        | _grant((Op.READ,), (Pc.GIT_INTERNAL,))
    )

    return {
        Pr.WORKER: (worker_allow, rule_worker),
        Pr.QA_READER: (qa_reader_allow, rule_qa),
        Pr.ADVERSARIAL_WRITER: (adversarial_allow, rule_adversarial),
        Pr.ORCHESTRATOR: (orchestrator_allow, rule_orchestrator),
        Pr.LLM_EVALUATOR: (llm_evaluator_allow, rule_llm_eval),
        Pr.INTERACTIVE_AGENT: (interactive_allow, rule_interactive),
        Pr.PIPELINE_DETERMINISTIC: (pipeline_allow, rule_pipeline),
        Pr.HUMAN_CLI: (human_cli_allow, rule_human_cli),
        Pr.ADMIN_SERVICE: (admin_service_allow, rule_admin),
    }


def build_matrix() -> dict[MatrixKey, CapabilityVerdict]:
    """Materialize the complete FK-55 §55.6 hard matrix.

    Returns:
        A mapping for every ``(Principal, OperationClass, PathClass)`` triple
        (432 entries) to an explicit ALLOW/DENY :class:`CapabilityVerdict`. The
        ALLOW cells are exactly the per-principal allow-sets (see
        :func:`_build_allow_sets`); every other cell is an explicit DENY
        (FAIL-CLOSED, ZERO DEBT — no implicit gaps).
    """
    allow_sets = _build_allow_sets()
    table: dict[MatrixKey, CapabilityVerdict] = {}
    for principal in Pr:
        allow_set, rule_id = allow_sets[principal]
        for op in _ALL_OPS:
            for path in _ALL_PATHS:
                key: MatrixKey = (principal, op, path)
                if (op, path) in allow_set:
                    table[key] = CapabilityVerdict.allow(
                        f"{principal.value} may {op.value} on {path.value}",
                        rule_id=rule_id,
                    )
                else:
                    table[key] = CapabilityVerdict.deny(
                        _REASON_NOT_GRANTED,
                        rule_id=_RULE_DEFAULT_DENY,
                    )
    return table


#: All operation/path enum members (full cross product driver).
_ALL_OPS: tuple[Op, ...] = tuple(Op)
_ALL_PATHS: tuple[Pc, ...] = tuple(Pc)

#: Number of cells the complete matrix must contain (9 × 6 × 8).
EXPECTED_MATRIX_CELLS = len(Pr) * len(_ALL_OPS) * len(_ALL_PATHS)


__all__ = [
    "EXPECTED_MATRIX_CELLS",
    "build_matrix",
]
