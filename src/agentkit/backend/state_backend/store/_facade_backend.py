"""Static compatibility exports for backend infrastructure facade symbols."""

from __future__ import annotations

from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord as JsonRecord,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    _cast_json_record as _cast_json_record,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    load_json_safe as load_json_safe,
)
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests as reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module as _backend_module,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _require_control_plane_backend as _require_control_plane_backend,
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

__all__ = [
    "JsonRecord",
    "reset_backend_cache_for_tests",
    "active_backend_is_sqlite",
    "control_plane_backend_available",
    "save_backend_instance_identity_global",
    "load_backend_instance_identity_global",
    "boot_backend_instance_identity_global",
    "load_json_safe",
]
