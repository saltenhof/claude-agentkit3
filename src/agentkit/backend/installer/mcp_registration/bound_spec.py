"""Digest-bound ``McpServerSpec`` projection (AG3-175 AC 5 / Review 175-P0-1).

The Spec is rendered once, probed with AG3-164, and projected into both harness
formats **without re-derivation**. The probe digest is bound at probe time; any
post-probe field change is detected and refuses the write.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_PROBE_BINDING_MISMATCH,
)
from agentkit.backend.installer.mcp_conformance.types import McpServerCommand
from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
    CodexMcpServerEntry,
)

if TYPE_CHECKING:
    from agentkit.backend.vectordb.runtime_binding import McpServerSpec

#: Canonical JSON separators for digest stability.
_SEP: Final = (",", ":")


class ProbeBindingError(Exception):
    """Raised when a probed Spec no longer matches its bound digest."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.reason = REASON_MCP_PROBE_BINDING_MISMATCH
        self.detail = detail


@dataclass(frozen=True, slots=True)
class BoundMcpServerRegistration:
    """A server Spec that was probed and digest-bound for dual projection.

    Attributes:
        server_id: Harness server key (e.g. ``story-knowledge-base``).
        spec: The identical Spec object that was probed (no re-derivation).
        probe_digest: SHA-256 of the canonical Spec form at probe time.
    """

    server_id: str
    spec: McpServerSpec
    probe_digest: str


def canonical_spec_digest(spec: McpServerSpec) -> str:
    """Return the SHA-256 digest of the Spec's registration-relevant fields.

    No type coercion: env keys/values are serialized as-is so the digest proves
    identity rather than normalizing types (Review 175-N01).
    """
    payload = {
        "command": spec.command,
        "args": list(spec.args),
        "cwd": spec.cwd,
        "env": dict(sorted(spec.env.items())),
    }
    raw = json.dumps(payload, sort_keys=True, separators=_SEP).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bind_after_probe(server_id: str, spec: McpServerSpec) -> BoundMcpServerRegistration:
    """Bind ``spec`` after a successful AG3-164 conformance probe."""
    return BoundMcpServerRegistration(
        server_id=server_id,
        spec=spec,
        probe_digest=canonical_spec_digest(spec),
    )


def require_probe_binding(bound: BoundMcpServerRegistration) -> None:
    """Refuse write when the Spec no longer matches the probe-time digest."""
    current = canonical_spec_digest(bound.spec)
    if current != bound.probe_digest:
        raise ProbeBindingError(
            f"MCP server {bound.server_id!r} Spec diverged after probe "
            f"(probe_digest={bound.probe_digest[:16]}…, "
            f"current={current[:16]}…); refusing write "
            f"(reason={REASON_MCP_PROBE_BINDING_MISMATCH})."
        )


def spec_to_conformance_command(spec: McpServerSpec) -> McpServerCommand:
    """Build the AG3-164 probe command **from the Spec only** (no re-derivation)."""
    return McpServerCommand(
        command=spec.command,
        args=list(spec.args),
        env=dict(spec.env),
        cwd=spec.cwd,
    )


def project_spec_to_claude_entry(spec: McpServerSpec) -> dict[str, object]:
    """Project the bound Spec into a Claude Code ``.mcp.json`` server entry."""
    return {
        "type": "stdio",
        "command": spec.command,
        "args": list(spec.args),
        "cwd": spec.cwd,
        "env": dict(spec.env),
    }


def project_spec_to_codex_entry(spec: McpServerSpec) -> CodexMcpServerEntry:
    """Project the bound Spec into a Codex ``[mcp_servers.<id>]`` entry."""
    return CodexMcpServerEntry(
        command=spec.command,
        args=tuple(spec.args),
        cwd=spec.cwd,
        env=dict(spec.env),
        required=True,
    )


__all__ = [
    "BoundMcpServerRegistration",
    "ProbeBindingError",
    "bind_after_probe",
    "canonical_spec_digest",
    "project_spec_to_claude_entry",
    "project_spec_to_codex_entry",
    "require_probe_binding",
    "spec_to_conformance_command",
]
