"""State-backend repository boundary: public API re-exports."""

from __future__ import annotations

from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord as JsonRecord,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    load_json_safe as load_json_safe,
)
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests as reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    active_backend_is_sqlite as active_backend_is_sqlite,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global as boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    control_plane_backend_available as control_plane_backend_available,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    load_backend_instance_identity_global as load_backend_instance_identity_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    save_backend_instance_identity_global as save_backend_instance_identity_global,
)
from agentkit.backend.state_backend.store import facade as _facade
from agentkit.backend.state_backend.store.public_api import PUBLIC_API

_STATIC_EXPORTS = (
    "JsonRecord",
    "active_backend_is_sqlite",
)

__all__ = list(dict.fromkeys((*PUBLIC_API, *_STATIC_EXPORTS)))

globals().update({name: getattr(_facade, name) for name in PUBLIC_API})
