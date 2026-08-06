"""In-memory writer-owned state ports for focused installer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    RegistrationResult,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.installer.registration import ProjectRegistration
    from agentkit.backend.project_management.entities import Project
    from agentkit.backend.skills import Skills
    from agentkit.backend.skills.bundle_store import SkillBundleStore


class InMemoryInstallerRegistrationRepository:
    """Registration port standing in for replayable writer mutations in tests."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}
        self.project_repo = InMemoryInstallerProjectRepository()
        self.hook_repo = InMemoryInstallerHookRepository()
        self.save_calls = 0
        self.upgrade_calls = 0

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration
        self.save_calls += 1

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        registration = self.rows[project_key]
        self.rows[project_key] = registration.model_copy(
            update={"last_verified_at": verified_at},
        )

    def update_upgraded(
        self,
        project_key: str,
        upgraded_at: datetime,
        new_digest: str,
    ) -> None:
        registration = self.rows[project_key]
        self.rows[project_key] = registration.model_copy(
            update={
                "last_upgraded_at": upgraded_at,
                "config_digest": new_digest,
            },
        )
        self.upgrade_calls += 1

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[key] for key in sorted(self.rows)]


def provisioned_installer_skills(
    store_root: Path,
) -> tuple[Skills, SkillBundleStore]:
    """Build the mandatory skill surface needed before installer preflights."""

    from agentkit.backend.installer.runner import MANDATORY_SKILLS
    from agentkit.backend.skills import (
        MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS,
        Skills,
    )
    from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
    from agentkit.backend.skills.repository import InMemorySkillBindingRepository

    store = SkillBundleStore(store_root=store_root)
    for skill_name in MANDATORY_SKILLS:
        bundle_id = f"{skill_name}-core"
        bundle_version = MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS.get(
            bundle_id,
            "4.0.0",
        )
        bundle_root = store_root / bundle_id / bundle_version
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(f"# {skill_name}\n", encoding="utf-8")
        store.register_bundle(
            SkillBundle(
                bundle_id=bundle_id,
                bundle_version=bundle_version,
                bundle_root=bundle_root,
                manifest_digest="0" * 64,
            ),
        )
    return Skills(
        bundle_store=store,
        binding_repo=InMemorySkillBindingRepository(),
    ), store


class InMemoryInstallerProjectRepository:
    """Project-management port standing in for the writer route in unit tests."""

    def __init__(self) -> None:
        self.rows: dict[str, Project] = {}

    def get(self, key: str) -> Project | None:
        return self.rows.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        rows = [self.rows[key] for key in sorted(self.rows)]
        if include_archived:
            return rows
        return [row for row in rows if row.archived_at is None]

    def save(self, project: Project) -> None:
        self.rows[project.key] = project


class InMemoryInstallerHookRepository:
    """Hook port standing in for replayable writer mutations in unit tests."""

    def __init__(self) -> None:
        self.rows: dict[str, list[HookDefinition]] = {}

    def register(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        existing = self.rows.setdefault(project_key, [])
        registered: list[str] = []
        skipped: list[str] = []
        for definition in hook_definitions:
            if definition in existing:
                skipped.append(definition.matcher)
            else:
                existing.append(definition)
                registered.append(definition.matcher)
        return RegistrationResult(registered=registered, skipped=skipped)

    def list_for_project(self, project_key: str) -> list[HookDefinition]:
        return list(self.rows.get(project_key, []))

    def clear_for_project(self, project_key: str) -> None:
        self.rows.pop(project_key, None)


__all__ = [
    "InMemoryInstallerHookRepository",
    "InMemoryInstallerProjectRepository",
    "InMemoryInstallerRegistrationRepository",
    "provisioned_installer_skills",
]
