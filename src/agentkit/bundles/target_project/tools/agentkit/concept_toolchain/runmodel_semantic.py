"""Request and receipt models for FK-78 semantic-gate evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_digests import canonical_request_digest
from .runmodel_run import BaseRevision, parse_base_revision
from .runmodel_validation import (
    Ctx,
    Issue,
    check_keys,
    read_enum,
    read_json_object,
    read_matched,
    read_object_items,
    read_semver,
    read_sha,
    read_str,
    read_str_list,
    read_time,
)

if TYPE_CHECKING:
    from pathlib import Path

@dataclass(frozen=True)
class SemanticChunk:
    """One ordered content chunk of a semantic request pack."""

    path: str
    locator: str
    digest: str


REQUEST_PACK_KEYS = (
    "schema_version",
    "gate",
    "scope_id",
    "base_revision",
    "template_id",
    "template_digest",
    "chunks",
    "request_digest",
)


@dataclass(frozen=True)
class SemanticRequestPack:
    """Validated semantic request pack (FK-78 section 78.14)."""

    schema_version: str
    gate: str
    scope_id: str
    base_revision: BaseRevision
    template_id: str
    template_digest: str
    chunks: tuple[SemanticChunk, ...]
    request_digest: str


def load_semantic_request_pack(path: Path) -> tuple[SemanticRequestPack | None, list[Issue]]:
    """Load and validate one semantic request pack fail-closed.

    Also recomputes the canonical ``request_digest`` and fails on mismatch.
    """
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "pack", REQUEST_PACK_KEYS)
    chunks: list[SemanticChunk] = []
    for item_where, item in read_object_items(ctx, raw, "pack", "chunks"):
        check_keys(ctx, item, item_where, ("path", "locator", "digest"))
        chunks.append(
            SemanticChunk(
                path=read_str(ctx, item, item_where, "path"),
                locator=read_str(ctx, item, item_where, "locator"),
                digest=read_sha(ctx, item, item_where, "digest"),
            )
        )
    pack = SemanticRequestPack(
        schema_version=read_semver(ctx, raw, "pack"),
        gate=read_enum(ctx, raw, "pack", "gate", Vocab.SEMANTIC_GATES),
        scope_id=read_str(ctx, raw, "pack", "scope_id"),
        base_revision=parse_base_revision(ctx, raw, "pack"),
        template_id=read_str(ctx, raw, "pack", "template_id"),
        template_digest=read_sha(ctx, raw, "pack", "template_digest"),
        chunks=tuple(chunks),
        request_digest=read_sha(ctx, raw, "pack", "request_digest"),
    )
    if not ctx.issues and pack.request_digest != canonical_request_digest(raw):
        ctx.error("pack.request_digest", "does not match the canonical digest of the pack")
    if ctx.issues:
        return None, ctx.issues
    return pack, []


@dataclass(frozen=True)
class SemanticFinding:
    """One ERROR finding reported by a semantic receipt."""

    finding_id: str
    chunk_path: str
    chunk_locator: str
    scope_id: str
    statement: str
    severity: str


@dataclass(frozen=True)
class SemanticReceipt:
    """Validated semantic receipt (FK-78 section 78.14)."""

    schema_version: str
    gate: str
    request_digest: str
    model: str
    principal_id: str
    session_ref: str
    status: str
    findings: tuple[SemanticFinding, ...]
    chunk_digests: tuple[str, ...]
    completed_at: str


SEMANTIC_RECEIPT_KEYS = (
    "schema_version",
    "gate",
    "request_digest",
    "model",
    "principal_id",
    "session_ref",
    "status",
    "findings",
    "chunk_digests",
    "completed_at",
)


def load_semantic_receipt(path: Path) -> tuple[SemanticReceipt | None, list[Issue]]:
    """Load and validate one semantic receipt fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "receipt", SEMANTIC_RECEIPT_KEYS)
    findings: list[SemanticFinding] = []
    for item_where, item in read_object_items(ctx, raw, "receipt", "findings"):
        check_keys(ctx, item, item_where, ("finding_id", "chunk_path", "chunk_locator", "scope_id", "statement", "severity"))
        findings.append(
            SemanticFinding(
                finding_id=read_str(ctx, item, item_where, "finding_id"),
                chunk_path=read_str(ctx, item, item_where, "chunk_path"),
                chunk_locator=read_str(ctx, item, item_where, "chunk_locator"),
                scope_id=read_str(ctx, item, item_where, "scope_id"),
                statement=read_str(ctx, item, item_where, "statement"),
                severity=read_enum(ctx, item, item_where, "severity", ("ERROR",)),
            )
        )
    receipt = SemanticReceipt(
        schema_version=read_semver(ctx, raw, "receipt"),
        gate=read_enum(ctx, raw, "receipt", "gate", Vocab.SEMANTIC_GATES),
        request_digest=read_sha(ctx, raw, "receipt", "request_digest"),
        model=read_str(ctx, raw, "receipt", "model"),
        principal_id=read_matched(
            ctx, raw, "receipt", "principal_id", Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL
        ),
        session_ref=read_str(ctx, raw, "receipt", "session_ref"),
        status=read_enum(ctx, raw, "receipt", "status", Vocab.SEMANTIC_RECEIPT_STATUSES),
        findings=tuple(findings),
        chunk_digests=read_str_list(ctx, raw, "receipt", "chunk_digests", Vocab.SHA256_RE, "sha256 digest"),
        completed_at=read_time(ctx, raw, "receipt", "completed_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []
