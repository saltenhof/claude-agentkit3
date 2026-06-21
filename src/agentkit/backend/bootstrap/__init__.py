"""Bootstrap package: composition root and one-time app initialization.

This package bundles the explicit, side-effect-free bootstrap mechanics.
Consumers should call ``build_producer_registry()`` (or analogous builders)
rather than relying on ``__init__.py`` side effects.

Stories:
- AG3-023 §2.1.6.2 — composition root with ``build_producer_registry``
"""

from __future__ import annotations

from agentkit.backend.bootstrap.composition_root import build_producer_registry

__all__ = ["build_producer_registry"]
