"""Unit tests for CapabilityMatrix completeness + fail-closed default (FK-55 §55.6, AK5/AK9)."""

from __future__ import annotations

from agentkit.backend.governance.principal_capabilities import (
    CapabilityDecision,
    CapabilityMatrix,
    OperationClass,
    PathClass,
    Principal,
)
from agentkit.backend.governance.principal_capabilities.matrix import TRIPLE_NOT_IN_MATRIX
from agentkit.backend.governance.principal_capabilities.matrix_data import (
    EXPECTED_MATRIX_CELLS,
    build_matrix,
)

_MATRIX = CapabilityMatrix()


def test_matrix_is_complete_for_every_triple() -> None:
    # AK5: every (Principal, OperationClass, PathClass) triple has an explicit
    # entry (no implicit gaps). 9 x 6 x 8 = 432 cells (PathClass is exactly 8 —
    # no synthetic UNCLASSIFIED column, ERROR 1).
    table = build_matrix()
    assert len(table) == EXPECTED_MATRIX_CELLS == 9 * 6 * 8
    for principal in Principal:
        for op in OperationClass:
            for path in PathClass:
                assert (principal, op, path) in table


def test_missing_triple_defaults_to_deny() -> None:
    # AK9: a triple absent from a (sparse) matrix fails closed to DENY.
    sparse = CapabilityMatrix(table={})
    verdict = sparse.is_allowed(
        Principal.WORKER, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE
    )
    assert verdict.decision is CapabilityDecision.DENY
    assert verdict.reason == TRIPLE_NOT_IN_MATRIX


def test_worker_may_write_story_scope() -> None:
    # FK-55 §55.7.2 + §31.2.8.
    v = _MATRIX.is_allowed(
        Principal.WORKER, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE
    )
    assert v.decision is CapabilityDecision.ALLOW


def test_worker_may_not_write_qa_artifact_content_plane() -> None:
    # FK-55 §55.7.2: worker has no write on content-plane (QA artifacts).
    v = _MATRIX.is_allowed(
        Principal.WORKER, OperationClass.WRITE, PathClass.CONTENT_PLANE
    )
    assert v.decision is CapabilityDecision.DENY


def test_orchestrator_read_control_plane_allow_but_no_write() -> None:
    # FK-55 §55.7.5 + §31.2.8.
    assert _MATRIX.is_allowed(
        Principal.ORCHESTRATOR, OperationClass.READ, PathClass.CONTROL_PLANE
    ).decision is CapabilityDecision.ALLOW
    assert _MATRIX.is_allowed(
        Principal.ORCHESTRATOR, OperationClass.WRITE, PathClass.CODEBASE_STORY_SCOPE
    ).decision is CapabilityDecision.DENY
    assert _MATRIX.is_allowed(
        Principal.ORCHESTRATOR, OperationClass.READ, PathClass.CONTENT_PLANE
    ).decision is CapabilityDecision.DENY


def test_adversarial_writer_sandbox_only() -> None:
    # FK-55 §55.7.4 + invariant adversarial_writer_is_sandbox_only.
    assert _MATRIX.is_allowed(
        Principal.ADVERSARIAL_WRITER, OperationClass.WRITE, PathClass.QA_SANDBOX
    ).decision is CapabilityDecision.ALLOW
    assert _MATRIX.is_allowed(
        Principal.ADVERSARIAL_WRITER,
        OperationClass.WRITE,
        PathClass.CODEBASE_STORY_SCOPE,
    ).decision is CapabilityDecision.DENY


def test_llm_evaluator_has_no_local_filesystem_capability() -> None:
    # invariant llm_evaluator_has_no_local_filesystem_capability: empty allow set.
    for op in OperationClass:
        for path in PathClass:
            assert _MATRIX.is_allowed(Principal.LLM_EVALUATOR, op, path).decision is (
                CapabilityDecision.DENY
            )


def test_git_internal_never_writable_for_story_principals() -> None:
    # invariant git_internal_never_mutated_via_free_bash.
    for principal in (
        Principal.WORKER,
        Principal.ORCHESTRATOR,
        Principal.QA_READER,
        Principal.ADVERSARIAL_WRITER,
    ):
        assert _MATRIX.is_allowed(
            principal, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL
        ).decision is CapabilityDecision.DENY


def test_service_principals_git_internal_mutation_fail_closed() -> None:
    # ERROR 7 / FK-55 §55.9 / §55.10.7 / §31.2.8: the dangerous service-principal
    # git_internal MUTATION requires an official service path (step 6, deferred).
    # Until it lands the matrix is FAIL-CLOSED: git_internal mutation is DENY for
    # ALL service principals; read stays allowed.
    for principal in (
        Principal.PIPELINE_DETERMINISTIC,
        Principal.HUMAN_CLI,
        Principal.ADMIN_SERVICE,
    ):
        assert _MATRIX.is_allowed(
            principal, OperationClass.GIT_MUTATION, PathClass.GIT_INTERNAL
        ).decision is CapabilityDecision.DENY
        assert _MATRIX.is_allowed(
            principal, OperationClass.WRITE, PathClass.GIT_INTERNAL
        ).decision is CapabilityDecision.DENY
        assert _MATRIX.is_allowed(
            principal, OperationClass.READ, PathClass.GIT_INTERNAL
        ).decision is CapabilityDecision.ALLOW


def test_human_cli_no_free_governance_or_content_mutation() -> None:
    # ERROR 7: human_cli acts via official commands; direct governance/content
    # mutation is DENY until the official service path lands.
    assert _MATRIX.is_allowed(
        Principal.HUMAN_CLI, OperationClass.WRITE, PathClass.GOVERNANCE_PLANE
    ).decision is CapabilityDecision.DENY
    assert _MATRIX.is_allowed(
        Principal.HUMAN_CLI, OperationClass.WRITE, PathClass.CONTENT_PLANE
    ).decision is CapabilityDecision.DENY
    # The official-command surface (repo_admin_surface) stays allowed.
    assert _MATRIX.is_allowed(
        Principal.HUMAN_CLI, OperationClass.ADMIN_TRANSITION, PathClass.REPO_ADMIN_SURFACE
    ).decision is CapabilityDecision.ALLOW


def test_takeover_reconcile_clear_matrix_cells_are_privileged() -> None:
    for principal in (Principal.HUMAN_CLI, Principal.ADMIN_SERVICE):
        assert (
            _MATRIX.is_allowed(
                principal,
                OperationClass.ADMIN_TRANSITION,
                PathClass.REPO_ADMIN_SURFACE,
            ).decision
            is CapabilityDecision.ALLOW
        )
    for principal in (
        Principal.INTERACTIVE_AGENT,
        Principal.ORCHESTRATOR,
        Principal.WORKER,
        Principal.QA_READER,
        Principal.ADVERSARIAL_WRITER,
        Principal.LLM_EVALUATOR,
    ):
        assert (
            _MATRIX.is_allowed(
                principal,
                OperationClass.ADMIN_TRANSITION,
                PathClass.REPO_ADMIN_SURFACE,
            ).decision
            is CapabilityDecision.DENY
        )
