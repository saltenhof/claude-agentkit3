"""Regression tests for the AG3-088 remediation fixes.

Covers three review findings:

* FIX 1 (AC1): ``install_agentkit`` is a PURE delegation façade — it contains
  no post-engine checkpoint orchestration; the AG3-056 CI preflight is owned by
  the engine path (``run_checkpoint_install``) and still runs there.
* FIX 2 (AC10-AC12): CP 8 must perform ZERO mutation in dry_run AND verify —
  including the central prompt-bundle store (``_ensure_prompt_bundle_store_entry``
  must not run in a read-only mode).
* FIX 3 (AC8): CP 10c distinguishes "resolved this run" (-> UPDATED) from
  "already complete" (-> SKIPPED/PASS).
"""

from __future__ import annotations

import ast
import inspect
import re
from typing import TYPE_CHECKING

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.cp07_to_09 import cp08_skill_bindings
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import cp10c_are_scope_validation
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.context import ScopeInteractionMode
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_PLANNED_NO_MUTATION,
)
from agentkit.backend.installer.paths import default_prompt_bundle_store_root
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# --------------------------------------------------------------------------- #
# FIX 1 — install_agentkit is a PURE delegation façade (AC1)
# --------------------------------------------------------------------------- #


def test_install_agentkit_facade_only_delegates() -> None:
    """AC1: the façade body contains NO checkpoint orchestration.

    Structural proof (not a grep of arbitrary prose): the façade's AST may only
    delegate to ``run_checkpoint_install``. It must NOT call the CI preflight, NOT
    build a project.yaml, NOT construct an ``InstallResult`` — all of which would
    be the façade doing checkpoint orchestration of its own (the prior bug).
    """
    from agentkit.backend.installer import runner

    source = inspect.getsource(runner.install_agentkit)
    tree = ast.parse(source)
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                called_names.add(func.attr)

    assert "run_checkpoint_install" in called_names
    # No orchestration of its own in the façade.
    forbidden = {
        "run_ci_preflight_checkpoint_result",
        "_build_project_yaml",
        "InstallResult",
        "_run_ci_preflight",
    }
    leaked = forbidden & called_names
    assert not leaked, f"façade still orchestrates: {sorted(leaked)}"


