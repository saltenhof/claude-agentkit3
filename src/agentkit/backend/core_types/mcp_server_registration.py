"""Harness-neutral MCP-server registration contract (AG3-175, FK-76 §76.5.4).

This module is the SINGLE SOURCE OF TRUTH for *what* gets registered as an MCP
server, independent of *which* harness format it is projected into. It carries:

- :data:`REGISTERED_ENV_KEYS` — the environment keys the registration renders.
- :data:`AK3_MCP_SERVER_NAMES` — the server names AK3 owns (ownership predicate
  for the Codex config classification and the ``.mcp.json`` merge).
- :class:`DesiredMcpServer` — the immutable, strictly validated registration
  value object.
- :func:`canonical_registration_payload` / :func:`registration_digest` — the
  canonical serialisation and its digest that bind the PROBED registration to
  the WRITTEN one (AG3-175 Scope 1 / AC 5: one spec, rendered once, projected
  into both formats without re-derivation).

Why it lives in ``core_types``: FK-76 §76.9 fixes the import direction —
``installation-and-bootstrap`` calls ``harness_integration``, never the reverse.
Both the installer (which decides *whether/when* to register, FK-50 §50.3 CP 10)
and the Codex harness adapter (which owns the *format*, FK-76 §76.5.4) need this
contract, so it belongs in the BC-neutral foundation. Per the architecture
conformance boundary ``architecture-conformance.boundary.core_types`` (bloodgroup
A, ``domain_core_foundation``) this module imports ONLY stdlib.

Deliberately NOT here: the bridge to the conformance probe's
``McpServerCommand`` and the projection into ``.codex/config.toml``. Both would
require importing an installer / harness module and would break the leaf
property; they live with their owners.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: MCP server key of the FK-13 story-knowledge-base server (FK-50 §50.3 CP 10).
STORY_KNOWLEDGE_BASE_SERVER: str = "story-knowledge-base"

#: MCP server key of the ARE integration (FK-03 §3.1 binds ``are.mcp_server``).
ARE_MCP_SERVER: str = "are-mcp"

#: Server names AK3 owns in a harness MCP configuration.
#:
#: Deliberately INDEPENDENT of the current feature flags: "which names belong to
#: AK3" is an ownership statement, not a runtime question. A feature-dependent set
#: would make ``detach`` classify an ``are-mcp`` table that AK3 itself wrote as
#: foreign (and therefore leave it behind) as soon as ``features.are`` is off.
AK3_MCP_SERVER_NAMES: frozenset[str] = frozenset(
    {STORY_KNOWLEDGE_BASE_SERVER, ARE_MCP_SERVER}
)

#: Environment keys rendered into the story-knowledge-base registration.
#:
#: This is the set the STARTED PROCESS requires, which is strictly larger than
#: the set ``vectordb.runtime_binding.REQUIRED_ENV_KEYS`` validates: the runtime
#: binding checks ``PROJECT_ID`` plus both Weaviate endpoints, while the stdio
#: entry point ``vectordb.engine.main`` additionally requires
#: ``AGENTKIT_CONCEPTS_DIR`` (no default — a default once pointed the server at
#: AK3's own development corpus, N20/D2) and honours ``AGENTKIT_STORIES_DIR``.
#:
#: ``AGENTKIT_STORIES_DIR`` is rendered EXPLICITLY although the entry point
#: defaults it, because the default resolves against the process ``cwd`` and D2
#: forbids ``cwd`` from being a second configuration source; a project that
#: configures a different story root would otherwise be indexed from the wrong
#: directory silently.
#:
#: A contract test pins this as a superset of ``REQUIRED_ENV_KEYS`` so a future
#: addition there fails loudly instead of shipping an incomplete environment.
REGISTERED_ENV_KEYS: tuple[str, ...] = (
    "PROJECT_ID",
    "WEAVIATE_HTTP_ENDPOINT",
    "WEAVIATE_GRPC_ENDPOINT",
    "AGENTKIT_CONCEPTS_DIR",
    "AGENTKIT_STORIES_DIR",
)

#: Wire value of the MCP transport in a ``.mcp.json`` server entry.
MCP_JSON_STDIO_TYPE: str = "stdio"

#: Digest domain tag: keeps the registration digest from ever colliding with a
#: digest computed over some other canonical payload in the codebase.
_DIGEST_DOMAIN: str = "agentkit.mcp-server-registration.v1"

#: A server name must be a safe, quotable TOML/JSON key: no whitespace, no dots
#: that would create an unintended nested TOML table, no quotes or brackets.
_SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class McpServerRegistrationError(ValueError):
    """Raised when a desired MCP registration is invalid or has been altered.

    Used both for construction-time validation of :class:`DesiredMcpServer` and
    for the post-probe binding check (:func:`registration_digest` mismatch).
    """


@dataclass(frozen=True, slots=True)
class DesiredMcpServer:
    """One MCP server AK3 wants registered, fully rendered and immutable.

    Frozen and slotted on purpose: AG3-175 AC 5 requires that a field cannot be
    changed after the conformance probe. ``frozen=True`` makes in-place mutation
    impossible (rather than merely discouraged), and every collection field is a
    ``tuple`` so no element can be appended behind the digest's back. A
    substitution via :func:`dataclasses.replace` remains possible by design and
    is what :func:`registration_digest` detects.

    Attributes:
        name: Server key in the harness configuration (``mcpServers.<name>`` /
            ``[mcp_servers.<name>]``).
        command: Executable command, resolved by the harness against ``cwd`` or
            ``PATH``.
        args: Full argument vector.
        cwd: Working / containment boundary. NOT a configuration source (D2).
        env: Fully rendered environment as ordered ``(key, value)`` pairs.
        required: Whether the harness must treat the server as mandatory
            (FK-76 §76.5.4 ``required = true``). Projected only into formats
            that model it.
    """

    name: str
    command: str
    args: tuple[str, ...]
    cwd: str
    env: tuple[tuple[str, str], ...]
    required: bool = True

    def __post_init__(self) -> None:
        """Validate the rendered registration fail-closed.

        Raises:
            McpServerRegistrationError: On any missing, empty, wrongly typed or
                structurally unsafe field.
        """
        self._check_name()
        self._check_command()
        self._check_args()
        self._check_cwd()
        self._check_env()
        if not isinstance(self.required, bool):
            raise McpServerRegistrationError(
                f"server {self.name!r}: 'required' must be a real bool, got "
                f"{type(self.required).__name__} (no truthy coercion, fail-closed)."
            )

    def _check_name(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise McpServerRegistrationError(
                "MCP server name is missing/empty (fail-closed)."
            )
        if not _SERVER_NAME_PATTERN.fullmatch(self.name):
            raise McpServerRegistrationError(
                f"MCP server name {self.name!r} is not a safe configuration key; "
                "expected [A-Za-z0-9][A-Za-z0-9_-]* (fail-closed)."
            )

    def _check_command(self) -> None:
        if not isinstance(self.command, str) or not self.command.strip():
            raise McpServerRegistrationError(
                f"server {self.name!r}: 'command' must be a non-empty string "
                "(fail-closed)."
            )

    def _check_args(self) -> None:
        if not isinstance(self.args, tuple):
            raise McpServerRegistrationError(
                f"server {self.name!r}: 'args' must be a tuple so the rendered "
                f"registration stays immutable, got {type(self.args).__name__}."
            )
        for arg in self.args:
            if not isinstance(arg, str):
                raise McpServerRegistrationError(
                    f"server {self.name!r}: every arg must be a string, got "
                    f"{type(arg).__name__}."
                )

    def _check_cwd(self) -> None:
        if not isinstance(self.cwd, str) or not self.cwd.strip():
            raise McpServerRegistrationError(
                f"server {self.name!r}: 'cwd' must be a non-empty string; it is "
                "the containment boundary (fail-closed)."
            )

    def _check_env(self) -> None:
        if not isinstance(self.env, tuple):
            raise McpServerRegistrationError(
                f"server {self.name!r}: 'env' must be a tuple of (key, value) "
                f"pairs, got {type(self.env).__name__}."
            )
        seen: set[str] = set()
        for pair in self.env:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise McpServerRegistrationError(
                    f"server {self.name!r}: every env entry must be a "
                    "(key, value) pair (fail-closed)."
                )
            key, value = pair
            if not isinstance(key, str) or not key.strip():
                raise McpServerRegistrationError(
                    f"server {self.name!r}: env keys must be non-empty strings."
                )
            if not isinstance(value, str):
                raise McpServerRegistrationError(
                    f"server {self.name!r}: env value for {key!r} must be a "
                    f"string, got {type(value).__name__}."
                )
            if key in seen:
                raise McpServerRegistrationError(
                    f"server {self.name!r}: duplicate env key {key!r} "
                    "(fail-closed, no last-wins)."
                )
            seen.add(key)

    def env_dict(self) -> dict[str, str]:
        """Return the rendered environment as a dict (declared order preserved)."""
        return dict(self.env)

    def to_mcp_json_entry(self) -> dict[str, object]:
        """Project into a Claude-Code ``.mcp.json`` server entry (FK-76 §76.5.4).

        ``required`` is not part of the ``.mcp.json`` shape (Claude Code has no
        such field); it is projected only into the Codex table. ``cwd`` IS part
        of the entry — the AK3 repo's own ``.mcp.json`` uses it productively.
        """
        return {
            "type": MCP_JSON_STDIO_TYPE,
            "command": self.command,
            "args": list(self.args),
            "cwd": self.cwd,
            "env": self.env_dict(),
        }


def before_image_fingerprint(content: bytes | None) -> str | None:
    """Return the digest of a before-image file, or ``None`` when it was absent.

    The before-image is represented by a digest rather than by its raw bytes:
    an existing harness config may be invalid UTF-8 (which is itself a rejection
    case), so it cannot be embedded in a JSON payload verbatim. ``None`` is a
    genuine state — "the file did not exist" — and must stay distinguishable
    from "the file existed and was empty", because a rollback has to DELETE in
    the first case and restore empty content in the second.

    Args:
        content: The file's bytes as read before any write, or ``None`` if the
            file did not exist.

    Returns:
        The hex SHA-256 digest, or ``None`` for an absent file.
    """
    if content is None:
        return None
    return hashlib.sha256(content).hexdigest()


def canonical_registration_payload(
    servers: Sequence[DesiredMcpServer],
    *,
    mcp_json_text: str,
    codex_toml_text: str,
    before_image: Mapping[str, str | None] | None = None,
) -> str:
    """Return the canonical serialisation that the registration digest covers.

    The payload spans the server specs, the two fully rendered texts AND the
    before-image fingerprints. Covering the texts closes the gap "probed object
    X, but wrote a text rendered from object Y". Covering the before-image is
    what makes it a *bound* before-image: a rollback cannot restore the content
    of another file or another run, because specs, rendered texts and
    before-image form one digest-protected unit.

    Determinism: servers are sorted by name, env pairs are sorted by key, and
    ``json.dumps`` runs with ``sort_keys=True`` and fixed separators, so the
    payload depends on the values only — never on declaration or dict order.

    Args:
        servers: The desired servers (any order; sorted internally).
        mcp_json_text: The fully rendered ``.mcp.json`` content.
        codex_toml_text: The fully rendered ``.codex/config.toml`` content.
        before_image: Mapping of artifact name to before-image fingerprint (see
            :func:`before_image_fingerprint`). ``None`` means "not bound".

    Returns:
        The canonical JSON string.
    """
    payload = {
        "domain": _DIGEST_DOMAIN,
        "servers": [
            {
                "name": server.name,
                "command": server.command,
                "args": list(server.args),
                "cwd": server.cwd,
                "env": [list(pair) for pair in sorted(server.env)],
                "required": server.required,
            }
            for server in sorted(servers, key=lambda item: item.name)
        ],
        "mcp_json_text": mcp_json_text,
        "codex_toml_text": codex_toml_text,
        "before_image": dict(before_image) if before_image is not None else None,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def registration_digest(
    servers: Sequence[DesiredMcpServer],
    *,
    mcp_json_text: str,
    codex_toml_text: str,
    before_image: Mapping[str, str | None] | None = None,
) -> str:
    """Return the SHA-256 hex digest of the canonical registration payload.

    Args:
        servers: The desired servers.
        mcp_json_text: The fully rendered ``.mcp.json`` content.
        codex_toml_text: The fully rendered ``.codex/config.toml`` content.
        before_image: Before-image fingerprints to bind into the digest.

    Returns:
        The hex digest binding specs, rendered texts and before-image together.
    """
    canonical = canonical_registration_payload(
        servers,
        mcp_json_text=mcp_json_text,
        codex_toml_text=codex_toml_text,
        before_image=before_image,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "AK3_MCP_SERVER_NAMES",
    "ARE_MCP_SERVER",
    "MCP_JSON_STDIO_TYPE",
    "REGISTERED_ENV_KEYS",
    "STORY_KNOWLEDGE_BASE_SERVER",
    "DesiredMcpServer",
    "McpServerRegistrationError",
    "before_image_fingerprint",
    "canonical_registration_payload",
    "registration_digest",
]
