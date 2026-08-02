"""CP 10 dual-harness registration: two-file semantics (AG3-175 AC 4/5/6/7).

Drives the REAL CP 10 handler. The conformance probe must pass for the write
phase to be reached, so the desired set is routed to the real
``tests/fixtures/minimal_mcp_server.py`` — the established pattern of the
existing CP 10 suite. The productive command's own startability is proven
separately and offline in ``tests/unit/installer/test_registered_entry_starts.py``.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.core_types.mcp_server_registration import (
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
)
from agentkit.backend.installer.bootstrap_checkpoints import cp10_mcp_registration as cp10_mod
from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    cp05_pipeline_config,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp_registration import cp10_mcp_registration
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_CONFIGURATION_INVALID,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_REGISTRATION_INCOMPLETE,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pytest import MonkeyPatch

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"

_MCP_JSON = ".mcp.json"
_CODEX_REL = Path(".codex") / "config.toml"


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
    features_vectordb: bool = True,
    http_endpoint: str | None = "http://weaviate.test.invalid:9903",
    grpc_endpoint: str | None = "weaviate.test.invalid:50051",
) -> Any:
    """Build a context with CP 5 actually run (no hand-made pipeline state)."""
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    config = make_config(
        root,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_vectordb=features_vectordb,
        vectordb_http_endpoint=http_endpoint,
        vectordb_grpc_endpoint=grpc_endpoint,
        mcp_registration_probe=None,
    )
    ctx = build_checkpoint_context(config, mode)
    cp05_pipeline_config(ctx)
    return ctx


def _use_conforming(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)


def _snapshot(root: Path) -> tuple[bytes | None, bytes | None]:
    mcp = root / _MCP_JSON
    codex = root / _CODEX_REL
    return (
        mcp.read_bytes() if mcp.is_file() else None,
        codex.read_bytes() if codex.is_file() else None,
    )


# --------------------------------------------------------------------------- #
# AC 1 — both configurations registered, idempotent
# --------------------------------------------------------------------------- #


def test_register_writes_both_harness_configurations(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.CREATED
    root = Path(ctx.project_root)
    assert (root / _MCP_JSON).is_file()
    codex = (root / _CODEX_REL).read_text(encoding="utf-8")
    assert f"[mcp_servers.{STORY_KNOWLEDGE_BASE_SERVER}]" in codex
    assert "required = true" in codex


def test_second_run_is_pass_and_writes_nothing(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.CREATED
    root = Path(ctx.project_root)
    before = _snapshot(root)

    again = cp10_mcp_registration(ctx)

    assert again.status is CheckpointStatus.PASS
    assert again.reason == REASON_ALREADY_SATISFIED
    assert _snapshot(root) == before


def test_foreign_entries_in_both_files_are_preserved(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text('{"mcpServers": {"foreign": {"command": "node"}}}\n', encoding="utf-8")
    (root / _CODEX_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _CODEX_REL).write_bytes(b"# mine\n[user.custom]\nalpha = 1\n")

    assert cp10_mcp_registration(ctx).status is CheckpointStatus.UPDATED

    mcp = (root / _MCP_JSON).read_text(encoding="utf-8")
    codex = (root / _CODEX_REL).read_text(encoding="utf-8")
    assert '"foreign"' in mcp
    assert "[user.custom]" in codex
    assert "# mine" in codex


# --------------------------------------------------------------------------- #
# AC 4 — no registration without a passed conformance check
# --------------------------------------------------------------------------- #


def test_failed_conformance_writes_neither_file(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    def _broken(ctx: Any) -> tuple[DesiredMcpServer, ...]:
        return (
            DesiredMcpServer(
                name=STORY_KNOWLEDGE_BASE_SERVER,
                command="definitely-missing-mcp-binary",
                args=(),
                cwd=str(ctx.project_root),
                env=(),
            ),
        )

    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _broken)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert _snapshot(root) == (None, None)


# --------------------------------------------------------------------------- #
# AC 5 — digest binding: a field changed after the probe blocks the write
# --------------------------------------------------------------------------- #


def test_field_mutation_after_the_probe_prevents_both_writes(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """The write must be PREVENTED, not silently performed with new content."""
    _use_conforming(monkeypatch)
    real_probe = cp10_mod.probe_registration

    def _probe_then_mutate(rendered: Any, **kwargs: Any) -> Any:
        probed, failure = real_probe(rendered, **kwargs)
        if probed is None:
            return probed, failure
        mutated_server = dataclasses.replace(probed.rendered.servers[0], cwd="C:/somewhere-else")
        tampered = dataclasses.replace(probed.rendered, servers=(mutated_server,))
        return dataclasses.replace(probed, rendered=tampered), None

    monkeypatch.setattr(cp10_mod, "probe_registration", _probe_then_mutate)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
    assert "changed after the conformance probe" in (result.detail or "")
    assert _snapshot(root) == (None, None)


# --------------------------------------------------------------------------- #
# AC 6 — honest two-file error semantics
# --------------------------------------------------------------------------- #


def test_codex_parse_error_yields_zero_writes(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """A rejection in EITHER file must leave BOTH byte-identical.

    Revert-red against the phase order: if the ``.mcp.json`` write happened before
    the Codex file was read and rendered, ``.mcp.json`` would already differ here.
    """
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (root / _CODEX_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _CODEX_REL).write_bytes(b"[unclosed\n")
    before = _snapshot(root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert _snapshot(root) == before


def test_io_error_after_first_write_rolls_back_and_names_the_error(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """AC 6: simulated I/O failure on the SECOND write.

    The simulated failure is the single permitted stub in this story: the path
    "I/O error after the first write" is otherwise unreachable. It is scoped to
    exactly one function and one call.
    """
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text('{"mcpServers": {"keep": {"command": "x"}}}\n', encoding="utf-8")
    before_mcp, _ = _snapshot(root)

    def _explode(_project_root: Path, _content: str) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(cp10_mod, "write_codex_config_text", _explode)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_REGISTRATION_INCOMPLETE
    assert "rolled back" in (result.detail or "")
    # The bound before-image was restored: .mcp.json is byte-identical again.
    assert (root / _MCP_JSON).read_bytes() == before_mcp


def test_rollback_deletes_a_file_that_did_not_exist_before(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """``None`` before-image means DELETE on rollback, not leave an empty file."""
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    def _explode(_project_root: Path, _content: str) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(cp10_mod, "write_codex_config_text", _explode)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_REGISTRATION_INCOMPLETE
    assert not (root / _MCP_JSON).exists()


def test_retry_after_incomplete_registration_converges(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """AC 6: a repeated run converges idempotently after an aborted one."""
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)

    def _explode(_project_root: Path, _content: str) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(cp10_mod, "write_codex_config_text", _explode)
    assert cp10_mcp_registration(ctx).reason == REASON_REGISTRATION_INCOMPLETE

    monkeypatch.undo()
    _use_conforming(monkeypatch)
    retry = cp10_mcp_registration(ctx)

    assert retry.status in (CheckpointStatus.CREATED, CheckpointStatus.UPDATED)
    assert (root / _MCP_JSON).is_file()
    assert (root / _CODEX_REL).is_file()
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.PASS


def test_crash_window_state_converges_when_only_codex_is_missing(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """The documented crash window: .mcp.json written, Codex not. A rerun fixes it."""
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    assert cp10_mcp_registration(ctx).status is CheckpointStatus.CREATED
    # Simulate the crash aftermath: the Codex half is gone, .mcp.json remains.
    (root / _CODEX_REL).unlink()

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.UPDATED
    assert (root / _CODEX_REL).is_file()


# --------------------------------------------------------------------------- #
# AC 7 — the strictness matrix at the checkpoint boundary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "codex_bytes",
    [
        pytest.param(b'x = "\xff\xfe"\n', id="not_utf8"),
        pytest.param(b"[unclosed\n", id="unparsable"),
        pytest.param(b"[a]\nx = 1\nx = 2\n", id="duplicate_key"),
        pytest.param(b"[a]\nx = 1\n[a]\ny = 2\n", id="duplicate_table"),
        pytest.param(b"mcp_servers = 5\n", id="mcp_servers_not_table"),
        pytest.param(b"[mcp_servers]\nfoo = 5\n", id="server_entry_not_table"),
        pytest.param(b"hooks = 5\n", id="hooks_not_table"),
        pytest.param(
            b"[mcp_servers.story-knowledge-base]\nrequired = 1\n",
            id="server_field_type_invalid",
        ),
        pytest.param(
            b'[mcp_servers.story-knowledge-base]\ncommand = "other-tool"\nargs = []\n',
            id="server_name_foreign_occupied",
        ),
    ],
)
def test_rejection_matrix_leaves_both_files_byte_identical(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
    codex_bytes: bytes,
) -> None:
    _use_conforming(monkeypatch)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (root / _CODEX_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _CODEX_REL).write_bytes(codex_bytes)
    before = _snapshot(root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert _snapshot(root) == before


# --------------------------------------------------------------------------- #
# Configuration source (finding C): fail-closed, never a synthesised endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("http_endpoint", "grpc_endpoint"),
    [(None, "weaviate.test.invalid:50051"), ("http://w.invalid:9903", None), (None, None)],
)
def test_missing_endpoint_configuration_fails_closed_without_writes(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    http_endpoint: str | None,
    grpc_endpoint: str | None,
) -> None:
    """No endpoint is ever synthesised (PO decision D2); zero writes."""
    ctx = _ctx(
        tmp_path,
        registration_repo,
        http_endpoint=http_endpoint,
        grpc_endpoint=grpc_endpoint,
    )
    root = Path(ctx.project_root)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
    assert _snapshot(root) == (None, None)


def test_missing_endpoint_configuration_also_fails_in_dry_run(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """A plan that cannot name the values it would write is not a plan."""
    ctx = _ctx(
        tmp_path,
        registration_repo,
        mode=ExecutionMode.DRY_RUN,
        http_endpoint=None,
        grpc_endpoint=None,
    )
    result = cp10_mcp_registration(ctx)
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
