"""Unit tests for the four FK-37 §37.1.3 named fail-closed checks (AC12)."""

from __future__ import annotations

from agentkit.backend.integration_stabilization.fk37_checks import (
    FK37CheckName,
    check_fk37_binding_integrity,
    check_fk37_declared_surfaces_only,
    check_fk37_integration_target_matrix_passed,
    check_fk37_manifest_approval_required,
    check_fk37_stability_gate,
    check_fk37_stabilization_budget_not_exhausted,
)
from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudget,
    StabilizationBudgetCaps,
)


def _caps(**kwargs: int) -> StabilizationBudgetCaps:
    defaults = dict(
        max_loops=5, max_new_surfaces=3,
        max_contract_changes=2, max_regressions_per_cycle=2,
    )
    defaults.update(kwargs)
    return StabilizationBudgetCaps(**defaults)  # type: ignore[arg-type]


def _manifest(
    target_seams: tuple[str, ...] = ("src/api/",),
    integration_targets: tuple[str, ...] = ("e2e_login",),
) -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id="PROJ-42",
        implementation_contract="integration_stabilization",
        target_seams=target_seams,
        allowed_repos_paths=("worktrees/main/",),
        integration_targets=integration_targets,
        allowed_contract_changes=(),
        stabilization_budget=_caps(),
    )


def _approval(m: IntegrationScopeManifest, run_id: str = "run-001") -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=m.project_key,
        story_id=m.story_id,
        run_id=run_id,
        manifest_version=m.version,
        manifest_hash=m.content_hash,
    )


def _budget(
    loops_used: int = 0,
    surfaces_used: int = 0,
    changes_used: int = 0,
    regressions: int = 0,
    **cap_kwargs: int,
) -> StabilizationBudget:
    return StabilizationBudget(
        caps=_caps(**cap_kwargs),
        loops_used=loops_used,
        new_surfaces_used=surfaces_used,
        contract_changes_used=changes_used,
        regressions_this_cycle=regressions,
    )


# ---------------------------------------------------------------------------
# FK37CheckName wire keys
# ---------------------------------------------------------------------------


def test_fk37_check_name_constants() -> None:
    assert FK37CheckName.INTEGRATION_TARGET_MATRIX_PASSED == "integration_target_matrix_passed"
    assert FK37CheckName.DECLARED_SURFACES_ONLY == "declared_surfaces_only"
    assert FK37CheckName.STABILIZATION_BUDGET_NOT_EXHAUSTED == "stabilization_budget_not_exhausted"
    assert FK37CheckName.STABILITY_GATE == "stability_gate"
    assert FK37CheckName.MANIFEST_APPROVAL_REQUIRED == "manifest_approval_required"
    assert FK37CheckName.BINDING_INTEGRITY == "binding_integrity"


# ---------------------------------------------------------------------------
# 1. manifest_approval_required
# ---------------------------------------------------------------------------


class TestCheckManifestApprovalRequired:
    def test_pass_with_record(self) -> None:
        m = _manifest()
        result = check_fk37_manifest_approval_required(_approval(m))
        assert result.approved is True

    def test_block_without_record(self) -> None:
        result = check_fk37_manifest_approval_required(None)
        assert result.approved is False


# ---------------------------------------------------------------------------
# 2. binding_integrity
# ---------------------------------------------------------------------------


class TestCheckBindingIntegrity:
    def test_pass_on_valid_binding(self) -> None:
        m = _manifest()
        a = _approval(m, run_id="run-001")
        result = check_fk37_binding_integrity(m, a, current_run_id="run-001")
        assert result.binding_valid is True

    def test_block_on_hash_mismatch(self) -> None:
        m = _manifest()
        a = ManifestApprovalRecord(
            project_key=m.project_key, story_id=m.story_id,
            run_id="run-001", manifest_version=m.version,
            manifest_hash="deadbeef",
        )
        result = check_fk37_binding_integrity(m, a, current_run_id="run-001")
        assert result.binding_valid is False

    def test_block_on_run_id_mismatch(self) -> None:
        m = _manifest()
        a = _approval(m, run_id="run-001")
        result = check_fk37_binding_integrity(m, a, current_run_id="run-999")
        assert result.binding_valid is False


# ---------------------------------------------------------------------------
# 3. declared_surfaces_only (Layer 1)
# ---------------------------------------------------------------------------


class TestCheckDeclaredSurfacesOnly:
    def test_pass_all_declared(self) -> None:
        m = _manifest(target_seams=("src/api/",))
        result = check_fk37_declared_surfaces_only(
            touched_paths=("src/api/handler.py",),
            manifest=m,
        )
        assert result.passed is True

    def test_fail_undeclared_surface(self) -> None:
        m = _manifest(target_seams=("src/api/",))
        result = check_fk37_declared_surfaces_only(
            touched_paths=("src/other/module.py",),
            manifest=m,
        )
        assert result.passed is False
        assert "src/other/module.py" in result.undeclared_paths


# ---------------------------------------------------------------------------
# 4. stabilization_budget_not_exhausted
# ---------------------------------------------------------------------------


