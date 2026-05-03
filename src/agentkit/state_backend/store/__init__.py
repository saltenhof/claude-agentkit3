"""State-backend repository boundary: public API re-exports."""

from __future__ import annotations

from agentkit.state_backend.store import facade as _facade
from agentkit.state_backend.store.public_api import PUBLIC_API

__all__ = list(PUBLIC_API)

globals().update({name: getattr(_facade, name) for name in PUBLIC_API})
