"""Execution-Contract-Digest: assembler, effect classes, fence predicate.

Owner: prompt-runtime BC (FK-44 `authority_over` scope
``execution-contract-digest``). Blood-type A
(``concept/methodology/software-blutgruppen.md``): pure canonicalization +
SHA-256 over already-resolved plain inputs. No I/O, no ``state_backend`` row
layer, no HTTP -- callers (``control_plane``, blood-type R/AT) gather the raw
inputs and persist the result; this module knows nothing about Postgres, the
run's persistence identity, or the wire/HTTP layer.

FK-44 §44.3a generalizes the existing run-prompt-pin (§44.3) into a broader
execution contract: an active run works against a FROZEN business execution
contract, whose digest is formed at setup from

  (a) the story-spec version / load-bearing spec fields (FK-59 §59.9a:
      Scope, acceptance criteria, story text);
  (b) the relevant project/QA/gate configuration;
  (c) the skill-, prompt- and capability-versions.

The run-prompt-pin (``prompt_runtime.pins``) remains a COMPONENT of this
digest; its own semantics (``binding_changes_affect_only_future_runs``) are
unchanged -- this module never reads or writes the pin file itself.

Also carries the three effect classes for a contract-component change during
an active run (SOLL-096) and the digest-as-fence-PREDICATE DEFINITION
(SOLL-097, FK-91 §91.1a Rule 15). The predicate's USE in job-completion
fencing (``stale_observation`` classification) is AG3-144 -- this module only
DEFINES the predicate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

#: Bumped whenever the canonicalization or the digest's component list
#: changes (contract-pinned, ``tests/contract/**``). A format change is a NEW
#: digest identity, never a silent reinterpretation of an existing one.
DIGEST_FORMAT_VERSION = 1

_SHA256_HEX_LENGTH = 64


class StorySpecComponent(BaseModel):
    """The story's load-bearing spec fields (FK-59 §59.9a).

    Mirrors ``story_context_manager.story_model.StorySpecification`` -- the
    story-lifecycle BC's authoritative spec content (Scope / acceptance
    criteria / story text as currently modelled: ``need``/``solution``
    carry the problem/solution narrative, ``acceptance`` the acceptance
    criteria, the remaining fields the scope-defining references). There is
    no separate persisted "spec version" counter in the domain model; the
    digest is content-addressed over the CURRENT specification value, which
    is a strictly stronger identity than a monotonic counter (any content
    change necessarily changes the digest).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    need: str | None = None
    solution: str | None = None
    acceptance: tuple[str, ...] = ()
    definition_of_done: tuple[str, ...] | None = None
    concept_refs: tuple[str, ...] | None = None
    guardrail_refs: tuple[str, ...] | None = None
    external_sources: tuple[str, ...] | None = None


class RunPromptPinComponent(BaseModel):
    """The run-prompt-pin coordinates consumed as a digest component (FK-44 §44.3).

    Carries the same three coordinates ``prompt_runtime.pins.PromptRunPin``
    pins for a run. This module never resolves or persists the pin itself
    (AT-free) -- the caller resolves it and passes its coordinates in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_manifest_sha256: str


class SkillVersionComponent(BaseModel):
    """One bound skill's version coordinate (FK-43 ``skill-binding``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    bundle_id: str
    bundle_version: str


class ExecutionContractInputs(BaseModel):
    """All raw, already-resolved inputs the digest is deterministically formed from.

    Component list (FK-44 §44.3a):
      (a) ``story_spec`` -- the story-spec version / load-bearing fields.
      (b) ``project_config_version`` / ``project_config_digest`` -- the
          relevant project/QA/gate configuration (the canonical
          ``ProjectRegistration.config_version``/``config_digest`` pair;
          SINGLE SOURCE OF TRUTH, never a second ``project.yaml``
          canonicalization).
      (c) ``skill_versions`` / ``capability_version`` -- the skill- and
          capability-versions. ``run_prompt_pin`` carries the prompt version
          (FK-44 §44.3, a component of this digest, not duplicated here).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_spec: StorySpecComponent
    project_config_version: str
    project_config_digest: str
    skill_versions: tuple[SkillVersionComponent, ...] = ()
    capability_version: str
    run_prompt_pin: RunPromptPinComponent


def _canonical_json(value: object) -> str:
    """Deterministic JSON: recursively sorted keys, compact, stable across runs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonicalize_execution_contract(inputs: ExecutionContractInputs) -> str:
    """Build the canonical (deterministic) serialization of *inputs*.

    Contract-pinned (``tests/contract/**``): the component list and key
    names are part of the digest's public shape. ``digest_format_version``
    is the first-class format identity -- any future canonicalization change
    bumps :data:`DIGEST_FORMAT_VERSION`, which changes the digest for every
    subsequent run rather than silently reinterpreting the existing format.

    ``skill_versions`` is sorted by the TOTAL key ``(skill_name, bundle_id,
    bundle_version)`` -- not merely ``skill_name`` (Codex r1 CRITICAL finding):
    a single-field key is not a total order over the component multiset, so
    two callers enumerating the SAME components in a different order could
    produce different canonical JSON whenever ``skill_name`` repeats (e.g. two
    bundle coordinates bound under the same skill name). This pure
    canonicalizer is the contract boundary (FK-44 `authority_over`) and must
    be self-sufficiently deterministic; it must never rely on an upstream
    caller's de-duplication or ordering discipline to get a stable byte shape.

    Args:
        inputs: The fully-resolved digest inputs.

    Returns:
        The canonical JSON text (deterministic key order, no whitespace).
    """
    payload = {
        "digest_format_version": DIGEST_FORMAT_VERSION,
        "story_spec": inputs.story_spec.model_dump(mode="json"),
        "project_config_version": inputs.project_config_version,
        "project_config_digest": inputs.project_config_digest,
        "skill_versions": [
            component.model_dump(mode="json")
            for component in sorted(
                inputs.skill_versions,
                key=lambda c: (c.skill_name, c.bundle_id, c.bundle_version),
            )
        ],
        "capability_version": inputs.capability_version,
        "run_prompt_pin": inputs.run_prompt_pin.model_dump(mode="json"),
    }
    return _canonical_json(payload)


