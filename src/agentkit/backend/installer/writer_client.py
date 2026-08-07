"""Authenticated HTTPS adapters for writer-owned installer state."""

from __future__ import annotations

import urllib.parse
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from agentkit.backend.boundary.filesystem import assert_project_local_file_path
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.governance.errors import HookRegistrationError
from agentkit.backend.governance.hook_registration import RegistrationResult
from agentkit.backend.installer.http_models import (
    GovernanceHookClearRequest,
    GovernanceHookListResponse,
    GovernanceHookRegistrationRequest,
    GovernanceHookRegistrationResponse,
    InstallerWriterReadyResponse,
    ProjectRegistrationListResponse,
    ProjectRegistrationMutationResponse,
    ProjectRegistrationReadResponse,
    ProjectRegistrationUpgradeRequest,
    RegisterProjectStateRequest,
    SkillBindingDeleteRequest,
    SkillBindingListResponse,
    SkillBindingMutationResponse,
    SkillBindingReadResponse,
    SkillBindingWriteRequest,
)
from agentkit.backend.installer.registration import (
    CheckpointResult,
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.backend.skills import SkillBinding

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from agentkit.backend.governance.repository import HookRegistrationRepository
    from agentkit.harness_client.projectedge.client import ControlPlaneTransport
    from agentkit_wire.governance_registration import HookDefinition

_CHILD_OPERATION_NAMESPACE = uuid.UUID("96d25c1a-5c1b-4ec0-8dc0-5584935d9ad2")


class InstallerWriterClient:
    """Root client for one replayable register-project or upgrade-project run."""

    def __init__(
        self,
        transport: ControlPlaneTransport,
        *,
        project_key: str,
        op_id: str,
    ) -> None:
        self._transport = transport
        self._project_key = project_key
        self._op_id = op_id

    @property
    def project_key(self) -> str:
        """Return the authenticated project scope."""

        return self._project_key

    def assert_ready(self) -> None:
        """Prove writer reachability/authentication before any local mutation."""

        data = self._send(method="GET", suffix="/writer-ready")
        response = InstallerWriterReadyResponse.model_validate(data)
        if not response.ready:
            raise RuntimeError("active control-plane writer is not ready")

    def register_project_state(
        self,
        *,
        project_name: str,
        project_root: Path,
        github_owner: str,
        github_repo: str,
        runtime_profile: RuntimeProfile,
        project_yaml: dict[str, object],
    ) -> CheckpointResult:
        """Run CP7 registration and visible-project convergence in the writer."""

        request = RegisterProjectStateRequest(
            op_id=self._child_op_id("cp7-project-state"),
            project_name=project_name,
            project_root=project_root,
            github_owner=github_owner,
            github_repo=github_repo,
            runtime_profile=runtime_profile,
            project_yaml=project_yaml,
        )
        data = self._send(
            method="POST",
            suffix="/register-project",
            payload=request.model_dump(mode="json"),
        )
        return CheckpointResult.model_validate(data)

    def registration_repository(self) -> WriterProjectRegistrationRepository:
        """Return the read adapter used by CP7 plans and upgrade detection."""

        return WriterProjectRegistrationRepository(self)

    def skill_binding_repository(self) -> WriterSkillBindingRepository:
        """Return the CP8 state adapter bound to this root operation."""

        return WriterSkillBindingRepository(self)

    def hook_registration_repository(self) -> WriterHookRegistrationRepository:
        """Return the CP9/UP04 hook persistence adapter."""

        return WriterHookRegistrationRepository(self)

    def _child_op_id(self, operation: str) -> str:
        """Derive a stable bounded claim id from the exposed root operation id."""

        derived = uuid.uuid5(
            _CHILD_OPERATION_NAMESPACE,
            f"{self._project_key}\x00{self._op_id}\x00{operation}",
        )
        return f"op-{derived.hex}"

    def _send(
        self,
        *,
        method: str,
        suffix: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        project = urllib.parse.quote(self._project_key, safe="")
        data = self._transport.send(
            method=method,
            path=f"/v1/projects/{project}/installation{suffix}",
            payload=payload,
        )
        data.pop("correlation_id", None)
        return data


class WriterProjectRegistrationRepository:
    """Read-only CP7 repository adapter; mutations use the aggregate CP7 route."""

    def __init__(self, client: InstallerWriterClient) -> None:
        self._client = client

    def get(self, project_key: str) -> ProjectRegistration | None:
        """Load the authenticated project's registration through the writer."""

        self._assert_scope(project_key)
        data = self._client._send(method="GET", suffix="/project-registration")
        response = ProjectRegistrationReadResponse.model_validate(data)
        if response.registration is None:
            return None
        return ProjectRegistration.model_validate(response.registration)

    def list_all(self) -> list[ProjectRegistration]:
        """List registrations through the writer-owned read surface."""

        data = self._client._send(method="GET", suffix="/project-registrations")
        response = ProjectRegistrationListResponse.model_validate(data)
        return [ProjectRegistration.model_validate(item) for item in response.registrations]

    def save(self, registration: ProjectRegistration) -> None:
        """Reject repository-level mutation; CP7 is the sole aggregate command."""

        del registration
        raise RuntimeError("CP7 project state mutations require the aggregate writer route")

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        """Reject unsupported repository-level verification mutation."""

        del project_key, verified_at
        raise RuntimeError("project verification mutation has no installer writer contract")

    def update_upgraded(
        self,
        project_key: str,
        upgraded_at: datetime,
        new_digest: str,
    ) -> None:
        """Persist the digest after an AK3-owned migration through the writer."""

        self._assert_scope(project_key)
        registration = self.get(project_key)
        if registration is None:
            raise RuntimeError("cannot update a missing project registration")
        from agentkit.backend.installer.paths import CONFIG_DIR, PROJECT_CONFIG_FILE
        from agentkit.backend.installer.runner import _canonical_config_digest

        relative_config = Path(CONFIG_DIR) / PROJECT_CONFIG_FILE
        config_path = assert_project_local_file_path(
            registration.project_root,
            relative_config,
        )
        backup_path = assert_project_local_file_path(
            registration.project_root,
            relative_config.with_name(relative_config.name + ".bak"),
        )
        source_project_yaml = _read_project_yaml_mapping(backup_path)
        migrated_project_yaml = _read_project_yaml_mapping(config_path)
        if _canonical_config_digest(source_project_yaml) != registration.config_digest:
            raise RuntimeError(
                "config migration backup does not match the registered digest baseline"
            )
        if _canonical_config_digest(migrated_project_yaml) != new_digest:
            raise RuntimeError(
                "current project config does not match the migrated digest"
            )
        request = ProjectRegistrationUpgradeRequest(
            op_id=self._client._child_op_id("project-registration-upgraded"),
            new_digest=new_digest,
            source_project_yaml=source_project_yaml,
            migrated_project_yaml=migrated_project_yaml,
        )
        del upgraded_at  # The writer owns the authoritative mutation timestamp.
        data = self._client._send(
            method="POST",
            suffix="/project-registration",
            payload=request.model_dump(mode="json"),
        )
        response = ProjectRegistrationMutationResponse.model_validate(data)
        if response.project_key != project_key or response.action != "upgraded":
            raise RuntimeError("installer writer returned an invalid upgrade acknowledgement")

    def _assert_scope(self, project_key: str) -> None:
        if project_key != self._client.project_key:
            raise ValueError("installer repository project scope mismatch")


def _read_project_yaml_mapping(path: Path) -> dict[str, object]:
    """Read one migration witness mapping fail-closed."""

    if not path.is_file():
        raise RuntimeError(f"config migration witness is missing: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"config migration witness is unreadable: {path}") from exc
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) for key in loaded
    ):
        raise RuntimeError(f"config migration witness is not a string-keyed mapping: {path}")
    return cast("dict[str, object]", loaded)


class WriterSkillBindingRepository:
    """Project-scoped CP8 binding repository over authenticated HTTPS."""

    def __init__(self, client: InstallerWriterClient) -> None:
        self._client = client
        self._ambiguous_saves: set[str] = set()

    def save(self, binding: SkillBinding) -> None:
        """Persist a binding lifecycle state inside the active writer."""

        request = SkillBindingWriteRequest(
            op_id=self._client._child_op_id(
                f"skill-save:{binding.skill_name}:{binding.status.value}",
            ),
            binding_id=binding.binding_id,
            skill_name=binding.skill_name,
            bundle_id=binding.bundle_id,
            bundle_version=binding.bundle_version,
            content_digest=binding.content_digest,
            target_path=binding.target_path,
            binding_mode=binding.binding_mode,
            status=binding.status,
        )
        try:
            data = self._client._send(
                method="POST",
                suffix=(
                    f"/skill-bindings/"
                    f"{urllib.parse.quote(binding.skill_name, safe='')}"
                ),
                payload=request.model_dump(mode="json"),
            )
            SkillBindingMutationResponse.model_validate(data)
        except ControlPlaneApiError as exc:
            # In-flight/mismatch/conflict and server failures can describe a
            # prior same-claim attempt whose terminal effect is not yet visible
            # to this response.  Preserve that possible effect exactly like a
            # transport loss.  Validation/auth failures happen before mutation
            # and therefore permit the caller's normal cleanup.
            if exc.error_code in {
                "idempotency_mismatch",
                "operation_conflict",
                "operation_in_flight",
            } or exc.http_status >= 500:
                self._ambiguous_saves.add(binding.skill_name)
            raise
        except Exception:
            # The writer may have committed before the response was lost.  A
            # compensating delete would then invalidate the stable save replay:
            # the retry would replay "saved" without recreating the row.  Keep
            # the possible row and surface an honest partial state instead; a
            # retry with the same root op_id replays/continues to VERIFIED and
            # converges both filesystem and canonical binding state.
            self._ambiguous_saves.add(binding.skill_name)
            raise

    def load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        """Load a binding from the writer-owned state backend."""

        self._assert_scope(project_key)
        data = self._client._send(
            method="GET",
            suffix=f"/skill-bindings/{urllib.parse.quote(skill_name, safe='')}",
        )
        response = SkillBindingReadResponse.model_validate(data)
        if response.binding is None:
            return None
        return SkillBinding.model_validate(response.binding)

    def list_for_project(self, project_key: str) -> list[SkillBinding]:
        """List bindings from the writer-owned state backend."""

        self._assert_scope(project_key)
        data = self._client._send(method="GET", suffix="/skill-bindings")
        response = SkillBindingListResponse.model_validate(data)
        return [SkillBinding.model_validate(item) for item in response.bindings]

    def delete(self, project_key: str, skill_name: str) -> None:
        """Delete a binding through a replayable writer mutation."""

        self._assert_scope(project_key)
        if skill_name in self._ambiguous_saves:
            raise RuntimeError(
                "skill binding save outcome is ambiguous; retaining canonical "
                "writer state for same-op replay convergence"
            )
        request = SkillBindingDeleteRequest(
            op_id=self._client._child_op_id(f"skill-delete:{skill_name}"),
        )
        data = self._client._send(
            method="POST",
            suffix=(
                f"/skill-bindings/{urllib.parse.quote(skill_name, safe='')}/delete"
            ),
            payload=request.model_dump(mode="json"),
        )
        SkillBindingMutationResponse.model_validate(data)

    def _assert_scope(self, project_key: str) -> None:
        # Skills currently derives its lookup key from project_root.stem. The
        # authenticated CLI project key remains authoritative on the wire.
        if not project_key.strip():
            raise ValueError("skill binding project scope must not be empty")


class WriterHookRegistrationRepository:
    """CP9/UP04 hook repository over the active writer."""

    def __init__(self, client: InstallerWriterClient) -> None:
        self._client = client

    def register(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist hook definitions through the unified writer claim contract."""

        self._assert_scope(project_key)
        request = GovernanceHookRegistrationRequest(
            op_id=self._client._child_op_id("governance-hooks-register"),
            hook_definitions=tuple(hook_definitions),
        )
        data = self._client._send(
            method="POST",
            suffix="/governance-hooks",
            payload=request.model_dump(mode="json"),
        )
        response = GovernanceHookRegistrationResponse.model_validate(data)
        return RegistrationResult(
            registered=list(response.registered),
            skipped=list(response.skipped),
            errors=[HookRegistrationError(message) for message in response.errors],
        )

    def list_for_project(self, project_key: str) -> list[HookDefinition]:
        """Load registered hooks through the writer-owned read surface."""

        self._assert_scope(project_key)
        data = self._client._send(method="GET", suffix="/governance-hooks")
        response = GovernanceHookListResponse.model_validate(data)
        return list(response.hook_definitions)

    def clear_for_project(self, project_key: str) -> None:
        """Clear hook rows through a replayable writer mutation."""

        self._assert_scope(project_key)
        request = GovernanceHookClearRequest(
            op_id=self._client._child_op_id("governance-hooks-clear"),
        )
        self._client._send(
            method="POST",
            suffix="/governance-hooks/clear",
            payload=request.model_dump(mode="json"),
        )

    def _assert_scope(self, project_key: str) -> None:
        if project_key != self._client.project_key:
            raise ValueError("installer hook repository project scope mismatch")


class InstallerHookGovernance:
    """Hook registration as edge orchestration (FK-30 §30.3.1).

    CP9 and UP04 need exactly two effects, and they sit on two different
    machines:

    1. **persist** the desired hook definitions -- canonical state, therefore the
       core, reached through the injected ``HookRegistrationRepository`` (in
       production the REST-backed :class:`WriterHookRegistrationRepository`);
    2. **materialise** ``.claude/settings.json`` and ``.codex/hooks.json`` --
       files on the DEVELOPER machine, therefore the edge.

    Because the second half can only run on the edge, the composed operation is
    edge orchestration. AG3-239 moved it here out of the core ``Governance``
    class, which had to reach back into
    ``harness_client.harness_adapters.settings_writer`` to write those files --
    a core module writing onto a developer machine, which the split deployment
    cannot do at all.

    The same move removed the fail-closed dummy lock repository this class used
    to construct: it existed only because the core class demanded a
    ``LockRecordRepository`` for an operation this path never calls.

    Fail-closed: a broken settings file raises rather than silently continuing
    (FK-30 §30.3.1).
    """

    def __init__(
        self,
        *,
        hook_repo: HookRegistrationRepository,
        project_key: str,
        project_root: Path,
    ) -> None:
        self._hook_repo = hook_repo
        self._project_key = project_key
        self._project_root = project_root

    def register_hooks(
        self,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist remotely, then materialize local harness settings.

        Args:
            hook_definitions: Hook definitions to register.

        Returns:
            ``RegistrationResult`` with ``registered``, ``skipped``, ``errors``.

        Raises:
            Exception: On unrecoverable backend failures or a broken harness
                settings file.
        """
        from agentkit.harness_client.harness_adapters.settings_writer import (
            ClaudeCodeSettingsWriter,
            CodexSettingsWriter,
        )

        result = self._hook_repo.register(self._project_key, hook_definitions)
        # FK-30 §30.3.1 / FK-76 §76.5.2: materialise the harness settings files
        # AFTER the backend persist, on the machine that owns them.
        ClaudeCodeSettingsWriter(self._project_root).write(hook_definitions)
        CodexSettingsWriter(self._project_root).write(hook_definitions)
        return result


__all__ = [
    "InstallerHookGovernance",
    "InstallerWriterClient",
    "WriterHookRegistrationRepository",
    "WriterProjectRegistrationRepository",
    "WriterSkillBindingRepository",
]
