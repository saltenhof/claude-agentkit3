"""Unit: harness-neutral MCP registration contract (AG3-175 Scope 1 / AC 5).

Pure logic: validation, canonical serialisation, digest stability and the
immutability property AC 5 rests on. No filesystem, no process, no harness.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from agentkit.backend.core_types.mcp_server_registration import (
    AK3_MCP_SERVER_NAMES,
    ARE_MCP_SERVER,
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
    McpServerRegistrationError,
    before_image_fingerprint,
    canonical_registration_payload,
    registration_digest,
)

_ENV: tuple[tuple[str, str], ...] = (
    ("PROJECT_ID", "AG3"),
    ("WEAVIATE_HTTP_ENDPOINT", "http://weaviate.internal:9903"),
    ("WEAVIATE_GRPC_ENDPOINT", "weaviate.internal:50051"),
    ("AGENTKIT_CONCEPTS_DIR", "C:/proj/concepts"),
    ("AGENTKIT_STORIES_DIR", "C:/proj/stories"),
)


def _server(**overrides: object) -> DesiredMcpServer:
    """Build a valid desired server, overriding single fields for negatives."""
    kwargs: dict[str, object] = {
        "name": STORY_KNOWLEDGE_BASE_SERVER,
        "command": "python",
        "args": ("-m", "agentkit.backend.vectordb.engine"),
        "cwd": "C:/proj",
        "env": _ENV,
        "required": True,
    }
    kwargs.update(overrides)
    return DesiredMcpServer(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Ownership / env-key constants
# --------------------------------------------------------------------------- #


def test_ak3_owns_exactly_the_two_known_server_names() -> None:
    """The ownership set is feature-flag independent (detach classification)."""
    assert frozenset({STORY_KNOWLEDGE_BASE_SERVER, ARE_MCP_SERVER}) == AK3_MCP_SERVER_NAMES


def test_registered_env_keys_cover_runtime_binding_requirements() -> None:
    """Drift lock: the rendered env must satisfy the PROCESS, not just the validator.

    ``RuntimeBinding.REQUIRED_ENV_KEYS`` validates three keys; the stdio entry
    point additionally requires ``AGENTKIT_CONCEPTS_DIR``. If a future change
    adds a key to ``REQUIRED_ENV_KEYS`` without extending the registration, this
    test fails instead of shipping an incomplete environment (AG3-175 §1.6a).
    """
    from agentkit.backend.vectordb.runtime_binding import REQUIRED_ENV_KEYS

    assert set(REGISTERED_ENV_KEYS) >= set(REQUIRED_ENV_KEYS)


def test_registered_env_keys_include_the_concepts_dir_the_entry_point_demands() -> None:
    """``AGENTKIT_CONCEPTS_DIR`` has no default in the entry point (N20/D2)."""
    assert "AGENTKIT_CONCEPTS_DIR" in REGISTERED_ENV_KEYS
    assert "AGENTKIT_STORIES_DIR" in REGISTERED_ENV_KEYS


def test_registered_env_keys_have_no_duplicates() -> None:
    assert len(REGISTERED_ENV_KEYS) == len(set(REGISTERED_ENV_KEYS))


# --------------------------------------------------------------------------- #
# Immutability (AC 5: in-place mutation must be impossible, not discouraged)
# --------------------------------------------------------------------------- #


def test_in_place_field_mutation_is_impossible() -> None:
    """A frozen dataclass makes the natural 'mutate then write' path unavailable."""
    server = _server()
    with pytest.raises(dataclasses.FrozenInstanceError):
        server.cwd = "C:/elsewhere"  # type: ignore[misc]


def test_collections_are_tuples_so_nothing_can_be_appended() -> None:
    server = _server()
    assert isinstance(server.args, tuple)
    assert isinstance(server.env, tuple)


# --------------------------------------------------------------------------- #
# Validation matrix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"name": ""}, "missing/empty"),
        ({"name": "   "}, "missing/empty"),
        ({"name": "has space"}, "safe configuration key"),
        ({"name": "nested.name"}, "safe configuration key"),
        ({"name": 'quote"name'}, "safe configuration key"),
        ({"command": ""}, "'command' must be a non-empty string"),
        ({"command": "  "}, "'command' must be a non-empty string"),
        ({"args": ["-m", "x"]}, "'args' must be a tuple"),
        ({"args": ("-m", 5)}, "every arg must be a string"),
        ({"cwd": ""}, "'cwd' must be a non-empty string"),
        ({"cwd": "  "}, "containment boundary"),
        ({"env": {"A": "1"}}, "'env' must be a tuple"),
        ({"env": (("A",),)}, r"every env entry must be a \(key, value\) pair"),
        ({"env": (("", "1"),)}, "env keys must be non-empty strings"),
        ({"env": (("A", 1),)}, "must be a string"),
        ({"env": (("A", "1"), ("A", "2"))}, "duplicate env key"),
        ({"required": 1}, "must be a real bool"),
        ({"required": "true"}, "must be a real bool"),
    ],
)
def test_invalid_registration_is_rejected(
    overrides: dict[str, object], needle: str
) -> None:
    """Every malformed field is a named, fail-closed rejection."""
    with pytest.raises(McpServerRegistrationError, match=needle):
        _server(**overrides)


def test_empty_args_and_empty_env_are_valid() -> None:
    """A server may legitimately take no arguments and no environment."""
    server = _server(args=(), env=())
    assert server.args == ()
    assert server.env_dict() == {}


# --------------------------------------------------------------------------- #
# Projection into .mcp.json
# --------------------------------------------------------------------------- #


def test_mcp_json_entry_carries_command_args_cwd_and_env() -> None:
    entry = _server().to_mcp_json_entry()
    assert entry == {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "agentkit.backend.vectordb.engine"],
        "cwd": "C:/proj",
        "env": {
            "PROJECT_ID": "AG3",
            "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.internal:9903",
            "WEAVIATE_GRPC_ENDPOINT": "weaviate.internal:50051",
            "AGENTKIT_CONCEPTS_DIR": "C:/proj/concepts",
            "AGENTKIT_STORIES_DIR": "C:/proj/stories",
        },
    }


def test_mcp_json_entry_omits_required_which_claude_code_does_not_model() -> None:
    """``required`` belongs to the Codex table only (FK-76 §76.5.4)."""
    assert "required" not in _server().to_mcp_json_entry()


def test_mcp_json_entry_is_json_serialisable() -> None:
    json.dumps(_server().to_mcp_json_entry(), allow_nan=False)


# --------------------------------------------------------------------------- #
# Canonical payload + digest
# --------------------------------------------------------------------------- #


def _digest(servers: tuple[DesiredMcpServer, ...], **texts: str) -> str:
    return registration_digest(
        servers,
        mcp_json_text=texts.get("mcp_json_text", "{}\n"),
        codex_toml_text=texts.get("codex_toml_text", "[hooks]\n"),
    )


def test_digest_is_stable_across_equal_values() -> None:
    assert _digest((_server(),)) == _digest((_server(),))


def test_digest_ignores_server_declaration_order() -> None:
    a = _server()
    b = _server(name=ARE_MCP_SERVER, command="agentkit-are-mcp", args=(), env=())
    assert _digest((a, b)) == _digest((b, a))


def test_digest_ignores_env_declaration_order() -> None:
    forward = _server(env=_ENV)
    reversed_env = _server(env=tuple(reversed(_ENV)))
    assert _digest((forward,)) == _digest((reversed_env,))


@pytest.mark.parametrize(
    "overrides",
    [
        {"command": "python3"},
        {"args": ("-m", "agentkit.backend.vectordb.mcp_server")},
        {"cwd": "C:/other"},
        {"env": (*_ENV[:-1], ("AGENTKIT_STORIES_DIR", "C:/other/stories"))},
        {"required": False},
        {"name": ARE_MCP_SERVER},
    ],
)
def test_digest_changes_when_any_field_changes(overrides: dict[str, object]) -> None:
    """Every covered field is genuinely part of the binding."""
    assert _digest((_server(),)) != _digest((_server(**overrides),))


@pytest.mark.parametrize(
    "texts",
    [
        {"mcp_json_text": '{"mcpServers": {}}\n'},
        {"codex_toml_text": "[mcp_servers.story-knowledge-base]\n"},
    ],
)
def test_digest_changes_when_a_rendered_text_changes(texts: dict[str, str]) -> None:
    """Closes 'probed object X, wrote a text rendered from object Y'.

    The rendered texts are opaque to the digest — exercising the pure function
    over its input domain, not standing in for a component.
    """
    assert _digest((_server(),)) != _digest((_server(),), **texts)


def test_replaced_server_is_detected_by_the_digest() -> None:
    """AC 5 core: substitution after the probe changes the digest.

    ``dataclasses.replace`` is the only remaining way to 'change a field', since
    in-place assignment is impossible. It must be detectable.
    """
    original = _server()
    probed = _digest((original,))
    mutated = dataclasses.replace(original, cwd="C:/elsewhere")
    assert _digest((mutated,)) != probed


def test_canonical_payload_is_deterministic_sorted_json() -> None:
    payload = canonical_registration_payload(
        (_server(),), mcp_json_text="{}\n", codex_toml_text="[hooks]\n"
    )
    parsed = json.loads(payload)
    assert parsed["servers"][0]["name"] == STORY_KNOWLEDGE_BASE_SERVER
    # env pairs are canonically sorted by key
    env_keys = [pair[0] for pair in parsed["servers"][0]["env"]]
    assert env_keys == sorted(env_keys)
    # no incidental whitespace: the payload is a compact, digest-stable string
    assert ", " not in payload


def test_canonical_payload_is_domain_tagged() -> None:
    """The domain tag prevents collision with any other canonical digest."""
    payload = canonical_registration_payload(
        (), mcp_json_text="", codex_toml_text=""
    )
    assert "agentkit.mcp-server-registration.v1" in payload


# --------------------------------------------------------------------------- #
# Before-image binding
# --------------------------------------------------------------------------- #


def test_absent_before_image_fingerprint_is_none() -> None:
    """``None`` means "file did not exist" — rollback must DELETE, not blank it."""
    assert before_image_fingerprint(None) is None


def test_empty_before_image_is_distinguishable_from_an_absent_one() -> None:
    assert before_image_fingerprint(b"") is not None
    assert before_image_fingerprint(b"") != before_image_fingerprint(b"x")


def test_before_image_fingerprint_survives_invalid_utf8() -> None:
    """An existing harness config may be invalid UTF-8; a digest still binds it.

    This is why the payload carries a fingerprint rather than the raw bytes: the
    bytes could not be embedded in a JSON payload at all.
    """
    assert before_image_fingerprint(b"\xff\xfe not utf-8") is not None


def test_digest_changes_when_the_bound_before_image_changes() -> None:
    """Makes the before-image genuinely BOUND, not merely carried alongside."""
    args = {"mcp_json_text": "{}\n", "codex_toml_text": "[hooks]\n"}
    absent = registration_digest(
        (_server(),), **args, before_image={"mcp_json": None, "codex_config": None}
    )
    present = registration_digest(
        (_server(),),
        **args,
        before_image={
            "mcp_json": before_image_fingerprint(b"{}\n"),
            "codex_config": None,
        },
    )
    assert absent != present


def test_digest_without_a_before_image_is_stable() -> None:
    """Omitting the before-image is a distinct, deterministic state."""
    args = {"mcp_json_text": "{}\n", "codex_toml_text": "[hooks]\n"}
    unbound = registration_digest((_server(),), **args)
    assert unbound == registration_digest((_server(),), **args)
    assert unbound != registration_digest(
        (_server(),), **args, before_image={"mcp_json": None, "codex_config": None}
    )
