"""FK-50 §50.3 CP 7 -- State-Backend project registration (idempotent).

One checkpoint, one module. CP 7 is the only installer step that writes the
``project_registry`` row plus its mirror in the visible project list, and it is
the only one that must refuse the whole install when the MANDATORY GitHub
coordinates are missing or malformed. Keeping it beside the generic installer
runner mixed a hard precondition gate, a registry convergence and a two-table
outcome mapping into a module that owns none of them.

Split out of ``installer/runner.py`` (AG3-229); the checkpoint behaviour, its
statuses, reasons and detail strings are unchanged.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.installer.runner import (
    PROJECT_CONFIG_VERSION,
    _canonical_config_digest,
    _resolve_registration_repo,
    _sync_project_management_project,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.registration import (
        CheckpointResult,
        ProjectRegistration,
    )
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.runner import InstallConfig


def _elapsed_ms(start: float) -> int:
    """Return milliseconds elapsed since a ``time.monotonic`` timestamp."""

    elapsed = time.monotonic() - start
    return int(elapsed * 1000)


def _cp7_updated_detail(
    project_key: str,
    existing_config_digest: str | None,
    registry_action: str,
    digest: str,
    project_action: str,
) -> str:
    """Return the CP7 UPDATED detail for registry/project convergence."""

    if existing_config_digest is not None and registry_action == "updated":
        return (
            f"Project {project_key!r} config_digest changed "
            f"({existing_config_digest[:12]} -> {digest[:12]}); "
            f"project-management row {project_action}."
        )
    return f"Project {project_key!r} registration already matched but project-management row was {project_action}."


def _run_cp7_state_backend_registration(
    config: InstallConfig,
    root: Path,
    yaml_data: dict[str, object],
) -> CheckpointResult:
    """Run FK-50 §50.3 CP 7 — State-Backend project registration (idempotent).

    Computes the ``config_digest`` over the canonicalised project.yaml, looks up
    the existing registration and converges on one consistent state
    (``formal.installer.invariants §register_project_is_idempotent``):

    * no existing registration -> ``save`` a fresh :class:`ProjectRegistration`
      (``CheckpointStatus.CREATED``).
    * existing registration with the SAME ``config_digest`` -> no write,
      ``CheckpointStatus.SKIPPED`` (idempotent re-run).
    * existing registration with a DIVERGENT ``config_digest`` ->
      ``update_upgraded`` (new digest + ``last_upgraded_at``),
      ``CheckpointStatus.UPDATED``.

    The ``project_registry`` row requires ``github_owner``/``github_repo`` NOT
    NULL (story §2.1.1; FK-50 §50.3 CP 7 records GitHub owner/repo as a MANDATORY
    coordinate). When the install config carries no GitHub coordinates, CP 7 is a
    hard precondition failure: it records NOTHING and returns
    ``CheckpointStatus.FAILED`` (FK-50 §50.6 — a CP 7 precondition violation is
    FAILED, never a silent SKIP that leaves the project unregistered after a
    "successful" install). It never fabricates github values (ZERO DEBT) and never
    writes a partial row (FAIL-CLOSED). ``SKIPPED`` is reserved for the genuine
    idempotency case (existing registration, identical ``config_digest``).

    Args:
        config: The install configuration (carries the registration repo, the
            GitHub coordinates and the runtime profile).
        root: Project root (recorded as ``project_root``).
        yaml_data: The project.yaml mapping just written (digest source).

    Returns:
        The :class:`CheckpointResult` for CP 7.
    """
    from agentkit.backend.installer.registration import RuntimeProfile

    start = time.monotonic()
    coordinates = _cp7_validated_github_coordinates(config, start=start)
    if not isinstance(coordinates, tuple):
        return coordinates
    owner, repo_name = coordinates

    if config.writer_client is not None:
        return config.writer_client.register_project_state(
            project_name=config.project_name,
            project_root=root,
            github_owner=owner,
            github_repo=repo_name,
            runtime_profile=config.runtime_profile or RuntimeProfile.CORE,
            project_yaml=yaml_data,
        )

    repo = _resolve_registration_repo(config, root)
    digest = _canonical_config_digest(yaml_data)
    existing = repo.get(config.project_key)
    registry_action = _converge_project_registry(
        repo,
        config,
        root,
        existing=existing,
        owner=owner,
        repo_name=repo_name,
        digest=digest,
    )
    try:
        project_action = _sync_project_management_project(config, root, yaml_data)
    except Exception as exc:  # noqa: BLE001 - CP7 must return a typed failure.
        return _cp7_sync_failure_result(config, exc, start=start)
    return _cp7_convergence_result(
        config,
        existing=existing,
        registry_action=registry_action,
        project_action=project_action,
        digest=digest,
        start=start,
    )


def _cp7_validated_github_coordinates(
    config: InstallConfig,
    *,
    start: float,
) -> tuple[str, str] | CheckpointResult:
    """Return the mandatory GitHub coordinates, or the CP 7 failure that refuses them."""
    from agentkit.backend.installer.github_coordinates import validate_github_coordinate
    from agentkit.backend.installer.registration import (
        CP7_STATE_BACKEND_REGISTRATION,
        REASON_INVALID_GITHUB_COORDINATES,
        REASON_MISSING_GITHUB_COORDINATES,
        CheckpointResult,
        CheckpointStatus,
    )

    # FK-50 §50.3 CP 7 lists GitHub owner/repo as MANDATORY coordinates. A
    # missing (``None``) OR empty/whitespace-only coordinate is equally invalid:
    # ``""`` / ``"   "`` carries no GitHub identity and would persist a
    # meaningless ``project_registry`` row (fail-open). Both are treated as a
    # hard precondition violation => FAILED, no write. §50.6 maps a CP 7
    # precondition violation to FAILED. Returning SKIPPED here would leave the
    # project UNREGISTERED after a "successful" install (fail-open). It never
    # fabricates github values (ZERO DEBT) and never writes a partial row.
    owner = config.github_owner
    repo_name = config.github_repo
    if owner is None or repo_name is None or not owner.strip() or not repo_name.strip():
        return CheckpointResult(
            checkpoint=CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "Missing or empty github_owner/github_repo on InstallConfig; "
                "project_registry requires both NOT NULL and non-empty (FK-50 "
                "§50.3 CP 7). CP 7 fails closed rather than leaving the project "
                "unregistered or persisting an empty coordinate."
            ),
            reason=REASON_MISSING_GITHUB_COORDINATES,
            duration_ms=_elapsed_ms(start),
        )

    # FAIL-CLOSED / SSOT (AG3-039 R7 ERROR-2): the coordinates are PRESENT but
    # must additionally be WELL-FORMED before they are persisted. The CLI and
    # the remote-URL parser already gate on ``validate_github_coordinate``; a
    # direct ``install_agentkit(InstallConfig(...))`` call would otherwise bypass
    # that single validation truth and persist a malformed coordinate (e.g.
    # ``".."``, ``"-bad"``, a slash- or control-char-laden value). Enforce the
    # SAME predicate at this port so no path can write an invalid row. The
    # downstream ``ProjectRegistration`` model validator is the hard floor; this
    # check turns a would-be ``ValueError`` into a clean FAILED CheckpointResult.
    if validate_github_coordinate(owner, repo_name) is None:
        return CheckpointResult(
            checkpoint=CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Malformed github_owner={owner!r} / github_repo={repo_name!r} "
                "on InstallConfig; not a well-formed GitHub owner/repo (FK-50 "
                "§50.3 CP 7, AG3-039 R6 E-b). CP 7 fails closed rather than "
                "persisting an invalid project_registry coordinate."
            ),
            reason=REASON_INVALID_GITHUB_COORDINATES,
            duration_ms=_elapsed_ms(start),
        )
    return (owner, repo_name)


def _converge_project_registry(
    repo: ProjectRegistrationRepository,
    config: InstallConfig,
    root: Path,
    *,
    existing: ProjectRegistration | None,
    owner: str,
    repo_name: str,
    digest: str,
) -> str:
    """Bring the ``project_registry`` row onto the current digest; name what happened."""
    from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile

    if existing is None:
        repo.save(
            ProjectRegistration(
                project_key=config.project_key,
                project_root=root,
                github_owner=owner,
                github_repo=repo_name,
                runtime_profile=config.runtime_profile or RuntimeProfile.CORE,
                config_version=PROJECT_CONFIG_VERSION,
                config_digest=digest,
                registered_at=datetime.now(tz=UTC),
            )
        )
        return "created"
    if existing.config_digest == digest:
        return "unchanged"
    repo.update_upgraded(config.project_key, datetime.now(tz=UTC), digest)
    return "updated"


def _cp7_sync_failure_result(
    config: InstallConfig,
    exc: BaseException,
    *,
    start: float,
) -> CheckpointResult:
    """Report a registry row that could not be mirrored into the visible project list."""
    from agentkit.backend.installer.registration import (
        CP7_STATE_BACKEND_REGISTRATION,
        CheckpointResult,
        CheckpointStatus,
    )

    detail = f"Project {config.project_key!r} was written to project_registry "
    detail += "but could not be synchronised to the visible project list "
    detail += f"(projects): {type(exc).__name__}: {exc}"
    return CheckpointResult(
        checkpoint=CP7_STATE_BACKEND_REGISTRATION,
        status=CheckpointStatus.FAILED,
        detail=detail,
        reason="project_management_sync_failed",
        duration_ms=_elapsed_ms(start),
    )


def _cp7_convergence_result(
    config: InstallConfig,
    *,
    existing: ProjectRegistration | None,
    registry_action: str,
    project_action: str,
    digest: str,
    start: float,
) -> CheckpointResult:
    """Map the registry/project-list outcome pair onto ONE CP 7 checkpoint status."""
    from agentkit.backend.installer.registration import (
        CP7_STATE_BACKEND_REGISTRATION,
        REASON_CONFIG_DIGEST_UNCHANGED,
        CheckpointResult,
        CheckpointStatus,
    )

    reason: str | None = None
    if registry_action == "created":
        status = CheckpointStatus.CREATED
        detail = f"Registered project {config.project_key!r} (digest {digest[:12]}); project-management row {project_action}."
    elif registry_action == "unchanged" and project_action == "unchanged":
        status = CheckpointStatus.SKIPPED
        reason = REASON_CONFIG_DIGEST_UNCHANGED
        detail = (
            f"Project {config.project_key!r} already registered with matching "
            "config_digest and visible project row; idempotent skip."
        )
    else:
        status = CheckpointStatus.UPDATED
        existing_config_digest = existing.config_digest if existing is not None else None
        detail = _cp7_updated_detail(
            config.project_key,
            existing_config_digest,
            registry_action,
            digest,
            project_action,
        )
    return CheckpointResult(
        checkpoint=CP7_STATE_BACKEND_REGISTRATION,
        status=status,
        detail=detail,
        reason=reason,
        duration_ms=_elapsed_ms(start),
    )
