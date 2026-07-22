"""Per-checkpoint behaviour tests for the installer engine (AG3-088).

Covers story AC3/AC4/AC5/AC6/AC7/AC8/AC10: each checkpoint returns a correct
CheckpointResult (incl. mandatory reason on SKIP/FAIL); CP 2 is fail-closed on a
missing/unreachable repo; CP 3/CP 4 are reserved; CP 8 calls
``PromptRuntime.update_binding``; CP 9 calls ``Governance.register_hooks``; CP 10
writes the target ``.mcp.json`` in register but not in dry-run/verify; CP 10c
ARE-scope paths (pending_selection / resolved / are_disabled).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.control_plane.third_party_models import (
    ThirdPartyValidationRequest,
    ThirdPartyValidationResponse,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    REASON_REPO_UNREACHABLE,
    cp01_package_check,
    cp02_repo_check,
    cp03_reserved,
    cp04_reserved,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import (
    cp10_mcp_registration,
    cp10c_are_scope_validation,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
    run_checkpoint_install,
)
from agentkit.backend.installer.checkpoint_engine.context import ScopeInteractionMode
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ARE_DISABLED,
    REASON_PENDING_SELECTION,
    REASON_RESERVED,
    REASON_VECTORDB_DISABLED,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.repo_probe import RepoProbeResult

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient


class _PassingAreProjectEdge:
    """Typed backend verdict seam for the ARE-only full-flow unit test."""

    def validate_third_party(
        self, *, project_key: str, request: ThirdPartyValidationRequest
    ) -> ThirdPartyValidationResponse:
        assert project_key == "proj"
        return ThirdPartyValidationResponse.model_validate(
            {
                "op_id": request.op_id,
                "status": "PASS",
                "systems": [
                    {"system": "sonar", "status": "SKIPPED", "detail": "not applicable"},
                    {"system": "jenkins", "status": "SKIPPED", "detail": "not applicable"},
                    {"system": "are", "status": "PASS", "detail": "probe verdict"},
                ],
            }
        )


def _ctx(config: object, mode: ExecutionMode, **kw: object) -> object:
    return build_checkpoint_context(config, mode, **kw)  # type: ignore[arg-type]


def _result_for(results: object, checkpoint: str) -> object:
    return next(r for r in results if r.checkpoint == checkpoint)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# CP 1 / CP 2 / CP 3 / CP 4
# --------------------------------------------------------------------------- #


def test_cp01_package_check_passes(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    config = make_config(
        tmp_path, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    result = cp01_package_check(_ctx(config, ExecutionMode.REGISTER))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.PASS


def test_cp02_fail_closed_on_missing_repo(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC4: CP 2 is FAILED when the injected probe reports the repo absent."""

    def _absent_probe(owner: str, repo: str) -> RepoProbeResult:
        return RepoProbeResult(exists=False, detail=f"repo {owner}/{repo} not found")

    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        repo_existence_probe=_absent_probe,
    )
    result = cp02_repo_check(_ctx(config, ExecutionMode.REGISTER))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_REPO_UNREACHABLE


def test_cp02_pass_when_probe_confirms_repo(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    def _present_probe(owner: str, repo: str) -> RepoProbeResult:
        return RepoProbeResult(exists=True, detail="ok")

    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        repo_existence_probe=_present_probe,
    )
    result = cp02_repo_check(_ctx(config, ExecutionMode.REGISTER))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.PASS


