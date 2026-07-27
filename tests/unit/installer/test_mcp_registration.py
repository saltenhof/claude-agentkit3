"""Unit: installer-side MCP registration (AG3-175 Scope 1 / AC 4 / AC 5).

Covers the env rendering, the value-equal spec projection, the LOSSLESS bridge
into the conformance probe, the ``.mcp.json`` projection and the probe-receipt
binding. No harness format here — the Codex projection has its own module.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from agentkit.backend.core_types.mcp_server_registration import (
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
    McpServerRegistrationError,
)
from agentkit.backend.installer.mcp_registration import (
    CODEX_CONFIG_ARTIFACT,
    MCP_JSON_ARTIFACT,
    STORY_KNOWLEDGE_BASE_ARGS,
    STORY_KNOWLEDGE_BASE_COMMAND,
    ProbedRegistration,
    RegistrationBeforeImage,
    RenderedRegistration,
    build_registration_env,
    desired_server_from_spec,
    merge_mcp_json_servers,
    render_mcp_json_text,
    server_command_from_desired,
)
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding

_HTTP = "http://weaviate.internal:9903"
_GRPC = "weaviate.internal:50051"


def _env(**overrides: str) -> dict[str, str]:
    base = build_registration_env(
        project_id="AG3",
        weaviate_http_endpoint=_HTTP,
        weaviate_grpc_endpoint=_GRPC,
        concepts_dir="C:/proj/concepts",
        stories_dir="C:/proj/stories",
    )
    base.update(overrides)
    return base


def _spec(cwd: str = "C:/proj") -> object:
    """Build a real FK-13 spec through the productive RuntimeBinding path."""
    binding = RuntimeBinding.from_env(
        _env(),
        command=STORY_KNOWLEDGE_BASE_COMMAND,
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd=cwd,
    )
    return binding.spec


def _desired(cwd: str = "C:/proj") -> DesiredMcpServer:
    return desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, _spec(cwd))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The corrected command: engine, not the library module
# --------------------------------------------------------------------------- #


def test_registered_args_name_the_executable_module_not_the_library() -> None:
    """``mcp_server`` is a library module; ``engine`` is the stdio entry point.

    Running the library module as ``-m`` exits 0 without serving, which the
    AG3-164 gate reports as ``mcp_process_exited``. See the behavioural proof in
    ``test_registered_entry_starts.py``.
    """
    assert STORY_KNOWLEDGE_BASE_ARGS == ("-m", "agentkit.backend.vectordb.engine")
    assert "mcp_server" not in STORY_KNOWLEDGE_BASE_ARGS[1]


# --------------------------------------------------------------------------- #
# Env rendering
# --------------------------------------------------------------------------- #


def test_env_carries_exactly_the_registered_keys_in_declared_order() -> None:
    env = _env()
    assert tuple(env) == REGISTERED_ENV_KEYS


@pytest.mark.parametrize(
    "field",
    [
        "project_id",
        "weaviate_http_endpoint",
        "weaviate_grpc_endpoint",
        "concepts_dir",
        "stories_dir",
    ],
)
@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_env_value_is_rejected(field: str, empty: str) -> None:
    """No value is defaulted or synthesised (D2)."""
    kwargs = {
        "project_id": "AG3",
        "weaviate_http_endpoint": _HTTP,
        "weaviate_grpc_endpoint": _GRPC,
        "concepts_dir": "C:/proj/concepts",
        "stories_dir": "C:/proj/stories",
    }
    kwargs[field] = empty
    with pytest.raises(McpServerRegistrationError, match="missing/empty"):
        build_registration_env(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Spec projection (value equality)
# --------------------------------------------------------------------------- #


def test_projection_carries_the_spec_values_verbatim() -> None:
    server = _desired()
    assert server.command == STORY_KNOWLEDGE_BASE_COMMAND
    assert server.args == STORY_KNOWLEDGE_BASE_ARGS
    assert server.cwd == "C:/proj"
    assert server.env_dict() == _env()
    assert server.required is True


def test_non_default_endpoints_survive_verbatim_into_the_projection() -> None:
    """AC 5 negative matrix: no default is ever substituted."""
    odd_http = "https://vectors.example.test:18443"
    odd_grpc = "vectors.example.test:16051"
    binding = RuntimeBinding.from_env(
        _env(WEAVIATE_HTTP_ENDPOINT=odd_http, WEAVIATE_GRPC_ENDPOINT=odd_grpc),
        command=STORY_KNOWLEDGE_BASE_COMMAND,
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd="C:/proj",
    )
    server = desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, binding.spec)
    assert server.env_dict()["WEAVIATE_HTTP_ENDPOINT"] == odd_http
    assert server.env_dict()["WEAVIATE_GRPC_ENDPOINT"] == odd_grpc


def test_projection_rejects_env_diverging_from_the_spec_attributes() -> None:
    """A spec whose env contradicts its own attributes can never be projected."""
    spec = _spec()
    tampered = dataclasses.replace(spec, project_id="OTHER")  # type: ignore[type-var]
    with pytest.raises(McpServerRegistrationError, match="value-equal to the spec"):
        desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, tampered)


def test_projection_rejects_a_missing_registered_env_key() -> None:
    """A spec passing RuntimeBinding but lacking AGENTKIT_CONCEPTS_DIR is refused.

    This is the exact failure mode AC 5 exists to prevent: the validator accepts
    three keys, the process needs four.
    """
    partial = {
        "PROJECT_ID": "AG3",
        "WEAVIATE_HTTP_ENDPOINT": _HTTP,
        "WEAVIATE_GRPC_ENDPOINT": _GRPC,
    }
    binding = RuntimeBinding.from_env(
        partial,
        command=STORY_KNOWLEDGE_BASE_COMMAND,
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd="C:/proj",
    )
    with pytest.raises(McpServerRegistrationError) as exc:
        desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, binding.spec)
    assert "AGENTKIT_CONCEPTS_DIR" in str(exc.value)


def test_projection_rejects_an_unexpected_env_key() -> None:
    binding = RuntimeBinding.from_env(
        _env(GH_REPO="owner/repo"),
        command=STORY_KNOWLEDGE_BASE_COMMAND,
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd="C:/proj",
    )
    with pytest.raises(McpServerRegistrationError) as exc:
        desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, binding.spec)
    assert "GH_REPO" in str(exc.value)


# --------------------------------------------------------------------------- #
# The lossless probe bridge (the cwd divergence fix)
# --------------------------------------------------------------------------- #


def test_probe_bridge_carries_cwd_and_env_losslessly() -> None:
    """CP 10 previously rebuilt the probe command with a different cwd."""
    server = _desired(cwd="C:/proj")
    command = server_command_from_desired(server)
    assert command.command == server.command
    assert tuple(command.args) == server.args
    assert command.cwd == server.cwd == "C:/proj"
    assert command.env == server.env_dict()


def test_probe_bridge_does_not_lose_cwd_the_way_the_json_entry_path_does() -> None:
    """Pins WHY the bridge bypasses ``server_command_from_mcp_entry``.

    That function cannot carry ``cwd`` at all (mcp_conformance/check.py:227), so
    a probe built through it necessarily diverges from the written entry.
    """
    from agentkit.backend.installer.mcp_conformance import server_command_from_mcp_entry

    server = _desired()
    via_entry = server_command_from_mcp_entry(server.to_mcp_json_entry())
    assert via_entry.cwd is None
    assert server_command_from_desired(server).cwd == server.cwd


# --------------------------------------------------------------------------- #
# .mcp.json projection
# --------------------------------------------------------------------------- #


def test_merge_upserts_and_preserves_foreign_entries() -> None:
    existing: dict[str, object] = {
        "mcpServers": {"foreign": {"command": "node", "args": ["x.js"]}}
    }
    merged, changed = merge_mcp_json_servers(existing, (_desired(),))
    assert changed is True
    servers = merged["mcpServers"]
    assert isinstance(servers, dict)
    assert servers["foreign"] == {"command": "node", "args": ["x.js"]}
    assert STORY_KNOWLEDGE_BASE_SERVER in servers


def test_merge_is_idempotent_on_a_second_pass() -> None:
    merged, first = merge_mcp_json_servers({}, (_desired(),))
    _, second = merge_mcp_json_servers(merged, (_desired(),))
    assert first is True
    assert second is False


def test_merge_never_removes_a_previously_written_ak3_server() -> None:
    """UPSERT semantics: an are-mcp entry from an earlier run survives."""
    existing: dict[str, object] = {"mcpServers": {"are-mcp": {"command": "x"}}}
    merged, _ = merge_mcp_json_servers(existing, (_desired(),))
    servers = merged["mcpServers"]
    assert isinstance(servers, dict)
    assert "are-mcp" in servers


def test_merge_rejects_a_non_object_mcp_servers_value() -> None:
    with pytest.raises(TypeError, match="must be a JSON object"):
        merge_mcp_json_servers({"mcpServers": 5}, (_desired(),))


def test_rendered_text_keeps_the_previous_serialisation_shape() -> None:
    """indent=2 + sort_keys + trailing newline, as CP 10 wrote it before."""
    text, _ = render_mcp_json_text({}, (_desired(),))
    assert text.endswith("}\n")
    assert '\n  "mcpServers"' in text
    reparsed = json.loads(text)
    entry = reparsed["mcpServers"][STORY_KNOWLEDGE_BASE_SERVER]
    assert entry["cwd"] == "C:/proj"
    assert entry["env"]["AGENTKIT_CONCEPTS_DIR"] == "C:/proj/concepts"


# --------------------------------------------------------------------------- #
# Probe receipt binding (AC 5)
# --------------------------------------------------------------------------- #


def _rendered(server: DesiredMcpServer | None = None) -> RenderedRegistration:
    chosen = server or _desired()
    text, _ = render_mcp_json_text({}, (chosen,))
    return RenderedRegistration(
        servers=(chosen,),
        mcp_json_text=text,
        codex_toml_text="[hooks.pre_tool_use]\n",
        before_image=RegistrationBeforeImage(mcp_json=None, codex_config=None),
    )


def test_verify_binding_accepts_an_untouched_receipt() -> None:
    rendered = _rendered()
    receipt = ProbedRegistration(
        rendered=rendered, digest_at_probe=rendered.digest(), tool_names=()
    )
    receipt.verify_binding()


def test_verify_binding_detects_a_field_changed_after_the_probe() -> None:
    """AC 5: change a field after the probe -> the write must be prevented."""
    rendered = _rendered()
    digest_at_probe = rendered.digest()
    mutated_server = dataclasses.replace(rendered.servers[0], cwd="C:/elsewhere")
    mutated = dataclasses.replace(rendered, servers=(mutated_server,))
    receipt = ProbedRegistration(
        rendered=mutated, digest_at_probe=digest_at_probe, tool_names=()
    )
    with pytest.raises(McpServerRegistrationError, match="changed after the conformance probe"):
        receipt.verify_binding()


def test_verify_binding_detects_a_swapped_rendered_text() -> None:
    rendered = _rendered()
    digest_at_probe = rendered.digest()
    swapped = dataclasses.replace(rendered, codex_toml_text="[evil]\n")
    receipt = ProbedRegistration(
        rendered=swapped, digest_at_probe=digest_at_probe, tool_names=()
    )
    with pytest.raises(McpServerRegistrationError):
        receipt.verify_binding()


def test_verify_binding_detects_a_swapped_before_image() -> None:
    """The before-image is BOUND: a rollback cannot restore another run's content."""
    rendered = _rendered()
    digest_at_probe = rendered.digest()
    swapped = dataclasses.replace(
        rendered,
        before_image=RegistrationBeforeImage(mcp_json=b"{}\n", codex_config=None),
    )
    receipt = ProbedRegistration(
        rendered=swapped, digest_at_probe=digest_at_probe, tool_names=()
    )
    with pytest.raises(McpServerRegistrationError):
        receipt.verify_binding()


def test_absent_and_empty_before_image_are_distinguishable() -> None:
    """``None`` (delete on rollback) must never collapse into empty content."""
    absent = RegistrationBeforeImage(mcp_json=None, codex_config=None)
    empty = RegistrationBeforeImage(mcp_json=b"", codex_config=None)
    assert absent.fingerprints()[MCP_JSON_ARTIFACT] is None
    assert empty.fingerprints()[MCP_JSON_ARTIFACT] is not None
    assert absent.fingerprints()[CODEX_CONFIG_ARTIFACT] is None


def test_rendered_registration_is_frozen() -> None:
    rendered = _rendered()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rendered.mcp_json_text = "{}"  # type: ignore[misc]
