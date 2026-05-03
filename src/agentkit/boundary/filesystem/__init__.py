"""Infrastructure I/O boundary module for atomic filesystem operations.

Boundary kind: infrastructure_io
Blood group:   R
Importable by: any
May import:    boundary.shared
"""

from __future__ import annotations

from agentkit.boundary.filesystem.atomic import atomic_write_json
from agentkit.boundary.filesystem.read import load_json_object, read_projection_json_object

__all__ = ["atomic_write_json", "load_json_object", "read_projection_json_object"]
