"""Mutation mutex, intent, and scope-lock records for FK-78."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_validation import (
    Ctx,
    Issue,
    check_keys,
    read_enum,
    read_int,
    read_json_object,
    read_matched,
    read_object_items,
    read_semver,
    read_sha,
    read_str,
    read_time,
)

if TYPE_CHECKING:
    from pathlib import Path

MUTEX_KEYS = ("owner_principal", "owner_session", "nonce", "acquired_at", "heartbeat_at", "ttl_seconds")

INTENT_KEYS = ("holder_principal", "holder_session", "intent_nonce", "acquired_at", "ttl_seconds")


@dataclass(frozen=True)
class IntentState:
    """Validated ``RUN.mutex.intent`` payload (coordination intent, FK-78 78.4).

    One single intent serializes EVERY mutex change and effect (acquire,
    takeover, heartbeat, write, release). It carries its own nonce so it
    can only be released by its holder (compare-before-delete).
    """

    holder_principal: str
    holder_session: str
    intent_nonce: str
    acquired_at: str
    ttl_seconds: int


def load_intent_state(path: Path) -> tuple[IntentState | None, list[Issue]]:
    """Load and validate the coordination-intent payload fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "intent", INTENT_KEYS)
    state = IntentState(
        holder_principal=read_matched(
            ctx, raw, "intent", "holder_principal", Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL
        ),
        holder_session=read_str(ctx, raw, "intent", "holder_session"),
        intent_nonce=read_str(ctx, raw, "intent", "intent_nonce"),
        acquired_at=read_time(ctx, raw, "intent", "acquired_at"),
        ttl_seconds=read_int(ctx, raw, "intent", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return state, []


def parse_timestamp(value: str) -> datetime.datetime:
    """Parse a UTC-``Z`` timestamp into an aware datetime."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def now_utc() -> datetime.datetime:
    """Return the current UTC time (single seam for time-ordering checks)."""
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class MutexState:
    """Validated ``RUN.mutex`` payload (mutation mutex, FK-78 section 78.4).

    Liveness is measured against ``heartbeat_at``, which long operations
    refresh before every write step, so a legitimate long run is never
    taken over as if it had crashed.
    """

    owner_principal: str
    owner_session: str
    nonce: str
    acquired_at: str
    heartbeat_at: str
    ttl_seconds: int


def load_mutex_state(path: Path) -> tuple[MutexState | None, list[Issue]]:
    """Load and validate the mutation-mutex payload fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "mutex", MUTEX_KEYS)
    state = MutexState(
        owner_principal=read_matched(
            ctx, raw, "mutex", "owner_principal", Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL
        ),
        owner_session=read_str(ctx, raw, "mutex", "owner_session"),
        nonce=read_str(ctx, raw, "mutex", "nonce"),
        acquired_at=read_time(ctx, raw, "mutex", "acquired_at"),
        heartbeat_at=read_time(ctx, raw, "mutex", "heartbeat_at"),
        ttl_seconds=read_int(ctx, raw, "mutex", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return state, []


SCOPE_LOCK_KEYS = ("schema_version", "scope_id", "locked_by_run", "fencing_token", "backend", "acquired_at", "ttl_seconds")


@dataclass(frozen=True)
class ScopeLock:
    """Validated filesystem scope-lock blob (FK-78 section 78.11).

    FK-78 fixes the lock semantics (owner run, fencing token, TTL); this
    catalog is the toolchain's normative JSON materialization of it.
    """

    schema_version: str
    scope_id: str
    locked_by_run: str
    fencing_token: int
    backend: str
    acquired_at: str
    ttl_seconds: int


def load_scope_lock(path: Path) -> tuple[ScopeLock | None, list[Issue]]:
    """Load and validate one scope-lock blob fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "lock", SCOPE_LOCK_KEYS)
    lock = ScopeLock(
        schema_version=read_semver(ctx, raw, "lock"),
        scope_id=read_str(ctx, raw, "lock", "scope_id"),
        locked_by_run=read_matched(ctx, raw, "lock", "locked_by_run", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        fencing_token=read_int(ctx, raw, "lock", "fencing_token", minimum=1),
        backend=read_enum(ctx, raw, "lock", "backend", Vocab.LOCK_BACKENDS),
        acquired_at=read_time(ctx, raw, "lock", "acquired_at"),
        ttl_seconds=read_int(ctx, raw, "lock", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return lock, []


LOCK_EVIDENCE_KEYS = ("schema_version", "backend", "remote", "refs")


def _lock_evidence_ref_keys() -> tuple[str, ...]:
    return (
        "scope_id",
        "ref",
        "expected_ref",
        "old_oid",
        "new_oid",
        "observed_oid",
        "lock_blob_digest",
        "fencing_token",
        "ttl_seconds",
        "acquired_at",
        "attested_by_principal",
        "attested_by_session",
        "verified_at",
    )


LOCK_EVIDENCE_REF_KEYS = _lock_evidence_ref_keys()

_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


@dataclass(frozen=True)
class LockEvidenceRef:
    """One verified git-remote lock ref (orchestrator-side CAS evidence)."""

    scope_id: str
    ref: str
    expected_ref: str
    old_oid: str
    new_oid: str
    observed_oid: str
    lock_blob_digest: str
    fencing_token: int
    ttl_seconds: int
    acquired_at: str
    attested_by_principal: str
    attested_by_session: str
    verified_at: str


@dataclass(frozen=True)
class LockEvidence:
    """Validated ``promotion/lock-evidence.json`` for the git-remote backend.

    The toolchain performs no network operations; the orchestrator records
    its ref-CAS verification here (one entry per locked scope), which the
    promotion check accepts as completing evidence.
    """

    schema_version: str
    backend: str
    remote: str
    refs: tuple[LockEvidenceRef, ...]


def load_lock_evidence(path: Path) -> tuple[LockEvidence | None, list[Issue]]:
    """Load and validate one git-remote lock-evidence file fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "evidence", LOCK_EVIDENCE_KEYS)
    refs: list[LockEvidenceRef] = []
    for item_where, item in read_object_items(ctx, raw, "evidence", "refs"):
        check_keys(ctx, item, item_where, LOCK_EVIDENCE_REF_KEYS)
        ref_name = read_str(ctx, item, item_where, "ref")
        if ref_name and not ref_name.startswith("refs/"):
            ctx.error(f"{item_where}.ref", f"must be a fully qualified ref name, got {ref_name!r}")
        expected_ref = read_str(ctx, item, item_where, "expected_ref")
        if expected_ref and not expected_ref.startswith("refs/"):
            ctx.error(f"{item_where}.expected_ref", f"must be a fully qualified ref name, got {expected_ref!r}")
        refs.append(
            LockEvidenceRef(
                scope_id=read_str(ctx, item, item_where, "scope_id"),
                ref=ref_name,
                expected_ref=expected_ref,
                old_oid=read_matched(ctx, item, item_where, "old_oid", _GIT_OID_RE, Vocab.GIT_OBJECT_ID_LABEL),
                new_oid=read_matched(ctx, item, item_where, "new_oid", _GIT_OID_RE, Vocab.GIT_OBJECT_ID_LABEL),
                observed_oid=read_matched(ctx, item, item_where, "observed_oid", _GIT_OID_RE, Vocab.GIT_OBJECT_ID_LABEL),
                lock_blob_digest=read_sha(ctx, item, item_where, "lock_blob_digest"),
                fencing_token=read_int(ctx, item, item_where, "fencing_token", minimum=1),
                ttl_seconds=read_int(ctx, item, item_where, "ttl_seconds", minimum=1),
                acquired_at=read_time(ctx, item, item_where, "acquired_at"),
                attested_by_principal=read_matched(
                    ctx,
                    item,
                    item_where,
                    "attested_by_principal",
                    Vocab.PRINCIPAL_ID_RE,
                    Vocab.PRINCIPAL_ID_LABEL,
                ),
                attested_by_session=read_str(ctx, item, item_where, "attested_by_session"),
                verified_at=read_time(ctx, item, item_where, "verified_at"),
            )
        )
    evidence = LockEvidence(
        schema_version=read_semver(ctx, raw, "evidence"),
        backend=read_enum(ctx, raw, "evidence", "backend", ("git-remote",)),
        remote=read_str(ctx, raw, "evidence", "remote"),
        refs=tuple(refs),
    )
    if ctx.issues:
        return None, ctx.issues
    return evidence, []
