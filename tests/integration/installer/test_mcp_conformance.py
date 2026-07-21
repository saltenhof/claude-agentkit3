"""Integration: real-subprocess MCP conformance + official SDK interop."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints import cp10 as cp10_mod
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import cp10_mcp_registration
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.mcp_conformance import (
    McpServerCommand,
    check_mcp_conformance,
)
from agentkit.backend.installer.registration import CheckpointStatus

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_OFFICIAL_SDK_SERVER = _REPO_ROOT / "tests" / "fixtures" / "official_mcp_sdk_server.py"


def test_integration_check_mcp_conformance_against_real_server() -> None:
    result = check_mcp_conformance(
        McpServerCommand(
            command=sys.executable,
            args=[str(_MINIMAL_SERVER)],
        ),
        timeout_seconds=15.0,
    )
    assert result.ok is True
    assert "ping" in result.tool_names


def test_integration_official_mcp_sdk_server() -> None:
    """Required interop against the official MCP Python SDK stdio server.

    ``mcp`` is a declared runtime dependency and the hard contract oracle for
    payload validation. Missing import must fail the suite, not skip.
    """
    import mcp  # noqa: F401 — hard runtime requirement; ImportError fails the test

    result = check_mcp_conformance(
        McpServerCommand(
            command=sys.executable,
            args=[str(_OFFICIAL_SDK_SERVER)],
        ),
        timeout_seconds=45.0,
    )
    assert result.ok is True, result.detail
    assert "ping" in result.tool_names


def test_integration_cp10_registers_only_after_real_handshake(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    registration_repo = InMemoryRegistrationRepo()
    entry = {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(_MINIMAL_SERVER)],
    }

    def _desired(_ctx: object) -> dict[str, object]:
        return {"integration-mcp": entry}

    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired)  # type: ignore[attr-defined]
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "bundles",
        registration_repo=registration_repo,
        features_are=True,
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    result = cp10_mcp_registration(ctx)
    assert result.status is CheckpointStatus.CREATED
    written = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert written["mcpServers"]["integration-mcp"] == entry