def test_engine_path_runs_ci_preflight_in_register(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC1: the CI preflight runs via the ENGINE path (run_checkpoint_install).

    With ``ci_available=False`` (test default) the preflight is SKIPPED/
    not_applicable, but it is still APPENDED by the engine path — proving the
    engine owns it (the façade no longer adds it).
    """
    from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert result.success
    ci = [
        r
        for r in (result.checkpoint_results or ())
        if r.checkpoint == "ci_preflight_jenkins_precondition"
    ]
    assert ci, "engine path did not append the CI preflight result"
    assert ci[0].status is CheckpointStatus.SKIPPED
    assert ci[0].reason == "not_applicable"


def test_install_agentkit_appends_ci_via_engine(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC1: the façade still yields the CI preflight (inherited from the engine)."""
    from agentkit.backend.installer.runner import install_agentkit

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    result = install_agentkit(config)
    assert result.success
    checkpoints = {r.checkpoint for r in (result.checkpoint_results or ())}
    assert "ci_preflight_jenkins_precondition" in checkpoints


def test_engine_does_not_run_ci_preflight_in_read_only(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """The engine never hits the live CI boundary in dry_run/verify (FK-50 §50.2)."""
    from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        result = run_checkpoint_install(config, mode=mode)
        checkpoints = {r.checkpoint for r in (result.checkpoint_results or ())}
        assert "ci_preflight_jenkins_precondition" not in checkpoints, mode


# --------------------------------------------------------------------------- #
# FIX 2 — CP 8 mutates the prompt-bundle store ONLY in register (AC10-AC12)
# --------------------------------------------------------------------------- #


def _store_snapshot() -> dict[str, bytes]:
    store_root = default_prompt_bundle_store_root()
    snapshot: dict[str, bytes] = {}
    if store_root.is_dir():
        for path in sorted(store_root.rglob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(store_root))] = path.read_bytes()
    return snapshot


def _cp8_ctx(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    mode: ExecutionMode,
) -> object:
    config = make_config(
        tmp_path / "proj",
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
    )
    (tmp_path / "proj").mkdir(exist_ok=True)
    return build_checkpoint_context(config, mode)


def test_cp08_does_not_touch_prompt_store_in_read_only(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC10-AC12: CP 8 must NOT create/copy into the prompt-bundle store in
    dry_run OR verify — even though it reports the planned bundle_id@version.

    Isolates the store to a per-test dir, snapshots it before/after, and proves
    it stays byte-identical (and is never even created) in BOTH read-only modes.
    """
    store_root = tmp_path / "prompt-bundle-store"
    monkeypatch.setenv("AGENTKIT_PROMPT_BUNDLE_STORE_ROOT", str(store_root))

    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        before = _store_snapshot()
        ctx = _cp8_ctx(tmp_path, registration_repo, mode)
        result = cp08_skill_bindings(ctx)  # type: ignore[arg-type]
        after = _store_snapshot()
        assert before == after, mode
        assert not store_root.exists(), f"{mode} created the prompt-bundle store"
        # The plan/read-only result still reports the bundle binding intent.
        assert result.detail is not None and "PromptRuntime.update_binding" in result.detail
        if mode is ExecutionMode.DRY_RUN:
            assert result.status is CheckpointStatus.CREATED
            assert result.reason == REASON_PLANNED_NO_MUTATION
        else:
            assert result.status is CheckpointStatus.PASS


def test_cp08_register_materialises_prompt_store(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Register mode DOES materialise the central prompt-bundle store (contrast)."""
    store_root = tmp_path / "prompt-bundle-store"
    monkeypatch.setenv("AGENTKIT_PROMPT_BUNDLE_STORE_ROOT", str(store_root))

    ctx = _cp8_ctx(tmp_path, registration_repo, ExecutionMode.REGISTER)
    # CP 5 must publish project.yaml first; CP 8 deploys post-registration.
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import cp05_pipeline_config

    cp05_pipeline_config(ctx)  # type: ignore[arg-type]
    result = cp08_skill_bindings(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED
    assert store_root.is_dir(), "register did not materialise the prompt-bundle store"
    assert _store_snapshot(), "prompt-bundle store is empty after register"


# --------------------------------------------------------------------------- #
# FIX 3 — CP 10c resolved-this-run -> UPDATED (AC8)
# --------------------------------------------------------------------------- #


def _are_ctx_complete(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    *,
    mode: ExecutionMode = ExecutionMode.REGISTER,
) -> object:
    """Build a CP 10c context with a COMPLETE ARE mapping + ARE-MCP registered."""
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_are=True,
        are_module_scope_map={"scope-x": "app"},
        repositories=[{"name": "app", "path": ".", "are_scope": "scope-x"}],
    )
    ctx = build_checkpoint_context(
        config, mode, scope_interaction_mode=ScopeInteractionMode.AGENTIC
    )
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import cp05_pipeline_config
    from agentkit.backend.installer.bootstrap_checkpoints.cp10 import cp10_mcp_registration

    cp05_pipeline_config(ctx)
    cp10_mcp_registration(ctx)
    return ctx


def test_cp10c_resolved_this_run_is_updated(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: a mapping resolved DURING this run -> UPDATED (register mode)."""
    ctx = _are_ctx_complete(tmp_path, registration_repo)
    # Simulate the orchestrating agent's resolve_pending_scope_mapping() having
    # written the mapping in THIS run (recorded on the run-state).
    ctx.run_state.resolved_scope_mappings = {"scope-x": "app"}  # type: ignore[attr-defined]
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.UPDATED
    assert result.detail is not None and "Resolved this run" in result.detail


def test_cp10c_already_complete_is_idempotent_skip(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: an already-complete mapping (nothing resolved this run) -> SKIPPED."""
    ctx = _are_ctx_complete(tmp_path, registration_repo)
    # No resolved_scope_mappings -> nothing was written this run.
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_ALREADY_SATISFIED


def test_cp10c_resolved_this_run_is_plan_updated_in_dry_run(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: resolved-this-run in dry_run -> plan-UPDATED (no mutation token)."""
    ctx = _are_ctx_complete(tmp_path, registration_repo, mode=ExecutionMode.DRY_RUN)
    ctx.run_state.resolved_scope_mappings = {"scope-x": "app"}  # type: ignore[attr-defined]
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.UPDATED
    assert result.reason == REASON_PLANNED_NO_MUTATION


def test_cp10c_resolved_this_run_is_pass_in_verify(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: resolved-this-run in verify -> PASS (read-only)."""
    ctx = _are_ctx_complete(tmp_path, registration_repo, mode=ExecutionMode.VERIFY)
    ctx.run_state.resolved_scope_mappings = {"scope-x": "app"}  # type: ignore[attr-defined]
    result = cp10c_are_scope_validation(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.PASS


def test_facade_source_has_no_imperative_ci_orchestration() -> None:
    """AC1 belt-and-suspenders: the façade source has no ci/InstallResult tokens."""
    from agentkit.backend.installer import runner

    source = inspect.getsource(runner.install_agentkit)
    # The façade returns the engine result verbatim; it must not re-assemble one.
    assert not re.search(r"\bInstallResult\(", source)
    assert "ci_result" not in source
