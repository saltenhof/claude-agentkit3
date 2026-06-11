"""Worker type definitions for spawn and coordination.

Since AG3-021, ``SpawnReason`` is re-exported from ``agentkit.core_types``.
The canonical definition lives in the foundation module;
this file only holds the BC-stable import path for worker consumers.
"""

from __future__ import annotations

from agentkit.core_types import SpawnReason

__all__ = ["SpawnReason"]