def compute_execution_contract_digest(inputs: ExecutionContractInputs) -> str:
    """Deterministically compute the ``execution_contract_digest`` (SHA-256 hex).

    Same *inputs* always yield an identical digest (AC1); a change to any
    load-bearing spec field, the project/QA/gate config, a skill/prompt/
    capability version or the run-prompt-pin coordinates yields a DIFFERENT
    digest.

    Args:
        inputs: The fully-resolved digest inputs.

    Returns:
        The lowercase 64-char SHA-256 hex digest.
    """
    canonical = canonicalize_execution_contract(inputs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExecutionContractDigestRecord(BaseModel):
    """Persisted, run-scoped execution-contract digest (FK-44 §44.3a, SOLL-095).

    Identity is ``(project_key, story_id, run_id)`` -- one row per run,
    inserted exactly once, atomically with the run's committed setup-start
    (mirrors ``control_plane.records.RunOwnershipRecord``). Read-only after
    insert: there is no update path (fail-closed --
    ``execution_contract_digest`` never silently drifts for a running run).

    Raises:
        ValueError: On an empty identity field or a digest that is not a
            64-char lowercase hex string.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    execution_contract_digest: str
    digest_format_version: int
    formed_at: datetime

    @field_validator("project_key", "story_id", "run_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identity fields must be non-empty")
        return value

    @field_validator("execution_contract_digest")
    @classmethod
    def _valid_sha256_hex(cls, value: str) -> str:
        if len(value) != _SHA256_HEX_LENGTH or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise ValueError(
                "execution_contract_digest must be a 64-char lowercase SHA-256 "
                f"hex digest, got {value!r}",
            )
        return value


# ---------------------------------------------------------------------------
# Three effect classes (SOLL-096, FK-44 §44.3a)
# ---------------------------------------------------------------------------


class ExecutionContractEffectClass(StrEnum):
    """The three admissible effect classes for a contract-component change
    during an active execution regime (FK-44 §44.3a). Never a fourth, never
    a silent mid-run drift.

    * ``RUN_NEUTRAL`` -- the change touches no component of the running
      run's digest at all.
    * ``PINNED_FOR_NEW_RUNS`` -- the DEFAULT: the change becomes effective,
      but only for future runs; the running run keeps working on its own
      persisted digest (mirrors the run-prompt-pin's
      ``binding_changes_affect_only_future_runs``, FK-44 §44.3).
    * ``DELIBERATE_ADMINISTRATIVE_INTERVENTION`` -- the change is meant to
      hit the running run; it runs visibly against the run owner or as an
      explicit run invalidation (FK-56 §56.13), never as silent drift. The
      command surface for this class is AG3-148/AG3-154.
    """

    RUN_NEUTRAL = "run_neutral"
    PINNED_FOR_NEW_RUNS = "pinned_for_new_runs"
    DELIBERATE_ADMINISTRATIVE_INTERVENTION = "deliberate_administrative_intervention"


#: The default effect class for any contract-component change made during
#: an active run, absent an explicit administrative decision otherwise
#: (FK-44 §44.3a).
DEFAULT_EXECUTION_CONTRACT_EFFECT_CLASS = (
    ExecutionContractEffectClass.PINNED_FOR_NEW_RUNS
)


# ---------------------------------------------------------------------------
# Digest-as-fence-PREDICATE definition (SOLL-097, FK-91 §91.1a Rule 15)
# ---------------------------------------------------------------------------


class ExecutionContractFenceOutcome(StrEnum):
    """Deterministic, lock-free outcome of the digest fence predicate."""

    MATCH = "match"
    MISMATCH = "mismatch"


def evaluate_execution_contract_fence(
    *,
    persisted_digest: str,
    current_digest: str,
) -> ExecutionContractFenceOutcome:
    """Compare a run's PERSISTED digest against a freshly formed current one.

    Pure equality, no I/O, no lock (FK-44 §44.3a / FK-91 §91.1a Rule 15):
    deterministic MATCH/MISMATCH for the same two digest strings, every
    time. A MISMATCH means the execution-contract basis diverged
    (administratively) after the run started. The USE of this predicate in
    job-completion fencing -- treating the affected result as
    ``stale_observation`` -- is AG3-144; this function only DEFINES the
    predicate.

    Args:
        persisted_digest: The run's persisted ``execution_contract_digest``.
        current_digest: A digest freshly (re)computed from the current
            contract basis.

    Returns:
        ``MATCH`` when both digests are identical, else ``MISMATCH``.
    """
    if persisted_digest == current_digest:
        return ExecutionContractFenceOutcome.MATCH
    return ExecutionContractFenceOutcome.MISMATCH


__all__ = [
    "DEFAULT_EXECUTION_CONTRACT_EFFECT_CLASS",
    "DIGEST_FORMAT_VERSION",
    "ExecutionContractDigestRecord",
    "ExecutionContractEffectClass",
    "ExecutionContractFenceOutcome",
    "ExecutionContractInputs",
    "RunPromptPinComponent",
    "SkillVersionComponent",
    "StorySpecComponent",
    "canonicalize_execution_contract",
    "compute_execution_contract_digest",
    "evaluate_execution_contract_fence",
]
