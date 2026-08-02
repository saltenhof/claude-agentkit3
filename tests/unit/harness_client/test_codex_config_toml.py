"""Unit: the one Codex TOML writer — strictness, preservation, ownership.

AG3-175 AC 7 (strictness/preservation matrix) and the ownership predicate that
replaces byte equality in the install idempotency and the detach classification.
Pure text-to-text: no filesystem, no process.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from agentkit.backend.core_types.mcp_server_registration import (
    AK3_SERVER_SHAPES,
    ARE_MCP_SERVER,
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
)
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    CodexConfigError,
    CodexConfigOwnership,
    CodexConfigRejection,
    classify_ownership,
    is_recognised_ak3_server_table,
    render_canonical_codex_config,
    render_codex_config,
)

_HOOK = "agentkit-hook-codex"
_ROOT = Path("C:/proj")


def _ak3_command() -> str:
    """The ABSOLUTE interpreter path AK3 registers (never a bare name)."""
    from agentkit.backend.installer.mcp_registration import (
        resolve_story_knowledge_base_command,
    )

    return resolve_story_knowledge_base_command()


def _server(
    name: str = STORY_KNOWLEDGE_BASE_SERVER,
    *,
    command: str | None = None,
    args: tuple[str, ...] = ("-m", "agentkit.backend.vectordb.engine"),
) -> DesiredMcpServer:
    return DesiredMcpServer(
        name=name,
        command=_ak3_command() if command is None else command,
        args=args,
        cwd=str(_ROOT),
        env=tuple((key, "value") for key in REGISTERED_ENV_KEYS),
        required=True,
    )


def _are_server() -> DesiredMcpServer:
    """ARE server matching its EXPECTED shape (AK3_SERVER_SHAPES)."""
    shape = AK3_SERVER_SHAPES[ARE_MCP_SERVER]
    return DesiredMcpServer(
        name=ARE_MCP_SERVER,
        command=shape.command,
        args=shape.args,
        cwd=str(_ROOT),
        env=tuple((key, "value") for key in sorted(shape.env_keys)),
    )


def _render(raw: bytes | None, *servers: DesiredMcpServer) -> str:
    return render_codex_config(
        raw, hook_command=_HOOK, project_root=_ROOT, servers=servers
    )


def _hook_only() -> bytes:
    return _render(None).encode("utf-8")


def _hook_plus_mcp() -> bytes:
    return _render(None, _server()).encode("utf-8")


# --------------------------------------------------------------------------- #
# Canonical rendering + the invariant the ownership predicate relies on
# --------------------------------------------------------------------------- #


def test_fresh_render_carries_the_hook_entry() -> None:
    text = _render(None)
    assert "[hooks.pre_tool_use]" in text
    assert f'command = "{_HOOK}"' in text
    assert "mcp_servers" not in text


def test_fresh_render_with_server_carries_all_five_fields_and_required() -> None:
    text = _render(None, _server())
    parsed = tomllib.loads(text)
    entry = parsed["mcp_servers"][STORY_KNOWLEDGE_BASE_SERVER]
    assert entry["command"] == _ak3_command()
    assert entry["args"] == ["-m", "agentkit.backend.vectordb.engine"]
    assert entry["cwd"] == str(_ROOT)
    assert entry["env"]["PROJECT_ID"] == "value"
    assert entry["required"] is True


def test_canonical_render_is_stable_under_re_render() -> None:
    """The invariant the ownership predicate depends on (§4.4).

    A file AK3 wrote must be byte-identical to its own canonical rendering, or
    detach would classify AK3's own file as MIXED and leave it behind.
    """
    once = _hook_plus_mcp()
    twice = _render(once, _server()).encode("utf-8")
    assert once == twice


def test_canonical_render_is_deterministic_across_server_order() -> None:
    a = _server()
    b = _are_server()
    assert _render(None, a, b) == _render(None, b, a)


def test_render_is_idempotent_on_a_second_merge_into_foreign_content() -> None:
    existing = b'# keep\n[user.custom]\nalpha = 1\n'
    once = _render(existing, _server()).encode("utf-8")
    twice = _render(once, _server()).encode("utf-8")
    assert once == twice


# --------------------------------------------------------------------------- #
# Rejection matrix (AC 7) — every case is a NAMED error and yields no output
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        # invalid UTF-8
        (b'command = "\xff\xfe"\n', CodexConfigRejection.NOT_UTF8),
        # TOML syntax error
        (b"[unclosed\n", CodexConfigRejection.UNPARSABLE_TOML),
        # duplicate key and duplicate table (rejected natively by tomllib)
        (b"[a]\nx = 1\nx = 2\n", CodexConfigRejection.UNPARSABLE_TOML),
        (b"[a]\nx = 1\n[a]\ny = 2\n", CodexConfigRejection.UNPARSABLE_TOML),
        # AK3-owned top-level keys holding a non-table
        (b"hooks = 5\n", CodexConfigRejection.HOOKS_NOT_TABLE),
        (b"[hooks]\npre_tool_use = 5\n", CodexConfigRejection.HOOK_ENTRY_NOT_TABLE),
        (b"mcp_servers = 5\n", CodexConfigRejection.MCP_SERVERS_NOT_TABLE),
        (
            b"[mcp_servers]\nsome-server = 5\n",
            CodexConfigRejection.SERVER_ENTRY_NOT_TABLE,
        ),
        # wrong types in AK3-OWNED server fields
        (
            b"[mcp_servers.story-knowledge-base]\ncommand = 5\n",
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b'[mcp_servers.story-knowledge-base]\ncommand = ""\n',
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b'[mcp_servers.story-knowledge-base]\nargs = "not-a-list"\n',
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b"[mcp_servers.story-knowledge-base]\nargs = [1, 2]\n",
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b"[mcp_servers.story-knowledge-base]\ncwd = 5\n",
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b'[mcp_servers.story-knowledge-base]\nenv = "nope"\n',
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b"[mcp_servers.story-knowledge-base.env]\nPROJECT_ID = 5\n",
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
        (
            b"[mcp_servers.story-knowledge-base]\nrequired = 1\n",
            CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        ),
    ],
)
def test_rejection_matrix(raw: bytes, code: CodexConfigRejection) -> None:
    """Each malformed input is a named rejection; nothing is rendered."""
    with pytest.raises(CodexConfigError) as exc:
        _render(raw, _server())
    assert exc.value.code is code


def test_foreign_occupation_of_an_ak3_server_name_is_rejected() -> None:
    """A DIFFERENT program under an AK3 name must never be overwritten."""
    raw = (
        b"[mcp_servers.story-knowledge-base]\n"
        b'command = "some-other-tool"\n'
        b'args = ["--serve"]\n'
    )
    with pytest.raises(CodexConfigError) as exc:
        _render(raw, _server())
    assert exc.value.code is CodexConfigRejection.SERVER_NAME_FOREIGN_OCCUPIED


def test_matching_command_and_args_is_our_own_entry_not_foreign_occupation() -> None:
    """Same identity (command+args) -> upsert, and unknown fields survive."""
    raw = (
        b"[mcp_servers.story-knowledge-base]\n"
        + _rendered_command_bytes()
        + b"\n"
        + b'args = ["-m", "agentkit.backend.vectordb.engine"]\n'
        + b'future_codex_field = "keep me"\n'
    )
    text = _render(raw, _server())
    parsed = tomllib.loads(text)
    entry = parsed["mcp_servers"][STORY_KNOWLEDGE_BASE_SERVER]
    assert entry["future_codex_field"] == "keep me"
    assert entry["cwd"] == str(_ROOT)


def test_foreign_server_with_odd_field_types_is_not_rejected() -> None:
    """Strictness is scoped: a foreign server's internals are not AK3's business.

    Being strict here would refuse an install over somebody else's configuration
    while claiming to preserve foreign content.
    """
    raw = b"[mcp_servers.other-server]\ncommand = 5\nargs = \"whatever\"\n"
    text = _render(raw, _server())
    parsed = tomllib.loads(text)
    assert parsed["mcp_servers"]["other-server"]["command"] == 5


# --------------------------------------------------------------------------- #
# Preservation matrix (AC 7, positive side)
# --------------------------------------------------------------------------- #


_FOREIGN = (
    b"# top-of-file comment owned by the project\n"
    b"[hooks.pre_tool_use]\n"
    b'command = "agentkit-hook-codex"\n'
    b"\n"
    b"# user note: do not remove\n"
    b"[user.custom]\n"
    b"zebra = 1   # trailing comment\n"
    b"alpha = 2\n"
    b"\n"
    b"[profiles.work]\n"
    b'model = "o3"\n'
    b"\n"
    b"[mcp_servers.other-server]\n"
    b'command = "node"\n'
    b'args = ["server.js"]\n'
    b'unknown_harness_field = "keep me"\n'
)


def test_preservation_matrix_keeps_every_foreign_element() -> None:
    text = _render(_FOREIGN, _server())

    # comments
    assert "# top-of-file comment owned by the project" in text
    assert "# user note: do not remove" in text
    assert "# trailing comment" in text
    # foreign key ORDER inside a foreign table
    assert text.index("zebra") < text.index("alpha")
    # foreign tables and foreign server, value-equal
    parsed = tomllib.loads(text)
    assert parsed["user"]["custom"] == {"zebra": 1, "alpha": 2}
    assert parsed["profiles"]["work"] == {"model": "o3"}
    assert parsed["mcp_servers"]["other-server"] == {
        "command": "node",
        "args": ["server.js"],
        "unknown_harness_field": "keep me",
    }
    # and AK3's own entry is present
    assert STORY_KNOWLEDGE_BASE_SERVER in parsed["mcp_servers"]


def test_merge_never_removes_an_ak3_server_written_earlier() -> None:
    """UPSERT: an are-mcp table from an earlier run survives a vectordb-only run."""
    raw = _render(None, _server(), _are_server()).encode(
        "utf-8"
    )
    text = _render(raw, _server())
    parsed = tomllib.loads(text)
    assert set(parsed["mcp_servers"]) == {STORY_KNOWLEDGE_BASE_SERVER, ARE_MCP_SERVER}


def test_hook_entry_is_repaired_when_a_foreign_file_lacks_it() -> None:
    raw = b"[user.custom]\nalpha = 1\n"
    text = _render(raw, _server())
    parsed = tomllib.loads(text)
    assert parsed["hooks"]["pre_tool_use"]["command"] == _HOOK
    assert parsed["user"]["custom"] == {"alpha": 1}


# --------------------------------------------------------------------------- #
# Ownership predicate — the classification detach depends on
# --------------------------------------------------------------------------- #


def test_absent_file_is_foreign() -> None:
    assert classify_ownership(None, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.FOREIGN


def test_hook_only_ak3_file_is_ak3_only() -> None:
    assert (
        classify_ownership(_hook_only(), hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.AK3_ONLY
    )


def test_hook_plus_ak3_mcp_table_is_ak3_only() -> None:
    """The Befund-B fix: byte equality against a fixed string said MIXED here."""
    assert (
        classify_ownership(_hook_plus_mcp(), hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.AK3_ONLY
    )


def test_foreign_table_alongside_ak3_content_is_mixed() -> None:
    raw = _hook_plus_mcp() + b"\n[user.custom]\nalpha = 1\n"
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


def test_foreign_mcp_server_alongside_ak3_content_is_mixed() -> None:
    raw = _hook_plus_mcp() + b'\n[mcp_servers.other]\ncommand = "node"\n'
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


def test_comment_only_user_edit_is_mixed_not_ak3_only() -> None:
    """THE regression guard for preserved_foreign_files.

    A value-based ownership predicate cannot see an added comment and would call
    this file AK3-only, so detach would DELETE it — a weakening of the guarantee
    that today's byte comparison provides. The derived-canonical byte gate is what
    prevents that.
    """
    raw = _hook_plus_mcp() + b"\n# my own note, please keep\n"
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


def test_unknown_field_in_our_own_server_table_is_mixed() -> None:
    raw = _hook_plus_mcp().replace(
        b"required = true", b'required = true\nfuture_field = "x"'
    )
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


def test_foreign_hook_key_is_mixed() -> None:
    raw = _hook_only() + b'\n[hooks.post_tool_use]\ncommand = "other"\n'
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


def test_different_hook_command_is_not_ak3_owned() -> None:
    raw = _render(None).replace(_HOOK, "someone-elses-hook").encode("utf-8")
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.FOREIGN


def test_file_without_any_ak3_content_is_foreign() -> None:
    raw = b"[user.custom]\nalpha = 1\n"
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.FOREIGN


def test_unreadable_file_is_unreadable_and_never_raises() -> None:
    """Detach must preserve what it cannot read rather than delete it."""
    assert (
        classify_ownership(b"[unclosed\n", hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.UNREADABLE
    )
    assert (
        classify_ownership(b'x = "\xff\xfe"\n', hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.UNREADABLE
    )


def test_ak3_only_file_with_are_server_is_classified_owned() -> None:
    """Ownership is feature-flag independent: are-mcp counts as AK3 content."""
    raw = _render(None, _are_server()).encode("utf-8")
    assert classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.AK3_ONLY


def test_render_canonical_matches_classification_for_every_owned_subset() -> None:
    """Cross-check: whatever the canonical renderer emits classifies as AK3_ONLY."""
    for servers in ((), (_server(),), (_server(), _are_server())):
        raw = _render(None, *servers).encode("utf-8")
        assert (
            classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT)
            is CodexConfigOwnership.AK3_ONLY
        ), servers


def test_render_canonical_helper_is_reachable_directly() -> None:
    text = render_canonical_codex_config(hook_command=_HOOK, server_tables={})
    assert "[hooks.pre_tool_use]" in text


def test_unknown_field_survives_the_merge_and_keeps_the_file_preserved() -> None:
    """Closes the loop between the two halves of the guarantee.

    The merge path preserves an unknown field in AK3's own table; the ownership
    predicate must then keep classifying that file as MIXED, so detach preserves
    it instead of deleting the field along with the file.
    """
    raw = (
        b"[hooks.pre_tool_use]\n"
        b'command = "agentkit-hook-codex"\n'
        b"\n"
        b"[mcp_servers.story-knowledge-base]\n"
        + _rendered_command_bytes()
        + b"\n"
        + b'args = ["-m", "agentkit.backend.vectordb.engine"]\n'
        + b'future_codex_field = "keep me"\n'
    )
    merged = _render(raw, _server()).encode("utf-8")

    assert b'future_codex_field = "keep me"' in merged
    assert classify_ownership(merged, hook_command=_HOOK, project_root=_ROOT) is CodexConfigOwnership.MIXED


# --------------------------------------------------------------------------- #
# R01 — the VALUE gate. A comparison against the values FOUND is
# self-referential and can only see a spelling deviation; these cases prove the
# predicate compares against what AK3 EXPECTS to write.
# --------------------------------------------------------------------------- #


def _ak3_file_bytes() -> bytes:
    return _render(None, _server()).encode("utf-8")


def _rendered_command_bytes() -> bytes:
    """The ``command = "..."`` line AK3 actually renders (absolute interpreter)."""
    return f"command = {json.dumps(_ak3_command())}".encode()


def _replace_in_table(raw: bytes, old: bytes, new: bytes) -> bytes:
    assert old in raw, f"fixture drift: {old!r} not in rendered file"
    return raw.replace(old, new)


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        ("foreign command", _rendered_command_bytes(), b'command = "foreign-tool"'),
        (
            "foreign args",
            b'args = ["-m", "agentkit.backend.vectordb.engine"]',
            b'args = ["--evil"]',
        ),
        ("required turned off", b"required = true", b"required = false"),
        ("an env key dropped", b'PROJECT_ID = "value", ', b""),
    ],
)
def test_altered_values_under_an_ak3_name_are_not_ak3_owned(
    label: str, old: bytes, new: bytes
) -> None:
    """A user's table under an AK3-reserved name must never be deleted by detach."""
    raw = _replace_in_table(_ak3_file_bytes(), old, new)
    assert (
        classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.MIXED
    ), label


