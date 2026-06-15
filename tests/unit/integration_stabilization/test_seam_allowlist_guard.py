"""Unit tests for SeamAllowlistGuard overlay (AC7)."""

from __future__ import annotations

from agentkit.governance.protocols import ViolationType
from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    StabilizationBudgetCaps,
)
from agentkit.integration_stabilization.seam_allowlist_guard import (
    SeamAllowlistGuard,
    materialize_seam_allowlist,
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


class TestMaterializeSeamAllowlist:
    def test_combines_seams_and_repos(self) -> None:
        m = _manifest(
            target_seams=("src/api/", "src/db/"),
            allowed_repos_paths=("worktrees/main/",),
        )
        result = materialize_seam_allowlist(m)
        assert len(result) == 3
        assert any("src" in p for p in result)

    def test_empty_manifest_produces_empty_allowlist(self) -> None:
        m = _manifest(target_seams=(), allowed_repos_paths=())
        result = materialize_seam_allowlist(m)
        assert result == ()


class TestSeamAllowlistGuard:
    """AC7: guard-overlay blocks writes outside seam allowlist."""

    def _guard(
        self,
        target_seams: tuple[str, ...] = ("src/api/",),
        allowed_repos_paths: tuple[str, ...] = (),
    ) -> SeamAllowlistGuard:
        m = _manifest(target_seams=target_seams, allowed_repos_paths=allowed_repos_paths)
        return SeamAllowlistGuard(materialize_seam_allowlist(m))

    def test_guard_name(self) -> None:
        guard = self._guard()
        assert guard.name == "seam_allowlist_guard"

    def test_write_within_seam_allowed(self) -> None:
        guard = self._guard(target_seams=("src/api/",))
        verdict = guard.evaluate(
            "file_write", {"file_path": "src/api/handler.py"}
        )
        assert verdict.allowed is True

    def test_write_outside_seam_blocked(self) -> None:
        """AC7 negative: write outside seam allowlist → BLOCK."""
        guard = self._guard(target_seams=("src/api/",))
        verdict = guard.evaluate(
            "file_write", {"file_path": "src/internal/secret.py"}
        )
        assert verdict.allowed is False
        assert verdict.violation_type == ViolationType.SCOPE_VIOLATION

    def test_file_edit_outside_seam_blocked(self) -> None:
        guard = self._guard(target_seams=("src/api/",))
        verdict = guard.evaluate(
            "file_edit", {"file_path": "src/elsewhere/file.py"}
        )
        assert verdict.allowed is False

    def test_non_write_operation_always_allowed(self) -> None:
        guard = self._guard(target_seams=())
        for op in ("file_read", "git_push", "shell_exec", "list_dir"):
            verdict = guard.evaluate(op, {"file_path": "src/anything.py"})
            assert verdict.allowed is True, f"expected allow for {op!r}"

    def test_empty_allowlist_blocks_all_writes(self) -> None:
        guard = SeamAllowlistGuard(())
        verdict = guard.evaluate("file_write", {"file_path": "src/api/x.py"})
        assert verdict.allowed is False

    def test_write_within_allowed_repos_path_allowed(self) -> None:
        guard = self._guard(
            target_seams=(),
            allowed_repos_paths=("worktrees/main/",),
        )
        verdict = guard.evaluate(
            "file_write",
            {"file_path": "worktrees/main/src/service.py"},
        )
        assert verdict.allowed is True

    def test_verdict_carries_detail(self) -> None:
        guard = self._guard(target_seams=("src/api/",))
        verdict = guard.evaluate(
            "file_write", {"file_path": "src/unrelated/x.py"}
        )
        assert verdict.detail is not None
        assert "file_path" in verdict.detail
