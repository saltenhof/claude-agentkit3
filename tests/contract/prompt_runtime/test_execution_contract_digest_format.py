"""Contract/golden pin for the execution-contract-digest FORMAT (AG3-143, AC1).

FK-44 §44.3a: the ``execution_contract_digest`` is a fencing predicate whose
byte-for-byte stability across releases is a contract, not an implementation
detail. This module pins:

- the CANONICALIZATION (the exact deterministic JSON serialization) and the
  COMPONENT LIST (the top-level keys the digest is formed over) via a golden
  canonical string;
- a GOLDEN digest for fixed inputs -- any change to the canonicalization, the
  component list, or the hashing changes this value and breaks the pin
  deliberately (CLAUDE.md state discipline: a persisted/wire format change
  must pull its contract/golden test with it);
- the ``DIGEST_FORMAT_VERSION`` first-class format identity;
- the persisted ``ExecutionContractDigestRecord`` field set (the run-scoped
  persistence shape) and the closed effect-class / fence-outcome vocabularies.

Any drift here is a concept break (FK-44 §44.3a) and must be addressed
explicitly, not by silently re-baselining the golden.
"""

from __future__ import annotations

from agentkit.backend.prompt_runtime.execution_contract import (
    DIGEST_FORMAT_VERSION,
    ExecutionContractDigestRecord,
    ExecutionContractEffectClass,
    ExecutionContractFenceOutcome,
    ExecutionContractInputs,
    RunPromptPinComponent,
    SkillVersionComponent,
    StorySpecComponent,
    canonicalize_execution_contract,
    compute_execution_contract_digest,
)

# ---------------------------------------------------------------------------
# Fixed golden input (frozen -- do NOT edit to make a changed format "pass")
# ---------------------------------------------------------------------------

_GOLDEN_INPUTS = ExecutionContractInputs(
    story_spec=StorySpecComponent(
        need="The problem narrative.",
        solution="The scope / solution text.",
        acceptance=("AC1 first", "AC2 second"),
        definition_of_done=("DoD one",),
        concept_refs=("FK-44",),
        guardrail_refs=("ARCH-55",),
        external_sources=("https://example.test",),
    ),
    project_config_version="7",
    project_config_digest="a" * 64,
    skill_versions=(
        SkillVersionComponent(skill_name="implement", bundle_id="core", bundle_version="3"),
        SkillVersionComponent(skill_name="review", bundle_id="core", bundle_version="2"),
    ),
    capability_version="0.1.0",
    run_prompt_pin=RunPromptPinComponent(
        prompt_bundle_id="core",
        prompt_bundle_version="1",
        prompt_manifest_sha256="f" * 64,
    ),
)

#: The frozen canonical serialization of ``_GOLDEN_INPUTS`` (compact, recursively
#: sorted keys). This IS the component-list + canonicalization contract.
_GOLDEN_CANONICAL = (
    '{"capability_version":"0.1.0","digest_format_version":1,'
    '"project_config_digest":"' + "a" * 64 + '",'
    '"project_config_version":"7",'
    '"run_prompt_pin":{"prompt_bundle_id":"core","prompt_bundle_version":"1",'
    '"prompt_manifest_sha256":"' + "f" * 64 + '"},'
    '"skill_versions":[{"bundle_id":"core","bundle_version":"3","skill_name":"implement"},'
    '{"bundle_id":"core","bundle_version":"2","skill_name":"review"}],'
    '"story_spec":{"acceptance":["AC1 first","AC2 second"],"concept_refs":["FK-44"],'
    '"definition_of_done":["DoD one"],"external_sources":["https://example.test"],'
    '"guardrail_refs":["ARCH-55"],"need":"The problem narrative.",'
    '"solution":"The scope / solution text."}}'
)

#: The frozen SHA-256 of ``_GOLDEN_CANONICAL``.
_GOLDEN_DIGEST = "7dee1354f664b4a40e5a07c702c4fdae1424cf0321f990828b6c71cc8476a851"


# ---------------------------------------------------------------------------
# AC1: canonicalization + component list + golden digest
# ---------------------------------------------------------------------------


def test_canonicalization_matches_golden() -> None:
    """The canonical serialization is byte-for-byte stable (component list +
    key structure pin). A change here is a deliberate format change.
    """
    assert canonicalize_execution_contract(_GOLDEN_INPUTS) == _GOLDEN_CANONICAL


def test_digest_matches_golden() -> None:
    """The digest of the fixed golden inputs is frozen (FK-44 §44.3a)."""
    assert compute_execution_contract_digest(_GOLDEN_INPUTS) == _GOLDEN_DIGEST


