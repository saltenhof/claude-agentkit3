"""The ONE semantic writer for the project-local ``.codex/config.toml``.

FK-76 §76.5.4 owns the Codex configuration FORMAT (the mirror of the Claude-Code
``.mcp.json`` contract); FK-50 §50.3 CP 10 owns whether/when a registration
happens. This module is the format side and nothing else: pure text-to-text, no
filesystem access (path resolution and containment stay in the installer edge,
which owns the target-project layout).

It replaces two competing truths that previously wrote the same file:

1. ``installer.codex_settings.build_codex_config_toml`` produced the whole file
   as a fixed three-line string and decided a rewrite by BYTE comparison. Merging
   an ``[mcp_servers.*]`` table into that file would be destroyed by the next
   install run.
2. ``bundles/target_project/.codex/config.toml`` was copied verbatim by
   ``runner._deploy_static_resource_files`` in CP 8 — before the writer even
   looked at the file.

Both are gone; every write goes through :func:`render_codex_config`.

Ownership model (the predicate that replaces byte equality):

* Top level, AK3 owns ``hooks`` and ``mcp_servers`` — nothing else.
* Inside ``hooks``, AK3 owns ``pre_tool_use``.
* Inside ``mcp_servers``, AK3 owns exactly :data:`AK3_MCP_SERVER_NAMES`.
* Inside an AK3 server table, AK3 owns :data:`AK3_OWNED_SERVER_FIELDS`; any other
  field is foreign and is preserved.

Preservation is deliberately conservative in BOTH dimensions. A value-only
predicate would regress the ``preserved_foreign_files`` guarantee: a file a user
extended with only a COMMENT contains no foreign *values*, so a value-based
classification would call it AK3-only and detach would delete it. The final
classification step therefore compares the raw bytes against the canonical
rendering of the AK3 content that was found — a byte comparison, but against a
DERIVED rendering instead of a fixed literal.

Why tomlkit (guardrail ARCH-23: exchangeable libraries stay behind one
abstraction): this module is the single import point. A value-only writer would
delete a target project's own Codex comments, and the ownership predicate would
then classify the file as AK3-only so detach would REMOVE it — turning "a comment
was lost" into "the file was deleted".
"""

from __future__ import annotations

import tomllib
from enum import StrEnum
from typing import TYPE_CHECKING

import tomlkit

from agentkit.backend.core_types.mcp_server_registration import (
    AK3_MCP_SERVER_NAMES,
    DesiredMcpServer,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Header comment of an AK3-rendered Codex configuration.
AK3_CONFIG_HEADER_COMMENT: str = "AgentKit-managed Codex hook configuration."

#: Top-level tables AK3 owns. Everything else at the top level is foreign.
AK3_OWNED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"hooks", "mcp_servers"})

#: Hook keys AK3 owns inside ``[hooks]``.
AK3_OWNED_HOOK_KEYS: frozenset[str] = frozenset({"pre_tool_use"})

#: Fields AK3 owns inside one of ITS OWN ``[mcp_servers.<name>]`` tables.
#: Any further field in such a table is an unknown harness-specific field and is
#: preserved value-equal (FK-76 §76.5.4 / AG3-175 AC 7).
AK3_OWNED_SERVER_FIELDS: frozenset[str] = frozenset(
    {"command", "args", "cwd", "env", "required"}
)

#: Deterministic field order of a rendered AK3 server table.
_SERVER_FIELD_ORDER: tuple[str, ...] = ("command", "args", "cwd", "env", "required")

#: Key of the hook table AK3 materialises.
_PRE_TOOL_USE: str = "pre_tool_use"
_HOOKS: str = "hooks"
_MCP_SERVERS: str = "mcp_servers"


