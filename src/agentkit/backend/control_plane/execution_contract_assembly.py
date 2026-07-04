"""Execution-contract-digest assembly for a fresh setup start (AG3-143).

Extracted from ``control_plane.runtime._ControlPlaneRuntimeAdmissionBase``
(Sonar build #988, ``PY_CLASS_MAX_LOC_800``: that class had accreted the
AG3-142 ownership-fence machinery AND the AG3-143 digest assembly, pushing it
over the 800-LOC warning threshold). This module gathers the
``execution_contract_digest``'s raw inputs -- the story's
``StorySpecification`` (FK-59 §59.9a load-bearing spec fields), the project's
registered config version/digest, the project's bound skill versions, the
installed AK3 capability version, and the run's run-prompt-pin (FK-44 §44.3)
-- and forms the deterministic digest via the pure prompt-runtime assembler
(FK-44 §44.3a, SOLL-095). A component that cannot be resolved is reported as
a rejection reason (never raised), so a genuinely fresh setup start rejects
fail-closed (AC2) instead of letting an exception escape the atomic claim
machinery.

Purely a cohesive relocation of pre-existing AG3-143 logic: the admission
class's ``_build_execution_contract_digest`` now thinly delegates to
:func:`build_execution_contract_digest` and keeps its own setup/finalize
control flow untouched; behavior is unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import PhaseMutationRequest
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

__all__ = (
    "ExecutionContractDigestOutcome",
    "build_execution_contract_digest",
)

#: AG3-143 (FK-44 §44.3a, AC2, Codex r1 CRITICAL fix): the shape a
#: ``ProjectRegistration.config_digest`` must have to be admitted as a digest
#: component -- a lowercase 64-char SHA-256 hex string, mirroring
#: :data:`agentkit.backend.prompt_runtime.execution_contract._SHA256_HEX_LENGTH`'s
#: validation. A blank or malformed ``config_digest``/``config_version`` must
#: never be silently hashed into the execution-contract digest as a partial
#: component -- it fails the fresh setup start closed instead (see
#: :func:`build_execution_contract_digest`).
_PROJECT_CONFIG_DIGEST_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ExecutionContractDigestOutcome:
    """Outcome of resolving a fresh setup's ``execution_contract_digest`` inputs.

    AG3-143 (FK-44 §44.3a, AC2): exactly one of ``digest`` /
    ``rejection_reason`` is non-``None``. A ``rejection_reason`` means at
    least one digest component (story spec, project registration/config,
    run-prompt-pin) could not be resolved -- the fresh setup start is
    rejected fail-closed BEFORE the engine dispatch runs, so no run ever
    enters the execution regime without a persisted digest and no partial
    engine write is produced by a digest failure.
    """

    digest: str | None
    rejection_reason: str | None


def build_execution_contract_digest(
    *,
    repo: ControlPlaneRuntimeRepository,
    request: PhaseMutationRequest,
    run_id: str,
) -> ExecutionContractDigestOutcome:
    """Resolve + form the execution_contract_digest for a fresh setup (AG3-143).

    FK-44 §44.3a (SOLL-095): gathers the digest's raw inputs -- the
    story's ``StorySpecification`` (the load-bearing spec fields,
    FK-59 §59.9a), the project's registered config version/digest (the
    relevant project/QA/gate configuration; SINGLE SOURCE OF TRUTH, never
    a second ``project.yaml`` canonicalization), the project's bound
    skill versions, the installed AK3 capability (package) version, and
    the run's run-prompt-pin (FK-44 §44.3, resolved/created HERE if this
    is the run's first prompt-runtime touch -- the normative "at setup"
    moment, AG3-143 closes the pre-existing gap where nothing called
    ``ensure_run_prompt_pin_present`` productively at setup) -- then forms
    the deterministic digest via the pure prompt-runtime assembler.

    A component that cannot be resolved is reported as a rejection
    reason (never raised): the caller rejects the fresh setup start
    fail-closed (AC2) instead of letting an exception escape the atomic
    claim machinery.

    Args:
        repo: The control-plane runtime persistence port used to load the
            run's ``StoryContext`` (the SAME port the caller uses for every
            other regime mutation -- one repository, one DI seam).
        request: The mutating call's ``PhaseMutationRequest``.
        run_id: The run's identifier (used to resolve/create the
            run-prompt-pin, FK-44 §44.3).

    Returns:
        The :class:`ExecutionContractDigestOutcome` -- either the formed
        digest or a fail-closed rejection reason.
    """
    from agentkit.backend.exceptions import ProjectError
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractInputs,
        RunPromptPinComponent,
        SkillVersionComponent,
        StorySpecComponent,
        compute_execution_contract_digest,
    )
    from agentkit.backend.prompt_runtime.pins import ensure_run_prompt_pin_present

    ctx = repo.load_story_context(request.project_key, request.story_id)
    if ctx is None:
        reason = "execution_contract_digest could not be formed: the run's "
        reason += "StoryContext is unexpectedly unresolvable at setup "
        reason += "(fail-closed, FK-44 §44.3a)."
        return ExecutionContractDigestOutcome(digest=None, rejection_reason=reason)

    from agentkit.backend.state_backend.store.project_registration_repository import (
        StateBackendProjectRegistrationRepository,
    )

    registration = StateBackendProjectRegistrationRepository().get(
        request.project_key
    )
    if registration is None:
        reason = "execution_contract_digest could not be formed: no "
        reason += f"project_registry entry for project_key={request.project_key!r} "
        reason += "(fail-closed, FK-44 §44.3a component 'project/QA/gate "
        reason += "configuration')."
        return ExecutionContractDigestOutcome(digest=None, rejection_reason=reason)
    #: Codex r1 CRITICAL fix (AC2): a registered project with a blank
    #: ``config_version`` or a malformed ``config_digest`` is an
    #: UNRESOLVABLE 'project/QA/gate configuration' component -- reject
    #: fail-closed here, the SAME way as the "no registration" branch
    #: above, instead of hashing a partial/invalid component into the
    #: digest. ``ProjectRegistration`` has no field-level validator for
    #: these (installer/upgrade tests seed non-hex placeholder digests
    #: that a model-level validator would break); this is the digest's
    #: own admission gate for the shape it actually depends on.
    if not registration.config_version.strip() or not (
        _PROJECT_CONFIG_DIGEST_HEX_PATTERN.fullmatch(registration.config_digest)
    ):
        reason = "execution_contract_digest could not be formed: "
        reason += f"project_key={request.project_key!r} has a blank "
        reason += "config_version or a config_digest that is not a 64-char "
        reason += "lowercase SHA-256 hex string (fail-closed, FK-44 §44.3a "
        reason += "component 'project/QA/gate configuration')."
        return ExecutionContractDigestOutcome(digest=None, rejection_reason=reason)

    from agentkit.backend.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )

    spec = StateBackendStoryRepository().get_specification(ctx.story_uuid)
    if spec is None:
        reason = "execution_contract_digest could not be formed: no "
        reason += f"StorySpecification for story_uuid={ctx.story_uuid} "
        reason += "(fail-closed, FK-44 §44.3a component 'story-spec fields')."
        return ExecutionContractDigestOutcome(digest=None, rejection_reason=reason)

    from agentkit.backend.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    skill_versions = tuple(
        sorted(
            (
                SkillVersionComponent(
                    skill_name=binding.skill_name,
                    bundle_id=binding.bundle_id,
                    bundle_version=binding.bundle_version,
                )
                for binding in StateBackendSkillBindingRepository().list_for_project(
                    request.project_key
                )
            ),
            key=lambda component: component.skill_name,
        )
    )

    try:
        pin = ensure_run_prompt_pin_present(registration.project_root, run_id=run_id)
    except ProjectError as exc:
        reason = "execution_contract_digest could not be formed: the "
        reason += f"run-prompt-pin could not be resolved ({exc}); fail-closed "
        reason += "(FK-44 §44.3a component 'run-prompt-pin', FK-44 §44.3)."
        return ExecutionContractDigestOutcome(digest=None, rejection_reason=reason)

    import agentkit

    inputs = ExecutionContractInputs(
        story_spec=StorySpecComponent(
            need=spec.need,
            solution=spec.solution,
            acceptance=tuple(spec.acceptance),
            definition_of_done=(
                tuple(spec.definition_of_done)
                if spec.definition_of_done is not None
                else None
            ),
            concept_refs=(
                tuple(spec.concept_refs) if spec.concept_refs is not None else None
            ),
            guardrail_refs=(
                tuple(spec.guardrail_refs)
                if spec.guardrail_refs is not None
                else None
            ),
            external_sources=(
                tuple(spec.external_sources)
                if spec.external_sources is not None
                else None
            ),
        ),
        project_config_version=registration.config_version,
        project_config_digest=registration.config_digest,
        skill_versions=skill_versions,
        capability_version=agentkit.__version__,
        run_prompt_pin=RunPromptPinComponent(
            prompt_bundle_id=pin.prompt_bundle_id,
            prompt_bundle_version=pin.prompt_bundle_version,
            prompt_manifest_sha256=pin.prompt_manifest_sha256,
        ),
    )
    return ExecutionContractDigestOutcome(
        digest=compute_execution_contract_digest(inputs),
        rejection_reason=None,
    )
