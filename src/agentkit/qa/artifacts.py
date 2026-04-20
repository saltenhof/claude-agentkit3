"""QA artifact persistence and reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    PROTECTED_QA_ARTIFACTS,
    VERIFY_DECISION_FILE,
    load_latest_verify_decision,
    load_latest_verify_decision_for_scope,
    record_layer_artifacts,
    record_verify_decision,
    resolve_runtime_scope,
)
from agentkit.state_backend.exports import (
    build_verify_decision_artifact,
    load_json_object,
    load_verify_decision_projection,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
    write_layer_projection,
    write_verify_decision_projection,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import LayerResult


def load_verify_decision_artifact(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the canonical verify decision, falling back only if absent."""

    try:
        scope = resolve_runtime_scope(story_dir)
    except CorruptStateError:
        scope = None
    if scope is not None and scope.run_id is not None:
        payload = load_latest_verify_decision_for_scope(scope)
        if payload is not None:
            return VERIFY_DECISION_FILE, payload

    payload = load_latest_verify_decision(story_dir)
    if payload is not None:
        return VERIFY_DECISION_FILE, payload

    return load_verify_decision_projection(story_dir)


def write_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
) -> tuple[str, ...]:
    """Persist canonical layer records."""

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
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
) -> tuple[str, ...]:
    """Persist canonical decision records."""

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
    "PROTECTED_QA_ARTIFACTS",
    "VERIFY_DECISION_FILE",
    "build_verify_decision_artifact",
    "load_json_object",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
