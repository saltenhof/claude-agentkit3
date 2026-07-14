"""Installer capability composition builders."""

from __future__ import annotations

from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.installer.bounded_executor import BoundedThreadExecutor
from agentkit.backend.installer.third_party_clients import (
    DefaultThirdPartyClientFactory,
    EnvironmentSecretResolver,
)
from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    StateBackendInflightIdempotencyGuard,
)


def build_third_party_preflight_service() -> ThirdPartyPreflightService:
    """Build the backend-owned third-system validation capability."""
    repository = ControlPlaneRuntimeRepository()
    return ThirdPartyPreflightService(
        resolver=EnvironmentSecretResolver(),
        clients=DefaultThirdPartyClientFactory(),
        guard=StateBackendInflightIdempotencyGuard(),
        operation_loader=repository.load_operation,
        executor=BoundedThreadExecutor(),
    )


__all__ = ["build_third_party_preflight_service"]
