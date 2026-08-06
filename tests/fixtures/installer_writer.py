"""Loopback control-plane writer and its state ports for installer tests.

``LoopbackInstallerWriter`` / ``writer_backed_install_kwargs`` run the
productive installer writer routes in-process so a test install travels the
same contract as ``agentkit register-project``. Both docstrings name exactly
which parts of that contract the loopback does NOT reproduce.
"""

from __future__ import annotations

import io
import json
import urllib.error
import uuid
from typing import TYPE_CHECKING

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    RegistrationResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.control_plane_http.installer_writer_routes import (
        InstallerWriterRoutes,
    )
    from agentkit.backend.installer.registration import ProjectRegistration
    from agentkit.backend.installer.writer_client import InstallerWriterClient
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


class LoopbackInstallerWriter:
    """Run the productive installer writer routes in this process.

    The object is the *server* side of the installer writer contract. It wires
    the real :class:`InstallerWriterService`, the real
    :class:`InstallerWriterRoutes` and the real
    :class:`InstallerMutationCoordinator`, and hands out real
    :class:`InstallerWriterClient` instances bound to a loopback transport.

    Consequently the CP7/CP8/CP9 traffic of a test install travels the same
    request models, the same route dispatch, the same ``op_id`` claim/replay
    coordinator and the same aggregate CP7 command as a real
    ``agentkit register-project``. The state-owning repositories live *inside*
    the writer, exactly as in production -- the ``InstallConfig`` under test
    never gets a locally writing ``project_repo``.

    ``state_backed`` selects the writer's own persistence:

    * ``False`` -- in-memory repositories, for tests that need an installed
      project but no canonical level-1 state.
    * ``True`` -- the productive composition
      (``build_installer_writer_service``), so the registration and visible
      project rows land in the real state backend where every productive reader
      (e.g. the ``StoryWorkspaceLocator``) looks for them.

    What this does NOT reproduce (see ``writer_backed_install_kwargs``):
    the HTTPS/TLS hop, token issuance and validation, writer-lease/single-writer
    enforcement, and cross-process concurrency.
    """

    def __init__(self, *, state_backed: bool = False) -> None:
        from agentkit.backend.control_plane_http.installer_writer_routes import (
            InstallerWriterRoutes,
        )
        from agentkit.backend.installer.mutation_idempotency import (
            InstallerMutationCoordinator,
        )
        from agentkit.backend.installer.writer_service import InstallerWriterService
        from agentkit.backend.skills.repository import InMemorySkillBindingRepository
        from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
            InMemoryInflightIdempotencyGuard,
        )

        self.registration_repo = InMemoryInstallerRegistrationRepository()
        self.project_repo = self.registration_repo.project_repo
        self.hook_repo = self.registration_repo.hook_repo
        self.skill_binding_repo = InMemorySkillBindingRepository()
        # The claim/replay owner keeps the first-class in-process guard in both
        # modes: the productive ``StateBackendInflightIdempotencyGuard`` opens
        # the writer-lease-scoped atomic mutation, which only a process holding
        # the control-plane writer lease may enter.
        self.guard = InMemoryInflightIdempotencyGuard()
        if state_backed:
            from agentkit.backend.bootstrap.composition_installer import (
                build_installer_writer_service,
            )

            owner = build_installer_writer_service()
        else:
            owner = InstallerWriterService(
                registration_repository=lambda: self.registration_repo,  # type: ignore[arg-type]
                project_repository=lambda: self.project_repo,
                skill_binding_repository=lambda: self.skill_binding_repo,
                hook_repository=lambda: self.hook_repo,
            )
        self.routes: InstallerWriterRoutes = InstallerWriterRoutes(
            owner=owner,
            mutation_coordinator=InstallerMutationCoordinator(self.guard),
        )

    def client(self, *, project_key: str, op_id: str) -> InstallerWriterClient:
        """Return a real writer client whose transport loops back to the routes."""

        from agentkit.backend.installer.writer_client import InstallerWriterClient

        return InstallerWriterClient(
            _LoopbackWriterTransport(self.routes, project_key=project_key),
            project_key=project_key,
            op_id=op_id,
        )


class _LoopbackWriterTransport:
    """Carry one installer writer request from the client into the routes.

    Implements :class:`ControlPlaneTransport` without a socket. Error bodies are
    mapped by the productive client's own error handler so the fixture cannot
    grow a second, friendlier error contract.
    """

    def __init__(self, routes: InstallerWriterRoutes, *, project_key: str) -> None:
        self._routes = routes
        self._project_key = project_key
        self._token_id = f"loopback-token-{uuid.uuid4().hex}"

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Dispatch one authenticated installer writer request into the routes."""

        del headers, timeout
        from agentkit.backend.auth.middleware import AuthResult

        correlation_id = f"loopback-{uuid.uuid4().hex}"
        auth_result = AuthResult(
            auth_kind="project_api_token",
            project_key=self._project_key,
            session_id=None,
            token_id=self._token_id,
        )
        if method == "GET":
            response = self._routes.handle_get(path, correlation_id, auth_result)
        elif method == "POST":
            response = self._routes.handle_post(
                path,
                dict(payload or {}),
                correlation_id,
                auth_result,
            )
        else:
            raise AssertionError(f"unsupported installer writer method: {method}")
        if response is None:
            raise RuntimeError(f"no installer writer route for {method} {path}")
        return self._decode(response, path, correlation_id)

    @staticmethod
    def _decode(
        response: object,
        path: str,
        correlation_id: str,
    ) -> dict[str, object]:
        from agentkit.harness_client.projectedge.client import HttpsJsonTransport

        status_code = int(getattr(response, "status_code"))  # noqa: B009
        body = bytes(getattr(response, "body"))  # noqa: B009
        if status_code >= 400:
            # Reuse the productive client's error mapping (typed
            # ControlPlaneApiError vs. RuntimeError) instead of restating it.
            error = urllib.error.HTTPError(
                url=path,
                code=status_code,
                msg="installer writer loopback",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(body),
            )
            return HttpsJsonTransport._handle_http_error(error)
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("control-plane response must be a JSON object")
        # The real transport lifts the server correlation id out of the response
        # header when the body carries none; mirror that so the client's
        # ``_send`` pops the same key it pops in production.
        data.setdefault("correlation_id", correlation_id)
        return data


def writer_backed_install_kwargs(
    bundle_store_root: Path,
    *,
    project_key: str,
    op_id: str | None = None,
    state_backed: bool = False,
) -> dict[str, object]:
    """Bind an ``InstallConfig`` to a loopback control-plane writer.

    Production reaches ``install_agentkit`` / ``run_checkpoint_install`` through
    two callers: ``agentkit register-project`` and ``agentkit verify-project``
    (``cli/installer_commands.py`` ``_cmd_register_project`` /
    ``_cmd_verify_project``). Both bind registration, hook and skill-binding
    persistence plus the aggregate CP7 command to the authenticated active
    control-plane writer through the same
    ``_wire_register_config_to_writer``; ``upgrade-project`` has the third,
    equivalent wiring. The installer consequently refuses every local
    State-Backend fallback (``installer/runner.py`` ``_resolve_skills_and_store``
    / ``_resolve_registration_repo`` / ``_resolve_project_repo`` /
    ``_register_default_governance_hooks``).

    A test that needs a really installed project therefore has to supply the
    same ports the production caller supplies; running the installer without
    them is not a shortcut but a call the production flow never makes.

    **What this reproduces.** The returned kwargs mirror
    ``_wire_register_config_to_writer`` port for port: a real
    :class:`InstallerWriterClient` on ``writer_client`` (so CP7 runs through the
    atomic ``register_project_state`` aggregate operation, *not* the local
    two-step path at ``runner.py`` ``_run_cp7_state_backend_registration``), the
    client's read-only registration repository (whose ``save`` refuses, as in
    production), the client's hook repository, and a ``Skills`` surface whose
    binding repository is the client's. Like production it supplies **no**
    ``project_repo``: the visible-project row is written inside the writer.
    Behind the client run the productive routes, service and ``op_id``
    claim/replay coordinator (:class:`LoopbackInstallerWriter`).

    **What this does NOT reproduce.** It is a loopback, not a live control
    plane, and the following parts of the contract are therefore out of scope
    for any test using it:

    * no HTTPS/TLS transport -- requests bypass the socket, the certificate
      chain and the ``X-AK3-Client`` / ``X-AK3-Skill-Bundle`` handshake headers;
    * no authentication -- the project API token is synthesized, never issued or
      validated, so token scoping, expiry and revocation are untested here;
    * no ``assert_ready`` handshake -- readiness is answered unconditionally,
      because production performs it in ``prepare_installer_auth_context``
      before the installer runs, outside these kwargs;
    * no writer lease and no single-writer enforcement -- nothing here proves
      that only one writer may mutate the database;
    * no durable claim/replay -- the ``op_id`` guard is always the in-process
      one, so crash durability, the Postgres writer-lease-scoped atomic mutation
      and cross-process concurrency are not exercised;
    * with ``state_backed=False`` additionally no database at all: the writer's
      repositories are in-process, and nothing the install registers is visible
      to a productive reader;
    * no ``project_edge_client``.

    Those properties belong to the integration/e2e level against a live control
    plane; a test built on these kwargs must not claim them.

    Args:
        bundle_store_root: Root of the per-test systemwide skill-bundle store.
        project_key: The installed project's key. It must equal the
            ``InstallConfig.project_key`` -- the writer scopes every route and
            repository call to it, exactly as the authenticated CLI does.
        op_id: Optional client-owned root operation id; a fresh one is derived
            when omitted, matching ``_operation_id`` in the CLI.
        state_backed: Whether the writer persists into the real state backend
            (productive repositories) instead of in-process ones. Required
            whenever a productive reader must see the installed project, e.g.
            the ``StoryWorkspaceLocator`` resolving the level-1
            ``project_registry``.

    Returns:
        Keyword arguments for :class:`InstallConfig` carrying the writer client,
        the writer-owned skill surface, bundle store, registration and hook
        ports.
    """

    from agentkit.backend.skills import Skills

    _, store = provisioned_installer_skills(bundle_store_root)
    writer = LoopbackInstallerWriter(state_backed=state_backed)
    client = writer.client(
        project_key=project_key,
        op_id=op_id or f"op-{uuid.uuid4().hex}",
    )
    return {
        "skills": Skills(
            bundle_store=store,
            binding_repo=client.skill_binding_repository(),
        ),
        "skill_bundle_store": store,
        "writer_client": client,
        "registration_repo": client.registration_repository(),
        "hook_registration_repo": client.hook_registration_repository(),
    }


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
    "LoopbackInstallerWriter",
    "provisioned_installer_skills",
    "writer_backed_install_kwargs",
]
