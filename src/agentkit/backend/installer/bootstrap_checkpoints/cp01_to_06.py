"""Checkpoint handlers CP 1, CP 2, CP 3, CP 4, CP 5, CP 6 (FK-50 §50.3).

Early preconditions and the project-config / profile-resolution checkpoints:

* CP 1 — Python package check (``import agentkit; assert agentkit.__version__``).
* CP 2 — GitHub repo existence / ``gh`` auth check (fail-closed, FK-50 §50.6).
* CP 3 / CP 4 — reserved no-op nodes (number stability, FK-50 §50.3).
* CP 5 — pipeline config (``.agentkit/config/project.yaml``), transferred from
  the legacy ``install_agentkit`` body (idempotent: never overwrites).
* CP 6 — project-profile resolution as a real checkpoint with a result
  (previously the internal ``_resolve_skill_profile`` only).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_RESERVED,
    REASON_RUNTIME_DEPENDENCY_UNAVAILABLE,
)
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.dependency_preflight import (
        DependencyPreflightReport,
    )
    from agentkit.backend.installer.registration import CheckpointResult

#: Machine reason for a CP 1 failure (package not importable / no version).
REASON_PACKAGE_UNAVAILABLE = "package_unavailable"
#: Machine reason for a CP 1 failure outside the dedicated virtual environment.
REASON_RUNTIME_NOT_ISOLATED = "runtime_not_isolated"
#: Machine reason for a CP 2 failure (repo missing / gh unauthenticated / absent).
REASON_REPO_UNREACHABLE = "repo_unreachable"
#: Machine reason for a CP 2 failure (mandatory coordinates absent).
REASON_MISSING_COORDINATES = "missing_github_coordinates"


def dependency_preflight_checkpoint(
    *,
    report: DependencyPreflightReport | None,
    declaration_error: str | None,
    preflight_duration_ms: int,
) -> CheckpointResult:
    """Build the sole CP 1 result for an incomplete runtime environment."""
    from agentkit.backend.installer.dependency_preflight import (
        format_dependency_failures,
    )

    if report is not None and report.passed:
        raise ValueError("dependency preflight failure result requires a failing report")
    if declaration_error is not None:
        detail = (
            "AgentKit runtime dependency declaration is unavailable: "
            f"{declaration_error}"
        )
    elif report is not None:
        detail = format_dependency_failures(report)
    else:
        detail = "AgentKit runtime dependency preflight produced no report."
    return make_result(
        nid.CP_01_PACKAGE_CHECK,
        status=CheckpointStatus.FAILED,
        detail=detail,
        reason=REASON_RUNTIME_DEPENDENCY_UNAVAILABLE,
        start=time.monotonic(),
        prior_duration_ms=preflight_duration_ms,
    )


def runtime_isolation_checkpoint(
    *,
    detail: str,
    start: float,
) -> CheckpointResult:
    """Build the CP 1 result for the pre-dependency runtime boundary."""
    return make_result(
        nid.CP_01_PACKAGE_CHECK,
        status=CheckpointStatus.FAILED,
        detail=detail,
        reason=REASON_RUNTIME_NOT_ISOLATED,
        start=start,
    )


def cp01_package_check(context: CheckpointContext) -> CheckpointResult:
    """CP 1 — verify AgentKit and its declared runtime set (read-only).

    Pure check, no action (FK-50 §50.3 CP 1). Identical in every mode (never
    mutates), so dry-run/verify produce the same PASS/FAILED as register.
    """
    start = time.monotonic()
    from agentkit.backend.installer.interpreter import (
        InterpreterResolutionError,
        resolve_ak3_interpreter,
    )

    try:
        interpreter = resolve_ak3_interpreter()
    except InterpreterResolutionError as exc:
        return runtime_isolation_checkpoint(
            detail=str(exc),
            start=start,
        )
    dependency_report = context.run_state.dependency_preflight
    preflight_precedes_handler = dependency_report is not None
    if dependency_report is None:
        from agentkit.backend.installer.dependency_preflight import (
            DependencyDeclarationError,
            check_runtime_dependencies,
        )

        try:
            dependency_report = check_runtime_dependencies()
        except DependencyDeclarationError as exc:
            return dependency_preflight_checkpoint(
                report=None,
                declaration_error=str(exc),
                preflight_duration_ms=exc.duration_ms,
            )
        context.run_state.dependency_preflight = dependency_report
    if not dependency_report.passed:
        return dependency_preflight_checkpoint(
            report=dependency_report,
            declaration_error=None,
            preflight_duration_ms=dependency_report.duration_ms,
        )
    prior_duration_ms = (
        dependency_report.duration_ms if preflight_precedes_handler else 0
    )
    try:
        import agentkit

        version = getattr(agentkit, "__version__", "")
    except Exception as exc:  # noqa: BLE001 - any import failure is fail-closed
        return make_result(
            nid.CP_01_PACKAGE_CHECK,
            status=CheckpointStatus.FAILED,
            detail=f"agentkit package is not importable: {exc}",
            reason=REASON_PACKAGE_UNAVAILABLE,
            start=start,
            prior_duration_ms=prior_duration_ms,
        )
    if not version:
        return make_result(
            nid.CP_01_PACKAGE_CHECK,
            status=CheckpointStatus.FAILED,
            detail="agentkit.__version__ is empty; package metadata missing.",
            reason=REASON_PACKAGE_UNAVAILABLE,
            start=start,
            prior_duration_ms=prior_duration_ms,
        )
    return make_result(
        nid.CP_01_PACKAGE_CHECK,
        status=CheckpointStatus.PASS,
        detail=(
            f"agentkit {version} is isolated at {interpreter}; "
            f"{dependency_report.declared_count} declared runtime dependencies "
            "are importable."
        ),
        start=start,
        prior_duration_ms=prior_duration_ms,
    )


def cp02_repo_check(context: CheckpointContext) -> CheckpointResult:
    """CP 2 — verify the GitHub repo exists and ``gh`` is authenticated.

    Fail-closed (FK-50 §50.6, story AC4): a missing/unreachable repo or an
    unauthenticated ``gh`` is ``FAILED``, never a silent skip. The live check
    is an operational boundary, injected as a :class:`RepoExistenceProbe` on
    the config. AG3-146: the productive probe
    (:class:`~agentkit.backend.installer.repo_probe.GhCliRepoExistenceProbe`)
    routes through the code-backend port's ``repo_probe`` capability instead
    of invoking ``gh`` directly here or in the probe itself -- CP 2 stays
    ``gh``-mechanic-free (AC3):

    * a malformed/missing coordinate is always FAILED (fail-closed; never
      fabricated);
    * an injected probe returning ``exists=False`` (repo absent / ``gh``
      unauthenticated) is FAILED (the AC4 negative path);
    * with no probe injected, CP 2 validates the coordinate FORMAT only (the
      offline applicability path — it never fabricates a live verification);
    * a probe returning ``exists=True`` is PASS.

    The probe is read-only, so CP 2 runs identically in every execution mode.
    """
    from agentkit.backend.installer.github_coordinates import validate_github_coordinate

    start = time.monotonic()
    raw_owner = context.config.github_owner
    raw_repo = context.config.github_repo
    # Missing iff absent or whitespace-only (a "   " flag carries no identity).
    if raw_owner is None or raw_repo is None or not raw_owner.strip() or not raw_repo.strip():
        return make_result(
            nid.CP_02_REPO_CHECK,
            status=CheckpointStatus.FAILED,
            detail=("Missing github_owner/github_repo; CP 2 cannot verify the repo (FK-50 §50.3 CP 2)."),
            reason=REASON_MISSING_COORDINATES,
            start=start,
        )
    # Validate the RAW (unstripped) coordinate so an embedded control char (e.g.
    # a trailing newline ``"acme\n"``) is rejected fail-closed, not normalised
    # away (AG3-039 ERROR-1; validate_github_coordinate is the single truth).
    if validate_github_coordinate(raw_owner, raw_repo) is None:
        return make_result(
            nid.CP_02_REPO_CHECK,
            status=CheckpointStatus.FAILED,
            detail=f"Malformed github coordinate {raw_owner!r}/{raw_repo!r} (FK-50 §50.6).",
            reason=REASON_REPO_UNREACHABLE,
            start=start,
        )
    owner = raw_owner
    repo = raw_repo

    probe = context.config.repo_existence_probe
    if probe is None:
        return make_result(
            nid.CP_02_REPO_CHECK,
            status=CheckpointStatus.PASS,
            detail=(f"Coordinate {owner}/{repo} is well-formed (no live gh probe injected; format-only check)."),
            start=start,
        )
    outcome = probe(owner, repo)
    if not outcome.exists:
        return make_result(
            nid.CP_02_REPO_CHECK,
            status=CheckpointStatus.FAILED,
            detail=outcome.detail,
            reason=REASON_REPO_UNREACHABLE,
            start=start,
        )
    return make_result(
        nid.CP_02_REPO_CHECK,
        status=CheckpointStatus.PASS,
        detail=outcome.detail,
        start=start,
    )


def _reserved(node_id: str, context: CheckpointContext) -> CheckpointResult:
    """Deterministic reserved no-op result (``SKIPPED``/``reason=reserved``)."""
    start = time.monotonic()
    detail = f"Checkpoint {node_id} is reserved for checkpoint-number stability."
    if is_dry_run(context.mode):
        return planned_result(
            node_id,
            planned_status=CheckpointStatus.SKIPPED,
            detail=detail,
            skip_reason=REASON_RESERVED,
            start=start,
        )
    return make_result(
        node_id,
        status=CheckpointStatus.SKIPPED,
        detail=detail,
        reason=REASON_RESERVED,
        start=start,
    )


def cp03_reserved(context: CheckpointContext) -> CheckpointResult:
    """CP 3 — reserved no-op (FK-50 §50.3, story AC5)."""
    return _reserved(nid.CP_03_RESERVED, context)


def cp04_reserved(context: CheckpointContext) -> CheckpointResult:
    """CP 4 — reserved no-op (FK-50 §50.3, story AC5)."""
    return _reserved(nid.CP_04_RESERVED, context)


def cp05_pipeline_config(context: CheckpointContext) -> CheckpointResult:
    """CP 5 — materialise ``.agentkit/config/project.yaml`` (idempotent).

    Behaviour transferred from the legacy ``install_agentkit`` body: build the
    project.yaml mapping, write it when absent/changed (never overwrites with
    an unchanged digest), and publish the mapping on the run-state for CP 7
    (digest) and CP 10c (ARE-scope map). Dry-run/verify never write; they still
    publish the would-be mapping so downstream read-only checkpoints can verify.
    """
    from agentkit.backend.installer.config_boundary import (
        verify_config_before_first_effect,
    )
    from agentkit.backend.installer.paths import project_config_path
    from agentkit.backend.installer.runner import (
        _write_yaml_if_changed,
        scaffold_project_structure,
    )

    start = time.monotonic()
    yaml_data = context.run_state.project_yaml
    if yaml_data is None or context.run_state.project_config is None:
        raise ProjectError(
            "CP 5 has no strictly validated candidate configuration",
            detail={"reason": "configuration_invalid"},
        )
    yaml_path = project_config_path(context.project_root)
    rel = str(yaml_path.relative_to(context.project_root))
    exists = yaml_path.is_file()

    if not context.mode.mutations_allowed:
        return _cp05_read_only_result(context, exists=exists, rel=rel, start=start)

    before = context.run_state.config_before_image
    if before is None:
        raise ProjectError(
            "CP 5 has no configuration before-image",
            detail={"reason": "configuration_invalid"},
        )
    verify_config_before_first_effect(
        before,
        context.run_state.project_config,
    )

    # CP 5 materialises the NEUTRAL project scaffold (dirs + runtime working
    # dirs) and then the project.yaml. The active harness bindings are deferred
    # to CP 8 (strictly after CP 7), preserving the
    # ``state_backend_registration_precedes_bundle_binding`` invariant.
    _materialize_required_corpus_dirs(context)
    _record_new_scaffold_paths(
        context,
        scaffold_project_structure(context.config, context.project_root),
    )

    if before.existed:
        status = CheckpointStatus.PASS
        detail = f"{rel} is byte-identical to the strictly validated input."
    elif _write_yaml_if_changed(yaml_path, yaml_data):
        context.run_state.created_files.append(rel)
        status = CheckpointStatus.CREATED if not exists else CheckpointStatus.UPDATED
        detail = f"{'Created' if not exists else 'Updated'} {rel}."
    else:
        status = CheckpointStatus.PASS
        detail = f"{rel} already current; no write (idempotent)."
    return make_result(nid.CP_05_PIPELINE_CONFIG, status=status, detail=detail, start=start)


def _cp05_read_only_result(
    context: CheckpointContext,
    *,
    exists: bool,
    rel: str,
    start: float,
) -> CheckpointResult:
    planned = CheckpointStatus.PASS if exists else CheckpointStatus.CREATED
    detail = (
        f"{rel} already present; would leave unchanged (idempotent)."
        if exists
        else f"Would create {rel}."
    )
    if is_dry_run(context.mode):
        return planned_result(
            nid.CP_05_PIPELINE_CONFIG,
            planned_status=planned,
            detail=detail,
            start=start,
        )
    return make_result(
        nid.CP_05_PIPELINE_CONFIG,
        status=planned,
        detail=detail,
        start=start,
    )


def _materialize_required_corpus_dirs(context: CheckpointContext) -> None:
    project_config = context.run_state.project_config
    assert project_config is not None
    for required_rel in (project_config.concepts_dir, project_config.wiki_stories_dir):
        required_dir = context.project_root / required_rel
        if required_dir.is_dir():
            continue
        required_dir.mkdir(parents=True)
        context.run_state.created_files.append(str(required_rel))


def _record_new_scaffold_paths(context: CheckpointContext, scaffold_paths: list[str]) -> None:
    for scaffold_rel in scaffold_paths:
        if scaffold_rel not in context.run_state.created_files:
            context.run_state.created_files.append(scaffold_rel)


def cp06_profile_resolution(context: CheckpointContext) -> CheckpointResult:
    """CP 6 — resolve the project profile (``core``/``are``) as a checkpoint.

    Promotes the internal ``_resolve_skill_profile`` to a real checkpoint with a
    :class:`CheckpointResult` (story §2.1.2). Pure resolution, no mutation, so it
    is identical in every mode. Publishes the resolved
    :class:`RuntimeProfile` on the run-state for CP 7.
    """
    from agentkit.backend.installer.registration import RuntimeProfile
    from agentkit.backend.installer.runner import _resolve_skill_profile

    start = time.monotonic()
    # Skill profile resolution validates the configured profile fail-closed.
    _resolve_skill_profile(context.config)
    profile = context.config.runtime_profile or RuntimeProfile.CORE
    context.run_state.resolved_profile = profile
    return make_result(
        nid.CP_06_PROFILE_RESOLUTION,
        status=CheckpointStatus.PASS,
        detail=f"Resolved runtime profile {profile.value!r}.",
        start=start,
    )


__all__ = [
    "REASON_MISSING_COORDINATES",
    "REASON_PACKAGE_UNAVAILABLE",
    "REASON_REPO_UNREACHABLE",
    "cp01_package_check",
    "cp02_repo_check",
    "cp03_reserved",
    "cp04_reserved",
    "cp05_pipeline_config",
    "cp06_profile_resolution",
    "dependency_preflight_checkpoint",
]
