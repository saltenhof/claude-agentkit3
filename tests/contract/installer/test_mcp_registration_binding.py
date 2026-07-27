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
    STORY_KNOWLEDGE_BASE_COMMAND,
    ProbedRegistration,
    RegistrationBeforeImage,
    RenderedRegistration,
    build_registration_env,
    desired_server_from_spec,
    render_mcp_json_text,
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
        command=STORY_KNOWLEDGE_BASE_COMMAND,
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
            command=STORY_KNOWLEDGE_BASE_COMMAND,
            args=STORY_KNOWLEDGE_BASE_ARGS,
            cwd=bad_cwd,
        )


@pytest.mark.parametrize("forbidden", ["http://localhost:8080", "http://127.0.0.1:8080"])
def test_synthesised_localhost_default_is_rejected(forbidden: str) -> None:
    """Ratified D2 semantics -- pinned so it is never 'repaired' as a bug."""
    from agentkit.backend.vectordb.runtime_binding import RuntimeBindingError

    env = build_registration_env(
        project_id="DEMO",
        weaviate_http_endpoint=forbidden,
        weaviate_grpc_endpoint=_GRPC,
        concepts_dir=f"{_PROJECT}/concepts",
        stories_dir=f"{_PROJECT}/stories",
    )
    with pytest.raises(RuntimeBindingError):
        RuntimeBinding.from_env(
            env,
            command=STORY_KNOWLEDGE_BASE_COMMAND,
            args=STORY_KNOWLEDGE_BASE_ARGS,
            cwd=_PROJECT,
        )


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
