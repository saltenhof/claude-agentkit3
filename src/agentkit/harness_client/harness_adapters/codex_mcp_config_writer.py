"""Codex project-local MCP config writer (FK-76 §76.5.4, AG3-175).

Single source of truth for writing ``[mcp_servers.<id>]`` into the
**project-local** ``.codex/config.toml``. Mirrors the Claude Code
``.mcp.json`` registration contract:

* project-local only — never userspace (``~/.codex/``, ``CODEX_HOME``)
* semantic merge — foreign content is **surgically preserved as source text**
  (datetime/date/time, array-of-tables, nested tables, control-char strings,
  unknown fields stay byte-stable except the owned server span)
* fail-closed — no library leniency, no type coercion, no last-wins
* each write is atomic for this single file

**Merge strategy (Review 175-R01/R02):** a text-preserving surgical UPSERT of
only the AK3-owned ``[mcp_servers.<id>]`` (+ ``.env``) tables. The document is
parsed with ``tomllib`` for validation and change detection, but foreign spans
are never re-serialized. This is the root fix for over-strict full-document
re-serialization that rejected valid foreign TOML constructs.

This module owns the Codex MCP **format**. The installer (FK-50 §50.3 CP 10)
owns when registration runs and the conformance precondition.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agentkit.backend.utils.io import atomic_write_text

#: Machine-readable reason: target ``.codex/config.toml`` not strictly loadable.
REASON_CODEX_MCP_CONFIGURATION_INVALID: Final = "mcp_configuration_invalid"
#: Machine-readable reason: path escapes the project root (symlink/junction).
REASON_CODEX_MCP_PATH_ESCAPE: Final = "mcp_configuration_invalid"

#: Project-local Codex directory name (FK-76 §76.5.4 — format ownership).
_CODEX_DIR: Final = ".codex"
#: Project-local Codex config file name (FK-76 §76.5.4).
_CODEX_CONFIG_FILE: Final = "config.toml"

_BARE_KEY_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")
#: Any TOML table / array-of-tables header line.
_ANY_HEADER_RE: Final = re.compile(r"^\s*\[")
#: Exactly the parent ``[mcp_servers]`` table (not a dotted sub-table).
_MCP_SERVERS_PARENT_RE: Final = re.compile(r"^\[mcp_servers\]\s*(?:#.*)?$")


class CodexMcpConfigError(Exception):
    """Fail-closed error from the Codex MCP config writer.

    Attributes:
        reason: Stable machine-readable reason token (ARCH-55).
        detail: Human-readable explanation.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CodexMcpServerEntry:
    """Fields written under ``[mcp_servers.<id>]`` (FK-76 §76.5.4).

    Attributes:
        command: Executable to start.
        args: Argument vector.
        cwd: Working directory / containment boundary.
        env: Environment map (string keys and values only).
        required: Always ``True`` for AK3-managed servers.
    """

    command: str
    args: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    required: bool = True

    def as_table_dict(self) -> dict[str, object]:
        """Return a plain dict suitable for merge/equality checks."""
        return {
            "command": self.command,
            "args": list(self.args),
            "cwd": self.cwd,
            "env": dict(self.env),
            "required": self.required,
        }


def project_codex_mcp_config_path(project_root: Path) -> Path:
    """Return the project-local ``.codex/config.toml`` path (never userspace)."""
    return Path(project_root) / _CODEX_DIR / _CODEX_CONFIG_FILE


def merge_mcp_server(
    project_root: Path,
    server_id: str,
    entry: CodexMcpServerEntry,
    *,
    rendered_text: str | None = None,
) -> tuple[str, bool]:
    """Merge ``entry`` into project-local ``.codex/config.toml`` (idempotent UPSERT).

    Surgical text merge: validates with ``tomllib``, then inserts/replaces only
    the owned server tables. Foreign bytes are left intact.

    Returns:
        ``(rendered_toml, changed)``.

    Raises:
        CodexMcpConfigError: On fail-closed matrix violation or path escape.
    """
    _validate_server_id(server_id)
    _validate_entry_types(entry)
    config_path = _resolve_contained_config_path(project_root)

    if rendered_text is not None:
        text = rendered_text
        present = True
    elif config_path.is_file() or config_path.is_symlink():
        text = _read_utf8_strict(config_path)
        present = True
    else:
        text = ""
        present = False

    return surgical_merge_mcp_server(text if present else "", server_id, entry)


