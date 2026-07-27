"""CP 10 regression tests for the Codex review findings (AG3-175 R03/R04/R05/R06).

Kept in a dedicated module so each finding stays traceable to the test that pins
it. Every test here fails when the corresponding fix is reverted.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

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
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_CONFIGURATION_INVALID,
    REASON_MCP_CONFIGURATION_INVALID,
)
from agentkit.backend.installer.mcp_conformance import (
    McpConformanceReason,
    McpConformanceResult,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pytest import MonkeyPatch

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_MCP_JSON = ".mcp.json"
_CODEX_REL = Path(".codex") / "config.toml"
_HTTP = "http://weaviate.test.invalid:9903"
_GRPC = "weaviate.test.invalid:50051"


def _conforming_desired(ctx: Any) -> tuple[DesiredMcpServer, ...]:
    """Desired set whose command is a REAL, conforming MCP server."""
    return (
        DesiredMcpServer(
            name=STORY_KNOWLEDGE_BASE_SERVER,
            command=sys.executable,
            args=(str(_MINIMAL_SERVER),),
            cwd=str(ctx.project_root),
            env=(("PROJECT_ID", "AG3"),),
        ),
    )


def _ctx(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    *,
    mode: ExecutionMode = ExecutionMode.REGISTER,
) -> Any:
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    config = make_config(
        root,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_vectordb=True,
    )
    ctx = build_checkpoint_context(config, mode)
    cp05_pipeline_config(ctx)
    return ctx


def _snapshot(root: Path) -> tuple[bytes | None, bytes | None]:
    mcp = root / _MCP_JSON
    codex = root / _CODEX_REL
    return (
        mcp.read_bytes() if mcp.is_file() else None,
        codex.read_bytes() if codex.is_file() else None,
    )


def _broken_probe(*_args: object, **_kwargs: object) -> McpConformanceResult:
    return McpConformanceResult(
        ok=False,
        reason=McpConformanceReason.PROCESS_EXITED,
        detail="server stopped answering.",
    )


# --------------------------------------------------------------------------- #
# R04 — the idempotent PASS must still assert a passed handshake.
#
# FK-50 §50.3 CP 10 defines it as "bereits identische Eintraege -> PASS
# (Conformance erneut bestanden)". A PASS without a probe reports a server that
# has STOPPED working as fine. This regressed against ``main``, where the gate ran
# before the idempotency return, and no test in the suite caught it.
# --------------------------------------------------------------------------- #


def test_idempotent_rerun_still_probes_and_fails_when_the_server_broke(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """A byte-identical registration whose server broke must NOT report PASS."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.CREATED
    before = _snapshot(root)

    # Nothing about the desired registration changes; only the server stops
    # answering -- exactly the situation the re-probe exists to catch.
    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _broken_probe)
    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED, (
        "an unchanged registration was reported PASS without re-probing"
    )
    assert result.reason == "mcp_process_exited"
    assert _snapshot(root) == before  # still no mutation


