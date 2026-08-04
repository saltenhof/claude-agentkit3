"""Fail-closed scope validation for the atomic FK-69 QA batch."""

from __future__ import annotations

from typing import Any

from agentkit.backend.exceptions import CorruptStateError


def _required_int(row: dict[str, object], key: str) -> int:
    value = row[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} is not an integer")
    return value


def _row_scope(
    row: dict[str, object],
) -> tuple[str, str, str, int]:
    try:
        return (
            str(row["project_key"]),
            str(row["story_id"]),
            str(row["run_id"]),
            _required_int(row, "attempt_no"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptStateError("QA batch contains a row with an incomplete scope") from exc


def _validate_finding_rows(
    finding_rows: object,
    *,
    expected_scope: tuple[str, str, str, int],
    stage_id: str,
    artifact_id: str,
    identities: set[tuple[str, str]],
) -> None:
    if not isinstance(finding_rows, list):
        raise CorruptStateError("QA batch layer has malformed finding rows")
    for finding_row in finding_rows:
        if not isinstance(finding_row, dict):
            raise CorruptStateError("QA batch contains a malformed finding row")
        identity = (
            str(finding_row.get("stage_id", "")),
            str(finding_row.get("finding_id", "")),
        )
        if (
            _row_scope(finding_row) != expected_scope
            or identity[0] != stage_id
            or not identity[1]
            or str(finding_row.get("artifact_id", "")) != artifact_id
        ):
            raise CorruptStateError(f"QA batch finding is outside its parent stage: {identity!r}")
        if identity in identities:
            raise CorruptStateError(f"QA batch contains duplicate finding identity: {identity!r}")
        identities.add(identity)


def _validate_layer_payload(
    item: dict[str, object],
    *,
    expected_scope: tuple[str, str, str, int],
    attempt_nr: int,
    stage_ids: set[str],
    layer_names: set[str],
    finding_identities: set[tuple[str, str]],
) -> None:
    layer = str(item.get("layer", ""))
    if not layer or layer in layer_names:
        raise CorruptStateError(f"QA batch contains an empty or duplicate layer identity: {layer!r}")
    layer_names.add(layer)
    stage_row = item.get("stage_row")
    reference = item.get("artifact_reference")
    if not isinstance(stage_row, dict) or not isinstance(reference, dict):
        raise CorruptStateError(f"QA batch layer {layer!r} lacks a typed stage/reference row")
    if _row_scope(stage_row) != expected_scope:
        raise CorruptStateError(f"QA batch stage scope does not match the replaced snapshot: {layer!r}")
    stage_id = str(stage_row.get("stage_id", ""))
    if not stage_id or stage_id in stage_ids:
        raise CorruptStateError(f"QA batch contains an empty or duplicate stage identity: {stage_id!r}")
    stage_ids.add(stage_id)
    artifact_id = str(item.get("artifact_id", ""))
    reference_matches = (
        str(stage_row.get("layer", "")) == layer
        and str(stage_row.get("artifact_id", "")) == artifact_id
        and str(reference.get("artifact_class", "")) == "qa"
        and str(reference.get("story_id", "")) == expected_scope[1]
        and str(reference.get("run_id", "")) == expected_scope[2]
        and str(reference.get("record_key", "")) == artifact_id
        and item.get("artifact_attempt") == attempt_nr
    )
    if not reference_matches:
        raise CorruptStateError(f"QA batch layer {layer!r} is not bound to its canonical artifact reference")
    _validate_finding_rows(
        item.get("finding_rows"),
        expected_scope=expected_scope,
        stage_id=stage_id,
        artifact_id=artifact_id,
        identities=finding_identities,
    )


def _validate_outcome_rows(
    rows: list[dict[str, object]],
    *,
    expected_scope: tuple[str, str, str, int],
    stage_ids: set[str],
) -> None:
    identities: set[tuple[str, str, str, int, str, str]] = set()
    for row in rows:
        try:
            identity = (
                str(row["project_key"]),
                str(row["story_id"]),
                str(row["run_id"]),
                _required_int(row, "attempt_no"),
                str(row["stage_id"]),
                str(row["check_id"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptStateError("QA batch contains an outcome with an incomplete identity") from exc
        if identity[:4] != expected_scope:
            raise CorruptStateError(
                "QA batch outcome scope does not match the replaced attempt "
                f"snapshot: expected={expected_scope!r}, actual={identity[:4]!r}"
            )
        if identity[4] not in stage_ids:
            raise CorruptStateError(f"QA batch outcome has no parent stage in the complete snapshot: {identity[4:]!r}")
        if identity in identities:
            raise CorruptStateError(f"QA batch contains duplicate outcome identity: {identity!r}")
        identities.add(identity)


def validate_qa_layer_batch_rows(
    *,
    flow_row: dict[str, Any],
    canonical_story_id: str,
    layer_payload_rows: list[dict[str, object]],
    check_outcome_rows: list[dict[str, object]],
    attempt_nr: int,
) -> None:
    """Require every row to belong uniquely to the replaced snapshot."""
    try:
        expected_scope = (
            str(flow_row["project_key"]),
            canonical_story_id,
            str(flow_row["run_id"]),
            attempt_nr,
        )
        flow_story_id = str(flow_row["story_id"])
    except KeyError as exc:
        raise CorruptStateError("QA batch flow scope is incomplete") from exc
    if flow_story_id != canonical_story_id:
        raise CorruptStateError("QA batch flow story does not match the canonical story scope")

    stage_ids: set[str] = set()
    layer_names: set[str] = set()
    finding_identities: set[tuple[str, str]] = set()
    for item in layer_payload_rows:
        _validate_layer_payload(
            item,
            expected_scope=expected_scope,
            attempt_nr=attempt_nr,
            stage_ids=stage_ids,
            layer_names=layer_names,
            finding_identities=finding_identities,
        )
    _validate_outcome_rows(
        check_outcome_rows,
        expected_scope=expected_scope,
        stage_ids=stage_ids,
    )
