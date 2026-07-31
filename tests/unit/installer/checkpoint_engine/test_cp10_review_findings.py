"""CP 10 regression tests for the Codex review findings (AG3-175 R03/R04/R05/R06).

Kept in a dedicated module so each finding stays traceable to the test that pins
it. Every test here fails when the corresponding fix is reverted.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
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
    REASON_REGISTRATION_INCOMPLETE,
)
from agentkit.backend.installer.mcp_conformance import (
    McpConformanceReason,
    McpConformanceResult,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        mcp_registration_probe=None,
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

    assert result.status is CheckpointStatus.FAILED, "an unchanged registration was reported PASS without re-probing"
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
        '{"mcpServers": {"story-knowledge-base": {"command": "someone-elses-tool", "args": ["--serve"]}}}\n',
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
    entry = json.loads((root / _MCP_JSON).read_text(encoding="utf-8"))["mcpServers"][STORY_KNOWLEDGE_BASE_SERVER]
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


# --------------------------------------------------------------------------- #
# R02 — one read per file. Two reads let a concurrent foreign edit bind a NEWER
# before-image to a STALER rendering, after which the pre-write guard found
# before-image and disk in agreement and AUTHORISED the stale overwrite it exists
# to prevent. Codex reproduced it in memory; these tests reproduce it on the real
# handler and assert the honest outcome: the foreign change either survives or the
# run makes zero writes -- never that it silently disappears.
# --------------------------------------------------------------------------- #


def _stale_first_read(monkeypatch: MonkeyPatch, filename: str, stale: bytes) -> dict[str, int]:
    """Make the FIRST read of ``filename`` return stale bytes, later reads the disk.

    This is the only deterministic way to simulate a concurrent foreign writer: it
    stands in for "another process rewrote the file between AK3's two reads".
    """
    real_bytes = Path.read_bytes
    real_text = Path.read_text
    calls = {"n": 0}

    def _first_is_stale(self: Path) -> bool:
        if self.name != filename:
            return False
        calls["n"] += 1
        return calls["n"] == 1

    def _patched_bytes(self: Path) -> bytes:
        if _first_is_stale(self):
            return stale
        return real_bytes(self)

    def _patched_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if _first_is_stale(self):
            return stale.decode("utf-8")
        return real_text(self, *args, **kwargs)

    # BOTH APIs share one counter: a concurrent writer does not care which call
    # AK3 happens to use, and patching only one would let a two-read
    # implementation pass by reading through the unpatched API.
    monkeypatch.setattr(Path, "read_bytes", _patched_bytes)
    monkeypatch.setattr(Path, "read_text", _patched_text)
    return calls


def test_concurrent_foreign_mcp_json_change_is_never_silently_lost(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """A foreign ``.mcp.json`` entry must survive, or the run must write nothing."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    mcp = root / _MCP_JSON

    stale_a = b'{\n  "mcpServers": {\n    "foreign-A": {\n      "command": "a"\n    }\n  }\n}\n'
    current_b = b'{\n  "mcpServers": {\n    "foreign-B": {\n      "command": "b"\n    }\n  }\n}\n'
    mcp.write_bytes(current_b)
    calls = _stale_first_read(monkeypatch, _MCP_JSON, stale_a)

    result = cp10_mcp_registration(ctx)

    assert calls["n"] >= 1, "the .mcp.json read was not exercised"
    on_disk = mcp.read_bytes()
    if result.status is CheckpointStatus.FAILED:
        # Zero writes: the stale snapshot was detected before writing.
        assert on_disk == current_b
    else:
        # Or the write happened from a consistent snapshot and kept the foreign entry.
        assert b"foreign-B" in on_disk
    assert b"foreign-B" in on_disk, "the concurrent foreign .mcp.json entry was silently lost"


