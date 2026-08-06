"""Installer capability composition builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from agentkit.backend.installer.mutation_idempotency import (
        InstallerMutationCoordinator,
    )
    from agentkit.backend.installer.writer_service import InstallerWriterService


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


def build_installer_writer_service() -> InstallerWriterService:
    """Compose the installer state owner over productive repository adapters."""
    from agentkit.backend.installer.writer_service import InstallerWriterService
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )
    from agentkit.backend.state_backend.store.project_registration_repository import (
        StateBackendProjectRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    return InstallerWriterService(
        registration_repository=lambda: StateBackendProjectRegistrationRepository(),
        project_repository=lambda: StateBackendProjectRepository(),
        skill_binding_repository=lambda: StateBackendSkillBindingRepository(),
        hook_repository=lambda: StateBackendHookRegistrationRepository(),
    )


def build_installer_mutation_coordinator() -> InstallerMutationCoordinator:
    """Compose installer mutations over the writer-fenced idempotency owner."""
    from agentkit.backend.installer.mutation_idempotency import (
        InstallerMutationCoordinator,
    )

    return InstallerMutationCoordinator(StateBackendInflightIdempotencyGuard())


__all__ = [
    "build_installer_mutation_coordinator",
    "build_installer_writer_service",
    "build_third_party_preflight_service",
]
