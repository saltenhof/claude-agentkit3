"""Individual structural checks backed by the canonical state store."""

from __future__ import annotations

from agentkit.exceptions import CorruptStateError
from agentkit.qa.protocols import Finding, Severity, TrustClass
from agentkit.state_backend import (
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
    VERIFY_DECISION_FILE,
    read_artifact_record,
    read_phase_snapshot_record,
    read_phase_state_record,
    read_story_context_record,
)
from agentkit.state_backend.exports import LAYER_ARTIFACT_FILES

_ARTIFACT_NAME_TO_KIND: dict[str, str] = {
    artifact_name: layer
    for layer, artifact_name in LAYER_ARTIFACT_FILES.items()
}
_ARTIFACT_NAME_TO_KIND[VERIFY_DECISION_FILE] = "verify_decision"


def check_context_exists(story_dir) -> Finding | None:
    """Check that a canonical story context record exists."""

    try:
        if read_story_context_record(story_dir) is not None:
            return None
    except CorruptStateError:
        pass
    return Finding(
        layer="structural",
        check="context_exists",
        severity=Severity.CRITICAL,
        trust_class=TrustClass.SYSTEM,
        message=(
            "Canonical story context record missing; "
            f"{CONTEXT_EXPORT_FILE} cannot act as truth"
        ),
    )


def check_context_valid(story_dir) -> Finding | None:
    """Check that the canonical story context can be loaded."""

    try:
        read_story_context_record(story_dir)
    except CorruptStateError:
        return Finding(
            layer="structural",
            check="context_valid",
            severity=Severity.CRITICAL,
            trust_class=TrustClass.SYSTEM,
            message="Canonical story context record is corrupt or invalid",
        )
    return None


def check_phase_snapshots(story_dir, required_phases: list[str]) -> list[Finding]:
    """Check that required canonical phase snapshots exist."""

    findings: list[Finding] = []
    for phase in required_phases:
        try:
            snapshot = read_phase_snapshot_record(story_dir, phase)
        except CorruptStateError:
            snapshot = None
        if snapshot is None:
            findings.append(
                Finding(
                    layer="structural",
                    check="phase_snapshots",
                    severity=Severity.HIGH,
                    trust_class=TrustClass.SYSTEM,
                    message=f"Canonical phase snapshot missing for phase '{phase}'",
                    suggestion=f"Ensure phase '{phase}' completed before verify.",
                )
            )
    return findings


def check_artifacts_present(story_dir, required_artifacts: list[str]) -> list[Finding]:
    """Check that required operational artifacts exist."""

    findings: list[Finding] = []
    for artifact in required_artifacts:
        artifact_kind = _ARTIFACT_NAME_TO_KIND.get(artifact)
        if artifact_kind is not None:
            try:
                if read_artifact_record(story_dir, artifact_kind) is not None:
                    continue
            except CorruptStateError:
                pass
        elif (story_dir / artifact).exists():
            continue

        artifact_path = story_dir / artifact
        if artifact_kind is not None:
            findings.append(
                Finding(
                    layer="structural",
                    check="artifacts_present",
                    severity=Severity.HIGH,
                    trust_class=TrustClass.SYSTEM,
                    message=(
                        "Required canonical artifact record missing "
                        f"for projection '{artifact}'"
                    ),
                    file_path=str(artifact_path),
                )
            )
            continue

        findings.append(
            Finding(
                layer="structural",
                check="artifacts_present",
                severity=Severity.HIGH,
                trust_class=TrustClass.SYSTEM,
                message=f"Required artifact missing: '{artifact}'",
                file_path=str(artifact_path),
            )
        )
    return findings


def check_no_corrupt_state(story_dir) -> Finding | None:
    """Check that the canonical current phase-state record is valid if present."""

    try:
        read_phase_state_record(story_dir)
    except CorruptStateError:
        return Finding(
            layer="structural",
            check="no_corrupt_state",
            severity=Severity.HIGH,
            trust_class=TrustClass.SYSTEM,
            message=(
                "Canonical phase state record is corrupt or invalid; "
                f"{PHASE_STATE_EXPORT_FILE} cannot act as truth"
            ),
        )
    return None
