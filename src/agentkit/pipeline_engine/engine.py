"""Pipeline engine facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.pipeline.engine import EngineResult, PipelineEngine

__all__ = [
    "EngineResult",
    "PipelineEngine",
]


def __getattr__(name: str) -> object:
    """Lazy re-export to avoid circular import with pipeline.engine."""
    if name in {"EngineResult", "PipelineEngine"}:
        from agentkit.pipeline.engine import EngineResult, PipelineEngine  # noqa: PLC0415

        globals()["EngineResult"] = EngineResult
        globals()["PipelineEngine"] = PipelineEngine
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