def write_mcp_server(
    project_root: Path,
    server_id: str,
    entry: CodexMcpServerEntry,
) -> Path:
    """Atomically write the surgically merged project-local Codex MCP config.

    Never writes under userspace ``CODEX_HOME`` or ``~/.codex``.
    """
    config_path = _resolve_contained_config_path(project_root)
    rendered, _changed = merge_mcp_server(project_root, server_id, entry)
    _resolve_contained_config_path(project_root)
    atomic_write_text(config_path, rendered, newline="\n")
    return config_path


def load_codex_mcp_document(
    project_root: Path,
) -> tuple[dict[str, object] | None, bytes | None, str | None]:
    """Strict-load project-local ``.codex/config.toml`` for dual-file coordination.

    Returns:
        ``({}, None, None)`` when absent.
        ``(root, before_bytes, None)`` when present and valid.
        ``(None, before_bytes_or_None, detail)`` when present but invalid.
    """
    config_path = project_codex_mcp_config_path(project_root)
    try:
        _resolve_contained_config_path(project_root)
    except CodexMcpConfigError as exc:
        before: bytes | None = None
        if config_path.exists() or config_path.is_symlink():
            try:
                before = config_path.read_bytes()
            except OSError:
                before = None
        return None, before, exc.detail

    if not config_path.exists() and not config_path.is_symlink():
        return {}, None, None

    try:
        before_bytes = config_path.read_bytes()
    except OSError as exc:
        return None, None, f"cannot read project .codex/config.toml: {exc}"

    try:
        text = before_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, before_bytes, f"project .codex/config.toml is not valid UTF-8: {exc}"

    try:
        root = _strict_load_toml(text, present=True)
    except CodexMcpConfigError as exc:
        return None, before_bytes, exc.detail
    return root, before_bytes, None


def render_merged_codex_mcp(
    existing_text: str,
    server_id: str,
    entry: CodexMcpServerEntry,
) -> tuple[str, bool]:
    """Surgically merge ``entry`` into existing TOML source text (no I/O).

    Used by CP 10 two-file coordination so both harness files are fully prepared
    before the first write. ``existing_text`` is the raw UTF-8 source (empty
    string when the file is absent).
    """
    return surgical_merge_mcp_server(existing_text, server_id, entry)


def surgical_remove_mcp_server(
    existing_text: str,
    server_id: str,
) -> tuple[str, bool]:
    """Remove only ``[mcp_servers.<id>]`` spans; preserve all foreign bytes.

    Returns ``(new_text, changed)``. Empty ``existing_text`` is a no-op.
    Validates the document first (fail-closed on unreadable shape).
    """
    _validate_server_id(server_id)
    if existing_text == "":
        return "", False
    _strict_load_toml(existing_text, present=True)
    stripped = _remove_owned_server_spans(existing_text, server_id)
    if stripped == existing_text:
        return existing_text, False
    if stripped.strip():
        _strict_load_toml(stripped, present=True)
    return stripped, True


def surgical_merge_mcp_server(
    existing_text: str,
    server_id: str,
    entry: CodexMcpServerEntry,
) -> tuple[str, bool]:
    """Validate ``existing_text`` and UPSERT the owned server tables surgically.

    * Parse with ``tomllib`` (fail-closed on invalid TOML / bad ``mcp_servers``
      shape / wrong types on known server fields).
    * Foreign constructs (datetime, AoT, nested tables, control-char strings,
      unknown keys) are **not** re-serialized — their source spans stay.
    * Only ``[mcp_servers.<id>]`` and ``[mcp_servers.<id>.*]`` (plus an inline
      key under bare ``[mcp_servers]``) are removed/replaced.
    * When the owned server is already value-equal, the original text is
      returned unchanged (``changed=False``).
    """
    _validate_server_id(server_id)
    _validate_entry_types(entry)

    present = existing_text != ""
    root = _strict_load_toml(existing_text, present=present)
    servers = _mcp_servers_view(root)
    desired = entry.as_table_dict()
    existing = servers.get(server_id)

    if existing is not None and not isinstance(existing, dict):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"Codex mcp_servers.{server_id!r} is occupied by a non-table value "
            f"({type(existing).__name__}); refusing mutation (fail-closed).",
        )
    if existing == desired:
        return existing_text, False

    stripped = _remove_owned_server_spans(existing_text, server_id)
    owned_block = _render_owned_server_block(server_id, entry)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    if stripped and not stripped.endswith("\n\n"):
        # Separate foreign body from the owned block with a blank line when body
        # does not already end with one.
        if not stripped.endswith("\n"):
            stripped += "\n"
        if not stripped.endswith("\n\n"):
            stripped += "\n"
    rendered = stripped + owned_block
    if not rendered.endswith("\n"):
        rendered += "\n"

    # Post-condition: result must re-parse and carry the desired server.
    reloaded = _strict_load_toml(rendered, present=True)
    reloaded_servers = _mcp_servers_view(reloaded)
    if reloaded_servers.get(server_id) != desired:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"surgical merge failed to install mcp_servers.{server_id!r} "
            "(fail-closed).",
        )
    return rendered, True


