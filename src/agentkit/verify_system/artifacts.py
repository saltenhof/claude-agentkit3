"""QA artifact persistence and reads.

Migration AG3-023: Dieses Modul war zuvor direkter Persistenz-Owner.
Es ist jetzt ein Konsument von ArtifactManager — verify-system schreibt
nur noch via ArtifactManager, kein eigener Persistenz-Owner mehr.

Backward-Compat: Die drei Funktionen (write_layer_artifacts,
write_verify_decision_artifacts, load_verify_decision_artifact) behalten
ihre Signaturen. Interne Implementierung nutzt jetzt ArtifactManager
(falls verfuegbar, via _get_manager()), faellt aber auf die bisherige
Projektions-Persistenz zurueck wenn kein Manager injiziert wurde
(Legacy-Kompatibilitaets-Pfad fuer Aufrufer ausserhalb eines Story-Runs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.exceptions import CorruptStateError
from agentkit.governance.guard_system.protected_paths import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    PROTECTED_QA_ARTIFACTS,
    VERIFY_DECISION_FILE,
)
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.state_backend.store import (
    load_latest_verify_decision,
    load_latest_verify_decision_for_scope,
    record_layer_artifacts,
    record_verify_decision,
    resolve_runtime_scope,
)
from agentkit.verify_system.policy_engine.projections import (
    build_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult


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

    return _load_verify_decision_projection(_qa_projection_dir(story_dir))


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
            projection_dir=_qa_projection_dir(story_dir),
        )
    except CorruptStateError:
        # Legacy callers may use the facade outside a bound story run.
        produced: list[str] = []
        for layer_result in normalized:
            artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
            if artifact_name is None:
                continue
            target_dir = _qa_projection_dir(story_dir)
            _write_projection(target_dir / artifact_name, serialize_layer_result(layer_result, attempt_nr=attempt_nr))
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
            projection_dir=_qa_projection_dir(story_dir),
        )
    except CorruptStateError:
        # Legacy callers may use the facade outside a bound story run.
        canonical_payload = build_verify_decision_artifact(decision, attempt_nr=attempt_nr)
        target_dir = _qa_projection_dir(story_dir)
        _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
        return (VERIFY_DECISION_FILE,)


def _load_verify_decision_projection(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the verify-decision projection file if present."""

    canonical = load_json_object(story_dir / VERIFY_DECISION_FILE)
    if canonical is not None:
        return VERIFY_DECISION_FILE, canonical
    return None


def _write_projection(path: Path, payload: dict[str, object]) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _qa_projection_dir(story_dir: Path) -> Path:
    return resolve_qa_story_dir(story_dir, story_id=story_dir.name)


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