class CodexConfigRejection(StrEnum):
    """Machine-readable rejection codes of the Codex configuration writer.

    Note on TOML: there is no "non-table root" case — a TOML document's root is
    always a table (measured: ``tomllib.loads`` always returns a ``dict``). The
    equivalent situation is an AK3-owned top-level key that does not hold a
    table, covered by :attr:`HOOKS_NOT_TABLE` / :attr:`MCP_SERVERS_NOT_TABLE`.
    """

    #: File bytes are not valid UTF-8.
    NOT_UTF8 = "not_utf8"
    #: TOML syntax error. Also covers duplicate keys and duplicate tables, which
    #: ``tomllib`` rejects natively ("Cannot overwrite a value" / "Cannot declare
    #: (...) twice"); the parser message travels in the error detail.
    UNPARSABLE_TOML = "unparsable_toml"
    #: ``hooks`` is present but not a table.
    HOOKS_NOT_TABLE = "hooks_not_table"
    #: ``hooks.pre_tool_use`` is present but not a table.
    HOOK_ENTRY_NOT_TABLE = "hook_entry_not_table"
    #: ``mcp_servers`` is present but not a table.
    MCP_SERVERS_NOT_TABLE = "mcp_servers_not_table"
    #: An ``mcp_servers.<name>`` value is present but not a table.
    SERVER_ENTRY_NOT_TABLE = "server_entry_not_table"
    #: An AK3-owned field of an AK3-owned server table has the wrong type.
    SERVER_FIELD_TYPE_INVALID = "server_field_type_invalid"
    #: An AK3-owned server name is occupied by a DIFFERENT program.
    SERVER_NAME_FOREIGN_OCCUPIED = "server_name_foreign_occupied"
    #: The resolved configuration path escapes the project root (installer edge).
    PATH_ESCAPES_PROJECT_ROOT = "path_escapes_project_root"


class CodexConfigOwnership(StrEnum):
    """Classification of an existing ``.codex/config.toml``."""

    #: Contains AK3 content only, byte-identical to its canonical rendering.
    #: Safe for detach to remove.
    AK3_ONLY = "ak3_only"
    #: Contains AK3 content plus something AK3 does not own (a foreign table, a
    #: foreign server, an unknown field, or merely a comment). PRESERVED.
    MIXED = "mixed"
    #: No AK3 content at all (or no file). PRESERVED.
    FOREIGN = "foreign"
    #: Not decodable / not parsable. PRESERVED — never delete what we cannot read.
    UNREADABLE = "unreadable"


