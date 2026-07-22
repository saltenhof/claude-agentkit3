"""CP 10 registration-after-conformance tests (AG3-164 rework)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints import cp10_mcp as cp10_mod
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import (
    cp10_mcp_registration,
    cp10c_are_scope_validation,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
    run_checkpoint_install,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    DRY_RUN_PLAN_MARKER,
    REASON_MCP_COMMAND_NOT_FOUND,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_MCP_PROCESS_EXITED,
    REASON_MCP_PROTOCOL_ERROR,
    REASON_MCP_TOOLS_LIST_EMPTY,
    REASON_PLANNED_NO_MUTATION,
    REASON_VECTORDB_DISABLED,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.strict_json import (
    reject_duplicate_object_pairs,
    reject_non_json_constant,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_BAD_SERVERS = _REPO_ROOT / "tests" / "fixtures" / "mcp_bad_servers.py"


def _use_real_mcp_conformance(monkeypatch: MonkeyPatch) -> None:
    """Undo the unit-test autouse stub; exercise the real probe fail-closed."""
    from agentkit.backend.installer.mcp_conformance import check_mcp_conformance

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", check_mcp_conformance)


def _ctx(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    *,
    features_are: bool = False,
    features_vectordb: bool = False,
    mode: ExecutionMode = ExecutionMode.REGISTER,
) -> object:
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_are=features_are,
        features_vectordb=features_vectordb,
    )
    return build_checkpoint_context(config, mode)


def _desired_from_specs(specs: dict[str, dict[str, Any]]) -> Any:
    def _builder(_context: object) -> dict[str, object]:
        return dict(specs)

    return _builder


def _good_entry() -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(_MINIMAL_SERVER)],
    }


def test_cp10_never_skips_for_vectordb_optional_off(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AG3-176 AC6: no SKIPPED/vectordb_disabled — VectorDB is mandatory."""
    ctx = _ctx(tmp_path, registration_repo, features_are=False, features_vectordb=False)
    assert ctx.vectordb_enabled is True  # type: ignore[attr-defined]
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is not CheckpointStatus.SKIPPED
    assert result.reason != REASON_VECTORDB_DISABLED


def test_cp10_are_missing_command_fails_without_write(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    _use_real_mcp_conformance(monkeypatch)
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
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
        cp05_pipeline_config,
    )

    cp05_pipeline_config(ctx)
    # AG3-176: VectorDB mandatory — dual-harness probes story-kb first.
    # Without a runnable MCP command the registration fails closed and
    # writes nothing (same fail-closed class as the former ARE-only case).
    result = cp10_mcp_registration(ctx)
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_COMMAND_NOT_FOUND
    assert not (root / ".mcp.json").exists()


def test_cp10_failure_preserves_existing_mcp_json_bytes(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
    """AC2 regression: existing .mcp.json remains byte-identical on FAILED."""
    mcp_path = tmp_path / ".mcp.json"
    original = (
        '{\n  "mcpServers": {\n    "foreign": {"type": "stdio", "command": "x"}\n  }\n}\n'
    )
    mcp_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs(
            {
                "broken": {
                    "type": "stdio",
                    "command": "definitely-missing-mcp-binary",
                    "args": [],
                }
            }
        ),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert mcp_path.read_text(encoding="utf-8") == original


def test_cp10_are_full_install_fails_honestly(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
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
    result = run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert result.success is False
    mcp_path = root / ".mcp.json"
    if mcp_path.is_file():
        servers = json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers", {})
        assert "are-mcp" not in servers


def test_cp10_negative_process_exited(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
    specs = {
        "die-server": {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(_BAD_SERVERS), "die"],
        }
    }
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs))
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_PROCESS_EXITED
    assert not (tmp_path / ".mcp.json").exists()


def test_cp10_negative_protocol_error(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
    specs = {
        "noise-server": {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(_BAD_SERVERS), "noise"],
        }
    }
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs))
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_PROTOCOL_ERROR
    assert not (tmp_path / ".mcp.json").exists()


def test_cp10_negative_empty_tools(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
    specs = {
        "empty-server": {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(_BAD_SERVERS), "empty_tools"],
        }
    }
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs))
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_TOOLS_LIST_EMPTY
    assert not (tmp_path / ".mcp.json").exists()