def _render_owned_server_block(server_id: str, entry: CodexMcpServerEntry) -> str:
    """Render only the AK3-owned dotted tables (values we fully control)."""
    args_items = ", ".join(_format_toml_string(a) for a in entry.args)
    lines = [
        f"[mcp_servers.{server_id}]",
        f"command = {_format_toml_string(entry.command)}",
        f"args = [{args_items}]",
        f"cwd = {_format_toml_string(entry.cwd)}",
        "required = true",
        "",
        f"[mcp_servers.{server_id}.env]",
    ]
    for key in sorted(entry.env):
        lines.append(f"{_format_key(key)} = {_format_toml_string(entry.env[key])}")
    lines.append("")
    return "\n".join(lines)


def _format_key(key: str) -> str:
    if _BARE_KEY_RE.match(key):
        return key
    return _format_toml_string(key)


def _format_toml_string(value: str) -> str:
    """Format a basic TOML string with full control-char escaping.

    Escapes ``\\``, ``"``, short escapes, and every remaining C0 control plus
    DEL as ``\\uXXXX`` so the writer never emits unparseable TOML for values it
    serializes (owned entry fields).
    """
    parts: list[str] = []
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            parts.append("\\\\")
        elif ch == '"':
            parts.append('\\"')
        elif ch == "\b":
            parts.append("\\b")
        elif ch == "\t":
            parts.append("\\t")
        elif ch == "\n":
            parts.append("\\n")
        elif ch == "\f":
            parts.append("\\f")
        elif ch == "\r":
            parts.append("\\r")
        elif code < 0x20 or code == 0x7F:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(ch)
    return f'"{"".join(parts)}"'


def _owned_dotted_header_re(server_id: str) -> re.Pattern[str]:
    sid = re.escape(server_id)
    # [mcp_servers.<id>] and [mcp_servers.<id>.…] with bare or quoted id.
    return re.compile(
        rf"^\[mcp_servers\.(?:\"{sid}\"|'{sid}'|{sid})(?:\.[^\]]+)?\]\s*(?:#.*)?$"
    )


def _owned_inline_key_re(server_id: str) -> re.Pattern[str]:
    sid = re.escape(server_id)
    return re.compile(rf"^(?:\"{sid}\"|'{sid}'|{sid})\s*=")


def _remove_owned_server_spans(text: str, server_id: str) -> str:
    """Remove source spans that define the owned server; keep all other bytes."""
    if text == "":
        return ""
    lines = text.splitlines(keepends=True)
    owned_header = _owned_dotted_header_re(server_id)
    owned_key = _owned_inline_key_re(server_id)
    drop: set[int] = set()
    i = 0
    in_mcp_servers_parent = False
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        # Track bare [mcp_servers] parent for inline-key removal.
        if _MCP_SERVERS_PARENT_RE.match(stripped):
            in_mcp_servers_parent = True
            i += 1
            continue
        if _ANY_HEADER_RE.match(raw):
            in_mcp_servers_parent = False
            if owned_header.match(stripped):
                # Drop this header and body until the next table header.
                drop.add(i)
                i += 1
                while i < len(lines) and not _ANY_HEADER_RE.match(lines[i]):
                    drop.add(i)
                    i += 1
                continue
            i += 1
            continue
        if in_mcp_servers_parent and owned_key.match(stripped):
            end = _assignment_end_index(lines, i)
            for j in range(i, end):
                drop.add(j)
            i = end
            continue
        i += 1

    kept = [line for idx, line in enumerate(lines) if idx not in drop]
    return "".join(kept)


