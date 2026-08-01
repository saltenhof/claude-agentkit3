"""Canonical serialization and strict parsing of completion records."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.record_fields import positive_int, required_strings
from agentkit.backend.vectordb.sync import (
    ProducerCompletion,
    SyncError,
    SyncReceipt,
    completion_run_id,
    parse_utc_timestamp,
)
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "project_id",
    "source_file",
    "source_type",
    "corpus_revision",
    "digest",
    "state",
    "completed_at",
    "sequence",
    "generation",
)
_RUN_RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "project_id",
    "run_id",
    "receipts_json",
    "producer_completions_json",
    "batch_digest",
    "completed_at",
    "sequence_start",
    "sequence_end",
)
_RECEIPT_NAMESPACE = uuid.UUID("8c5e2f3a-1b6d-4e7a-9c8f-2a1b3c4d5e6f")
_RUN_RECEIPT_NAMESPACE = uuid.UUID("c3b74614-293d-4a72-9155-672f86d41b89")


@dataclass(frozen=True)
class _CompletionRunRecord:
    uuid: str
    properties: dict[str, str]
    receipts: tuple[SyncReceipt, ...]
    producer_completions: tuple[ProducerCompletion, ...]
    sequence_start: int
    sequence_end: int


def completion_position_uuid(project_id: str, sequence: int) -> str:
    """Return the deterministic identity of a completion position."""
    return str(uuid.uuid5(_RECEIPT_NAMESPACE, f"{project_id}|{sequence}"))


def run_position_uuid(project_id: str, sequence_start: int) -> str:
    """Return the deterministic identity of an atomic completion-run position."""
    return str(
        uuid.uuid5(
            _RUN_RECEIPT_NAMESPACE,
            f"{project_id}|{sequence_start}",
        )
    )


def _render_receipt_batch(receipts: Sequence[SyncReceipt]) -> str:
    """Render a canonical immutable completion batch."""
    payload = [
        {
            "project_id": receipt.project_id,
            "source_file": receipt.source_file,
            "source_type": receipt.source_type,
            "corpus_revision": receipt.corpus_revision,
            "digest": receipt.digest,
            "state": receipt.state.value,
            "completed_at": receipt.completed_at,
            "sequence": receipt.sequence,
            "generation": receipt.generation,
        }
        for receipt in receipts
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def render_producer_completions(
    completions: Sequence[ProducerCompletion],
) -> str:
    """Render canonical producer-wide completion summaries."""
    payload = [
        {
            "corpus_revision": completion.corpus_revision,
            "producer": completion.producer,
            "project_id": completion.project_id,
            "sequence": completion.sequence,
            "source_types": list(completion.source_types),
        }
        for completion in completions
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def run_receipt_digest(
    *,
    project_id: str,
    run_id: str,
    receipts_json: str,
    producer_completions_json: str,
    completed_at: str,
    sequence_start: int,
    sequence_end: int,
) -> str:
    """Bind the run record to its identity, receipt content and order."""
    material = json.dumps(
        {
            "completed_at": completed_at,
            "project_id": project_id,
            "producer_completions_json": producer_completions_json,
            "receipts_json": receipts_json,
            "run_id": run_id,
            "sequence_end": sequence_end,
            "sequence_start": sequence_start,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _reject_duplicate_json_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject duplicate keys in persisted receipt JSON (no last-wins)."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VectorDbUnavailableError(f"completion batch contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _parse_receipt_batch(
    *,
    project_id: str,
    raw: str,
) -> list[SyncReceipt]:
    """Strictly parse every receipt in one immutable run record."""
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VectorDbUnavailableError(f"completion batch is not strict JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise VectorDbUnavailableError("completion batch must be a JSON list")
    out: list[SyncReceipt] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise VectorDbUnavailableError(f"completion batch item {index} is not an object")
        if set(item) != set(_RECEIPT_FIELDS):
            raise VectorDbUnavailableError(f"completion batch item {index} has an invalid field set")
        source_file = item.get("source_file")
        if not isinstance(source_file, str) or not source_file:
            raise VectorDbUnavailableError(f"completion batch item {index} has no source_file")
        out.append(receipt_from_props(project_id, source_file, item))
    return out


def _parse_producer_completions(
    *,
    project_id: str,
    raw: str,
) -> list[ProducerCompletion]:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VectorDbUnavailableError(f"producer completion batch is not strict JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise VectorDbUnavailableError("producer completion batch must be a non-empty JSON list")
    completions: list[ProducerCompletion] = []
    for index, item in enumerate(payload):
        completions.append(
            _parse_producer_completion_item(
                project_id=project_id,
                item=item,
                index=index,
            )
        )
    producers = [item.producer for item in completions]
    if len(producers) != len(set(producers)):
        raise VectorDbUnavailableError("producer completion batch contains duplicate producers")
    return completions


def _parse_producer_completion_item(
    *,
    project_id: str,
    item: object,
    index: int,
) -> ProducerCompletion:
    if not isinstance(item, dict):
        raise VectorDbUnavailableError(f"producer completion item {index} is not an object")
    expected_keys = {
        "corpus_revision",
        "producer",
        "project_id",
        "sequence",
        "source_types",
    }
    if set(item) != expected_keys:
        raise VectorDbUnavailableError(f"producer completion item {index} has an invalid field set")
    source_types = item["source_types"]
    if (
        not isinstance(source_types, list)
        or not source_types
        or any(not isinstance(value, str) or not value for value in source_types)
    ):
        raise VectorDbUnavailableError(f"producer completion item {index} has invalid source_types")
    completion = ProducerCompletion(
        project_id=_strict_json_string(item["project_id"], field_name="project_id"),
        producer=_strict_json_string(item["producer"], field_name="producer"),
        source_types=tuple(source_types),
        corpus_revision=_strict_json_string(
            item["corpus_revision"],
            field_name="corpus_revision",
        ),
        sequence=positive_int(item["sequence"], field_name="sequence"),
    )
    if completion.project_id != project_id:
        raise VectorDbUnavailableError("producer completion carries a foreign project identity")
    try:
        completion.verify()
    except SyncError as exc:
        raise VectorDbUnavailableError(f"producer completion item {index} is invalid: {exc}") from exc
    return completion


def _parse_run_record(
    uid: str,
    props: Mapping[str, object],
    *,
    project_id: str,
) -> _CompletionRunRecord:
    values = required_strings(
        props,
        _RUN_RECEIPT_FIELDS,
        context=f"completion run {uid!r}",
    )
    if values["project_id"] != project_id:
        raise VectorDbUnavailableError(f"completion run {uid!r} carries a foreign project identity")
    sequence_start = positive_int(
        values["sequence_start"],
        field_name="sequence_start",
    )
    sequence_end = positive_int(
        values["sequence_end"],
        field_name="sequence_end",
    )
    expected_uuid = run_position_uuid(
        project_id,
        sequence_start,
    )
    if uid != expected_uuid:
        raise VectorDbUnavailableError(f"completion run {values['run_id']!r} is stored under the wrong atomic position identity")
    expected_digest = run_receipt_digest(
        project_id=project_id,
        run_id=values["run_id"],
        receipts_json=values["receipts_json"],
        producer_completions_json=values["producer_completions_json"],
        completed_at=values["completed_at"],
        sequence_start=sequence_start,
        sequence_end=sequence_end,
    )
    if values["batch_digest"] != expected_digest:
        raise VectorDbUnavailableError(f"completion run {values['run_id']!r} has an invalid digest")
    try:
        parse_utc_timestamp(values["completed_at"])
    except SyncError as exc:
        raise VectorDbUnavailableError(f"completion run {values['run_id']!r} has an invalid timestamp") from exc
    receipts = tuple(
        _parse_receipt_batch(
            project_id=project_id,
            raw=values["receipts_json"],
        )
    )
    producers = tuple(
        _parse_producer_completions(
            project_id=project_id,
            raw=values["producer_completions_json"],
        )
    )
    sequences = [receipt.sequence for receipt in receipts]
    expected_end = sequence_start + max(1, len(receipts)) - 1
    if (
        sequence_end != expected_end
        or sequences != list(range(sequence_start, sequence_start + len(receipts)))
        or any(item.sequence != sequence_end for item in producers)
    ):
        raise VectorDbUnavailableError(f"completion run {values['run_id']!r} has an invalid atomic range")
    expected_run_id = completion_run_id(
        project_id,
        tuple(_unstamp_receipt(item) for item in receipts),
        tuple(_unstamp_producer_completion(item) for item in producers),
    )
    if values["run_id"] != expected_run_id:
        raise VectorDbUnavailableError(f"completion run {values['run_id']!r} does not bind its semantic payload")
    return _CompletionRunRecord(
        uuid=uid,
        properties=values,
        receipts=receipts,
        producer_completions=producers,
        sequence_start=sequence_start,
        sequence_end=sequence_end,
    )


def _strict_json_string(raw: object, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise VectorDbUnavailableError(f"producer completion has invalid {field_name!r}")
    return raw


def _unstamp_receipt(receipt: SyncReceipt) -> SyncReceipt:
    return SyncReceipt.for_completion(
        project_id=receipt.project_id,
        source_file=receipt.source_file,
        source_type=receipt.source_type,
        corpus_revision=receipt.corpus_revision,
        generation=receipt.generation,
        completed_at=receipt.completed_at,
    )


def _unstamp_producer_completion(
    completion: ProducerCompletion,
) -> ProducerCompletion:
    return ProducerCompletion(
        project_id=completion.project_id,
        producer=completion.producer,
        source_types=completion.source_types,
        corpus_revision=completion.corpus_revision,
    )


def _verify_global_completion_ranges(
    ranges: Sequence[tuple[int, int]],
) -> None:
    previous_end = 0
    for start, end in sorted(ranges):
        if start <= previous_end:
            raise VectorDbUnavailableError(f"completion ranges overlap at position {start}")
        if end < start:
            raise VectorDbUnavailableError("completion range ends before it starts")
        previous_end = end


def receipt_from_props(project_id: str, source_file: str, props: Mapping[str, object]) -> SyncReceipt:
    """Rebuild a persisted receipt with FULL verification (N08/N16).

    Every mandatory field must be present and string-typed (no ``str()``
    coercion), the state must be a KNOWN receipt state, the timestamp a UTC
    instant, the sequence positive, and the digest must bind every identity AND
    ordering field. Anything else raises -- a malformed, replayed or unknown-state
    receipt can never advance the reported freshness, and an unknown state is
    REJECTED rather than skipped (which would hide it).
    """
    from agentkit.backend.vectordb.sync import ReceiptState, SyncError

    values = required_strings(
        props,
        ("project_id", "source_file", "source_type", "corpus_revision", "digest", "state", "completed_at"),
        context=f"sync receipt for {source_file!r}",
    )
    sequence = positive_int(props.get("sequence"), field_name="sequence")
    generation = positive_int(props.get("generation"), field_name="generation")
    if values["project_id"] != project_id or values["source_file"] != source_file:
        raise VectorDbUnavailableError(
            f"persisted sync receipt identity mismatch: record "
            f"({values['project_id']!r}, {values['source_file']!r}) != requested "
            f"({project_id!r}, {source_file!r}); fail-closed (N08)."
        )
    try:
        state = ReceiptState(values["state"])
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted sync receipt for {source_file!r} has unknown state "
            f"{values['state']!r}; fail-closed (N16: an unknown state is rejected, "
            "never skipped)."
        ) from exc
    receipt = SyncReceipt(
        project_id=project_id,
        source_file=source_file,
        source_type=values["source_type"],
        corpus_revision=values["corpus_revision"],
        digest=values["digest"],
        state=state,
        completed_at=values["completed_at"],
        sequence=sequence,
        generation=generation,
    )
    try:
        receipt.verify()
    except SyncError as exc:
        raise VectorDbUnavailableError(f"persisted sync receipt for {source_file!r} is not trustworthy: {exc}") from exc
    return receipt


__all__ = [
    "completion_position_uuid",
    "receipt_from_props",
    "render_producer_completions",
    "run_position_uuid",
    "run_receipt_digest",
]
