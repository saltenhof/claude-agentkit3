"""Static compatibility exports for ownership-fence facade symbols."""

from __future__ import annotations

from agentkit.backend.state_backend.governance_runtime_store import (
    OwnershipFenceScope as OwnershipFenceScope,
)
from agentkit.backend.state_backend.governance_runtime_store import (
    bind_ownership_fence_scope as bind_ownership_fence_scope,
)
from agentkit.backend.state_backend.governance_runtime_store import (
    require_ownership_fence_scope as require_ownership_fence_scope,
)
from agentkit.backend.state_backend.governance_runtime_store import (
    resolve_ownership_fence_snapshot as resolve_ownership_fence_snapshot,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    delete_session_run_binding_global as delete_session_run_binding_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global as insert_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_active_run_ownership_record_global as load_active_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_run_ownership_record_global as load_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_session_run_binding_global as load_session_run_binding_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_session_run_binding_global as save_session_run_binding_global,
)

__all__ = [
    "save_session_run_binding_global",
    "load_session_run_binding_global",
    "delete_session_run_binding_global",
    "insert_run_ownership_record_global",
    "load_run_ownership_record_global",
    "load_active_run_ownership_record_global",
    "resolve_ownership_fence_snapshot",
    "OwnershipFenceScope",
    "bind_ownership_fence_scope",
    "require_ownership_fence_scope",
]