def _assignment_end_index(lines: list[str], start: int) -> int:
    """Return exclusive end index of a key = value starting at ``start``."""
    # Accumulate until braces/brackets/strings are balanced and we hit EOL of
    # the complete assignment. Single-line is the common case.
    buf = ""
    i = start
    while i < len(lines):
        buf += lines[i]
        if _assignment_complete(buf):
            return i + 1
        i += 1
    return len(lines)


def _assignment_complete(text: str) -> bool:
    """Heuristic: assignment text is complete when brackets/braces/strings close."""
    # Strip comment only when not inside a string — keep simple state machine.
    in_string = False
    escape = False
    string_delim = ""
    brace = 0
    bracket = 0
    saw_eq = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == string_delim:
                in_string = False
            continue
        if ch in "\"'":
            in_string = True
            string_delim = ch
            continue
        if ch == "#":
            # Rest of line is comment; assignment complete if containers closed.
            break
        if ch == "=" and not saw_eq:
            saw_eq = True
            continue
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1
    if not saw_eq:
        return False
    return brace == 0 and bracket == 0 and not in_string


def _validate_server_id(server_id: str) -> None:
    if not isinstance(server_id, str) or not server_id.strip():
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP server id must be a non-empty string (fail-closed).",
        )
    if not _BARE_KEY_RE.match(server_id):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"Codex MCP server id {server_id!r} is not a bare TOML key (fail-closed).",
        )


def _validate_entry_types(entry: CodexMcpServerEntry) -> None:
    if not isinstance(entry.command, str) or not entry.command.strip():
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP 'command' must be a non-empty string (fail-closed).",
        )
    if not isinstance(entry.args, (list, tuple)) or not all(
        isinstance(a, str) for a in entry.args
    ):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP 'args' must be a sequence of strings (fail-closed).",
        )
    if not isinstance(entry.cwd, str) or not entry.cwd.strip():
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP 'cwd' must be a non-empty string (fail-closed).",
        )
    if not isinstance(entry.env, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in entry.env.items()
    ):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP 'env' must be a string-to-string mapping (fail-closed).",
        )
    if entry.required is not True:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex MCP 'required' must be true for AK3-managed servers (fail-closed).",
        )


def _resolve_contained_config_path(project_root: Path) -> Path:
    """Resolve ``project_root/.codex/config.toml`` and refuse path escape."""
    if not isinstance(project_root, Path):
        project_root = Path(project_root)
    try:
        root = project_root.resolve(strict=False)
    except OSError as exc:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_PATH_ESCAPE,
            f"cannot resolve project_root {project_root}: {exc}",
        ) from exc

    codex_dir = root / _CODEX_DIR
    config_path = codex_dir / _CODEX_CONFIG_FILE

    for candidate in _userspace_codex_paths():
        try:
            if config_path.resolve(strict=False) == candidate.resolve(strict=False):
                raise CodexMcpConfigError(
                    REASON_CODEX_MCP_PATH_ESCAPE,
                    "refusing to write Codex userspace/global config "
                    f"({candidate}); only project-local .codex/config.toml is allowed.",
                )
        except OSError:
            continue

    _assert_path_contained(root, codex_dir)
    _assert_path_contained(root, config_path)
    return config_path


def _userspace_codex_paths() -> list[Path]:
    paths: list[Path] = []
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        paths.append(Path(codex_home) / _CODEX_CONFIG_FILE)
        paths.append(Path(codex_home))
    home = Path.home()
    paths.append(home / ".codex" / _CODEX_CONFIG_FILE)
    paths.append(home / ".codex")
    return paths


def _assert_path_contained(project_root: Path, path: Path) -> None:
    try:
        parts_from_root = path.relative_to(project_root)
    except ValueError as exc:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_PATH_ESCAPE,
            f"path {path} is outside project root {project_root} (fail-closed).",
        ) from exc

    cursor = project_root
    for part in parts_from_root.parts:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            try:
                resolved = cursor.resolve(strict=False)
                resolved.relative_to(project_root.resolve(strict=False))
            except (OSError, ValueError) as exc:
                raise CodexMcpConfigError(
                    REASON_CODEX_MCP_PATH_ESCAPE,
                    f"symlink/junction at {cursor} escapes project root "
                    f"{project_root} (fail-closed).",
                ) from exc