def test_component_list_is_the_pinned_top_level_key_set() -> None:
    """The digest is formed over EXACTLY these top-level components (FK-44
    §44.3a): the format version, the story-spec, the project config
    version+digest, the skill versions, the capability version and the
    run-prompt-pin. A new/removed component is a deliberate format change.
    """
    import json

    payload = json.loads(_GOLDEN_CANONICAL)
    assert set(payload) == {
        "digest_format_version",
        "story_spec",
        "project_config_version",
        "project_config_digest",
        "skill_versions",
        "capability_version",
        "run_prompt_pin",
    }


def test_digest_format_version_is_pinned() -> None:
    assert DIGEST_FORMAT_VERSION == 1


# ---------------------------------------------------------------------------
# CRITICAL fix (Codex r1): skill_versions total-order determinism
# ---------------------------------------------------------------------------


def test_skill_versions_reordering_is_digest_invariant_with_duplicate_skill_name() -> None:
    """The canonicalizer sorts ``skill_versions`` by the TOTAL key
    ``(skill_name, bundle_id, bundle_version)`` -- not merely ``skill_name``.

    A single-field sort key is not a total order over the component
    multiset: Python's stable sort preserves the CALLER's original relative
    order for equal keys, so two callers passing the SAME multiset with
    duplicate ``skill_name`` values in a different order could canonicalize
    to different byte shapes (and therefore different digests) under a
    skill_name-only sort. This pure canonicalizer is the digest's contract
    boundary and must be self-sufficiently deterministic -- it must not rely
    on an upstream caller's de-duplication or ordering discipline.
    """
    duplicate_name_a = SkillVersionComponent(
        skill_name="same", bundle_id="a", bundle_version="1",
    )
    duplicate_name_b = SkillVersionComponent(
        skill_name="same", bundle_id="b", bundle_version="1",
    )

    def _inputs(skill_versions: tuple[SkillVersionComponent, ...]) -> ExecutionContractInputs:
        return ExecutionContractInputs(
            story_spec=StorySpecComponent(need="n", solution="s", acceptance=()),
            project_config_version="1",
            project_config_digest="a" * 64,
            skill_versions=skill_versions,
            capability_version="0.1.0",
            run_prompt_pin=RunPromptPinComponent(
                prompt_bundle_id="core",
                prompt_bundle_version="1",
                prompt_manifest_sha256="f" * 64,
            ),
        )

    ordered_ab = _inputs((duplicate_name_a, duplicate_name_b))
    ordered_ba = _inputs((duplicate_name_b, duplicate_name_a))

    canonical_ab = canonicalize_execution_contract(ordered_ab)
    canonical_ba = canonicalize_execution_contract(ordered_ba)

    assert canonical_ab == canonical_ba
    assert compute_execution_contract_digest(ordered_ab) == compute_execution_contract_digest(
        ordered_ba,
    )


# ---------------------------------------------------------------------------
# Component + persisted-record field sets (schema stability)
# ---------------------------------------------------------------------------


def test_story_spec_component_field_set() -> None:
    assert set(StorySpecComponent.model_fields) == {
        "need",
        "solution",
        "acceptance",
        "definition_of_done",
        "concept_refs",
        "guardrail_refs",
        "external_sources",
    }


def test_run_prompt_pin_component_field_set() -> None:
    assert set(RunPromptPinComponent.model_fields) == {
        "prompt_bundle_id",
        "prompt_bundle_version",
        "prompt_manifest_sha256",
    }


def test_skill_version_component_field_set() -> None:
    assert set(SkillVersionComponent.model_fields) == {
        "skill_name",
        "bundle_id",
        "bundle_version",
    }


def test_execution_contract_inputs_field_set() -> None:
    assert set(ExecutionContractInputs.model_fields) == {
        "story_spec",
        "project_config_version",
        "project_config_digest",
        "skill_versions",
        "capability_version",
        "run_prompt_pin",
    }


def test_persisted_digest_record_field_set() -> None:
    """The run-scoped persistence shape (execution_contract_digests row)."""
    assert set(ExecutionContractDigestRecord.model_fields) == {
        "project_key",
        "story_id",
        "run_id",
        "execution_contract_digest",
        "digest_format_version",
        "formed_at",
    }


def test_all_component_models_are_frozen_extra_forbid() -> None:
    for model in (
        StorySpecComponent,
        RunPromptPinComponent,
        SkillVersionComponent,
        ExecutionContractInputs,
        ExecutionContractDigestRecord,
    ):
        assert model.model_config.get("frozen") is True
        assert model.model_config.get("extra") == "forbid"


# ---------------------------------------------------------------------------
# Closed vocabularies (SOLL-096 effect classes, SOLL-097 fence outcome)
# ---------------------------------------------------------------------------


def test_effect_class_vocabulary_is_pinned() -> None:
    assert {member.value for member in ExecutionContractEffectClass} == {
        "run_neutral",
        "pinned_for_new_runs",
        "deliberate_administrative_intervention",
    }


def test_fence_outcome_vocabulary_is_pinned() -> None:
    assert {member.value for member in ExecutionContractFenceOutcome} == {
        "match",
        "mismatch",
    }