def test_cp03_and_cp04_are_reserved(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC5: CP 3/CP 4 deterministically SKIPPED with reason="reserved"."""
    config = make_config(
        tmp_path, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    ctx = _ctx(config, ExecutionMode.REGISTER)
    for handler in (cp03_reserved, cp04_reserved):
        result = handler(ctx)  # type: ignore[arg-type]
        assert result.status is CheckpointStatus.SKIPPED
        assert result.reason == REASON_RESERVED


# --------------------------------------------------------------------------- #
# CP 8 (update_binding) / CP 9 (register_hooks)
# --------------------------------------------------------------------------- #


def _stub_cp10_mcp_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub dual-harness MCP probe so full-flow unit installs stay offline."""
    import agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp as cp10_mod
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    monkeypatch.setattr(
        cp10_mod,
        "check_mcp_conformance",
        lambda cmd, **kwargs: McpConformanceResult(
            ok=True,
            reason=None,
            detail="stubbed ok",
            tool_names=("story_search", "concept_search"),
        ),
    )


def test_cp08_calls_prompt_runtime_update_binding(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: CP 8 invokes PromptRuntime.update_binding (the second binding path)."""
    _stub_cp10_mcp_ok(monkeypatch)
    calls: list[tuple[str, str]] = []
    from agentkit.backend.prompt_runtime.runtime import PromptRuntime

    original = PromptRuntime.update_binding

    def _spy(self: PromptRuntime, bundle_id: str, version: str) -> None:
        calls.append((bundle_id, version))
        original(self, bundle_id, version)

    monkeypatch.setattr(PromptRuntime, "update_binding", _spy)

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert result.success
    assert calls, "PromptRuntime.update_binding was not called by CP 8"


def test_cp09_calls_governance_register_hooks(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7: CP 9 invokes Governance.register_hooks."""
    _stub_cp10_mcp_ok(monkeypatch)
    calls: list[int] = []
    from agentkit.backend.governance.runner import Governance

    original = Governance.register_hooks

    def _spy(self: Governance, hook_definitions: object) -> object:
        calls.append(len(hook_definitions))  # type: ignore[arg-type]
        return original(self, hook_definitions)  # type: ignore[arg-type]

    monkeypatch.setattr(Governance, "register_hooks", _spy)

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert result.success
    assert calls, "Governance.register_hooks was not called by CP 9"


# --------------------------------------------------------------------------- #
# CP 10 — MCP registration + .mcp.json mutation (AC10)
# --------------------------------------------------------------------------- #


def test_cp10_no_longer_skips_when_features_vectordb_flag_false(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AG3-176 AC6: VectorDB is mandatory — no SKIPPED/vectordb_disabled path.

    Even when InstallConfig.features_vectordb is False, the orchestrator
    forces vectordb_enabled=True and CP10 attempts registration (may fail
    closed on preflight/conformance, but never SKIPPED for optional-off).
    """
    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    ctx = _ctx(config, ExecutionMode.REGISTER)
    assert ctx.vectordb_enabled is True  # type: ignore[attr-defined]
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import cp05_pipeline_config

    cp05_pipeline_config(ctx)  # type: ignore[arg-type]
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is not CheckpointStatus.SKIPPED
    assert result.reason != REASON_VECTORDB_DISABLED


def test_cp10_are_only_fails_without_phantom_are_mcp_entry(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG3-164 AC1/AC2: ARE profile fails honestly when MCP is not runnable.

    AG3-176: VectorDB is mandatory — dual-harness probes story-kb first.
    Real conformance (not the unit stub) fails closed; no phantom write.
    """
    import agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp as cp10_mod
    from agentkit.backend.installer.mcp_conformance import check_mcp_conformance

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", check_mcp_conformance)

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_are=True,
        features_vectordb=False,
        are_module_scope_map={"app": "scope-a"},
    )
    config.project_edge_client = cast("ProjectEdgeClient", _PassingAreProjectEdge())
    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert result.success is False
    mcp_path = root / ".mcp.json"
    if mcp_path.is_file():
        servers = json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers", {})
        assert "are-mcp" not in servers
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
        cp05_pipeline_config,
    )
    from agentkit.backend.installer.checkpoint_engine.reasons import (
        REASON_MCP_COMMAND_NOT_FOUND,
    )

    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    cp05_pipeline_config(ctx)
    cp10_result = cp10_mcp_registration(ctx)
    assert cp10_result.status is CheckpointStatus.FAILED
    assert cp10_result.reason == REASON_MCP_COMMAND_NOT_FOUND
    assert not (root / ".mcp.json").exists()


def test_cp10_does_not_write_mcp_json_in_dry_run_or_verify(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC10: dry_run/verify never write the target .mcp.json."""
    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_vectordb=True,
    )
    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        run_checkpoint_install(config, mode=mode)
        assert not (root / ".mcp.json").exists(), mode


# --------------------------------------------------------------------------- #
# CP 10c — ARE-scope validation (AC8)
# --------------------------------------------------------------------------- #


def _are_ctx(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    *,
    module_scope_map: dict[str, str] | None,
    repositories: list[dict[str, str]] | None,
    mode: ExecutionMode = ExecutionMode.REGISTER,
    interaction: str = ScopeInteractionMode.AGENTIC,
) -> object:
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_are=True,
        are_module_scope_map=module_scope_map,
        repositories=repositories,
    )
    ctx = build_checkpoint_context(config, mode, scope_interaction_mode=interaction)
    # Publish project.yaml, then run the real CP 10 predecessor with a
    # conforming ARE-MCP substitute (AG3-164). Product ``agentkit-are-mcp``
    # does not exist; the fixture builder routes desired servers to the
    # minimal real MCP test server so CP 10c consumes genuine predecessor
    # state rather than hand-written production JSON.
    import sys
    from pathlib import Path

    from agentkit.backend.installer.bootstrap_checkpoints import cp10_mcp as cp10_mod
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
        cp05_pipeline_config,
    )
    from agentkit.backend.installer.bootstrap_checkpoints.cp10 import (
        cp10_mcp_registration,
    )

    cp05_pipeline_config(ctx)
    if mode.mutations_allowed:
        repo_root = Path(__file__).resolve().parents[4]
        minimal = repo_root / "tests" / "fixtures" / "minimal_mcp_server.py"
        original = cp10_mod._desired_mcp_servers

        def _are_via_test_server(context: object) -> dict[str, object]:
            return {
                "are-mcp": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [str(minimal)],
                }
            }

        cp10_mod._desired_mcp_servers = _are_via_test_server  # type: ignore[assignment]
        try:
            cp10_result = cp10_mcp_registration(ctx)
        finally:
            cp10_mod._desired_mcp_servers = original  # type: ignore[assignment]
        assert cp10_result.status in (
            CheckpointStatus.CREATED,
            CheckpointStatus.UPDATED,
            CheckpointStatus.PASS,
        ), cp10_result
    return ctx


def test_cp10c_are_disabled_is_skipped(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: features.are=False -> CP 10c SKIPPED/reason=are_disabled."""
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_are=False,
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    result = cp10c_are_scope_validation(ctx)
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_ARE_DISABLED


def test_cp10c_pending_selection_in_agentic_mode(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: an unmapped ARE item -> SKIPPED/reason=pending_selection (agentic)."""
    ctx = _are_ctx(
        tmp_path,
        registration_repo,
        module_scope_map={},  # nothing mapped
        repositories=[{"name": "app", "path": ".", "are_scope": "scope-x"}],
    )
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_PENDING_SELECTION
    assert "PENDING_SELECTION" in (result.detail or "")


def test_cp10c_resolved_mapping_idempotent_skip(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: complete mapping -> idempotent SKIPPED (register) with reason."""
    ctx = _are_ctx(
        tmp_path,
        registration_repo,
        module_scope_map={"scope-x": "app"},
        repositories=[{"name": "app", "path": ".", "are_scope": "scope-x"}],
    )
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    # Idempotent re-run on a complete mapping -> already_satisfied (not pending).
    from agentkit.backend.installer.checkpoint_engine.reasons import REASON_ALREADY_SATISFIED

    assert result.reason == REASON_ALREADY_SATISFIED


def test_cp10c_resolved_mapping_pass_in_verify(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: complete mapping in read-only verify -> PASS."""
    ctx = _are_ctx(
        tmp_path,
        registration_repo,
        module_scope_map={"scope-x": "app"},
        repositories=[{"name": "app", "path": ".", "are_scope": "scope-x"}],
        mode=ExecutionMode.VERIFY,
    )
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.PASS