def test_empty_reserved_table_is_not_ak3_owned() -> None:
    """An empty reserved table is ambiguous, so it is preserved, not claimed."""
    raw = (
        b"# AgentKit-managed Codex hook configuration.\n\n"
        b"[hooks.pre_tool_use]\n"
        b'command = "agentkit-hook-codex"\n\n'
        b"[mcp_servers.story-knowledge-base]\n"
    )
    assert (
        classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.MIXED
    )


def test_ak3_registration_of_another_project_is_not_ak3_owned_here() -> None:
    """``cwd`` binds a registration to its project; another project's is foreign.

    Conservative on purpose: preserving is reversible, deleting is not.
    """
    other_root = Path("C:/some-other-project")
    other = DesiredMcpServer(
        name=STORY_KNOWLEDGE_BASE_SERVER,
        command=_ak3_command(),
        args=("-m", "agentkit.backend.vectordb.engine"),
        cwd=str(other_root),
        env=tuple((key, "value") for key in REGISTERED_ENV_KEYS),
    )
    raw = render_codex_config(
        None, hook_command=_HOOK, project_root=other_root, servers=(other,)
    ).encode("utf-8")
    assert (
        classify_ownership(raw, hook_command=_HOOK, project_root=_ROOT)
        is CodexConfigOwnership.MIXED
    )