def _read_utf8_strict(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"cannot read project .codex/config.toml: {exc}",
        ) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"project .codex/config.toml is not valid UTF-8: {exc}",
        ) from exc


def _strict_load_toml(text: str, *, present: bool) -> dict[str, object]:
    """Parse TOML fail-closed; validate only ``mcp_servers`` shape, not foreign types.

    Foreign root values may be datetime/date/time, lists of tables (AoT), etc.
    Those are accepted as long as ``tomllib`` accepts the document — they are
    never re-serialized by this writer.
    """
    if not present or text == "":
        return {}
    try:
        loaded: object = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"project .codex/config.toml is not strict TOML: {exc}",
        ) from exc
    if not isinstance(loaded, dict):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"project .codex/config.toml root must be a table; got {type(loaded).__name__}.",
        )
    if "mcp_servers" in loaded:
        servers = loaded["mcp_servers"]
        if not isinstance(servers, dict):
            raise CodexMcpConfigError(
                REASON_CODEX_MCP_CONFIGURATION_INVALID,
                "Codex 'mcp_servers' must be a table; "
                f"got {type(servers).__name__} (fail-closed).",
            )
        for name, entry in servers.items():
            if not isinstance(name, str):
                raise CodexMcpConfigError(
                    REASON_CODEX_MCP_CONFIGURATION_INVALID,
                    "Codex mcp_servers keys must be strings (fail-closed).",
                )
            if not isinstance(entry, dict):
                raise CodexMcpConfigError(
                    REASON_CODEX_MCP_CONFIGURATION_INVALID,
                    f"Codex mcp_servers.{name!r} must be a table; "
                    f"got {type(entry).__name__} (fail-closed).",
                )
            _validate_existing_server_shape(name, entry)
    return {str(k): v for k, v in loaded.items()}


def _mcp_servers_view(root: dict[str, object]) -> dict[str, object]:
    raw = root.get("mcp_servers")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            "Codex 'mcp_servers' must be a table; "
            f"got {type(raw).__name__} (fail-closed).",
        )
    return dict(raw)


def _validate_existing_server_shape(name: str, entry: Mapping[str, object]) -> None:
    """Type-check known fields when present; leave unknown fields alone."""
    if "command" in entry and not isinstance(entry["command"], str):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"Codex mcp_servers.{name}.command must be a string; "
            f"got {type(entry['command']).__name__} (fail-closed).",
        )
    if "args" in entry:
        args = entry["args"]
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise CodexMcpConfigError(
                REASON_CODEX_MCP_CONFIGURATION_INVALID,
                f"Codex mcp_servers.{name}.args must be an array of strings "
                "(fail-closed).",
            )
    if "cwd" in entry:
        cwd = entry["cwd"]
        if not isinstance(cwd, str):
            raise CodexMcpConfigError(
                REASON_CODEX_MCP_CONFIGURATION_INVALID,
                f"Codex mcp_servers.{name}.cwd must be a string; "
                f"got {type(cwd).__name__} (fail-closed).",
            )
    if "env" in entry:
        env = entry["env"]
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise CodexMcpConfigError(
                REASON_CODEX_MCP_CONFIGURATION_INVALID,
                f"Codex mcp_servers.{name}.env must be a string-to-string table "
                "(fail-closed).",
            )
    if "required" in entry and not isinstance(entry["required"], bool):
        raise CodexMcpConfigError(
            REASON_CODEX_MCP_CONFIGURATION_INVALID,
            f"Codex mcp_servers.{name}.required must be a boolean; "
            f"got {type(entry['required']).__name__} (fail-closed).",
        )


__all__ = [
    "REASON_CODEX_MCP_CONFIGURATION_INVALID",
    "REASON_CODEX_MCP_PATH_ESCAPE",
    "CodexMcpConfigError",
    "CodexMcpServerEntry",
    "load_codex_mcp_document",
    "merge_mcp_server",
    "project_codex_mcp_config_path",
    "render_merged_codex_mcp",
    "surgical_merge_mcp_server",
    "surgical_remove_mcp_server",
    "write_mcp_server",
]
