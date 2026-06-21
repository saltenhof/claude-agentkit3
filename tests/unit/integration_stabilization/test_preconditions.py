"""Unit tests for integration_stabilization preconditions (AC2/AC3/AC4/AC9).

Covers all five enforcement-point fail-closed checks:
- AC2: no-approval block + binding/hash/run mismatch block
- AC3: repo-set expansion block
- AC4: each budget cap including regression cap
- AC9: closure precondition per condition
- AC10: reclassification no-retroactive-legalization
"""

from __future__ import annotations

from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudget,
    StabilizationBudgetCaps,
)
from agentkit.backend.integration_stabilization.preconditions import (
    check_approval_present,
    check_binding_integrity,
    check_budget_not_exhausted,
    check_closure_precondition,
    check_manifest_repo_set,
    check_reclassification_no_retroactive_legalization,
)


def _caps(
    loops: int = 5,
    surfaces: int = 3,
    changes: int = 2,
    regressions: int = 2,
) -> StabilizationBudgetCaps:
    return StabilizationBudgetCaps(
        max_loops=loops,
        max_new_surfaces=surfaces,
        max_contract_changes=changes,
        max_regressions_per_cycle=regressions,
    )


def _manifest(
    allowed_repos_paths: tuple[str, ...] = ("worktrees/main/",),
    target_seams: tuple[str, ...] = ("src/api/",),
) -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id="PROJ-42",
        implementation_contract="integration_stabilization",
        target_seams=target_seams,
        allowed_repos_paths=allowed_repos_paths,
        integration_targets=("e2e_login",),
        allowed_contract_changes=(),
        stabilization_budget=_caps(),
    )


def _approval(manifest: IntegrationScopeManifest, run_id: str = "run-001") -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=manifest.project_key,
        story_id=manifest.story_id,
        run_id=run_id,
        manifest_version=manifest.version,
        manifest_hash=manifest.content_hash,
    )


# ---------------------------------------------------------------------------
# AC2: no-approval block
# ---------------------------------------------------------------------------


class TestCheckApprovalPresent:
    """Enforcement point: no approval -> blocked (AC2)."""

    def test_no_approval_record_blocks(self) -> None:
        result = check_approval_present(None)
        assert result.approved is False
        assert "fail-closed" in result.reason.lower() or "blocked" in result.reason.lower()

    def test_approval_record_present_passes(self) -> None:
        m = _manifest()
        rec = _approval(m)
        result = check_approval_present(rec)
        assert result.approved is True
        assert result.reason == ""


# ---------------------------------------------------------------------------
# AC2: binding/hash/run mismatch block
# ---------------------------------------------------------------------------


class TestCheckBindingIntegrity:
    """Enforcement point: hash/version/run mismatch -> blocked (AC2)."""

    def test_valid_binding_passes(self) -> None:
        m = _manifest()
        rec = _approval(m, run_id="run-001")
        result = check_binding_integrity(m, rec, current_run_id="run-001")
        assert result.binding_valid is True

    def test_hash_mismatch_blocks(self) -> None:
        m = _manifest()
        rec = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=m.version,
            manifest_hash="wrong-hash",
        )
        result = check_binding_integrity(m, rec, current_run_id="run-001")
        assert result.binding_valid is False
        assert "manifest_hash" in result.reason

    def test_version_mismatch_blocks(self) -> None:
        m = _manifest()
        rec = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=99,
            manifest_hash=m.content_hash,
        )
        result = check_binding_integrity(m, rec, current_run_id="run-001")
        assert result.binding_valid is False
        assert "manifest_version" in result.reason

    def test_run_mismatch_blocks(self) -> None:
        m = _manifest()
        rec = _approval(m, run_id="run-001")
        result = check_binding_integrity(m, rec, current_run_id="run-999")
        assert result.binding_valid is False
        assert "run_id" in result.reason

    def test_project_key_mismatch_blocks(self) -> None:
        m = _manifest()
        rec = ManifestApprovalRecord(
            project_key="OTHER",
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=m.version,
            manifest_hash=m.content_hash,
        )
        result = check_binding_integrity(m, rec, current_run_id="run-001")
        assert result.binding_valid is False

    def test_story_id_mismatch_blocks(self) -> None:
        m = _manifest()
        rec = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id="PROJ-99",
            run_id="run-001",
            manifest_version=m.version,
            manifest_hash=m.content_hash,
        )
        result = check_binding_integrity(m, rec, current_run_id="run-001")
        assert result.binding_valid is False