class TestCheckStabilizationBudgetNotExhausted:
    def test_pass_within_budget(self) -> None:
        result = check_fk37_stabilization_budget_not_exhausted(_budget())
        assert result.within_budget is True

    def test_block_loops_exhausted(self) -> None:
        result = check_fk37_stabilization_budget_not_exhausted(
            _budget(loops_used=5, max_loops=5)
        )
        assert result.within_budget is False

    def test_block_surfaces_exhausted(self) -> None:
        result = check_fk37_stabilization_budget_not_exhausted(
            _budget(surfaces_used=3, max_new_surfaces=3)
        )
        assert result.within_budget is False

    def test_block_changes_exhausted(self) -> None:
        result = check_fk37_stabilization_budget_not_exhausted(
            _budget(changes_used=2, max_contract_changes=2)
        )
        assert result.within_budget is False

    def test_block_regressions_exhausted(self) -> None:
        """AC4: regression cap tested individually."""
        result = check_fk37_stabilization_budget_not_exhausted(
            _budget(regressions=2, max_regressions_per_cycle=2)
        )
        assert result.within_budget is False


# ---------------------------------------------------------------------------
# 5. integration_target_matrix_passed (Layer 4)
# ---------------------------------------------------------------------------


class TestCheckIntegrationTargetMatrixPassed:
    def test_pass_all_targets_achieved(self) -> None:
        result = check_fk37_integration_target_matrix_passed(
            achieved_targets=frozenset({"t1", "t2"}),
            required_targets=frozenset({"t1", "t2"}),
        )
        assert result.passed is True
        assert result.unmet_targets == ()

    def test_fail_unmet_targets(self) -> None:
        result = check_fk37_integration_target_matrix_passed(
            achieved_targets=frozenset({"t1"}),
            required_targets=frozenset({"t1", "t2"}),
        )
        assert result.passed is False
        assert "t2" in result.unmet_targets

    def test_fail_no_targets_achieved(self) -> None:
        result = check_fk37_integration_target_matrix_passed(
            achieved_targets=frozenset(),
            required_targets=frozenset({"t1"}),
        )
        assert result.passed is False

    def test_pass_empty_required_targets(self) -> None:
        result = check_fk37_integration_target_matrix_passed(
            achieved_targets=frozenset(),
            required_targets=frozenset(),
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# 6. stability_gate (aggregate)
# ---------------------------------------------------------------------------


class TestCheckStabilityGate:
    """AC5/AC12: stability_gate is the aggregate of all four checks."""

    def test_pass_all_checks_pass(self) -> None:
        m = _manifest(
            target_seams=("src/api/",),
            integration_targets=("e2e_login",),
        )
        a = _approval(m, run_id="run-001")
        result = check_fk37_stability_gate(
            touched_paths=("src/api/handler.py",),
            manifest=m,
            budget=_budget(),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=a,
            current_run_id="run-001",
        )
        assert result.passed is True
        assert result.block_reasons == ()
        assert result.check_name == FK37CheckName.STABILITY_GATE

    def test_fail_no_approval(self) -> None:
        m = _manifest()
        result = check_fk37_stability_gate(
            touched_paths=("src/api/handler.py",),
            manifest=m,
            budget=_budget(),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=None,
            current_run_id="run-001",
        )
        assert result.passed is False
        assert any("manifest_approval_required" in r for r in result.block_reasons)

    def test_fail_undeclared_surface(self) -> None:
        m = _manifest(target_seams=("src/api/",))
        a = _approval(m, run_id="run-001")
        result = check_fk37_stability_gate(
            touched_paths=("src/undeclared/module.py",),
            manifest=m,
            budget=_budget(),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=a,
            current_run_id="run-001",
        )
        assert result.passed is False
        assert any("declared_surfaces_only" in r for r in result.block_reasons)

    def test_fail_budget_exhausted(self) -> None:
        m = _manifest()
        a = _approval(m, run_id="run-001")
        result = check_fk37_stability_gate(
            touched_paths=("src/api/x.py",),
            manifest=m,
            budget=_budget(loops_used=5, max_loops=5),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=a,
            current_run_id="run-001",
        )
        assert result.passed is False
        assert any("stabilization_budget_not_exhausted" in r for r in result.block_reasons)

    def test_fail_unmet_targets(self) -> None:
        m = _manifest(integration_targets=("e2e_login", "e2e_checkout"))
        a = _approval(m, run_id="run-001")
        result = check_fk37_stability_gate(
            touched_paths=("src/api/x.py",),
            manifest=m,
            budget=_budget(),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=a,
            current_run_id="run-001",
        )
        assert result.passed is False
        assert any(
            "integration_target_matrix_passed" in r for r in result.block_reasons
        )

    def test_fail_binding_integrity(self) -> None:
        m = _manifest()
        bad_approval = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=m.version,
            manifest_hash="wrong-hash",
        )
        result = check_fk37_stability_gate(
            touched_paths=("src/api/x.py",),
            manifest=m,
            budget=_budget(),
            achieved_targets=frozenset({"e2e_login"}),
            approval_record=bad_approval,
            current_run_id="run-001",
        )
        assert result.passed is False
        assert any("binding_integrity" in r for r in result.block_reasons)
