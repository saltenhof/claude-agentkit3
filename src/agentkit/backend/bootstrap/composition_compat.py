"""Compatibility helpers for the public composition-root namespace."""

from __future__ import annotations

import importlib
from typing import Any


def composition_root_attr(name: str) -> Any:
    """Resolve a mutable attribute from the public composition-root module."""
    root = importlib.import_module("agentkit.backend.bootstrap.composition_root")
    return getattr(root, name)
