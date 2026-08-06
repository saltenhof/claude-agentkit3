"""Pre-serve control-plane startup orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.control_plane.writer_lease import (
        ControlPlaneWriterLease,
    )

logger = logging.getLogger(__name__)


def run_pre_serve_startup(
    runtime_service: ControlPlaneRuntimeService,
    *,
    lease_factory: Callable[[], ControlPlaneWriterLease] | None = None,
) -> ControlPlaneWriterLease:
    """Acquire writer exclusivity, then bind identity after reconciliation."""
    from agentkit.backend.control_plane.instance_identity import (
        resolve_backend_instance_identity,
    )
    from agentkit.backend.control_plane.repository import (
        BackendInstanceIdentityRepository,
        ControlPlaneWriterLeaseRepository,
    )
    from agentkit.backend.control_plane.startup_reconcile import (
        run_startup_reconciliation,
    )
    lease = (lease_factory or ControlPlaneWriterLeaseRepository().acquire)()
    try:
        # The lifetime lease is deliberately acquired BEFORE this shared
        # incarnation changes.  A rejected second process therefore cannot make
        # the live writer's claims appear to belong to an earlier boot.
        identity = resolve_backend_instance_identity(BackendInstanceIdentityRepository())
        lease.bind_identity(identity)
        run_startup_reconciliation(
            runtime_service.repository,
            identity,
            object_claim_repo=runtime_service.object_claim_repository,
        )
        runtime_service.bind_instance_identity(identity)
    except Exception:
        lease.release()
        raise
    logger.info(
        "Startup reconciliation complete for backend instance %s "
        "(incarnation %d); listener may accept requests.",
        identity.backend_instance_id,
        identity.instance_incarnation,
    )
    return lease


__all__ = ["run_pre_serve_startup"]
