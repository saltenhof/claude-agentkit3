"""Bootstrap-Paket: Composition-Root und einmalige App-Initialisierung.

Dieses Paket buendelt die explizite, side-effect-freie Bootstrap-
Mechanik. Konsumenten sollen ``build_producer_registry()`` (oder
analoge Builder) aufrufen, statt sich auf ``__init__.py``-Side-Effects
zu verlassen.

Stories:
- AG3-023 §2.1.6.2 — Composition-Root mit ``build_producer_registry``
"""

from __future__ import annotations

from agentkit.bootstrap.composition_root import build_producer_registry

__all__ = ["build_producer_registry"]
