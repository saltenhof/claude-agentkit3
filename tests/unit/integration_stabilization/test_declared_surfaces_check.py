"""Unit tests for declared_surfaces_only deterministic check (AC6/AC12)."""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.integration_stabilization.declared_surfaces_check import (
    check_declared_surfaces_only,
    is_path_within_seam_allowlist,
)
from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    StabilizationBudgetCaps,
)


def _manifest(
    target_seams: tuple[str, ...] = ("src/api/", "src/db/"),
    allowed_repos_paths: tuple[str, ...] = ("worktrees/main/",),
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
        stabilization_budget=StabilizationBudgetCaps(
            max_loops=5,
            max_new_surfaces=3,
            max_contract_changes=2,
            max_regressions_per_cycle=2,
        ),
    )


class TestIsPathWithinSeamAllowlist:
    """Low-level path-matching helper."""

    def test_exact_match(self) -> None:
        assert is_path_within_seam_allowlist(
            "src/api", seam_allowlist=("src/api",)
        )

    def test_sub_path_match(self) -> None:
        assert is_path_within_seam_allowlist(
            "src/api/v1/endpoint.py", seam_allowlist=("src/api",)
        )

    def test_outside_seam_fails(self) -> None:
        assert not is_path_within_seam_allowlist(
            "src/internal/service.py", seam_allowlist=("src/api",)
        )

    def test_empty_allowlist_fails(self) -> None:
        assert not is_path_within_seam_allowlist(
            "src/anything.py", seam_allowlist=()
        )

    def test_prefix_not_confused_with_sibling(self) -> None:
        # 'src/apiother' is NOT inside 'src/api'
        assert not is_path_within_seam_allowlist(
            "src/apiother/foo.py", seam_allowlist=("src/api",)
        )


class TestCheckDeclaredSurfacesOnly:
    """AC6: deterministic Layer-1 check, no LLM path."""

    def test_all_paths_declared_passes(self) -> None:
        m = _manifest()
        result = check_declared_surfaces_only(
            touched_paths=("src/api/handler.py", "src/db/models.py"),
            manifest=m,
        )
        assert result.passed is True
        assert result.undeclared_paths == ()
        assert result.findings == ()

    def test_undeclared_path_fails(self) -> None:
        """AC6: undeclared surface → FAIL (BLOCKING)."""
        m = _manifest()
        result = check_declared_surfaces_only(
            touched_paths=("src/api/handler.py", "src/unrelated/module.py"),
            manifest=m,
        )
        assert result.passed is False
        assert "src/unrelated/module.py" in result.undeclared_paths
        assert len(result.findings) == 1
        assert result.findings[0].severity == Severity.BLOCKING

    def test_seam_allowlist_extends_declared_surfaces(self) -> None:
        m = _manifest(target_seams=("src/api/",))
        result = check_declared_surfaces_only(
            touched_paths=("src/extra/helper.py",),
            manifest=m,
            seam_allowlist=("src/extra/",),
        )
        assert result.passed is True

    def test_multiple_undeclared_paths_produce_multiple_findings(self) -> None:
        m = _manifest(target_seams=(), allowed_repos_paths=())
        result = check_declared_surfaces_only(
            touched_paths=("src/a.py", "src/b.py", "src/c.py"),
            manifest=m,
        )
        assert result.passed is False
        assert len(result.findings) == 3

    def test_empty_touched_paths_passes(self) -> None:
        m = _manifest()
        result = check_declared_surfaces_only(
            touched_paths=(),
            manifest=m,
        )
        assert result.passed is True

    def test_path_within_allowed_repos_paths_passes(self) -> None:
        m = _manifest(
            target_seams=(),
            allowed_repos_paths=("worktrees/main/",),
        )
        result = check_declared_surfaces_only(
            touched_paths=("worktrees/main/src/service.py",),
            manifest=m,
        )
        assert result.passed is True

    def test_findings_have_correct_check_id(self) -> None:
        m = _manifest(target_seams=())
        result = check_declared_surfaces_only(
            touched_paths=("src/elsewhere/file.py",),
            manifest=m,
        )
        assert result.findings[0].check == "integration.declared_surfaces_only"

    def test_no_llm_dependency(self) -> None:
        """AC6 invariant: declared_surfaces_only_is_deterministic.

        The function is a pure deterministic function — same inputs, same
        output. This test verifies determinism (no external state).
        """
        m = _manifest()
        r1 = check_declared_surfaces_only(
            touched_paths=("src/api/x.py", "src/unknown/y.py"),
            manifest=m,
        )
        r2 = check_declared_surfaces_only(
            touched_paths=("src/api/x.py", "src/unknown/y.py"),
            manifest=m,
        )
        assert r1 == r2
