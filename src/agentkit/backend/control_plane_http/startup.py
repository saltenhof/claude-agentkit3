"""Pre-serve control-plane startup orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService

logger = logging.getLogger(__name__)


def run_pre_serve_startup(runtime_service: ControlPlaneRuntimeService) -> None:
    """Bind this boot's identity after fail-closed orphan reconciliation."""
    from agentkit.backend.control_plane.instance_identity import (
        resolve_backend_instance_identity,
    )
    from agentkit.backend.control_plane.repository import (
        BackendInstanceIdentityRepository,
    )
    from agentkit.backend.control_plane.startup_reconcile import (
        run_startup_reconciliation,
    )

    identity = resolve_backend_instance_identity(BackendInstanceIdentityRepository())
    run_startup_reconciliation(
        runtime_service.repository,
        identity,
        object_claim_repo=runtime_service.object_claim_repository,
    )
    runtime_service.bind_instance_identity(identity)
    logger.info(
        "Startup reconciliation complete for backend instance %s "
        "(incarnation %d); listener may accept requests.",
        identity.backend_instance_id,
        identity.instance_incarnation,
    )


__all__ = ["run_pre_serve_startup"]
