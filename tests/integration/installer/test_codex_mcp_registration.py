"""Integration: dual-harness MCP registration across install runs (AG3-175).

Real filesystem, real functions, real CP 8 -> CP 10 order. These scenarios need
the multi-RUN behaviour that a single checkpoint call cannot show:

* the MCP table CP 10 merges must survive the next run's CP 8 writer AND the
  static-resource deploy (finding B, both destruction paths),
* a user-extended ``.codex/config.toml`` must survive an install run at all
  (the pre-existing data-loss defect closed in passing),
* nothing outside the project root is ever written (AC 3).

Scope note, deliberately honest: these tests drive the real CP 8 writer
(``write_codex_settings``), the real static-resource deploy
(``_deploy_static_resource_files``) and the real CP 10 handler in the real order
— not the full twelve-checkpoint engine, because CP 10's conformance probe would
need a reachable Weaviate for the productive command (``compose_runtime``
connects before serving stdio). The productive command's startability is proven
offline in ``tests/unit/installer/test_registered_entry_starts.py``; the live
end-to-end pass belongs to the opt-in e2e layer.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.unit.installer.checkpoint_engine.conftest import make_config

from agentkit.backend.core_types.mcp_server_registration import (
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
)
from agentkit.backend.installer import mcp_registration as mcp_registration_mod
from agentkit.backend.installer.bootstrap_checkpoints import cp10 as cp10_mod
from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    cp05_pipeline_config,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import cp10_mcp_registration
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.codex_settings import write_codex_settings
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.runner import (
    _deploy_static_resource_files,
    _resources_target_project_dir,
)
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def registration_repo(tmp_path: Path) -> StateBackendProjectRegistrationRepository:
    """The REAL production registration repository (review finding R06).

    Integration coverage must not lean on an in-memory double: CLAUDE.md allows one
    only where an isolated UNIT test is otherwise impossible, which does not apply
    here. The SQLite-backed production implementation is the same class the
    composition root wires, so this exercises the real seam.

    CP 10 never touches the registry -- ``test_registration_repository_is_never_
    touched_by_cp10`` proves that rather than assuming it -- but the config must
    carry a production collaborator regardless.
    """
    return StateBackendProjectRegistrationRepository(store_dir=tmp_path)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_CODEX_REL = Path(".codex") / "config.toml"


def _conforming_desired(ctx: Any) -> tuple[DesiredMcpServer, ...]:
    return (
        DesiredMcpServer(
            name=STORY_KNOWLEDGE_BASE_SERVER,
            command=sys.executable,
            args=(str(_MINIMAL_SERVER),),
            cwd=str(ctx.project_root),
            env=(("PROJECT_ID", "AG3"),),
        ),
    )


def _context(
    root: Path,
    registration_repo: StateBackendProjectRegistrationRepository,
    *,
    real_probe: bool = False,
) -> Any:
    probe_kwargs = {"mcp_registration_probe": None} if real_probe else {}
    config = make_config(
        root,
        bundle_store_root=root.parent / "bundles",
        registration_repo=registration_repo,
        features_vectordb=True,
        **probe_kwargs,
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    cp05_pipeline_config(ctx)
    return ctx


def _cp8_region(root: Path) -> None:
    """Run the CP 8 steps that touch ``.codex/config.toml``, in the real order.

    ``_deploy_static_resource_files`` runs FIRST (``runner.py`` line ~1147) and
    ``write_codex_settings`` second (line ~1186) — the ordering that made the
    bundle copy destructive.
    """
    _deploy_static_resource_files(_resources_target_project_dir(), root)
    write_codex_settings(root)


def test_both_configs_registered_and_mcp_table_survives_a_second_run(
    tmp_path: Path, registration_repo: StateBackendProjectRegistrationRepository, monkeypatch: MonkeyPatch
) -> None:
    """AC 1 across RUNS — the core of finding B.

    Revert-red twice over: restore the fixed-string byte comparison in
    ``write_codex_settings`` and the second run wipes the table; restore the
    bundle ``.codex/config.toml`` and the static deploy wipes it.
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    root = tmp_path / "proj"
    root.mkdir()
    ctx = _context(root, registration_repo)

    # ---- run 1: CP 8 region, then CP 10 ----
    _cp8_region(root)
    assert cp10_mcp_registration(ctx).status in (
        CheckpointStatus.CREATED,
        CheckpointStatus.UPDATED,
    )
    codex = root / _CODEX_REL
    parsed = tomllib.loads(codex.read_text(encoding="utf-8"))
    assert STORY_KNOWLEDGE_BASE_SERVER in parsed["mcp_servers"]
    assert parsed["hooks"]["pre_tool_use"]["command"] == "agentkit-hook-codex"

    # ---- run 2: the CP 8 region runs again, as in a real re-install ----
    _cp8_region(root)

    parsed_after = tomllib.loads(codex.read_text(encoding="utf-8"))
    assert STORY_KNOWLEDGE_BASE_SERVER in parsed_after["mcp_servers"], (
        "the MCP registration did not survive the second install run"
    )
    assert parsed_after["hooks"]["pre_tool_use"]["command"] == "agentkit-hook-codex"
    # And CP 10 now converges to PASS rather than rewriting.
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.PASS


