"""Hook wrapper CLI argument DTO for governance hook dispatch."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HookWrapperArgs:
    """Validated hook-wrapper command-line selector."""

    phase: str
    hook_id: str
