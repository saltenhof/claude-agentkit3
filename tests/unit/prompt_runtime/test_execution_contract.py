"""Tests for the execution-contract-digest assembler (AG3-143, FK-44 §44.3a).

Covers AC1 (digest determinism + canonicalization/component-list pin -- the
canonicalization/format PIN itself lives in
``tests/contract/prompt_runtime/test_execution_contract_digest_format.py``),
SOLL-096 (three effect classes) and SOLL-097 (the digest-as-fence-predicate
DEFINITION -- its USE in job-completion fencing is AG3-144, out of scope
here).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.backend.prompt_runtime.execution_contract import (
    DEFAULT_EXECUTION_CONTRACT_EFFECT_CLASS,
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
    evaluate_execution_contract_fence,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _pin(**overrides: str) -> RunPromptPinComponent:
    defaults: dict[str, str] = {
        "prompt_bundle_id": "core",
        "prompt_bundle_version": "1",
        "prompt_manifest_sha256": "f" * 64,
    }
    defaults.update(overrides)
    return RunPromptPinComponent(**defaults)


def _inputs(**overrides: object) -> ExecutionContractInputs:
    defaults: dict[str, object] = {
        "story_spec": StorySpecComponent(
            need="Need text",
            solution="Solution text",
            acceptance=("AC1", "AC2"),
        ),
        "project_config_version": "1",
        "project_config_digest": "a" * 64,
        "skill_versions": (
            SkillVersionComponent(
                skill_name="implement", bundle_id="core", bundle_version="3",
            ),
        ),
        "capability_version": "0.1.0",
        "run_prompt_pin": _pin(),
    }
    defaults.update(overrides)
    return ExecutionContractInputs(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC1: digest determinism
# ---------------------------------------------------------------------------


def test_same_inputs_yield_identical_digest() -> None:
    first = compute_execution_contract_digest(_inputs())
    second = compute_execution_contract_digest(_inputs())

    assert first == second
    assert len(first) == 64
    assert all(char in "0123456789abcdef" for char in first)


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_config_version": "2"},
        {"project_config_digest": "b" * 64},
        {"capability_version": "0.2.0"},
    ],
)
def test_changing_a_top_level_component_changes_the_digest(
    overrides: dict[str, object],
) -> None:
    baseline = compute_execution_contract_digest(_inputs())
    changed = compute_execution_contract_digest(_inputs(**overrides))

    assert baseline != changed


def test_changing_story_spec_acceptance_changes_the_digest() -> None:
    baseline = compute_execution_contract_digest(_inputs())
    changed_spec = StorySpecComponent(
        need="Need text", solution="Solution text", acceptance=("AC1", "AC2", "AC3"),
    )
    changed = compute_execution_contract_digest(_inputs(story_spec=changed_spec))

    assert baseline != changed


def test_changing_run_prompt_pin_changes_the_digest() -> None:
    baseline = compute_execution_contract_digest(_inputs())
    changed = compute_execution_contract_digest(
        _inputs(run_prompt_pin=_pin(prompt_bundle_version="2")),
    )

    assert baseline != changed


def test_skill_version_order_does_not_change_the_digest() -> None:
    """Skill-version ORDER is not semantically meaningful -- the assembler sorts
    by ``(skill_name, bundle_id, bundle_version)`` before canonicalizing, so two
    callers enumerating the same bound skills in a different order still
    produce the identical digest.
    """
    a = SkillVersionComponent(skill_name="a-skill", bundle_id="core", bundle_version="1")
    b = SkillVersionComponent(skill_name="b-skill", bundle_id="core", bundle_version="1")

    ordered_ab = compute_execution_contract_digest(_inputs(skill_versions=(a, b)))
    ordered_ba = compute_execution_contract_digest(_inputs(skill_versions=(b, a)))

    assert ordered_ab == ordered_ba


def test_adding_a_skill_binding_changes_the_digest() -> None:
    baseline = compute_execution_contract_digest(_inputs(skill_versions=()))
    with_skill = compute_execution_contract_digest(
        _inputs(
            skill_versions=(
                SkillVersionComponent(
                    skill_name="implement", bundle_id="core", bundle_version="1",
                ),
            ),
        ),
    )

    assert baseline != with_skill


def test_canonicalize_is_stable_deterministic_json() -> None:
    first = canonicalize_execution_contract(_inputs())
    second = canonicalize_execution_contract(_inputs())

    assert first == second
    assert '"digest_format_version":' in first
    # Compact, no incidental whitespace (deterministic byte-for-byte form).
    assert "\n" not in first
    assert ", " not in first


# ---------------------------------------------------------------------------
# ExecutionContractDigestRecord (persistence record, fail-closed validation)
# ---------------------------------------------------------------------------


def test_execution_contract_digest_record_accepts_valid_digest() -> None:
    from datetime import UTC, datetime

    record = ExecutionContractDigestRecord(
        project_key="ak3",
        story_id="AK3-001",
        run_id="run-1",
        execution_contract_digest="a" * 64,
        digest_format_version=DIGEST_FORMAT_VERSION,
        formed_at=datetime.now(UTC),
    )

    assert record.execution_contract_digest == "a" * 64
    assert record.digest_format_version == DIGEST_FORMAT_VERSION


@pytest.mark.parametrize(
    "bad_digest",
    [
        "",
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "A" * 64,
    ],
)
def test_execution_contract_digest_record_rejects_malformed_digest(
    bad_digest: str,
) -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        ExecutionContractDigestRecord(
            project_key="ak3",
            story_id="AK3-001",
            run_id="run-1",
            execution_contract_digest=bad_digest,
            digest_format_version=DIGEST_FORMAT_VERSION,
            formed_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("field_key", ["project_key", "story_id", "run_id"])
def test_execution_contract_digest_record_rejects_empty_identity_field(
    field_key: str,
) -> None:
    from datetime import UTC, datetime

    values: dict[str, object] = {
        "project_key": "ak3",
        "story_id": "AK3-001",
        "run_id": "run-1",
        "execution_contract_digest": "a" * 64,
        "digest_format_version": DIGEST_FORMAT_VERSION,
        "formed_at": datetime.now(UTC),
    }
    values[field_key] = "   "

    with pytest.raises(ValidationError):
        ExecutionContractDigestRecord(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SOLL-096: three effect classes
# ---------------------------------------------------------------------------


def test_effect_class_is_a_closed_three_value_enum() -> None:
    values = {member.value for member in ExecutionContractEffectClass}

    assert values == {
        "run_neutral",
        "pinned_for_new_runs",
        "deliberate_administrative_intervention",
    }


def test_default_effect_class_is_pinned_for_new_runs() -> None:
    """FK-44 §44.3a: the DEFAULT for a contract-component change during an
    active run is 'pinned-for-new-runs' -- the running run keeps its own
    digest; only a NEW run picks up the change. Never a silent mid-run drift.
    """
    assert (
        DEFAULT_EXECUTION_CONTRACT_EFFECT_CLASS
        is ExecutionContractEffectClass.PINNED_FOR_NEW_RUNS
    )


# ---------------------------------------------------------------------------
# SOLL-097 / FK-91 §91.1a Rule 15: digest-as-fence-PREDICATE definition
# ---------------------------------------------------------------------------


def test_fence_predicate_matches_identical_digests() -> None:
    digest = compute_execution_contract_digest(_inputs())

    outcome = evaluate_execution_contract_fence(
        persisted_digest=digest, current_digest=digest,
    )

    assert outcome is ExecutionContractFenceOutcome.MATCH


def test_fence_predicate_mismatches_diverged_digests() -> None:
    persisted = compute_execution_contract_digest(_inputs())
    current = compute_execution_contract_digest(_inputs(project_config_version="2"))

    outcome = evaluate_execution_contract_fence(
        persisted_digest=persisted, current_digest=current,
    )

    assert outcome is ExecutionContractFenceOutcome.MISMATCH


def test_fence_predicate_is_deterministic_and_lock_free() -> None:
    """No I/O, no shared state -- calling it repeatedly with the same inputs
    never changes the outcome (the 'lock-free' half of SOLL-097).
    """
    digest_a = "a" * 64
    digest_b = "b" * 64

    results = {
        evaluate_execution_contract_fence(
            persisted_digest=digest_a, current_digest=digest_b,
        )
        for _ in range(50)
    }

    assert results == {ExecutionContractFenceOutcome.MISMATCH}