# ---------------------------------------------------------------------------
# AC3: repo-set expansion block
# ---------------------------------------------------------------------------


class TestCheckManifestRepoSet:
    """Enforcement point: manifest must not introduce new repos (AC3)."""

    def test_within_bound_roots_passes(self) -> None:
        m = _manifest(
            allowed_repos_paths=("worktrees/main/src/",),
            target_seams=("worktrees/main/src/api/",),
        )
        result = check_manifest_repo_set(
            m, bound_roots=("worktrees/main/",)
        )
        assert result.within_bounds is True
        assert result.violating_paths == ()

    def test_exact_match_passes(self) -> None:
        m = _manifest(
            allowed_repos_paths=("worktrees/main",),
            target_seams=("worktrees/main",),
        )
        result = check_manifest_repo_set(
            m, bound_roots=("worktrees/main",)
        )
        assert result.within_bounds is True

    def test_outside_bound_roots_blocks(self) -> None:
        m = _manifest(
            allowed_repos_paths=("worktrees/main/", "worktrees/newrepo/"),
            target_seams=("worktrees/main/",),
        )
        result = check_manifest_repo_set(
            m, bound_roots=("worktrees/main/",)
        )
        assert result.within_bounds is False
        assert any("newrepo" in p for p in result.violating_paths)

    def test_target_seam_outside_bound_roots_blocks(self) -> None:
        """ERROR F: target_seams are ALSO covered by the repo-set boundary."""
        m = _manifest(
            allowed_repos_paths=("worktrees/main/",),
            target_seams=("worktrees/other/seam/",),
        )
        result = check_manifest_repo_set(m, bound_roots=("worktrees/main/",))
        assert result.within_bounds is False
        assert any("other" in p for p in result.violating_paths)

    def test_completely_new_repo_path_blocks(self) -> None:
        """AC3 invariant: manifest_may_not_expand_repo_set."""
        m = _manifest(
            allowed_repos_paths=("/outside/repo/",),
            target_seams=("/inside/repo/api/",),
        )
        result = check_manifest_repo_set(
            m, bound_roots=("/inside/repo/",)
        )
        assert result.within_bounds is False
        assert len(result.violating_paths) == 1

    def test_empty_allowed_repos_passes_trivially(self) -> None:
        m = IntegrationScopeManifest(
            version=1,
            project_key="PROJ",
            story_id="PROJ-42",
            implementation_contract="integration_stabilization",
            target_seams=(),
            allowed_repos_paths=(),
            integration_targets=("t1",),
            allowed_contract_changes=(),
            stabilization_budget=_caps(),
        )
        result = check_manifest_repo_set(m, bound_roots=("worktrees/main/",))
        assert result.within_bounds is True


# ---------------------------------------------------------------------------
# AC4: each budget cap (including regression cap)
# ---------------------------------------------------------------------------


class TestCheckBudgetNotExhausted:
    """Enforcement point: budget cap exhaustion -> blocked (AC4)."""

    def test_loops_cap_blocks(self) -> None:
        budget = StabilizationBudget(caps=_caps(loops=2), loops_used=2)
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert "loops" in result.exhausted_caps

    def test_new_surfaces_cap_blocks(self) -> None:
        budget = StabilizationBudget(caps=_caps(surfaces=1), new_surfaces_used=1)
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert "new_surfaces" in result.exhausted_caps

    def test_contract_changes_cap_blocks(self) -> None:
        budget = StabilizationBudget(
            caps=_caps(changes=1), contract_changes_used=1
        )
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert "contract_changes" in result.exhausted_caps

    def test_regressions_per_cycle_cap_blocks(self) -> None:
        """AC4 regression cap specifically tested."""
        budget = StabilizationBudget(
            caps=_caps(regressions=0), regressions_this_cycle=0
        )
        # max=0 means any (>= 0) would exhaust, so already at cap
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert "regressions_per_cycle" in result.exhausted_caps

    def test_regression_cap_at_limit_blocks(self) -> None:
        budget = StabilizationBudget(
            caps=_caps(regressions=2), regressions_this_cycle=2
        )
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert "regressions_per_cycle" in result.exhausted_caps

    def test_within_budget_passes(self) -> None:
        budget = StabilizationBudget(
            caps=_caps(loops=5, surfaces=3, changes=2, regressions=2),
            loops_used=1,
            new_surfaces_used=0,
            contract_changes_used=0,
            regressions_this_cycle=0,
        )
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is True
        assert result.exhausted_caps == ()

    def test_multiple_caps_exhausted_at_once(self) -> None:
        budget = StabilizationBudget(
            caps=_caps(loops=1, surfaces=1, changes=1, regressions=1),
            loops_used=1,
            new_surfaces_used=1,
            contract_changes_used=1,
            regressions_this_cycle=1,
        )
        result = check_budget_not_exhausted(budget)
        assert result.within_budget is False
        assert len(result.exhausted_caps) == 4