def test_cp10_positive_registers_real_mcp_server(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    entry = _good_entry()
    specs = {"test-mcp": entry}
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs))
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED
    mcp_path = tmp_path / ".mcp.json"
    assert mcp_path.is_file()
    servers = json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]
    assert servers["test-mcp"] == entry


def test_cp10_idempotent_rerun_is_pass(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P1-2: second REGISTER after successful conformance is PASS, no mutation."""
    entry = _good_entry()
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": entry}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    first = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert first.status is CheckpointStatus.CREATED
    mcp_path = tmp_path / ".mcp.json"
    before = mcp_path.read_bytes()
    second = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert second.status is CheckpointStatus.PASS
    assert mcp_path.read_bytes() == before


def test_cp10_conformance_applies_to_two_server_definitions(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    _use_real_mcp_conformance(monkeypatch)
    good = _good_entry()
    bad = {
        "type": "stdio",
        "command": "definitely-not-a-real-mcp-binary-xyz",
        "args": [],
    }
    specs = {"alpha-mcp": good, "beta-mcp": bad}
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs))
    ctx = _ctx(tmp_path, registration_repo, features_are=True, features_vectordb=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MCP_COMMAND_NOT_FOUND
    assert "beta-mcp" in (result.detail or "")
    assert not (tmp_path / ".mcp.json").exists()

    specs_ok = {"alpha-mcp": good, "gamma-mcp": {**good, "env": {"X": "1"}}}
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _desired_from_specs(specs_ok))
    result_ok = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result_ok.status is CheckpointStatus.CREATED
    servers = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]
    assert set(servers) == {"alpha-mcp", "gamma-mcp"}


def test_cp10_preserves_foreign_entries_on_successful_register(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign-tool": {
                        "type": "stdio",
                        "command": "echo",
                        "args": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    entry = _good_entry()
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": entry}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.UPDATED
    servers = json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]
    assert "foreign-tool" in servers
    assert "owned-mcp" in servers


def test_cp10_dry_run_and_verify_never_start_processes(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P0-4: dry-run/verify must not invoke the live conformance probe."""
    calls: list[str] = []

    def _boom(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run in dry-run/verify")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _boom)
    # AG3-176: dual-write path needs a valid project binding (strict project.yaml).
    cfg_dir = tmp_path / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "project.yaml").write_text(
        "project_key: demo\n"
        "project_name: demo\n"
        "repositories:\n  - name: app\n    path: .\n"
        "pipeline:\n"
        "  config_version: '3.0'\n"
        "  features:\n    multi_llm: false\n    vectordb: true\n"
        "  sonarqube: {available: false, enabled: false}\n"
        "  ci: {available: false, enabled: false}\n"
        "  vectordb: {host: weaviate.test.local, port: 19903, grpc_port: 50051}\n"
        "concepts_dir: concepts\n"
        "wiki_stories_dir: stories\n",
        encoding="utf-8",
    )
    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        calls.clear()
        ctx = _ctx(tmp_path, registration_repo, features_are=True, mode=mode)
        result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
        assert calls == []
        assert result.status in (
            CheckpointStatus.CREATED,
            CheckpointStatus.UPDATED,
            CheckpointStatus.PASS,
        )
        if mode is ExecutionMode.DRY_RUN:
            assert result.reason == REASON_PLANNED_NO_MUTATION
            assert DRY_RUN_PLAN_MARKER in (result.detail or "")
        assert not (tmp_path / ".mcp.json").exists()


def _assert_config_failed_byte_identical(
    *,
    mcp_path: Path,
    original: bytes,
    result: object,
    monkeypatch: MonkeyPatch,
    conformance_calls: list[str],
) -> None:
    """Shared assertions for invalid existing ``.mcp.json`` (Review-8 P0-1)."""
    assert result.status is CheckpointStatus.FAILED  # type: ignore[attr-defined]
    assert result.reason == REASON_MCP_CONFIGURATION_INVALID  # type: ignore[attr-defined]
    assert mcp_path.read_bytes() == original
    assert conformance_calls == [], "conformance must not start on invalid config"


def test_cp10_rejects_duplicate_top_level_names_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Duplicate top-level names → FAILED, byte-identical, no conformance."""
    mcp_path = tmp_path / ".mcp.json"
    # Two ``mcpServers`` keys: last-wins would drop the first foreign entry.
    original_text = (
        '{\n'
        '  "mcpServers": {"foreign-a": {"type": "stdio", "command": "a"}},\n'
        '  "mcpServers": {"foreign-b": {"type": "stdio", "command": "b"}}\n'
        '}\n'
    )
    original = original_text.encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_rejects_duplicate_nested_names_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Nested duplicate object names → FAILED without rewrite."""
    mcp_path = tmp_path / ".mcp.json"
    original_text = (
        '{\n'
        '  "mcpServers": {\n'
        '    "foreign": {\n'
        '      "type": "stdio",\n'
        '      "command": "x",\n'
        '      "command": "y"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    original = original_text.encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_rejects_non_json_constants_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """NaN / Infinity in existing file → FAILED; must not re-emit NaN."""
    mcp_path = tmp_path / ".mcp.json"
    original_text = (
        '{\n'
        '  "mcpServers": {\n'
        '    "foreign": {"type": "stdio", "command": "x", "timeout": NaN}\n'
        "  }\n"
        "}\n"
    )
    original = original_text.encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    for mode in (
        ExecutionMode.REGISTER,
        ExecutionMode.DRY_RUN,
        ExecutionMode.VERIFY,
    ):
        mcp_path.write_bytes(original)
        calls.clear()
        ctx = _ctx(tmp_path, registration_repo, features_are=True, mode=mode)
        result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
        _assert_config_failed_byte_identical(
            mcp_path=mcp_path,
            original=original,
            result=result,
            monkeypatch=monkeypatch,
            conformance_calls=calls,
        )


def test_cp10_rejects_overflow_non_finite_float_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Oversized JSON numbers that decode to inf must not pass the loader."""
    mcp_path = tmp_path / ".mcp.json"
    original_text = (
        '{\n'
        '  "mcpServers": {\n'
        '    "foreign": {"type": "stdio", "command": "x", "timeout": 1e400}\n'
        "  }\n"
        "}\n"
    )
    original = original_text.encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_rejects_non_object_root_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Array root must not be silently replaced by a new object root."""
    mcp_path = tmp_path / ".mcp.json"
    original = b"[]\n"
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_rejects_non_object_mcp_servers_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Numeric ``mcpServers`` must not be silently replaced by an object."""
    mcp_path = tmp_path / ".mcp.json"
    original_text = '{\n  "mcpServers": 42\n}\n'
    original = original_text.encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_successful_write_is_strict_reloadable(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Every successfully written ``.mcp.json`` must pass the strict loader."""
    entry = _good_entry()
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": entry}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED
    mcp_path = tmp_path / ".mcp.json"
    root, err = cp10_mod._load_target_mcp_json(mcp_path)
    assert err is None
    assert root is not None
    servers = root.get("mcpServers")
    assert isinstance(servers, dict)
    assert servers["owned-mcp"] == entry
    # Standards-strict decoder (no NaN) must also accept the written bytes.
    reloaded = json.loads(
        mcp_path.read_text(encoding="utf-8"),
        parse_constant=reject_non_json_constant,
        object_pairs_hook=reject_duplicate_object_pairs,
    )
    assert isinstance(reloaded, dict)


def test_cp10_rejects_non_object_server_entry_scalar_and_array(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P0-1: each mcpServers value must be an object (not scalar/array/null)."""
    payloads = (
        b'{"mcpServers":{"foreign":7}}\n',
        b'{"mcpServers":{"foreign":[]}}\n',
        b'{"mcpServers":{"foreign":null}}\n',
        b'{"mcpServers":{"foreign":"stdio"}}\n',
    )
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    mcp_path = tmp_path / ".mcp.json"
    for original in payloads:
        for mode in (
            ExecutionMode.REGISTER,
            ExecutionMode.DRY_RUN,
            ExecutionMode.VERIFY,
        ):
            mcp_path.write_bytes(original)
            calls.clear()
            ctx = _ctx(tmp_path, registration_repo, features_are=True, mode=mode)
            result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
            _assert_config_failed_byte_identical(
                mcp_path=mcp_path,
                original=original,
                result=result,
                monkeypatch=monkeypatch,
                conformance_calls=calls,
            )


def test_cp10_rejects_invalid_utf8_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P1-1: invalid UTF-8 → named FAILED, byte-identical, no process start."""
    mcp_path = tmp_path / ".mcp.json"
    original = b'{"mcpServers":{"foreign":{"type":"stdio","command":"\xff"}}}\n'
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )
    assert "UTF-8" in (result.detail or "")


def test_cp10_rejects_post_decode_mid_depth_nesting_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P1-1 (review-10): loads succeeds, former recursive walk would fail.

    Depth ~700 is below the C decoder RecursionError zone but above the old
    recursive-predicate stack limit (~500). Control ``json.loads`` with the
    strict hooks must succeed; the loader must still return named FAILED in
    every mode without mutation or process start.
    """
    depth = 700
    nested = "[" * depth + "0" + "]" * depth
    original_text = (
        "{\n"
        '  "mcpServers": {\n'
        '    "foreign": {\n'
        '      "type": "stdio",\n'
        '      "command": "x",\n'
        f'      "meta": {nested}\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    original = original_text.encode("utf-8")
    # Control oracle: decoder path that previously left post-decode walk exposed.
    control = json.loads(
        original_text,
        parse_constant=reject_non_json_constant,
        object_pairs_hook=reject_duplicate_object_pairs,
    )
    assert isinstance(control, dict)

    mcp_path = tmp_path / ".mcp.json"
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    for mode in (
        ExecutionMode.REGISTER,
        ExecutionMode.DRY_RUN,
        ExecutionMode.VERIFY,
    ):
        mcp_path.write_bytes(original)
        calls.clear()
        ctx = _ctx(tmp_path, registration_repo, features_are=True, mode=mode)
        result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
        _assert_config_failed_byte_identical(
            mcp_path=mcp_path,
            original=original,
            result=result,
            monkeypatch=monkeypatch,
            conformance_calls=calls,
        )
        assert "nesting" in (result.detail or "").lower()


def test_cp10_rejects_decoder_stack_overflow_nesting_without_mutation(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """Decoder-zone RecursionError still maps to mcp_configuration_invalid."""
    mcp_path = tmp_path / ".mcp.json"
    depth = 100_000
    original = ("[" * depth + "0" + "]" * depth).encode("utf-8")
    mcp_path.write_bytes(original)
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    ctx = _ctx(tmp_path, registration_repo, features_are=True)
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    _assert_config_failed_byte_identical(
        mcp_path=mcp_path,
        original=original,
        result=result,
        monkeypatch=monkeypatch,
        conformance_calls=calls,
    )


def test_cp10_rejects_lone_surrogates_in_key_and_value(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: MonkeyPatch,
) -> None:
    """P1-1: isolated UTF-16 surrogates rejected like the wire loader."""
    payloads = (
        b'{"mcpServers":{"\\ud800":{"type":"stdio","command":"x"}}}\n',
        b'{"mcpServers":{"foreign":{"type":"stdio","command":"\\ud800"}}}\n',
    )
    calls: list[str] = []

    def _track(_cmd: object, **_kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("conformance must not run")

    monkeypatch.setattr(cp10_mod, "check_mcp_conformance", _track)
    monkeypatch.setattr(
        cp10_mod,
        "_desired_mcp_servers",
        _desired_from_specs({"owned-mcp": _good_entry()}),
    )
    mcp_path = tmp_path / ".mcp.json"
    for original in payloads:
        mcp_path.write_bytes(original)
        calls.clear()
        ctx = _ctx(tmp_path, registration_repo, features_are=True)
        result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
        _assert_config_failed_byte_identical(
            mcp_path=mcp_path,
            original=original,
            result=result,
            monkeypatch=monkeypatch,
            conformance_calls=calls,
        )
        assert "surrogate" in (result.detail or "").lower()


def test_cp10c_existing_invalid_mcp_json_fails_in_readonly_modes(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """P1-2: present invalid .mcp.json fails CP10c in DRY_RUN and VERIFY."""
    mcp_path = tmp_path / ".mcp.json"
    original = b'{"mcpServers":7}\n'
    mcp_path.write_bytes(original)
    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        mcp_path.write_bytes(original)
        config = make_config(
            tmp_path,
            bundle_store_root=tmp_path / "b",
            registration_repo=registration_repo,
            features_are=True,
            are_module_scope_map={"scope-x": "app"},
            repositories=[{"name": "app", "path": ".", "are_scope": "scope-x"}],
        )
        ctx = build_checkpoint_context(config, mode)
        result = cp10c_are_scope_validation(ctx)
        assert result.status is CheckpointStatus.FAILED, mode
        assert result.reason == REASON_MCP_CONFIGURATION_INVALID, mode
        assert mcp_path.read_bytes() == original