def test_concurrent_foreign_codex_change_is_never_silently_lost(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Same invariant for ``.codex/config.toml``.

    Structurally the same defect: ``render_project_codex_config`` used to read the
    file a SECOND time, so the before-image and the rendering could disagree.
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    codex = root / _CODEX_REL
    codex.parent.mkdir(parents=True, exist_ok=True)

    stale_a = b'[hooks.pre_tool_use]\ncommand = "agentkit-hook-codex"\n\n[user.a]\nx = 1\n'
    current_b = b'[hooks.pre_tool_use]\ncommand = "agentkit-hook-codex"\n\n[user.b]\ny = 2\n'
    codex.write_bytes(current_b)
    calls = _stale_first_read(monkeypatch, "config.toml", stale_a)

    result = cp10_mcp_registration(ctx)

    assert calls["n"] >= 1, "the Codex config read was not exercised"
    on_disk = codex.read_bytes()
    if result.status is CheckpointStatus.FAILED:
        assert on_disk == current_b
    assert b"[user.b]" in on_disk, "the concurrent foreign Codex table was silently lost"


def test_phase_two_reads_each_file_exactly_once(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Structural pin: parse, render and before-image share ONE read per file.

    Counted up to the probe, i.e. phase 2/3 only; the deliberate pre-write reread
    happens afterwards and is counted separately.
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    (root / _MCP_JSON).write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (root / _CODEX_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _CODEX_REL).write_bytes(b'[hooks.pre_tool_use]\ncommand = "agentkit-hook-codex"\n')

    real = Path.read_bytes
    counts: dict[str, int] = {_MCP_JSON: 0, "config.toml": 0}

    def _counting(self: Path) -> bytes:
        if self.name in counts:
            counts[self.name] += 1
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", _counting)

    phase_two_counts: dict[str, int] = {}

    def _snapshot_counts(*args: Any, **kwargs: Any) -> Any:
        phase_two_counts.update(counts)
        return _broken_probe()

    monkeypatch.setattr(mcp_registration_mod, "check_mcp_conformance", _snapshot_counts)
    cp10_mcp_registration(ctx)

    assert phase_two_counts[_MCP_JSON] == 1, phase_two_counts
    assert phase_two_counts["config.toml"] == 1, phase_two_counts


# --------------------------------------------------------------------------- #
# R08 — the FAILED-rollback report needs its own regression proof. The
# implementation was already correct; the gap was purely evidential, and an
# untested negative assurance can regress unnoticed.
# --------------------------------------------------------------------------- #


def test_failed_rollback_is_reported_honestly_with_the_residual_state(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Second write fails AND the rollback fails: no clean rollback may be claimed.

    Two simulated I/O failures, both otherwise unreachable. The decisive assertion
    is on the RESIDUAL BYTES, not on the message: that is what makes it a proof
    that the report matches reality rather than a string check.
    """
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    mcp = root / _MCP_JSON
    previous = b'{\n  "mcpServers": {\n    "keep": {\n      "command": "x"\n    }\n  }\n}\n'
    mcp.write_bytes(previous)

    def _second_write_fails(_project_root: Path, _content: str) -> None:
        raise OSError("simulated disk failure on the Codex write")

    real_write_bytes = Path.write_bytes

    def _rollback_fails(self: Path, data: bytes) -> int:
        if self.name == _MCP_JSON:
            raise OSError("simulated disk failure on the rollback")
        return real_write_bytes(self, data)

    monkeypatch.setattr(cp10_mod, "write_codex_config_text", _second_write_fails)
    monkeypatch.setattr(Path, "write_bytes", _rollback_fails)

    result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_REGISTRATION_INCOMPLETE
    detail = result.detail or ""
    assert "ROLLBACK FAILED" in detail, detail
    # The residual state is what the report claims: .mcp.json is NOT the previous
    # content, it carries the newly written registration and must be reconciled.
    residual = mcp.read_bytes()
    assert residual != previous
    assert STORY_KNOWLEDGE_BASE_SERVER.encode() in residual
    assert "must be reconciled by a repeated run" in detail


def test_successful_rollback_does_not_claim_failure(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Counter-probe: the honest wording differs between the two outcomes."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    previous = b'{\n  "mcpServers": {\n    "keep": {\n      "command": "x"\n    }\n  }\n}\n'
    (root / _MCP_JSON).write_bytes(previous)

    def _second_write_fails(_project_root: Path, _content: str) -> None:
        raise OSError("simulated disk failure on the Codex write")

    monkeypatch.setattr(cp10_mod, "write_codex_config_text", _second_write_fails)

    result = cp10_mcp_registration(ctx)

    assert result.reason == REASON_REGISTRATION_INCOMPLETE
    assert "ROLLBACK FAILED" not in (result.detail or "")
    assert "rolled back" in (result.detail or "")
    assert (root / _MCP_JSON).read_bytes() == previous


# --------------------------------------------------------------------------- #
# R09 — a read I/O error must become a NAMED checkpoint result, not a raw
# exception out of the engine. These use a GENUINE read failure (a real Windows
# byte-range share lock via ``msvcrt``), not a patched raise.
# --------------------------------------------------------------------------- #

_WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="share-lock read failure is Windows-specific")


@contextlib.contextmanager
def _share_locked(path: Path) -> Iterator[None]:
    """Hold a real byte-range lock so another handle's read genuinely fails."""
    import msvcrt

    handle = path.open("r+b")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 0x7FFFFFFF)
        try:
            yield
        finally:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 0x7FFFFFFF)
    finally:
        handle.close()


@_WINDOWS_ONLY
def test_locked_mcp_json_is_a_named_result_not_a_raw_exception(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """A genuine share lock on ``.mcp.json`` yields FAILED/configuration_invalid."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    mcp = root / _MCP_JSON
    mcp.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    before = _snapshot(root)

    with _share_locked(mcp):
        result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
    assert "cannot be read" in (result.detail or "")
    assert _snapshot(root) == before


@_WINDOWS_ONLY
def test_locked_codex_config_is_a_named_result_not_a_raw_exception(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo, monkeypatch: MonkeyPatch
) -> None:
    """Same for ``.codex/config.toml``: named result, both files untouched."""
    monkeypatch.setattr(cp10_mod, "_desired_mcp_servers", _conforming_desired)
    ctx = _ctx(tmp_path, registration_repo)
    root = Path(ctx.project_root)
    codex = root / _CODEX_REL
    codex.parent.mkdir(parents=True, exist_ok=True)
    codex.write_bytes(b'[hooks.pre_tool_use]\ncommand = "agentkit-hook-codex"\n')
    before = _snapshot(root)

    with _share_locked(codex):
        result = cp10_mcp_registration(ctx)

    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_CONFIGURATION_INVALID
    assert _snapshot(root) == before


@_WINDOWS_ONLY
def test_cp8_wraps_a_locked_codex_config_in_installation_error(tmp_path: Path) -> None:
    """CP 8's writer promises InstallationError for unreadable configuration.

    It caught only ``CodexConfigError``, so a real share-lock ``OSError`` escaped
    untyped and aborted the engine instead of failing closed with a typed error.
    """
    from agentkit.backend.exceptions import InstallationError
    from agentkit.backend.installer.codex_settings import write_codex_settings

    root = tmp_path / "proj"
    (root / ".codex").mkdir(parents=True)
    codex = root / _CODEX_REL
    codex.write_bytes(b'[hooks.pre_tool_use]\ncommand = "agentkit-hook-codex"\n')
    before = codex.read_bytes()

    with _share_locked(codex), pytest.raises(InstallationError) as exc:
        write_codex_settings(root)

    assert "cannot be read" in str(exc.value)
    assert codex.read_bytes() == before
