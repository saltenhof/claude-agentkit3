"""Compatibility facade over canonical QA artifact persistence helpers."""

from __future__ import annotations

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    LEGACY_VERIFY_DECISION_FILE,
    PROTECTED_QA_ARTIFACTS,
    VERIFY_DECISION_FILE,
    record_layer_artifacts,
    record_verify_decision,
)
from agentkit.state_backend.exports import (
    build_legacy_verify_decision_artifact,
    build_verify_decision_artifact,
    load_json_object,
    load_verify_decision_projection,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
    write_layer_projection,
    write_verify_decision_projection,
)


def load_verify_decision_artifact(
    story_dir,
):
    """Compatibility wrapper for verify decision projection reads."""

    return load_verify_decision_projection(story_dir)


def write_layer_artifacts(
    story_dir,
    *,
    layer_results,
    attempt_nr: int,
):
    """Compatibility wrapper that persists canonical layer records."""

    normalized = tuple(layer_results)
    try:
        return record_layer_artifacts(
            story_dir,
            layer_results=normalized,
            attempt_nr=attempt_nr,
        )
    except CorruptStateError:
        # Legacy callers may use the facade outside a bound story run.
        produced: list[str] = []
        for layer_result in normalized:
            artifact_name = write_layer_projection(
                story_dir,
                layer_result=layer_result,
                attempt_nr=attempt_nr,
            )
            if artifact_name is not None:
                produced.append(artifact_name)
        return tuple(produced)


def write_verify_decision_artifacts(
    story_dir,
    *,
    decision,
    attempt_nr: int,
):
    """Compatibility wrapper that persists canonical decision records."""

    try:
        return record_verify_decision(
            story_dir,
            decision=decision,
            attempt_nr=attempt_nr,
        )
    except CorruptStateError:
        # Legacy callers may use the facade outside a bound story run.
        return write_verify_decision_projection(
            story_dir,
            decision=decision,
            attempt_nr=attempt_nr,
        )


__all__ = [
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "LEGACY_VERIFY_DECISION_FILE",
    "PROTECTED_QA_ARTIFACTS",
    "VERIFY_DECISION_FILE",
    "build_legacy_verify_decision_artifact",
    "build_verify_decision_artifact",
    "load_json_object",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