def test_empty_reserved_table_is_rejected_by_the_writer_not_filled() -> None:
    """An ambiguous occupation is a rejection, never a free slot to claim."""
    with pytest.raises(CodexConfigError) as exc:
        _render(b"[mcp_servers.story-knowledge-base]\n", _server())
    assert exc.value.code is CodexConfigRejection.SERVER_NAME_FOREIGN_OCCUPIED


def test_recognition_helper_accepts_only_the_expected_shape() -> None:
    """Directly pins the value gate against the SSOT shape table."""
    shape = AK3_SERVER_SHAPES[STORY_KNOWLEDGE_BASE_SERVER]
    good = {
        "command": _ak3_command(),
        "args": list(shape.args),
        "cwd": str(_ROOT),
        "env": dict.fromkeys(shape.env_keys, "value"),
        "required": True,
    }
    assert is_recognised_ak3_server_table(
        STORY_KNOWLEDGE_BASE_SERVER, good, project_root=_ROOT
    )
    for mutation in (
        {"command": "other"},
        {"command": "python"},  # relative: never what AK3 writes
        {"args": ["-m", "other"]},
        {"required": False},
        {"cwd": "C:/elsewhere"},
        {"env": {"PROJECT_ID": "v"}},
        {"env": dict.fromkeys(shape.env_keys, "")},
    ):
        assert not is_recognised_ak3_server_table(
            STORY_KNOWLEDGE_BASE_SERVER, {**good, **mutation}, project_root=_ROOT
        ), mutation
    # an extra or a missing field is also not our own registration
    assert not is_recognised_ak3_server_table(
        STORY_KNOWLEDGE_BASE_SERVER, {**good, "extra": 1}, project_root=_ROOT
    )
    assert not is_recognised_ak3_server_table(
        STORY_KNOWLEDGE_BASE_SERVER,
        {k: v for k, v in good.items() if k != "cwd"},
        project_root=_ROOT,
    )
