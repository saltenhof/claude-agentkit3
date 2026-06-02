"""Contract: pin the FK-55 §55.6 hard-matrix cells (AK5).

These assertions pin the central matrix rows transcribed from FK-55 §55.7 /
§31.2.8 / the principal-capability invariants. A drift in matrix_data.py must
break this contract test (the matrix is normative, not free to reinterpret).
"""

from __future__ import annotations

import pytest

from agentkit.governance.principal_capabilities import (
    CapabilityDecision,
    CapabilityMatrix,
    OperationClass,
    PathClass,
    Principal,
)
from agentkit.governance.principal_capabilities.matrix_data import (
    EXPECTED_MATRIX_CELLS,
    build_matrix,
)

_MATRIX = CapabilityMatrix()

_A = CapabilityDecision.ALLOW
_D = CapabilityDecision.DENY

# (principal, operation, path, expected_decision) — central FK-55 §55.6 cells.
_PINNED: tuple[tuple[Principal, OperationClass, PathClass, CapabilityDecision], ...] = (
    # worker (FK-55 §55.7.2)
    (Principal.WORKER, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE, _A),
    (Principal.WORKER, OperationClass.READ, PathClass.CONTENT_PLANE, _A),
    (Principal.WORKER, OperationClass.WRITE, PathClass.CONTENT_PLANE, _D),
    (Principal.WORKER, OperationClass.WRITE, PathClass.CODEBASE_OUT_OF_SCOPE, _D),
    (Principal.WORKER, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL, _D),
    (Principal.WORKER, OperationClass.WRITE, PathClass.GOVERNANCE_PLANE, _D),
    # qa_reader (FK-55 §55.7.3)
    (Principal.QA_READER, OperationClass.READ, PathClass.CODEBASE_STORY_SCOPE, _A),
    (Principal.QA_READER, OperationClass.EXECUTE, PathClass.CODEBASE_STORY_SCOPE, _A),
    (Principal.QA_READER, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE, _D),
    (Principal.QA_READER, OperationClass.WRITE, PathClass.QA_SANDBOX, _D),
    # adversarial_writer (FK-55 §55.7.4)
    (Principal.ADVERSARIAL_WRITER, OperationClass.READ, PathClass.CODEBASE_STORY_SCOPE, _A),
    (Principal.ADVERSARIAL_WRITER, OperationClass.WRITE, PathClass.QA_SANDBOX, _A),
    (Principal.ADVERSARIAL_WRITER, OperationClass.EXECUTE, PathClass.QA_SANDBOX, _A),
    (Principal.ADVERSARIAL_WRITER, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE, _D),
    # orchestrator (FK-55 §55.7.5 / §31.2.8)
    (Principal.ORCHESTRATOR, OperationClass.READ, PathClass.CONTROL_PLANE, _A),
    (Principal.ORCHESTRATOR, OperationClass.READ, PathClass.CONTENT_PLANE, _D),
    (Principal.ORCHESTRATOR, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE, _D),
    (Principal.ORCHESTRATOR, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL, _D),
    (Principal.ORCHESTRATOR, OperationClass.CURATE, PathClass.REPO_ADMIN_SURFACE, _D),
    # llm_evaluator (invariant: no local filesystem capability)
    (Principal.LLM_EVALUATOR, OperationClass.READ, PathClass.CODEBASE_STORY_SCOPE, _D),
    (Principal.LLM_EVALUATOR, OperationClass.WRITE, PathClass.QA_SANDBOX, _D),
    # pipeline_deterministic (FK-55 §55.9 / §31.2.8 official mutation authority).
    # ERROR 7 (FK-55 §55.9 / §55.10.7 / §31.2.8): the dangerous git_internal
    # MUTATION is privileged only via an official service path (deferred — step
    # 6, AG3-032 §2.2). Until then the matrix is FAIL-CLOSED: git_internal
    # mutation is DENY (read stays allowed); governance-plane (an owned plane)
    # stays allowed.
    (Principal.PIPELINE_DETERMINISTIC, OperationClass.WRITE, PathClass.GOVERNANCE_PLANE, _A),
    (Principal.PIPELINE_DETERMINISTIC, OperationClass.READ, PathClass.GIT_INTERNAL, _A),
    (Principal.PIPELINE_DETERMINISTIC, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL, _D),
    (Principal.PIPELINE_DETERMINISTIC, OperationClass.WRITE, PathClass.GIT_INTERNAL, _D),
    # human_cli (FK-55 §31.2.8 via official commands). ERROR 7: ".git nie frei,
    # nur ueber AgentKit-Kommandos" → direct git_internal mutation is DENY until
    # the official service path lands; admin_transition on the repo_admin_surface
    # (the official-command surface) stays allowed; read everywhere stays allowed.
    (Principal.HUMAN_CLI, OperationClass.ADMIN_TRANSITION, PathClass.REPO_ADMIN_SURFACE, _A),
    (Principal.HUMAN_CLI, OperationClass.READ, PathClass.GIT_INTERNAL, _A),
    (Principal.HUMAN_CLI, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL, _D),
    (Principal.HUMAN_CLI, OperationClass.WRITE, PathClass.GOVERNANCE_PLANE, _D),
    (Principal.HUMAN_CLI, OperationClass.WRITE, PathClass.CONTENT_PLANE, _D),
    # admin_service (FK-55 §55.9 official service path). ERROR 7: git_internal
    # mutation requires the official service path (deferred) → DENY; read allowed.
    (Principal.ADMIN_SERVICE, OperationClass.ADMIN_TRANSITION, PathClass.REPO_ADMIN_SURFACE, _A),
    (Principal.ADMIN_SERVICE, OperationClass.READ, PathClass.GIT_INTERNAL, _A),
    (Principal.ADMIN_SERVICE, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL, _D),
    (Principal.ADMIN_SERVICE, OperationClass.WRITE, PathClass.CODEBASE_OUT_OF_SCOPE, _D),
)


@pytest.mark.parametrize(("principal", "op", "path", "expected"), _PINNED)
def test_pinned_matrix_cells(
    principal: Principal,
    op: OperationClass,
    path: PathClass,
    expected: CapabilityDecision,
) -> None:
    assert _MATRIX.is_allowed(principal, op, path).decision is expected


def test_matrix_is_complete() -> None:
    # AK5: every triple present; 432 cells (9 principals × 6 ops × 8 paths —
    # PathClass is exactly 8, no synthetic UNCLASSIFIED column, ERROR 1).
    table = build_matrix()
    assert len(table) == EXPECTED_MATRIX_CELLS == 432
    assert set(table) == {
        (p, o, c) for p in Principal for o in OperationClass for c in PathClass
    }
