"""Public symbol list for the state-backend repository facade.

The literal name tuple lives in the sibling ``_public_api_names`` module so this
boundary file stays within the module-level LOC budget
(PY_MODULE_TOP_LEVEL_MAX_LOC_100). ``PUBLIC_API`` is re-exported here unchanged,
so ``from agentkit.state_backend.store.public_api import PUBLIC_API`` and its
contents are identical to before.
"""

from __future__ import annotations

from agentkit.state_backend.store._public_api_names import PUBLIC_API_NAMES

PUBLIC_API = PUBLIC_API_NAMES

__all__ = ["PUBLIC_API"]