def test_idempotent_pass_is_reached_only_through_a_passing_probe(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """The positive half: PASS happens, and the probe demonstrably ran."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.CREATED

    probed: list[str] = []
    real = mcp_registration_mod.check_mcp_conformance

    def _counting(server: Any, **kwargs: Any) -> Any:
        probed.append(server.command)
        return real(server, **kwargs)

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _counting)
    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.PASS
    assert result.reason == REASON_ALREADY_SATISFIED
    assert probed, "the idempotent PASS did not re-run the conformance probe"


def test_read_only_modes_still_never_start_a_process(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Restoring the probe order must not leak a process start into dry-run/verify."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)

    def _must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("conformance must not run in a read-only mode")

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _must_not_run)
    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        ctx = _ctx(tmp_path, registration_repo, mode=mode)
        cp10_mcp_registration(ctx)
        assert not (Path(ctx.project_root) / _MCP_JSON).exists(), mode


# --------------------------------------------------------------------------- #
# R03 — ``.mcp.json`` uses the SAME identity rule as the Codex writer.
# --------------------------------------------------------------------------- #


def test_foreign_occupation_of_an_ak3_name_in_mcp_json_is_rejected(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """``.mcp.json`` used to clobber silently while Codex refused.

    That asymmetry gave two different answers to "is this entry ours" for the same
    registration, depending only on the format (against PO decision D6).
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text(
        '{"mcpServers": {"story-knowledge-base": '
        '{"command": "someone-elses-tool", "args": ["--serve"]}}}\n',
        encoding="utf-8",
    )
    before = _snapshot(root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert _snapshot(root) == before


def test_our_own_mcp_json_entry_is_upserted_not_rejected(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Same command+args means it is AK3's own entry: upsert, never reject."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    import json

    (root / _MCP_JSON).write_text(
        json.dumps(
            {
                "mcpServers": {
                    STORY_KNOWLEDGE_BASE_SERVER: {
                        "command": sys.executable,
                        "args": [str(_MINIMAL_SERVER)],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.UPDATED
    entry = json.loads((root / _MCP_JSON).read_text(encoding="utf-8"))["mcpServers"][
        STORY_KNOWLEDGE_BASE_SERVER
    ]
    assert entry["cwd"] == str(root)


# --------------------------------------------------------------------------- #
# R05 — the ``cwd`` containment invariant, held before the probe.
# --------------------------------------------------------------------------- #


def test_cwd_other_than_the_project_root_is_refused_before_probing(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """A validated negative invariant; production cannot produce this today.

    It fails closed rather than probing one directory and registering another.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def _wrong_cwd(_ctx: Any) -> tuple[DesiredMcpServer, ...]:
        return (
            DesiredMcpServer(
                name=STORY_KNOWLEDGE_BASE_SERVER,
                command=sys.executable,
                args=(str(_MINIMAL_SERVER),),
                cwd=str(elsewhere),
                env=(("PROJECT_ID", "AG3"),),
            ),
        )

    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _wrong_cwd)

    def _must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the probe must not run for an invalid cwd")

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _must_not_run)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
    assert "project root" in (result.detail or "")
    assert _snapshot(root) == (None, None)


# --------------------------------------------------------------------------- #
# R06 — at least one path through CP 10's REAL derivation, unsubstituted.
#
# The mechanics tests substitute ``_desired_mcp_servers`` so the probe can pass.
# That leaves a blind spot: CP 10 could stop using the production
# ``RuntimeBinding`` / engine command and every one of them would stay green. It
# is the class of gap that let R04 through.
# --------------------------------------------------------------------------- #


def test_real_derivation_produces_the_production_spec_unsubstituted(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """No substitution at all: the real derivation from the real CP 5 state."""
    ctx = _ctx(tmp_path, registration_repo)

    servers = cp10_mod._desired_mcp_servers(ctx)

    assert len(servers) == 1
    server = servers[0]
    assert server.name == STORY_KNOWLEDGE_BASE_SERVER
    assert server.command == "python"
    assert server.args == ("-m", "agentkit.backend.vectordb.engine")
    assert Path(server.cwd).resolve() == Path(ctx.project_root).resolve()
    env = server.env_dict()
    assert set(env) == set(REGISTERED_ENV_KEYS)
    assert env["WEAVIATE_HTTP_ENDPOINT"] == _HTTP
    assert env["WEAVIATE_GRPC_ENDPOINT"] == _GRPC
    assert env["AGENTKIT_CONCEPTS_DIR"].endswith("concepts")
    assert env["AGENTKIT_STORIES_DIR"].endswith("stories")
    assert server.required is True


def test_real_derivation_is_what_the_probe_receives(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """The full handler with the REAL desired set.

    Only the probe boundary is observed -- probing the productive command for real
    needs a reachable Weaviate. Derivation, rendering and ordering are all
    production code here, so a regression away from the production spec fails.
    """
    observed: list[Any] = []

    def _record(server: Any, **_kwargs: Any) -> McpConformanceResult:
        observed.append(server)
        return _broken_probe()

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _record)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert len(observed) == 1
    probed = observed[0]
    assert probed.command == "python"
    assert tuple(probed.args) == ("-m", "agentkit.backend.vectordb.engine")
    assert probed.cwd == str(ctx.project_root)
    assert probed.env is not None
    assert set(probed.env) == set(REGISTERED_ENV_KEYS)
    assert _snapshot(root) == (None, None)
