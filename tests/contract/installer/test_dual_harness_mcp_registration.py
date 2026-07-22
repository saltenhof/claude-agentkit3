"""Contract tests for dual-harness MCP registration (AG3-175 AC 1–7).

Real boundaries: real writers, real files, real conformance probe (minimal
MCP fixture server). Fakes only at the external process port for the
story-kb command when needed.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints import cp10_mcp as cp10_mod
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import cp10_mcp_registration
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_COMMAND_NOT_FOUND,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_MCP_PROBE_BINDING_MISMATCH,
    REASON_REGISTRATION_INCOMPLETE,
)
from agentkit.backend.installer.mcp_registration import (
    BoundMcpServerRegistration,
    bind_after_probe,
    require_probe_binding,
)
from agentkit.backend.installer.mcp_registration.bound_spec import ProbeBindingError
from agentkit.backend.installer.mcp_registration.dual_write import (
    DualRegistrationError,
    apply_dual_registration_writes,
    prepare_dual_registration,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.vectordb.runtime_binding import McpServerSpec
from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
    load_codex_mcp_document,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_SERVER_ID = "story-knowledge-base"


@pytest.fixture
def registration_repo() -> InMemoryRegistrationRepo:
    """Local fixture — contract tests do not load the unit installer conftest."""
    return InMemoryRegistrationRepo()


@pytest.fixture(autouse=True)
def _stub_vectordb_preflight(monkeypatch: MonkeyPatch) -> None:
    """Offline Weaviate meta/ready probes (contract suite has no live Weaviate)."""
    monkeypatch.setattr(
        cp10_mod,
        "_PREFLIGHT_META_FETCHER",
        lambda host, port, timeout: {"version": "1.24.0", "hostname": str(host)},
    )
    monkeypatch.setattr(
        cp10_mod,
        "_PREFLIGHT_READY_PROBE",
        lambda host, port: True,
    )


def _ctx(
    root: Path,
    registration_repo: InMemoryRegistrationRepo,
    *,
    mode: ExecutionMode = ExecutionMode.REGISTER,
) -> object:
    config = make_config(
        root,
        bundle_store_root=root / "_bundles",
        registration_repo=registration_repo,
        features_vectordb=True,
        features_are=False,
        weaviate_host="weaviate.contract.test",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
    )
    return build_checkpoint_context(config, mode)


def _live_spec(root: Path, *, project_id: str = "P-CONTRACT") -> McpServerSpec:
    """Build a Spec whose command is the real minimal MCP fixture server."""
    return McpServerSpec(
        command=sys.executable,
        args=(str(_MINIMAL_SERVER),),
        cwd=str(root.resolve()),
        env={
            "PROJECT_ID": project_id,
            "WEAVIATE_HOST": "weaviate.contract.test",
            "WEAVIATE_HTTP_PORT": "19903",
            "WEAVIATE_GRPC_PORT": "50051",
            "CONCEPTS_DIR": str(root / "concepts"),
            "STORIES_DIR": str(root / "stories"),
        },
    )


def _force_dual_with_spec(
    monkeypatch: MonkeyPatch, root: Path, spec: McpServerSpec
) -> None:
    """Drive the dual-harness path with a fixture Spec (real probe boundary)."""

    def _build(_context: object) -> McpServerSpec:
        return spec

    monkeypatch.setattr(cp10_mod, "build_story_kb_spec", _build)
    # Ensure dual path is taken (production desired builder identity).
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", cp10_mod._DESIRED_MCP_SERVERS_IMPL)


def _bytes_or_missing(path: Path) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    return path.read_bytes()


def test_ac1_both_harnesses_registered_idempotent_foreign_preserved(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    # Foreign Claude entry.
    mcp_path = root / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign-claude": {
                        "type": "stdio",
                        "command": "echo",
                        "args": [],
                    }
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # Foreign Codex tables.
    codex_dir = root / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        "[hooks.pre_tool_use]\n"
        'command = "agentkit-hook-codex"\n'
        "\n"
        "[mcp_servers.foreign-codex]\n"
        'command = "echo"\n'
        'args = ["x"]\n'
        'cwd = "/tmp"\n',
        encoding="utf-8",
    )
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)
    ctx = _ctx(root, registration_repo)
    first = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert first.status is CheckpointStatus.UPDATED, first.detail
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "foreign-claude" in mcp["mcpServers"]
    assert _SERVER_ID in mcp["mcpServers"]
    codex = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert codex["hooks"]["pre_tool_use"]["command"] == "agentkit-hook-codex"
    assert "foreign-codex" in codex["mcp_servers"]
    assert _SERVER_ID in codex["mcp_servers"]
    before_mcp = mcp_path.read_bytes()
    before_codex = (codex_dir / "config.toml").read_bytes()
    second = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert second.status is CheckpointStatus.PASS
    assert mcp_path.read_bytes() == before_mcp
    assert (codex_dir / "config.toml").read_bytes() == before_codex


def test_ac2_fieldwise_value_equality_claude_and_codex(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    spec = _live_spec(root, project_id="AC2-PID")
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED, result.detail
    claude = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        _SERVER_ID
    ]
    codex = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))[
        "mcp_servers"
    ][_SERVER_ID]
    assert claude["command"] == codex["command"] == spec.command
    assert claude["args"] == codex["args"] == list(spec.args)
    assert claude["cwd"] == codex["cwd"] == spec.cwd
    assert claude["env"] == codex["env"] == dict(spec.env)
    assert codex["required"] is True
    assert claude["env"]["PROJECT_ID"] == "AC2-PID"
    assert claude["env"]["WEAVIATE_HOST"] == "weaviate.contract.test"


def test_ac3_isolated_codex_home_and_second_project_invisible(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    userspace = tmp_path / "CODEX_HOME"
    userspace.mkdir()
    sentinel = userspace / "config.toml"
    sentinel.write_text("# must stay\n", encoding="utf-8")
    sentinel_before = sentinel.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(userspace))
    root = tmp_path / "proj-a"
    root.mkdir()
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED
    assert sentinel.read_bytes() == sentinel_before
    assert not any(userspace.rglob("story-knowledge-base*"))
    other = tmp_path / "proj-b"
    other.mkdir()
    loaded, _, err = load_codex_mcp_document(other)
    assert err is None
    assert loaded == {}
    assert not (other / ".codex" / "config.toml").exists()


def test_ac4_failed_conformance_writes_nothing(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    original = b'{"mcpServers":{"foreign":{"type":"stdio","command":"x"}}}\n'
    mcp_path.write_bytes(original)
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_original = b'[hooks.pre_tool_use]\ncommand = "keep"\n'
    codex_path.write_bytes(codex_original)
    bad = McpServerSpec(
        command="definitely-missing-mcp-binary-xyz",
        args=(),
        cwd=str(root),
        env={
            "PROJECT_ID": "P",
            "WEAVIATE_HOST": "h",
            "WEAVIATE_HTTP_PORT": "1",
            "WEAVIATE_GRPC_PORT": "2",
        },
    )
    _force_dual_with_spec(monkeypatch, root, bad)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_COMMAND_NOT_FOUND
    assert mcp_path.read_bytes() == original
    assert codex_path.read_bytes() == codex_original


def test_ac5_real_probe_then_write_uses_probed_spec(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """AC 5: real AG3-164 probe path; written files match the probed Spec."""
    root = tmp_path / "proj"
    root.mkdir()
    spec = _live_spec(root, project_id="PROBE-BOUND")
    probed_cmds: list[object] = []
    real_check = cp10_mod.check_mcp_conformance

    def _track(cmd: object, **kwargs: object) -> object:
        probed_cmds.append(cmd)
        return real_check(cmd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED, result.detail
    assert probed_cmds, "AG3-164 conformance must run on the REGISTER path"
    probed = probed_cmds[0]
    assert probed.command == spec.command  # type: ignore[attr-defined]
    assert list(probed.args) == list(spec.args)  # type: ignore[attr-defined]
    assert probed.cwd == spec.cwd  # type: ignore[attr-defined]
    assert dict(probed.env or {}) == dict(spec.env)  # type: ignore[attr-defined]

    claude = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        _SERVER_ID
    ]
    codex = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))[
        "mcp_servers"
    ][_SERVER_ID]
    assert claude["command"] == codex["command"] == spec.command
    assert claude["args"] == codex["args"] == list(spec.args)
    assert claude["cwd"] == codex["cwd"] == spec.cwd
    assert claude["env"] == codex["env"] == dict(spec.env)
    assert codex["required"] is True


def test_ac5_post_probe_mutation_blocks_write_on_real_path(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """AC 5: after a real probe, mutating Spec fields refuses both writes."""
    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    mcp_original = b'{"mcpServers":{"foreign":{"type":"stdio","command":"x"}}}\n'
    mcp_path.write_bytes(mcp_original)
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_original = b'[hooks.pre_tool_use]\ncommand = "keep"\n'
    codex_path.write_bytes(codex_original)

    spec = _live_spec(root, project_id="BOUND")
    # Real probe first (via AG3-164), then return a forged bound registration
    # whose digest no longer matches the Spec about to be written.
    real_check = cp10_mod.check_mcp_conformance
    real_bind = cp10_mod.bind_after_probe

    def _probe_ok(cmd: object, **kwargs: object) -> object:
        return real_check(cmd, **kwargs)  # type: ignore[arg-type]

    def _forge_bind(server_id: str, probed_spec: McpServerSpec) -> BoundMcpServerRegistration:
        honest = real_bind(server_id, probed_spec)
        mutated = McpServerSpec(
            command=probed_spec.command,
            args=probed_spec.args,
            cwd=probed_spec.cwd,
            env={**dict(probed_spec.env), "PROJECT_ID": "OTHER"},
        )
        return BoundMcpServerRegistration(
            server_id=server_id,
            spec=mutated,
            probe_digest=honest.probe_digest,
        )

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _probe_ok)
    monkeypatch.setattr(cp10_mod, "bind_after_probe", _forge_bind)
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_PROBE_BINDING_MISMATCH
    assert mcp_path.read_bytes() == mcp_original
    assert codex_path.read_bytes() == codex_original

    # Field matrix: endpoint / cwd / missing env also diverge the digest.
    honest = bind_after_probe(_SERVER_ID, spec)
    for bad_spec in (
        McpServerSpec(command=spec.command, args=(), cwd="", env=dict(spec.env)),
        McpServerSpec(
            command=spec.command,
            args=(),
            cwd=spec.cwd,
            env={k: v for k, v in spec.env.items() if k != "WEAVIATE_HOST"},
        ),
        McpServerSpec(
            command=spec.command,
            args=(),
            cwd="/not/the/project",
            env={**dict(spec.env), "WEAVIATE_HOST": "other.endpoint.test"},
        ),
    ):
        forged = BoundMcpServerRegistration(
            server_id=_SERVER_ID,
            spec=bad_spec,
            probe_digest=honest.probe_digest,
        )
        with pytest.raises(ProbeBindingError) as excinfo:
            require_probe_binding(forged)
        assert excinfo.value.reason == REASON_MCP_PROBE_BINDING_MISMATCH


def test_ac6_parse_conflict_null_writes(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    mcp_original = b'{"mcpServers":{"foreign":{"type":"stdio","command":"x"}}}\n'
    mcp_path.write_bytes(mcp_original)
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    # Non-table mcp_servers — fail-closed before any write.
    codex_original = b"mcp_servers = 42\n"
    codex_path.write_bytes(codex_original)
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)
    # Skip live probe: configuration must fail first.
    def _no_probe(*_a: object, **_k: object) -> Any:
        raise AssertionError("conformance must not start on invalid codex config")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _no_probe)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert mcp_path.read_bytes() == mcp_original
    assert codex_path.read_bytes() == codex_original


def test_ac6_io_error_after_first_write_rolls_back(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    mcp_original = b'{"mcpServers":{}}\n'
    mcp_path.write_bytes(mcp_original)
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_original = b"[hooks.pre_tool_use]\ncommand = \"keep\"\n"
    codex_path.write_bytes(codex_original)

    spec = _live_spec(root)
    bound = bind_after_probe(_SERVER_ID, spec)
    plan = prepare_dual_registration(
        project_root=root,
        bound=bound,
        existing_mcp_json_root=json.loads(mcp_original.decode("utf-8")),
        mcp_json_before=mcp_original,
        other_mcp_json_servers={},
        mcp_json_renderer=lambda r: json.dumps(r, indent=2, sort_keys=True) + "\n",
    )
    assert plan.mcp_json_changed or plan.codex_changed

    from agentkit.backend.installer.mcp_registration import dual_write as dual_mod

    calls: list[Path] = []
    original = dual_mod.atomic_write_text

    def _flaky(path: Path, content: str, **kwargs: object) -> None:
        calls.append(path)
        if len(calls) == 1:
            return original(path, content, **kwargs)  # type: ignore[arg-type]
        raise OSError("simulated I/O failure on second write")

    monkeypatch.setattr(dual_mod, "atomic_write_text", _flaky)
    with pytest.raises(DualRegistrationError) as excinfo:
        apply_dual_registration_writes(plan)
    assert excinfo.value.reason == REASON_REGISTRATION_INCOMPLETE
    # Best-effort rollback restored before-images.
    assert mcp_path.read_bytes() == mcp_original
    assert codex_path.read_bytes() == codex_original

    # Retry converges idempotently with healthy writer.
    monkeypatch.setattr(dual_mod, "atomic_write_text", original)
    # Re-bind with live probe path through CP10.
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status in (CheckpointStatus.CREATED, CheckpointStatus.UPDATED)
    assert _SERVER_ID in json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]
    assert _SERVER_ID in tomllib.loads(codex_path.read_text(encoding="utf-8"))["mcp_servers"]


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe",
        b"mcp_servers = 1\n",
        b'[mcp_servers.story-knowledge-base]\ncommand = 9\n',
        b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nargs = {}\n',
        b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nenv = []\n',
        b'[mcp_servers.story-knowledge-base]\ncommand = "c"\nrequired = 1\n',
        b'[mcp_servers.story-knowledge-base]\ncommand = "c"\ncwd = 99\n',
        # Duplicate key in same table.
        b'[mcp_servers.foreign]\ncommand = "a"\ncommand = "b"\n',
        # Own name occupied by non-table (fremd belegt).
        b'[mcp_servers]\nstory-knowledge-base = "taken"\n',
    ],
)
def test_ac7_toml_matrix_byte_identical_both_files(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
    payload: bytes,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    mcp_original = b'{"mcpServers":{"foreign":{"type":"stdio","command":"x"}}}\n'
    mcp_path.write_bytes(mcp_original)
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_path.write_bytes(payload)
    codex_before = payload
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)

    def _track(*_a: object, **_k: object) -> Any:
        raise AssertionError("conformance must not start on invalid TOML")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert mcp_path.read_bytes() == mcp_original
    assert codex_path.read_bytes() == codex_before


def test_ac7_symlink_escape_byte_identical_both_files(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """AC 7: symlink/junction out of project root → named FAILED, no writes."""
    import os

    root = tmp_path / "proj"
    root.mkdir()
    mcp_path = root / ".mcp.json"
    mcp_original = b'{"mcpServers":{}}\n'
    mcp_path.write_bytes(mcp_original)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_toml = outside / "config.toml"
    outside_toml.write_text("x = 1\n", encoding="utf-8")
    outside_before = outside_toml.read_bytes()
    try:
        os.symlink(outside, root / ".codex", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink not available: {exc}")
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)

    def _track(*_a: object, **_k: object) -> Any:
        raise AssertionError("conformance must not start on path escape")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID
    assert mcp_path.read_bytes() == mcp_original
    assert outside_toml.read_bytes() == outside_before


def test_ac7_positive_preserves_unknown_harness_fields(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_path.write_text(
        "[mcp_servers.foreign]\n"
        'command = "echo"\n'
        'args = []\n'
        'cwd = "/tmp"\n'
        "experimental_flag = true\n"
        "\n"
        "[top_secret]\n"
        "token = \"keep\"\n",
        encoding="utf-8",
    )
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED, result.detail
    data = tomllib.loads(codex_path.read_text(encoding="utf-8"))
    assert data["top_secret"]["token"] == "keep"
    assert data["mcp_servers"]["foreign"]["experimental_flag"] is True
    assert data["mcp_servers"]["foreign"]["command"] == "echo"


def test_ac7_dual_path_preserves_datetime_and_aot(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """R01 regression on the real dual CP10 path (not unit-only writer)."""
    root = tmp_path / "proj"
    root.mkdir()
    codex_path = root / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_path.write_text(
        'released = 1979-05-27T07:32:00Z\n'
        'note = "\\b"\n'
        "\n"
        "[[plugins]]\n"
        'name = "alpha"\n',
        encoding="utf-8",
    )
    before_note = tomllib.loads('note = "\\b"\n')["note"]
    spec = _live_spec(root)
    _force_dual_with_spec(monkeypatch, root, spec)
    result = cp10_mcp_registration(_ctx(root, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED, result.detail
    text = codex_path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["plugins"] == [{"name": "alpha"}]
    assert data["note"] == before_note
    assert "1979-05-27T07:32:00Z" in text
    assert "[[plugins]]" in text
    assert _SERVER_ID in data["mcp_servers"]