# ---------------------------------------------------------------------------
# AC9: closure precondition per condition
# ---------------------------------------------------------------------------


class TestCheckClosurePrecondition:
    """Enforcement point: closure precondition (AC9)."""

    def test_all_conditions_met_passes(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=True,
            achieved_targets=frozenset({"e2e_login"}),
            required_targets=frozenset({"e2e_login"}),
            open_manifest_violations=0,
            replan_needed=False,
        )
        assert result.closure_allowed is True
        assert result.blocking_reasons == ()

    def test_stability_gate_not_passed_blocks(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=False,
            achieved_targets=frozenset({"e2e_login"}),
            required_targets=frozenset({"e2e_login"}),
            open_manifest_violations=0,
            replan_needed=False,
        )
        assert result.closure_allowed is False
        assert any("stability_gate" in r for r in result.blocking_reasons)

    def test_unmet_targets_blocks(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=True,
            achieved_targets=frozenset(),
            required_targets=frozenset({"e2e_login", "e2e_checkout"}),
            open_manifest_violations=0,
            replan_needed=False,
        )
        assert result.closure_allowed is False
        assert any("integration_targets" in r for r in result.blocking_reasons)

    def test_open_manifest_violation_blocks(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=True,
            achieved_targets=frozenset({"e2e_login"}),
            required_targets=frozenset({"e2e_login"}),
            open_manifest_violations=2,
            replan_needed=False,
        )
        assert result.closure_allowed is False
        assert any("manifest violation" in r for r in result.blocking_reasons)

    def test_replan_needed_blocks(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=True,
            achieved_targets=frozenset({"e2e_login"}),
            required_targets=frozenset({"e2e_login"}),
            open_manifest_violations=0,
            replan_needed=True,
        )
        assert result.closure_allowed is False
        assert any("replan" in r for r in result.blocking_reasons)

    def test_all_conditions_violated_produces_four_reasons(self) -> None:
        result = check_closure_precondition(
            stability_gate_passed=False,
            achieved_targets=frozenset(),
            required_targets=frozenset({"t1", "t2"}),
            open_manifest_violations=3,
            replan_needed=True,
        )
        assert result.closure_allowed is False
        assert len(result.blocking_reasons) == 4


# ---------------------------------------------------------------------------
# AC10: reclassification no-retroactive-legalization
# ---------------------------------------------------------------------------


class TestCheckReclassificationNoRetroactiveLegalization:
    """AC10: reclassification does not legalize pre-manifest deltas."""

    def test_with_fresh_epoch_quarantines_deltas(self) -> None:
        result = check_reclassification_no_retroactive_legalization(
            pre_snapshot_deltas=("delta-a", "delta-b"),
            evidence_epoch="epoch-2026-01-01T00:00:00",
        )
        assert result.legalization_blocked is True
        assert set(result.quarantined_deltas) == {"delta-a", "delta-b"}
        assert result.evidence_epoch == "epoch-2026-01-01T00:00:00"

    def test_no_epoch_means_legalization_not_enforced(self) -> None:
        """Without a fresh epoch the invariant cannot be enforced."""
        result = check_reclassification_no_retroactive_legalization(
            pre_snapshot_deltas=("delta-x",),
            evidence_epoch="",
        )
        assert result.legalization_blocked is False

    def test_empty_pre_snapshot_deltas_with_epoch_passes(self) -> None:
        result = check_reclassification_no_retroactive_legalization(
            pre_snapshot_deltas=(),
            evidence_epoch="epoch-fresh",
        )
        assert result.legalization_blocked is True
        assert result.quarantined_deltas == ()
