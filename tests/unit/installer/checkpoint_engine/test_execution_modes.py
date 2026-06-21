"""Execution-mode tests for the installer checkpoint engine (AG3-088).

Covers story AC11/AC12 + §2.1.5: register vs dry-run vs verify. Dry-run mutates
nothing (filesystem snapshot before==after) and carries the dry-run result
contract; verify is read-only; the idempotent re-run yields SKIPPED/UPDATED
instead of re-CREATE.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import run_checkpoint_install
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    DRY_RUN_PLAN_MARKER,
    REASON_PLANNED_NO_MUTATION,
)
from agentkit.backend.installer.registration import (
    CP7_STATE_BACKEND_REGISTRATION,
    CheckpointStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


def _fs_snapshot(root: Path) -> dict[str, str]:
    """Return a path -> content-digest snapshot of every file under ``root``."""
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[str(path.relative_to(root))] = digest
    return snapshot


def _all_surfaces_snapshot(root: Path) -> dict[str, dict[str, str]]:
    """Snapshot EVERY filesystem surface a checkpoint handler can touch.

    AG3-088 (story AC10-AC12, strengthened no-mutation proof): dry_run/verify
    must mutate NOTHING — not only ``project_root`` but also the CENTRAL
    prompt-bundle store (which CP 8 writes via ``_ensure_prompt_bundle_store_entry``
    in register mode). Snapshotting only ``project_root`` would miss a regression
    where CP 8 creates dirs / copies the prompt bundle into the (machine-global,
    test-isolated) store. We snapshot:

    * the target ``project_root`` (CP 5/8/9/10/11 project-local writes), and
    * the prompt-bundle store root (CP 8 central store materialisation).
    """
    from agentkit.backend.installer.paths import default_prompt_bundle_store_root

    store_root = default_prompt_bundle_store_root()
    return {
        "project_root": _fs_snapshot(root),
        "prompt_bundle_store": _fs_snapshot(store_root) if store_root.is_dir() else {},
    }


def _result_for(results: object, checkpoint: str) -> object:
    return next(r for r in results if r.checkpoint == checkpoint)  # type: ignore[attr-defined]


def test_register_runs_full_flow_and_persists(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """Register mode runs the flow and persists the registration (CREATED)."""
    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "bundles", registration_repo=registration_repo
    )

    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)

    assert result.success
    cp7 = _result_for(result.checkpoint_results, CP7_STATE_BACKEND_REGISTRATION)
    assert cp7.status is CheckpointStatus.CREATED
    assert registration_repo.get(root.stem) is not None
    # The active project artefacts were deployed (CP 8 region).
    assert (root / ".claude" / "settings.json").is_file()


def test_dry_run_mutates_nothing_and_reports_plan_contract(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: object,
) -> None:
    """AC11: dry_run performs NO mutation and carries the dry-run result contract.

    Strengthened (story AC10-AC12): the no-mutation proof snapshots ALL surfaces
    a handler can touch — ``project_root`` AND the central prompt-bundle store —
    and asserts they are byte-identical before==after. The prompt-bundle store is
    pointed at a per-test directory so the proof is independent of test ordering
    (the session-shared store would otherwise be pre-populated by a register run).
    """
    import os

    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    store_root = tmp_path / "prompt-bundle-store"
    monkeypatch.setenv("AGENTKIT_PROMPT_BUNDLE_STORE_ROOT", str(store_root))
    assert os.environ["AGENTKIT_PROMPT_BUNDLE_STORE_ROOT"] == str(store_root)

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "bundles", registration_repo=registration_repo
    )

    before = _all_surfaces_snapshot(root)
    result = run_checkpoint_install(config, mode=ExecutionMode.DRY_RUN)
    after = _all_surfaces_snapshot(root)

    # EVERY surface unchanged (project_root + central prompt-bundle store) and the
    # state backend untouched. The store dir must not even be CREATED by dry_run.
    assert before == after
    assert not store_root.exists(), "dry_run created the central prompt-bundle store"
    assert registration_repo.save_calls == 0
    assert registration_repo.get(root.stem) is None
    assert result.created_files == ()

    # Dry-run result contract: a planned CREATED carries reason planned_no_mutation
    # and the plan marker in detail.
    cp7 = _result_for(result.checkpoint_results, CP7_STATE_BACKEND_REGISTRATION)
    assert cp7.status is CheckpointStatus.CREATED
    assert cp7.reason == REASON_PLANNED_NO_MUTATION
    assert cp7.detail is not None and DRY_RUN_PLAN_MARKER in cp7.detail
    # Every MUTATING checkpoint's dry-run result carries the plan marker in detail
    # (pure read-only checks such as CP 1/CP 2/CP 12 legitimately produce a plain
    # PASS — they never mutate in any mode, so they need no plan marker).
    mutating = {
        nid.CP_05_PIPELINE_CONFIG,
        nid.CP_07_BACKEND_REGISTRATION,
        nid.CP_08_SKILL_BINDINGS,
        nid.CP_09_HOOK_REGISTRATION,
        nid.CP_10_MCP_REGISTRATION,
        nid.CP_11_GIT_HOOKS_AND_CLAUDE,
    }
    for cp in result.checkpoint_results or ():
        if cp.checkpoint in mutating:
            assert cp.detail is not None and DRY_RUN_PLAN_MARKER in cp.detail, cp.checkpoint


def test_verify_is_read_only(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: object,
) -> None:
    """AC12: verify mode mutates nothing and returns CheckpointResults.

    Strengthened (story AC10-AC12): snapshots ALL surfaces (project_root + the
    central prompt-bundle store) and asserts byte-identical before==after, with
    the store isolated to a per-test directory.
    """
    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    store_root = tmp_path / "prompt-bundle-store"
    monkeypatch.setenv("AGENTKIT_PROMPT_BUNDLE_STORE_ROOT", str(store_root))

    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "bundles", registration_repo=registration_repo
    )

    before = _all_surfaces_snapshot(root)
    result = run_checkpoint_install(config, mode=ExecutionMode.VERIFY)
    after = _all_surfaces_snapshot(root)

    assert before == after
    assert not store_root.exists(), "verify created the central prompt-bundle store"
    assert registration_repo.save_calls == 0
    assert result.checkpoint_results
    # CP 12 verification ran read-only.
    cp12 = _result_for(result.checkpoint_results, nid.CP_12_VERIFY_REGISTRATION)
    assert cp12.status is CheckpointStatus.PASS


def test_idempotent_rerun_skips_then_upgrades(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC12: idempotent re-run yields SKIPPED; a changed config yields UPDATED."""
    root = tmp_path / "proj"
    root.mkdir()
    bundles = tmp_path / "bundles"
    config = make_config(
        root, bundle_store_root=bundles, registration_repo=registration_repo
    )

    first = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert _result_for(
        first.checkpoint_results, CP7_STATE_BACKEND_REGISTRATION
    ).status is CheckpointStatus.CREATED

    # Identical config -> idempotent SKIP, no re-create.
    second = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    cp7_second = _result_for(second.checkpoint_results, CP7_STATE_BACKEND_REGISTRATION)
    assert cp7_second.status is CheckpointStatus.SKIPPED
    assert registration_repo.save_calls == 1  # not re-saved

    # Changed config (extra repo) -> UPDATED.
    changed = make_config(
        root,
        bundle_store_root=bundles,
        registration_repo=registration_repo,
        repositories=[{"name": "extra", "path": "extra"}],
    )
    third = run_checkpoint_install(changed, mode=ExecutionMode.REGISTER)
    cp7_third = _result_for(third.checkpoint_results, CP7_STATE_BACKEND_REGISTRATION)
    assert cp7_third.status is CheckpointStatus.UPDATED
    assert registration_repo.upgrade_calls == 1
