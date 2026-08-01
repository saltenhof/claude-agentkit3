"""Corpus-wide assertion and projection manifest models for FK-78."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_validation import (
    Ctx,
    Issue,
    check_keys,
    read_enum,
    read_json_object,
    read_nullable_object,
    read_object_items,
    read_optional_str,
    read_semver,
    read_sha,
    read_sha_or_null,
    read_str,
    read_str_list,
    read_sub_object,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

@dataclass(frozen=True)
class LifecycleSource:
    """Decision-record binding of a projection-manifest entry."""

    decision_id: str
    path: str
    digest: str
    status: str


@dataclass(frozen=True)
class AssertionSource:
    """Assertion source document with digest binding."""

    path: str
    digest: str | None


@dataclass(frozen=True)
class RequiredProjection:
    """One declared mandatory projection of a scope.

    ``target_mode`` selects the canonical digest rule (see
    :mod:`receipts`); ``selector`` is required for and only allowed with
    ``structured-selector``.
    """

    kind: str
    target: str
    target_mode: str
    selector: str | None
    target_digest: str | None
    receipt_ref: str | None
    equivalence_status: str


@dataclass(frozen=True)
class ProjectionBlocker:
    """One visible blocker of a projection-manifest entry."""

    reason: str
    owner: str
    visible_anchor: str


@dataclass(frozen=True)
class ManifestRef:
    """Digest-bound reference to a promotion manifest."""

    path: str
    digest: str


@dataclass(frozen=True)
class ProjectionEntry:
    """One scope entry of the corpus-wide projection manifest (FK-78 78.12)."""

    scope_id: str
    covered_scope_ids: tuple[str, ...]
    lifecycle: str
    lifecycle_source: LifecycleSource
    assertion_source: AssertionSource
    assertion_status: str
    required_projections: tuple[RequiredProjection, ...]
    blockers: tuple[ProjectionBlocker, ...]
    last_run_id: str | None
    last_promotion_manifest: ManifestRef | None
    raw: Mapping[str, object] = field(repr=False)


@dataclass(frozen=True)
class ProjectionManifest:
    """Validated ``concept/_meta/projection-manifest.json``."""

    schema_version: str
    entries: tuple[ProjectionEntry, ...]


PROJECTION_MANIFEST_KEYS = ("schema_version", "entries")

REQUIRED_PROJECTION_KEYS = ("kind", "target", "target_mode", "target_digest", "receipt_ref", "equivalence_status")

#: Canonical digest rules for projection targets (see :mod:`receipts`).

#: Declared relation kinds of structured ``required_registry_edges``.
REGISTRY_EDGE_KINDS = ("owns", "defers_to", "contract", "member", "producer", "consumer")

PROJECTION_ENTRY_KEYS = (
    "scope_id",
    "lifecycle",
    "lifecycle_source",
    "assertion_source",
    "assertion_status",
    "required_projections",
    "blockers",
    "last_run_id",
    "last_promotion_manifest",
)


def _parse_lifecycle_source(ctx: Ctx, entry: Mapping[str, object], where: str) -> LifecycleSource:
    sub = read_sub_object(ctx, entry, where, "lifecycle_source")
    if sub is None:
        return LifecycleSource(decision_id="", path="", digest="", status="")
    sub_where = f"{where}.lifecycle_source"
    check_keys(ctx, sub, sub_where, ("decision_id", "path", "digest", "status"))
    return LifecycleSource(
        decision_id=read_str(ctx, sub, sub_where, "decision_id"),
        path=read_str(ctx, sub, sub_where, "path"),
        digest=read_sha(ctx, sub, sub_where, "digest"),
        status=read_enum(ctx, sub, sub_where, "status", Vocab.DECISION_STATUSES),
    )


def _parse_projection_entry(ctx: Ctx, item_where: str, item: dict[str, object]) -> ProjectionEntry:
    check_keys(ctx, item, item_where, PROJECTION_ENTRY_KEYS, optional=("covered_scope_ids",))
    source_obj = read_sub_object(ctx, item, item_where, "assertion_source")
    assertion_source = AssertionSource(path="", digest=None)
    if source_obj is not None:
        source_where = f"{item_where}.assertion_source"
        check_keys(ctx, source_obj, source_where, ("path", "digest"))
        assertion_source = AssertionSource(
            path=read_str(ctx, source_obj, source_where, "path"),
            digest=read_sha_or_null(ctx, source_obj, source_where, "digest"),
        )
    projections: list[RequiredProjection] = []
    for proj_where, proj in read_object_items(ctx, item, item_where, "required_projections"):
        check_keys(ctx, proj, proj_where, REQUIRED_PROJECTION_KEYS, optional=("selector",))
        mode = read_enum(ctx, proj, proj_where, "target_mode", Vocab.TARGET_MODES)
        selector = read_optional_str(ctx, proj, proj_where, "selector")
        if mode == "structured-selector" and not selector:
            ctx.error(f"{proj_where}.selector", "required for target_mode 'structured-selector'")
        if mode and mode != "structured-selector" and selector:
            ctx.error(f"{proj_where}.selector", f"only allowed for target_mode 'structured-selector', not {mode!r}")
        projections.append(
            RequiredProjection(
                kind=read_enum(ctx, proj, proj_where, "kind", Vocab.PROJECTION_KINDS),
                target=read_str(ctx, proj, proj_where, "target"),
                target_mode=mode,
                selector=selector,
                target_digest=read_sha_or_null(ctx, proj, proj_where, "target_digest"),
                receipt_ref=read_optional_str(ctx, proj, proj_where, "receipt_ref"),
                equivalence_status=read_enum(ctx, proj, proj_where, "equivalence_status", Vocab.EQUIVALENCE_STATUSES),
            )
        )
    blockers: list[ProjectionBlocker] = []
    for blocker_where, blocker in read_object_items(ctx, item, item_where, "blockers"):
        check_keys(ctx, blocker, blocker_where, ("reason", "owner", "visible_anchor"))
        blockers.append(
            ProjectionBlocker(
                reason=read_str(ctx, blocker, blocker_where, "reason"),
                owner=read_str(ctx, blocker, blocker_where, "owner"),
                visible_anchor=read_str(ctx, blocker, blocker_where, "visible_anchor"),
            )
        )
    manifest_ref_obj = read_nullable_object(ctx, item, item_where, "last_promotion_manifest")
    manifest_ref: ManifestRef | None = None
    if manifest_ref_obj is not None:
        ref_where = f"{item_where}.last_promotion_manifest"
        check_keys(ctx, manifest_ref_obj, ref_where, ("path", "digest"))
        manifest_ref = ManifestRef(
            path=read_str(ctx, manifest_ref_obj, ref_where, "path"),
            digest=read_sha(ctx, manifest_ref_obj, ref_where, "digest"),
        )
    last_run_id = read_optional_str(ctx, item, item_where, "last_run_id")
    if last_run_id is not None and Vocab.RUN_ID_RE.fullmatch(last_run_id) is None:
        ctx.error(f"{item_where}.last_run_id", f"must be a run id or null, got {last_run_id!r}")
    return ProjectionEntry(
        scope_id=read_str(ctx, item, item_where, "scope_id"),
        covered_scope_ids=read_str_list(ctx, item, item_where, "covered_scope_ids"),
        lifecycle=read_enum(ctx, item, item_where, "lifecycle", Vocab.LIFECYCLES),
        lifecycle_source=_parse_lifecycle_source(ctx, item, item_where),
        assertion_source=assertion_source,
        assertion_status=read_enum(ctx, item, item_where, "assertion_status", Vocab.ASSERTION_STATUSES),
        required_projections=tuple(projections),
        blockers=tuple(blockers),
        last_run_id=last_run_id,
        last_promotion_manifest=manifest_ref,
        raw=item,
    )


def load_projection_manifest(path: Path) -> tuple[ProjectionManifest | None, list[Issue]]:
    """Load and validate the corpus-wide projection manifest fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "manifest", PROJECTION_MANIFEST_KEYS)
    entries = tuple(
        _parse_projection_entry(ctx, where, item) for where, item in read_object_items(ctx, raw, "manifest", "entries")
    )
    manifest = ProjectionManifest(schema_version=read_semver(ctx, raw, "manifest"), entries=entries)
    if ctx.issues:
        return None, ctx.issues
    return manifest, []
