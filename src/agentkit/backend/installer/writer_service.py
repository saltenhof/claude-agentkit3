"""Owner service for writer-executed installer state operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.skills import SkillBinding

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.governance.hook_registration import (
        HookDefinition,
        RegistrationResult,
    )
    from agentkit.backend.governance.repository import HookRegistrationRepository
    from agentkit.backend.installer.http_models import (
        ProjectRegistrationUpgradeRequest,
        RegisterProjectStateRequest,
        SkillBindingWriteRequest,
    )
    from agentkit.backend.installer.registration import (
        CheckpointResult,
        ProjectRegistration,
    )
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.project_management.repository import ProjectRepository
    from agentkit.backend.skills import SkillBindingRepository


class InstallerMigrationWitnessError(ValueError):
    """An upgrade request does not prove a deterministic AK3 migration."""


class InstallerWriterService:
    """Own installer state reads and mutations executed by the active writer."""

    def __init__(
        self,
        *,
        registration_repository: Callable[[], ProjectRegistrationRepository],
        project_repository: Callable[[], ProjectRepository],
        skill_binding_repository: Callable[[], SkillBindingRepository],
        hook_repository: Callable[[], HookRegistrationRepository],
    ) -> None:
        self._registration_repository = registration_repository
        self._project_repository = project_repository
        self._skill_binding_repository = skill_binding_repository
        self._hook_repository = hook_repository

    def register_project(
        self,
        project_key: str,
        request: RegisterProjectStateRequest,
    ) -> CheckpointResult:
        """Converge CP7 registration and visible-project state."""
        from agentkit.backend.installer.cp7_project_registration import (
            _run_cp7_state_backend_registration,
        )
        from agentkit.backend.installer.runner import InstallConfig

        config = InstallConfig(
            project_key=project_key,
            project_name=request.project_name,
            project_root=request.project_root,
            github_owner=request.github_owner,
            github_repo=request.github_repo,
            runtime_profile=request.runtime_profile,
            # The path is canonical registration data, never a backend storage
            # locator. Remote Core must not dereference a Dev filesystem path.
            registration_repo=self._registration_repository(),
            project_repo=self._project_repository(),
        )
        return _run_cp7_state_backend_registration(
            config,
            request.project_root,
            request.project_yaml,
        )

    def get_project_registration(
        self,
        project_key: str,
    ) -> ProjectRegistration | None:
        """Return the writer-owned CP7 registration."""
        return self._registration_repository().get(project_key)

    def update_project_registration_after_upgrade(
        self,
        project_key: str,
        request: ProjectRegistrationUpgradeRequest,
    ) -> None:
        """Verify and persist one deterministic AK3 config migration."""

        from agentkit.backend.installer.runner import _canonical_config_digest
        from agentkit.backend.installer.upgrade.config_migration import (
            ConfigMigrationError,
            migrate_config,
            read_config_version,
        )

        repository = self._registration_repository()
        registration = repository.get(project_key)
        if registration is None:
            raise RuntimeError("cannot update a missing project registration")
        source_digest = _canonical_config_digest(request.source_project_yaml)
        if source_digest != registration.config_digest:
            raise InstallerMigrationWitnessError(
                "config migration witness does not match the registered baseline"
            )
        try:
            target_version = read_config_version(request.migrated_project_yaml)
            expected_migration = migrate_config(
                request.source_project_yaml,
                target_version,
            )
        except ConfigMigrationError as exc:
            raise InstallerMigrationWitnessError(
                "config migration witness is semantically invalid"
            ) from exc
        expected_digest = _canonical_config_digest(expected_migration)
        submitted_digest = _canonical_config_digest(request.migrated_project_yaml)
        if (
            expected_migration != request.migrated_project_yaml
            or expected_digest != submitted_digest
        ):
            raise InstallerMigrationWitnessError(
                "config migration witness is not an AK3-owned migration result"
            )
        if submitted_digest != request.new_digest:
            raise InstallerMigrationWitnessError(
                "config migration witness digest does not match its result"
            )
        repository.update_upgraded(
            project_key,
            datetime.now(UTC),
            expected_digest,
        )

    def get_skill_binding(
        self,
        project_key: str,
        skill_name: str,
    ) -> SkillBinding | None:
        """Resolve one binding through the public agent-skills repository port."""
        return self._skill_binding_repository().load(project_key, skill_name)

    def list_skill_bindings(self, project_key: str) -> list[SkillBinding]:
        """List bindings through the public agent-skills repository port."""
        return self._skill_binding_repository().list_for_project(project_key)

    def save_skill_binding(
        self,
        project_key: str,
        request: SkillBindingWriteRequest,
    ) -> None:
        """Persist one CP8 lifecycle state through the agent-skills port."""
        binding = SkillBinding(
            binding_id=request.binding_id,
            project_key=project_key,
            skill_name=request.skill_name,
            bundle_id=request.bundle_id,
            bundle_version=request.bundle_version,
            content_digest=request.content_digest,
            target_path=request.target_path,
            binding_mode=request.binding_mode,
            status=request.status,
            pinned_at=datetime.now(UTC),
        )
        self._skill_binding_repository().save(binding)

    def delete_skill_binding(self, project_key: str, skill_name: str) -> None:
        """Delete one CP8 lifecycle row through the agent-skills port."""
        self._skill_binding_repository().delete(project_key, skill_name)

    def register_governance_hooks(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist CP9/UP04 hook definitions through the governance port."""
        return self._hook_repository().register(project_key, hook_definitions)

    def list_governance_hooks(self, project_key: str) -> list[HookDefinition]:
        """Return the project-scoped governance hook definitions."""
        return self._hook_repository().list_for_project(project_key)

    def clear_governance_hooks(self, project_key: str) -> None:
        """Clear project-scoped governance hook definitions."""
        self._hook_repository().clear_for_project(project_key)


__all__ = ["InstallerMigrationWitnessError", "InstallerWriterService"]
