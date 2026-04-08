"""Shared file operations for project_ops.

Re-exports atomic write helpers from :mod:`agentkit.utils.io` for
backwards compatibility within ``project_ops``.  New code outside
``project_ops`` should import directly from ``agentkit.utils.io``.
"""

from __future__ import annotations

from agentkit.utils.io import atomic_write_text, atomic_write_yaml, ensure_dir

__all__ = ["atomic_write_text", "atomic_write_yaml", "ensure_dir"]