class CodexConfigError(ValueError):
    """Fail-closed rejection of an existing or requested Codex configuration.

    Attributes:
        code: The machine-readable :class:`CodexConfigRejection`.
    """

    def __init__(self, code: CodexConfigRejection, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_codex_config(raw: bytes) -> dict[str, object]:
    """Strictly parse and shape-validate an existing Codex configuration.

    Args:
        raw: The file's bytes.

    Returns:
        The parsed root table.

    Raises:
        CodexConfigError: On invalid UTF-8, a TOML syntax error (including
            duplicate keys/tables) or an AK3-relevant shape violation.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodexConfigError(
            CodexConfigRejection.NOT_UTF8,
            f"existing .codex/config.toml is not valid UTF-8: {exc}",
        ) from exc
    try:
        parsed: dict[str, object] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CodexConfigError(
            CodexConfigRejection.UNPARSABLE_TOML,
            f"existing .codex/config.toml is not valid TOML: {exc}",
        ) from exc
    _validate_shape(parsed)
    return parsed


def _validate_shape(parsed: Mapping[str, object]) -> None:
    """Validate the structure AK3 must be able to reason about.

    Structural checks (is it a table?) apply to EVERY entry, because AK3 cannot
    merge into a file whose ``mcp_servers`` is not a table. Field TYPE checks
    apply only to AK3-owned server tables: a foreign server's internal fields are
    not AK3's business and are preserved verbatim, so being strict about them
    would refuse an install over somebody else's configuration.
    """
    hooks = parsed.get(_HOOKS)
    if hooks is not None:
        if not isinstance(hooks, dict):
            raise CodexConfigError(
                CodexConfigRejection.HOOKS_NOT_TABLE,
                f"'{_HOOKS}' must be a TOML table; got {type(hooks).__name__}.",
            )
        entry = hooks.get(_PRE_TOOL_USE)
        if entry is not None and not isinstance(entry, dict):
            raise CodexConfigError(
                CodexConfigRejection.HOOK_ENTRY_NOT_TABLE,
                f"'{_HOOKS}.{_PRE_TOOL_USE}' must be a TOML table; got "
                f"{type(entry).__name__}.",
            )
    servers = parsed.get(_MCP_SERVERS)
    if servers is None:
        return
    if not isinstance(servers, dict):
        raise CodexConfigError(
            CodexConfigRejection.MCP_SERVERS_NOT_TABLE,
            f"'{_MCP_SERVERS}' must be a TOML table; got {type(servers).__name__}.",
        )
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            raise CodexConfigError(
                CodexConfigRejection.SERVER_ENTRY_NOT_TABLE,
                f"'{_MCP_SERVERS}.{name}' must be a TOML table; got "
                f"{type(entry).__name__}.",
            )
        if name in AK3_MCP_SERVER_NAMES:
            _validate_owned_server_fields(name, entry)


def _validate_owned_server_fields(name: str, entry: Mapping[str, object]) -> None:
    """Type-check the AK3-owned fields of an AK3-owned server table."""
    command = entry.get("command")
    if command is not None and (not isinstance(command, str) or not command.strip()):
        _reject_field(name, "command", "a non-empty string", command)
    args = entry.get("args")
    if args is not None and (
        not isinstance(args, list) or not all(isinstance(a, str) for a in args)
    ):
        _reject_field(name, "args", "an array of strings", args)
    cwd = entry.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
        _reject_field(name, "cwd", "a non-empty string", cwd)
    env = entry.get("env")
    if env is not None and (
        not isinstance(env, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
    ):
        _reject_field(name, "env", "a table of string-to-string", env)
    required = entry.get("required")
    if required is not None and not isinstance(required, bool):
        _reject_field(name, "required", "a boolean", required)


def _reject_field(name: str, field: str, expectation: str, value: object) -> None:
    """Raise a typed rejection for a wrongly typed AK3-owned server field."""
    raise CodexConfigError(
        CodexConfigRejection.SERVER_FIELD_TYPE_INVALID,
        f"'{_MCP_SERVERS}.{name}.{field}' must be {expectation}; got "
        f"{type(value).__name__} ({value!r}).",
    )


def _reject_foreign_occupation(
    parsed: Mapping[str, object], servers: Sequence[DesiredMcpServer]
) -> None:
    """Reject an AK3 server name occupied by a DIFFERENT program.

    Identity of a server registration is its ``command`` + ``args`` — the same
    identity notion the harness hook merges use (FK-76 §76.5.1: "Identitaet eines
    AK3-Handlers ist ``(hook_event_name, matcher, command)``"). If another tool
    registered a different program under an AK3 name, that is a real collision
    and must not be overwritten silently. If command and args match, the entry is
    AK3's own registration: its owned fields are upserted and any unknown field
    in that table is preserved (which is how AC 7's two clauses — reject a
    foreign-occupied name, preserve unknown harness fields — coexist).
    """
    existing = parsed.get(_MCP_SERVERS)
    if not isinstance(existing, dict):
        return
    for server in servers:
        current = existing.get(server.name)
        if not isinstance(current, dict):
            continue
        current_command = current.get("command")
        current_args = current.get("args")
        if current_command is None and current_args is None:
            continue
        if current_command != server.command or list(current_args or []) != list(
            server.args
        ):
            raise CodexConfigError(
                CodexConfigRejection.SERVER_NAME_FOREIGN_OCCUPIED,
                f"'{_MCP_SERVERS}.{server.name}' is occupied by a different "
                f"program (command={current_command!r}, args={current_args!r}); "
                f"AK3 would register command={server.command!r}, "
                f"args={list(server.args)!r}. Refusing to overwrite a foreign "
                "registration under an AK3 server name (fail-closed).",
            )


def classify_ownership(
    raw: bytes | None, *, hook_command: str
) -> CodexConfigOwnership:
    """Classify an existing Codex configuration by AK3 ownership.

    Never raises: an unreadable file is :attr:`CodexConfigOwnership.UNREADABLE`,
    because detach must preserve what it cannot read rather than delete it.

    Args:
        raw: The file's bytes, or ``None`` when the file does not exist.
        hook_command: The AK3 hook command that an AK3-owned file carries.

    Returns:
        The ownership classification.
    """
    if raw is None:
        return CodexConfigOwnership.FOREIGN
    try:
        parsed = load_codex_config(raw)
    except CodexConfigError:
        return CodexConfigOwnership.UNREADABLE

    hooks = parsed.get(_HOOKS)
    hooks_table: Mapping[str, object] = hooks if isinstance(hooks, dict) else {}
    servers = parsed.get(_MCP_SERVERS)
    servers_table: Mapping[str, object] = servers if isinstance(servers, dict) else {}

    foreign_top = set(parsed) - AK3_OWNED_TOP_LEVEL_KEYS
    foreign_hooks = set(hooks_table) - AK3_OWNED_HOOK_KEYS
    foreign_servers = set(servers_table) - AK3_MCP_SERVER_NAMES
    ak3_servers = {
        name: entry
        for name, entry in servers_table.items()
        if name in AK3_MCP_SERVER_NAMES and isinstance(entry, dict)
    }
    hook_entry = hooks_table.get(_PRE_TOOL_USE)
    hook_is_ak3 = hook_entry == {"command": hook_command}
    has_ak3_content = hook_is_ak3 or bool(ak3_servers)

    if not has_ak3_content:
        return CodexConfigOwnership.FOREIGN
    if foreign_top or foreign_hooks or foreign_servers or not hook_is_ak3:
        return CodexConfigOwnership.MIXED

    # Final gate: compare against the canonical rendering of exactly the AK3
    # content found. This is what keeps a comment-only user edit PRESERVED — a
    # value-based predicate cannot see a comment, and deleting such a file would
    # weaken the preserved_foreign_files guarantee.
    canonical = render_canonical_codex_config(
        hook_command=hook_command, server_tables=ak3_servers
    )
    if _normalize_newlines(raw) == _normalize_newlines(canonical.encode("utf-8")):
        return CodexConfigOwnership.AK3_ONLY
    return CodexConfigOwnership.MIXED


def _normalize_newlines(content: bytes) -> bytes:
    """Return ``content`` with CRLF/CR line endings normalised to LF.

    The ownership gate compares bytes, but a LINE ENDING is an encoding artifact
    of the same content, not foreign content. Without this normalisation a
    ``.codex/config.toml`` stored with CRLF — by a Windows editor, by
    ``core.autocrlf``, or by AK3 itself before this story pinned ``newline=""`` —
    would never match its canonical rendering, so detach would classify a file AK3
    wrote ITSELF as foreign and leave it behind. That is the same defect class as
    the fixed-string byte comparison this predicate replaces.

    Everything the gate must still catch survives normalisation: an added comment,
    extra blank lines, reordered keys and unknown fields are all differences in
    content, not in line endings.
    """
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _server_to_table_mapping(server: DesiredMcpServer) -> dict[str, object]:
    """Return the AK3-owned field mapping of a desired server."""
    return {
        "command": server.command,
        "args": list(server.args),
        "cwd": server.cwd,
        "env": server.env_dict(),
        "required": server.required,
    }


def _build_server_table(fields: Mapping[str, object]) -> tomlkit.items.Table:
    """Build a deterministic tomlkit table for one server entry.

    Emits ONLY :data:`AK3_OWNED_SERVER_FIELDS`. This is load-bearing for the
    ownership predicate, not a simplification: if the canonical rendering could
    reproduce an unknown field, then a file carrying such a field would
    re-render byte-identically and classify as
    :attr:`CodexConfigOwnership.AK3_ONLY` — and detach would DELETE the user's
    unknown field along with the file. Because the canonical rendering drops it,
    such a file necessarily differs from its canonical form and classifies as
    MIXED, i.e. preserved. Unknown fields are still preserved on the MERGE path,
    where the existing table is upserted in place rather than rebuilt.
    """
    table = tomlkit.table()
    for key in _SERVER_FIELD_ORDER:
        if key not in fields:
            continue
        value = fields[key]
        if key == "env" and isinstance(value, dict):
            env = tomlkit.inline_table()
            env.update({str(k): str(v) for k, v in value.items()})
            table[key] = env
        else:
            table[key] = value
    return table


def render_canonical_codex_config(
    *,
    hook_command: str,
    server_tables: Mapping[str, Mapping[str, object]],
) -> str:
    """Render an AK3-only Codex configuration from scratch, deterministically.

    Used for a fresh file AND to re-render a file that is already AK3-only. The
    second case matters: re-rendering (instead of patching in place) is what makes
    "a file AK3 wrote is byte-identical to its canonical rendering" true by
    construction, which the ownership predicate relies on. Patching would leave
    the classification hostage to layout details such as blank lines.

    Args:
        hook_command: The AK3 hook command for ``[hooks.pre_tool_use]``.
        server_tables: AK3-owned server name to its field mapping, any order.

    Returns:
        The rendered TOML document.
    """
    doc = tomlkit.document()
    doc.add(tomlkit.comment(AK3_CONFIG_HEADER_COMMENT))
    hooks = tomlkit.table(is_super_table=True)
    pre_tool_use = tomlkit.table()
    pre_tool_use["command"] = hook_command
    hooks[_PRE_TOOL_USE] = pre_tool_use
    doc[_HOOKS] = hooks
    if server_tables:
        servers = tomlkit.table(is_super_table=True)
        for name in sorted(server_tables):
            servers[name] = _build_server_table(server_tables[name])
        doc[_MCP_SERVERS] = servers
    return tomlkit.dumps(doc)


def render_codex_config(
    raw: bytes | None,
    *,
    hook_command: str,
    servers: Sequence[DesiredMcpServer] = (),
) -> str:
    """Render the Codex configuration with the AK3 content merged in.

    Semantics:

    * No file / already AK3-only -> canonical re-render of the UNION of the AK3
      server tables already present and the desired ones (desired win field-wise).
      Never removes a server AK3 wrote earlier, mirroring the ``.mcp.json`` merge.
    * Otherwise (mixed / foreign) -> semantic merge into the existing document,
      preserving foreign tables, foreign servers, unknown fields, comments,
      formatting and key order.
    * Unreadable -> :class:`CodexConfigError`, no output.

    Args:
        raw: Existing file bytes, or ``None`` when absent.
        hook_command: The AK3 hook command to materialise.
        servers: The desired AK3 server registrations.

    Returns:
        The full file content to write.

    Raises:
        CodexConfigError: On any rejection from :func:`load_codex_config`, a
            wrongly typed AK3-owned field, or an AK3 name occupied by a
            different program. Nothing is written in that case.
    """
    desired = {server.name: _server_to_table_mapping(server) for server in servers}
    if raw is None:
        return render_canonical_codex_config(
            hook_command=hook_command, server_tables=desired
        )

    parsed = load_codex_config(raw)
    _reject_foreign_occupation(parsed, servers)
    ownership = classify_ownership(raw, hook_command=hook_command)
    if ownership is CodexConfigOwnership.UNREADABLE:  # pragma: no cover - defensive
        raise CodexConfigError(
            CodexConfigRejection.UNPARSABLE_TOML,
            "existing .codex/config.toml is not readable; refusing to write.",
        )

    if ownership is CodexConfigOwnership.AK3_ONLY:
        existing_servers = parsed.get(_MCP_SERVERS)
        found: dict[str, Mapping[str, object]] = {}
        if isinstance(existing_servers, dict):
            found = {
                name: entry
                for name, entry in existing_servers.items()
                if name in AK3_MCP_SERVER_NAMES and isinstance(entry, dict)
            }
        union: dict[str, Mapping[str, object]] = dict(found)
        for name, fields in desired.items():
            merged = dict(found.get(name, {}))
            merged.update(fields)
            union[name] = merged
        return render_canonical_codex_config(
            hook_command=hook_command, server_tables=union
        )

    return _merge_into_existing(raw, hook_command=hook_command, desired=desired)


def _merge_into_existing(
    raw: bytes,
    *,
    hook_command: str,
    desired: Mapping[str, Mapping[str, object]],
) -> str:
    """Merge AK3 content into a document that also holds foreign content.

    Round-trip merge via tomlkit: everything AK3 does not touch — foreign tables,
    foreign servers, unknown fields, comments, blank lines and key order — is
    preserved byte-for-byte.
    """
    doc = tomlkit.parse(raw.decode("utf-8"))

    hooks = doc.get(_HOOKS)
    if not isinstance(hooks, dict):
        hooks = tomlkit.table(is_super_table=True)
        doc[_HOOKS] = hooks
    hook_entry = hooks.get(_PRE_TOOL_USE)
    if isinstance(hook_entry, dict):
        hook_entry["command"] = hook_command
    else:
        entry = tomlkit.table()
        entry["command"] = hook_command
        hooks[_PRE_TOOL_USE] = entry

    if desired:
        servers = doc.get(_MCP_SERVERS)
        if not isinstance(servers, dict):
            servers = tomlkit.table(is_super_table=True)
            doc[_MCP_SERVERS] = servers
        for name in sorted(desired):
            fields = desired[name]
            current = servers.get(name)
            if isinstance(current, dict):
                # Upsert owned fields only; unknown fields in OUR table survive.
                for key in _SERVER_FIELD_ORDER:
                    if key not in fields:
                        continue
                    value = fields[key]
                    if key == "env" and isinstance(value, dict):
                        env = tomlkit.inline_table()
                        env.update({str(k): str(v) for k, v in value.items()})
                        current[key] = env
                    else:
                        current[key] = value
            else:
                servers[name] = _build_server_table(fields)

    return tomlkit.dumps(doc)


__all__ = [
    "AK3_CONFIG_HEADER_COMMENT",
    "AK3_OWNED_HOOK_KEYS",
    "AK3_OWNED_SERVER_FIELDS",
    "AK3_OWNED_TOP_LEVEL_KEYS",
    "CodexConfigError",
    "CodexConfigOwnership",
    "CodexConfigRejection",
    "classify_ownership",
    "load_codex_config",
    "render_canonical_codex_config",
    "render_codex_config",
]
