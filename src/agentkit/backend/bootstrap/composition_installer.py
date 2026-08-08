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
    from collections.abc import Callable
    from pathlib import Path

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


def build_project_root_lookup() -> Callable[[str], Path | None]:
    """Compose the canonical project-root lookup over the owner BC's port.

    The verify-system ``/v1`` surface (AG3-241) must resolve the core-host
    filesystem anchor of a project from canonical level-1 state (FK-10 §10.2.3 /
    I3), and it must do so WITHOUT reading the state backend itself: a
    control-plane HTTP module that bypasses the owner BC's port is an AC001/AC010
    violation. The owner is the installer writer service, which owns the CP-7
    ``project_registry`` record.

    Returns:
        A callable resolving ``project_key`` to its registered project root, or
        ``None`` when the project is not registered.
    """
    service = build_installer_writer_service()

    def lookup(project_key: str) -> Path | None:
        registration = service.get_project_registration(project_key)
        return None if registration is None else registration.project_root

    return lookup


def build_installer_mutation_coordinator() -> InstallerMutationCoordinator:
    """Compose installer mutations over the writer-fenced idempotency owner."""
    from agentkit.backend.installer.mutation_idempotency import (
        InstallerMutationCoordinator,
    )

    return InstallerMutationCoordinator(StateBackendInflightIdempotencyGuard())


__all__ = [
    "build_installer_mutation_coordinator",
    "build_installer_writer_service",
    "build_project_root_lookup",
    "build_third_party_preflight_service",
]
