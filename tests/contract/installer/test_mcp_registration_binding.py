"""Contract: the one-spec binding across both harness formats (AG3-175 AC 2/5).

Pins the stable cross-format contract: the SAME rendered spec appears field-wise
value-equal in ``.mcp.json`` and ``.codex/config.toml``, and a spec changed after
the conformance probe can never be written.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from pathlib import Path

import pytest

from agentkit.backend.core_types.mcp_server_registration import (
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    McpServerRegistrationError,
)
from agentkit.backend.installer.codex_settings import CODEX_HOOK_COMMAND
from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    ProbedRegistration,
    RegistrationBeforeImage,
    RenderedRegistration,
    build_registration_env,
    desired_server_from_spec,
    render_mcp_json_text,
    resolve_story_knowledge_base_command,
)
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    render_codex_config,
)

_PROJECT = "C:/projects/demo"
_HTTP = "https://weaviate.internal:9903"
_GRPC = "weaviate.internal:50051"

#: Fields whose VALUES must be identical in both formats. ``type`` exists only in
#: ``.mcp.json`` and ``required`` only in the Codex table -- both are
#: format-specific and deliberately excluded from the equality set.
_SHARED_FIELDS = ("command", "args", "cwd", "env")


def _desired() -> object:
    env = build_registration_env(
        project_id="DEMO",
        weaviate_http_endpoint=_HTTP,
        weaviate_grpc_endpoint=_GRPC,
        concepts_dir=f"{_PROJECT}/concepts",
        stories_dir=f"{_PROJECT}/stories",
    )
    binding = RuntimeBinding.from_env(
        env,
        command=resolve_story_knowledge_base_command(),
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd=_PROJECT,
    )
    return desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, binding.spec)


def _both_entries() -> tuple[dict[str, object], dict[str, object]]:
    server = _desired()
    mcp_text, _ = render_mcp_json_text({}, (server,))  # type: ignore[arg-type]
    codex_text = render_codex_config(
        None,
        hook_command=CODEX_HOOK_COMMAND,
        project_root=Path(_PROJECT),
        servers=(server,),  # type: ignore[arg-type]
    )
    mcp_entry = json.loads(mcp_text)["mcpServers"][STORY_KNOWLEDGE_BASE_SERVER]
    codex_entry = tomllib.loads(codex_text)["mcp_servers"][STORY_KNOWLEDGE_BASE_SERVER]
    return mcp_entry, codex_entry


# --------------------------------------------------------------------------- #
# AC 2 — field-wise value equality between the two formats
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", _SHARED_FIELDS)
def test_shared_field_is_value_equal_in_both_formats(field: str) -> None:
    mcp_entry, codex_entry = _both_entries()
    assert mcp_entry[field] == codex_entry[field], field


def test_env_carries_project_id_and_both_endpoints_in_both_formats() -> None:
    mcp_entry, codex_entry = _both_entries()
    for entry in (mcp_entry, codex_entry):
        env = entry["env"]
        assert isinstance(env, dict)
        assert set(env) == set(REGISTERED_ENV_KEYS)
        assert env["PROJECT_ID"] == "DEMO"
        assert env["WEAVIATE_HTTP_ENDPOINT"] == _HTTP
        assert env["WEAVIATE_GRPC_ENDPOINT"] == _GRPC


def test_codex_entry_declares_required_true() -> None:
    """FK-76 §76.5.4: the Codex table carries ``required = true``."""
    _, codex_entry = _both_entries()
    assert codex_entry["required"] is True


def test_mcp_json_entry_declares_the_stdio_transport() -> None:
    mcp_entry, _ = _both_entries()
    assert mcp_entry["type"] == "stdio"


def test_format_specific_fields_do_not_leak_across_formats() -> None:
    mcp_entry, codex_entry = _both_entries()
    assert "required" not in mcp_entry
    assert "type" not in codex_entry


def test_registered_args_name_the_executable_entry_point() -> None:
    """The registered module must be the stdio entry point, not the library."""
    mcp_entry, codex_entry = _both_entries()
    assert mcp_entry["args"] == ["-m", "agentkit.backend.vectordb.engine"]
    assert codex_entry["args"] == ["-m", "agentkit.backend.vectordb.engine"]


def test_cwd_is_the_project_root_in_both_formats() -> None:
    mcp_entry, codex_entry = _both_entries()
    assert mcp_entry["cwd"] == _PROJECT
    assert codex_entry["cwd"] == _PROJECT


# --------------------------------------------------------------------------- #
# AC 5 — the digest binding
# --------------------------------------------------------------------------- #


def _rendered() -> RenderedRegistration:
    server = _desired()
    mcp_text, _ = render_mcp_json_text({}, (server,))  # type: ignore[arg-type]
    codex_text = render_codex_config(
        None,
        hook_command=CODEX_HOOK_COMMAND,
        project_root=Path(_PROJECT),
        servers=(server,),  # type: ignore[arg-type]
    )
    return RenderedRegistration(
        servers=(server,),  # type: ignore[arg-type]
        mcp_json_text=mcp_text,
        codex_toml_text=codex_text,
        before_image=RegistrationBeforeImage(mcp_json=None, codex_config=None),
    )


def test_untouched_probe_receipt_verifies() -> None:
    rendered = _rendered()
    ProbedRegistration(
        rendered=rendered, digest_at_probe=rendered.digest(), tool_names=()
    ).verify_binding()


@pytest.mark.parametrize(
    "field_change",
    [
        {"cwd": "C:/elsewhere"},
        {"command": "python3"},
        {"args": ("-m", "agentkit.backend.vectordb.mcp_server")},
        {"required": False},
    ],
)
def test_any_field_changed_after_the_probe_is_detected(
    field_change: dict[str, object],
) -> None:
    """AC 5: the write must be prevented, not silently performed."""
    rendered = _rendered()
    digest_at_probe = rendered.digest()
    mutated = dataclasses.replace(
        rendered, servers=(dataclasses.replace(rendered.servers[0], **field_change),)  # type: ignore[arg-type]
    )
    receipt = ProbedRegistration(
        rendered=mutated, digest_at_probe=digest_at_probe, tool_names=()
    )
    with pytest.raises(McpServerRegistrationError, match="changed after the conformance probe"):
        receipt.verify_binding()


@pytest.mark.parametrize("env_key", REGISTERED_ENV_KEYS)
def test_any_env_value_changed_after_the_probe_is_detected(env_key: str) -> None:
    rendered = _rendered()
    digest_at_probe = rendered.digest()
    env = dict(rendered.servers[0].env)  # type: ignore[attr-defined]
    env[env_key] = "tampered"
    mutated_server = dataclasses.replace(
        rendered.servers[0], env=tuple(env.items())  # type: ignore[arg-type]
    )
    receipt = ProbedRegistration(
        rendered=dataclasses.replace(rendered, servers=(mutated_server,)),
        digest_at_probe=digest_at_probe,
        tool_names=(),
    )
    with pytest.raises(McpServerRegistrationError):
        receipt.verify_binding()


# --------------------------------------------------------------------------- #
# AC 5 negative matrix
# --------------------------------------------------------------------------- #


def test_non_default_endpoints_are_carried_verbatim() -> None:
    """No default is substituted anywhere in the chain."""
    mcp_entry, codex_entry = _both_entries()
    for entry in (mcp_entry, codex_entry):
        env = entry["env"]
        assert isinstance(env, dict)
        assert env["WEAVIATE_HTTP_ENDPOINT"] == _HTTP
        assert "localhost" not in env["WEAVIATE_HTTP_ENDPOINT"]


@pytest.mark.parametrize("bad_cwd", ["", "   "])
def test_empty_cwd_is_rejected(bad_cwd: str) -> None:
    env = build_registration_env(
        project_id="DEMO",
        weaviate_http_endpoint=_HTTP,
        weaviate_grpc_endpoint=_GRPC,
        concepts_dir=f"{_PROJECT}/concepts",
        stories_dir=f"{_PROJECT}/stories",
    )
    from agentkit.backend.vectordb.runtime_binding import RuntimeBindingError

    with pytest.raises(RuntimeBindingError):
        RuntimeBinding.from_env(
            env,
            command=resolve_story_knowledge_base_command(),
            args=STORY_KNOWLEDGE_BASE_ARGS,
            cwd=bad_cwd,
        )


@pytest.mark.parametrize("endpoint", ["http://localhost:8080", "http://127.0.0.1:8080"])
def test_explicitly_registered_loopback_endpoint_is_accepted(endpoint: str) -> None:
    """D2 is enforced by ORIGIN, not by endpoint spelling (decision 2026-08-02).

    The former block list rejected these two strings outright and thereby broke
    the NORMAL AK3 topology: a loopback Weaviate (FK-15 localhost-only). It could
    never tell a configured endpoint from an accidental one, because the string
    carries no provenance. ``build_registration_env`` IS the explicit
    configuration surface — it fails closed on a missing/empty value (the tests
    above) and never invents one, which is the whole content of D2.
    """
    env = build_registration_env(
        project_id="DEMO",
        weaviate_http_endpoint=endpoint,
        weaviate_grpc_endpoint=_GRPC,
        concepts_dir=f"{_PROJECT}/concepts",
        stories_dir=f"{_PROJECT}/stories",
    )
    binding = RuntimeBinding.from_env(
        env,
        command=resolve_story_knowledge_base_command(),
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd=_PROJECT,
    )
    assert binding.weaviate_http_endpoint == endpoint


def test_divergent_project_id_is_rejected() -> None:
    """A divergent PROJECT_ID in the installing shell is a hard error (D2)."""
    from agentkit.backend.vectordb.project_binding import (
        ProjectBindingError,
        resolve_authoritative_project_id,
    )

    with pytest.raises(ProjectBindingError, match="diverges"):
        resolve_authoritative_project_id(
            project_root=str(Path(_PROJECT)),
            supplied=None,
            env={"PROJECT_ID": "SOMETHING-ELSE"},
            config_project_id="DEMO",
        )


# --------------------------------------------------------------------------- #
# The registered interpreter must actually carry AK3 (regression 2026-08-02)
# --------------------------------------------------------------------------- #


def test_registered_command_is_an_absolute_interpreter_path() -> None:
    """REGRESSION: a bare ``python`` let the harness' PATH pick the interpreter.

    AK3 lives in its own venv; the interpreter first on a harness process' PATH
    generally does NOT carry AK3's dependencies. The MCP server then started and
    died on the first missing import — at first use, with the installer having
    reported success. The registered command is now the ABSOLUTE path of the
    interpreter that provides AK3.
    """
    command = resolve_story_knowledge_base_command()
    assert Path(command).is_absolute()
    assert Path(command).is_file()
    assert command != "python"

    mcp_entry, codex_entry = _both_entries()
    assert mcp_entry["command"] == command
    assert codex_entry["command"] == command


def test_ownership_still_recognises_a_machine_specific_interpreter() -> None:
    """The absolute path must not break AK3-ownership detection on detach.

    Ownership is carried by the server name, the exact ``args`` vector, the field
    set and ``cwd`` — never by a literal interpreter spelling, which is
    machine-specific by construction.
    """
    from agentkit.backend.core_types.mcp_server_registration import AK3_SERVER_SHAPES
    from agentkit.backend.installer.mcp_registration import render_mcp_json_without_ak3

    shape = AK3_SERVER_SHAPES[STORY_KNOWLEDGE_BASE_SERVER]
    assert shape.matches_command(resolve_story_knowledge_base_command())
    assert shape.matches_command("/opt/other-venv/bin/python")
    assert shape.matches_command(r"C:envsk3\Scripts\python.exe")
    # A bare tool name is never what AK3 writes -- a foreign entry parked under
    # the AK3 server name must NOT be classified as ours (and then stripped).
    assert not shape.matches_command("python")
    assert not shape.matches_command("foreign-tool")
    assert not shape.matches_command("")
    assert not shape.matches_command(None)

    server = _desired()
    mcp_text, _ = render_mcp_json_text({}, (server,))  # type: ignore[arg-type]
    stripped = json.loads(render_mcp_json_without_ak3(mcp_text.encode("utf-8")))
    assert STORY_KNOWLEDGE_BASE_SERVER not in stripped.get("mcpServers", {})


def test_interpreter_preflight_fails_closed_when_ak3_is_not_importable() -> None:
    """A non-importing interpreter is an INSTALL failure, not a first-use crash."""
    from types import SimpleNamespace

    from agentkit.backend.installer.mcp_registration import verify_interpreter_serves_ak3

    def _failing_runner(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        assert argv[1] == "-c"
        return SimpleNamespace(
            returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'tomlkit'"
        )

    with pytest.raises(McpServerRegistrationError, match="cannot import"):
        verify_interpreter_serves_ak3("C:/other/python.exe", runner=_failing_runner)


def test_interpreter_preflight_fails_closed_when_the_interpreter_cannot_run() -> None:
    from agentkit.backend.installer.mcp_registration import verify_interpreter_serves_ak3

    def _boom(argv: list[str], **_kwargs: object) -> object:
        raise OSError("no such executable")

    with pytest.raises(McpServerRegistrationError, match="could not be executed"):
        verify_interpreter_serves_ak3("C:/missing/python.exe", runner=_boom)


def test_interpreter_preflight_passes_for_the_running_interpreter() -> None:
    """The real venv interpreter imports the MCP entrypoint (no stub)."""
    from agentkit.backend.installer.mcp_registration import verify_interpreter_serves_ak3

    verify_interpreter_serves_ak3(resolve_story_knowledge_base_command())
