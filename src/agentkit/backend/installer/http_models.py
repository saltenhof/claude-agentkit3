"""HTTPS models for writer-owned installer state operations."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.installer.registration import RuntimeProfile
from agentkit.backend.skills import SkillBindingMode, SkillLifecycleStatus
from agentkit_wire.governance_registration import HookDefinition


class InstallerWriterReadyResponse(BaseModel):
    """Authenticated proof that the active writer accepts installer work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool


class RegisterProjectStateRequest(BaseModel):
    """CP7 state convergence request executed by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    project_root: Path
    github_owner: str = Field(min_length=1)
    github_repo: str = Field(min_length=1)
    runtime_profile: RuntimeProfile
    project_yaml: dict[str, object]


class SkillBindingWriteRequest(BaseModel):
    """Persist one CP8 binding lifecycle state inside the writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_path: Path
    binding_mode: SkillBindingMode
    status: SkillLifecycleStatus


class SkillBindingDeleteRequest(BaseModel):
    """Delete one CP8 binding during an honest local rollback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)


class SkillBindingMutationResponse(BaseModel):
    """Acknowledgement of a writer-owned binding mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_name: str
    action: str


class SkillBindingReadResponse(BaseModel):
    """Optional serialized binding returned by the writer read surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding: dict[str, object] | None


class SkillBindingListResponse(BaseModel):
    """Serialized project-scoped bindings returned by the writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bindings: tuple[dict[str, object], ...]


class ProjectRegistrationReadResponse(BaseModel):
    """Optional serialized CP7 registration returned by the writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registration: dict[str, object] | None


class ProjectRegistrationListResponse(BaseModel):
    """Serialized CP7 registrations returned by the writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registrations: tuple[dict[str, object], ...]


class ProjectRegistrationUpgradeRequest(BaseModel):
    """Persist a digest with a server-verifiable AK3 migration witness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    new_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_project_yaml: dict[str, object]
    migrated_project_yaml: dict[str, object]


class ProjectRegistrationMutationResponse(BaseModel):
    """Acknowledgement of a writer-owned registration lifecycle mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    action: str


class GovernanceHookRegistrationRequest(BaseModel):
    """Persist the CP9/UP04 hook definitions inside the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    hook_definitions: tuple[HookDefinition, ...]


class GovernanceHookRegistrationResponse(BaseModel):
    """Serializable result of writer-owned hook registration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registered: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]


class GovernanceHookListResponse(BaseModel):
    """Project-scoped hook definitions returned by the writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hook_definitions: tuple[HookDefinition, ...]


class GovernanceHookClearRequest(BaseModel):
    """Writer-owned hook clear command used by the repository protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)


__all__ = [
    "GovernanceHookClearRequest",
    "GovernanceHookListResponse",
    "GovernanceHookRegistrationRequest",
    "GovernanceHookRegistrationResponse",
    "InstallerWriterReadyResponse",
    "ProjectRegistrationListResponse",
    "ProjectRegistrationMutationResponse",
    "ProjectRegistrationReadResponse",
    "ProjectRegistrationUpgradeRequest",
    "RegisterProjectStateRequest",
    "SkillBindingDeleteRequest",
    "SkillBindingListResponse",
    "SkillBindingMutationResponse",
    "SkillBindingReadResponse",
    "SkillBindingWriteRequest",
]