def test_user_extended_codex_config_survives_two_install_runs(
    tmp_path: Path, registration_repo: StateBackendProjectRegistrationRepository
) -> None:
    """Pre-existing data-loss defect, closed in passing.

    Measured on the unfixed code, the static-resource deploy clobbered a
    user-extended ``.codex/config.toml`` at CP 8 — while ``detach`` goes out of its
    way to PRESERVE exactly that content (FK-10 §10.2.9). Install destroyed what
    detach protects.

    The loss had TWO causes and this test is revert-red against BOTH: re-add
    ``bundles/target_project/.codex/config.toml`` and the static copy overwrites
    the file; restore the fixed-string byte comparison in ``write_codex_settings``
    and that overwrites it instead.
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".codex").mkdir()
    (root / _CODEX_REL).write_bytes(
        b"# AgentKit-managed Codex hook configuration.\n"
        b"\n"
        b"[hooks.pre_tool_use]\n"
        b'command = "agentkit-hook-codex"\n'
        b"\n"
        b"# user note: my own Codex settings, please keep\n"
        b"[user.custom]\n"
        b"alpha = 1\n"
    )

    _cp8_region(root)
    _cp8_region(root)

    text = (root / _CODEX_REL).read_text(encoding="utf-8")
    assert "# user note: my own Codex settings, please keep" in text
    assert tomllib.loads(text)["user"]["custom"] == {"alpha": 1}


def test_bundle_no_longer_ships_a_competing_codex_config() -> None:
    """The third writer is gone (finding B, corrected).

    ``_deploy_static_resource_files`` copies EVERY non-``templates`` file from the
    bundle, so as long as a ``.codex/config.toml`` existed there it would be copied
    over the merged registration on every run.
    """
    assert not (_resources_target_project_dir() / ".codex" / "config.toml").exists()


def test_isolated_codex_home_is_never_written(
    tmp_path: Path, registration_repo: StateBackendProjectRegistrationRepository, monkeypatch: MonkeyPatch
) -> None:
    """AC 3 — no user/global configuration is written.

    Honest limitation: this is NOT revert-red. AK3 reads ``CODEX_HOME`` nowhere
    (verified: the name does not occur in ``src/`` or ``tools/``), so there is no
    production line whose removal would turn it red. It is a regression lock
    against a future change, not a proof of a fix.
    """
    codex_home = tmp_path / "user-codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)

    root = tmp_path / "proj"
    root.mkdir()
    ctx = _context(root, registration_repo)
    _cp8_region(root)
    assert cp10_mcp_registration(ctx).status in (
        CheckpointStatus.CREATED,
        CheckpointStatus.UPDATED,
    )

    assert list(codex_home.iterdir()) == [], "a user path was written"
    assert os.environ["CODEX_HOME"] == str(codex_home)


def test_registration_is_invisible_from_a_second_project_folder(
    tmp_path: Path, registration_repo: StateBackendProjectRegistrationRepository, monkeypatch: MonkeyPatch
) -> None:
    """AC 3 — project-local only; a sibling project sees nothing."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    first = tmp_path / "project-a"
    second = tmp_path / "project-b"
    first.mkdir()
    second.mkdir()

    ctx = _context(first, registration_repo)
    _cp8_region(first)
    assert cp10_mcp_registration(ctx).status in (
        CheckpointStatus.CREATED,
        CheckpointStatus.UPDATED,
    )

    assert (first / _CODEX_REL).is_file()
    assert not (second / _CODEX_REL).exists()
    assert not (second / ".mcp.json").exists()


