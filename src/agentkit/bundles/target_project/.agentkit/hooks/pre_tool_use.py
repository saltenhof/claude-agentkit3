"""Project-local pre-tool hook wrapper.

Registered on ``Bash|Write|Edit|Read|Grep|Glob`` and started WITHOUT arguments,
so it calls the argumentless collective entry point -- the per-guard CLI
(``<absolute-agentkit-hook-claude-wrapper> pre <id>``) would reject an empty argv with exit 2,
which this interface reads as BLOCK.
"""

from __future__ import annotations

from agentkit.harness_client.harness_adapters.claude_code import main_project_edge

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_project_edge())