def test_junctioned_codex_dir_is_refused_without_writing_the_target(
    tmp_path: Path, registration_repo: StateBackendProjectRegistrationRepository
) -> None:
    """AC 3 — no user path even via a reparse point.

    Revert-red against ``assert_project_local_codex_config``: without it the write
    would follow the junction into the simulated user directory.
    """
    from agentkit.backend.exceptions import InstallationError
    from agentkit.backend.skills import create_directory_link

    root = tmp_path / "proj"
    root.mkdir()
    user_dir = tmp_path / "simulated-user-home-codex"
    user_dir.mkdir()
    try:
        create_directory_link(root / ".codex", user_dir)
    except OSError:  # pragma: no cover - platform without links
        pytest.skip("filesystem supports neither symlinks nor junctions")

    with pytest.raises(InstallationError):
        write_codex_settings(root)

    assert list(user_dir.iterdir()) == [], "wrote through the reparse point"


def test_registration_repository_is_never_touched_by_cp10(
    tmp_path: Path,
    registration_repo: StateBackendProjectRegistrationRepository,
    monkeypatch: MonkeyPatch,
) -> None:
    """The registry belongs to CP 7; CP 10 must not read or write it.

    Proven rather than assumed (review finding R06): the config has to carry a
    registration collaborator, and this pins that CP 10 leaves it alone, so no
    reader can mistake the collaborator for part of the tested path.
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    root = tmp_path / "proj"
    root.mkdir()
    ctx = _context(root, registration_repo)
    _cp8_region(root)

    assert cp10_mcp_registration(ctx).status in (
        CheckpointStatus.CREATED,
        CheckpointStatus.UPDATED,
    )

    assert registration_repo.list_all() == [], (
        "CP 10 touched the project registry, which belongs to CP 7"
    )


def test_full_cp8_to_cp10_region_uses_the_real_derivation(
    tmp_path: Path,
    registration_repo: StateBackendProjectRegistrationRepository,
    monkeypatch: MonkeyPatch,
) -> None:
    """Integration path with NO substituted producer (review finding R06).

    Every other test in this module substitutes ``_desired_mcp_servers`` so the
    conformance probe can pass without a reachable Weaviate. That leaves the blind
    spot R06 names: CP 10 could stop using the production derivation and they would
    all stay green. Here the real derivation runs, the real CP 8 region runs, and
    only the probe boundary is observed -- so a regression away from the production
    command, cwd or env fails this test.
    """
    observed: list[Any] = []

    def _record(server: Any, **_kwargs: Any) -> Any:
        from agentkit.backend.installer.mcp_conformance import (
            McpConformanceReason,
            McpConformanceResult,
        )

        observed.append(server)
        return McpConformanceResult(
            ok=False,
            reason=McpConformanceReason.PROCESS_EXITED,
            detail="not probing a live Weaviate in CI.",
        )

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _record)
    root = tmp_path / "proj"
    root.mkdir()
    ctx = _context(root, registration_repo, real_probe=True)
    _cp8_region(root)

    result = cp10_mcp_registration(ctx)

    # The CP 8 region really ran: the hook entry is materialised.
    assert "agentkit-hook-codex" in (root / _CODEX_REL).read_text(encoding="utf-8")
    # The real derivation reached the probe with the production spec.
    assert len(observed) == 1, result
    probed = observed[0]
    assert probed.command == "python"
    assert tuple(probed.args) == ("-m", "agentkit.backend.vectordb.engine")
    assert probed.cwd == str(root)
    assert probed.env is not None
    assert set(probed.env) == set(REGISTERED_ENV_KEYS)
    # And a failing probe writes no registration.
    assert result.status is CheckpointStatus.FAILED
    assert not (root / ".mcp.json").exists()
