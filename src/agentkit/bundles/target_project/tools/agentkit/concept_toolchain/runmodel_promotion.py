"""Promotion intent and receipt models for FK-78 incubation runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_run import BaseRevision, parse_base_revision
from .runmodel_validation import (
    Ctx,
    Issue,
    check_keys,
    read_enum,
    read_int,
    read_json_object,
    read_matched,
    read_object_items,
    read_optional_str,
    read_semver,
    read_sha,
    read_sha_or_null,
    read_str,
    read_str_list,
    read_sub_object,
    read_time,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

@dataclass(frozen=True)
class ScopeBlocker:
    """One blocker entry of a promotion scope."""

    reason: str
    atom_ids: tuple[str, ...]
    owner: str
    visible_anchor: str


@dataclass(frozen=True)
class PromotionScope:
    """One scope entry of the promotion manifest."""

    scope_id: str
    promotion_disposition: str
    blockers: tuple[ScopeBlocker, ...]


@dataclass(frozen=True)
class RegistryEdge:
    """One required registry edge in object form.

    ``required_registry_edges`` entries come in two normalized forms: the
    structural object ``{from, to, kind}`` or a plain ``<path>#<anchor>``
    string that must resolve against the working tree.
    """

    from_ref: str
    to_ref: str
    kind: str


@dataclass(frozen=True)
class TestOracle:
    """One required test oracle (structural validation only)."""

    oracle_id: str
    kind: str
    locator: str


@dataclass(frozen=True)
class PromotionTarget:
    """One target file with before/after digest binding."""

    path: str
    before_sha256: str | None
    after_sha256: str


@dataclass(frozen=True)
class ScopeLockEntry:
    """One scope-lock claim recorded in the promotion manifest."""

    scope_id: str
    locked_by_run: str
    fencing_token: int
    backend: str


@dataclass(frozen=True)
class SemanticGateEntry:
    """Recorded state of one semantic gate (W2/W3)."""

    gate: str
    status: str
    receipt_path: str | None
    blocking_scope_ids: tuple[str, ...]


@dataclass(frozen=True)
class PromotionManifest:
    """Validated ``promotion/promotion-manifest.json`` (FK-78 section 78.11)."""

    schema_version: str
    run_id: str
    base_revision: BaseRevision
    scopes: tuple[PromotionScope, ...]
    required_decision_ids: tuple[str, ...]
    required_concept_ids: tuple[str, ...]
    required_formal_ids: tuple[str, ...]
    required_registry_edges: tuple[RegistryEdge | str, ...]
    required_support_paths: tuple[str, ...]
    required_test_oracles: tuple[TestOracle, ...]
    targets: tuple[PromotionTarget, ...]
    receipts_dir: str
    scope_locks: tuple[ScopeLockEntry, ...]
    semantic_gates: tuple[SemanticGateEntry, ...]


def _manifest_keys() -> tuple[str, ...]:
    return (
        "schema_version",
        "run_id",
        "base_revision",
        "scopes",
        "required_decision_ids",
        "required_concept_ids",
        "required_formal_ids",
        "required_registry_edges",
        "required_support_paths",
        "required_test_oracles",
        "targets",
        "receipts_dir",
        "scope_locks",
        "semantic_gates",
    )


MANIFEST_KEYS = _manifest_keys()


def _parse_scopes(ctx: Ctx, raw: Mapping[str, object]) -> tuple[PromotionScope, ...]:
    scopes: list[PromotionScope] = []
    for item_where, item in read_object_items(ctx, raw, "manifest", "scopes"):
        check_keys(ctx, item, item_where, ("scope_id", "promotion_disposition", "blockers"))
        blockers: list[ScopeBlocker] = []
        for blocker_where, blocker in read_object_items(ctx, item, item_where, "blockers"):
            check_keys(ctx, blocker, blocker_where, ("reason", "atom_ids", "owner", "visible_anchor"))
            blockers.append(
                ScopeBlocker(
                    reason=read_str(ctx, blocker, blocker_where, "reason"),
                    atom_ids=read_str_list(
                        ctx, blocker, blocker_where, "atom_ids", Vocab.ATOM_ID_RE, Vocab.ATOM_ID_LABEL
                    ),
                    owner=read_str(ctx, blocker, blocker_where, "owner"),
                    visible_anchor=read_str(ctx, blocker, blocker_where, "visible_anchor"),
                )
            )
        scopes.append(
            PromotionScope(
                scope_id=read_str(ctx, item, item_where, "scope_id"),
                promotion_disposition=read_enum(
                    ctx, item, item_where, "promotion_disposition", Vocab.PROMOTION_DISPOSITIONS
                ),
                blockers=tuple(blockers),
            )
        )
    return tuple(scopes)


def _parse_registry_edges(ctx: Ctx, raw: Mapping[str, object]) -> tuple[RegistryEdge | str, ...]:
    if "required_registry_edges" not in raw:
        return ()
    value = raw["required_registry_edges"]
    if not isinstance(value, list):
        ctx.error("manifest.required_registry_edges", Vocab.ARRAY_REQUIRED)
        return ()
    edges: list[RegistryEdge | str] = []
    for index, item in enumerate(value):
        item_where = f"manifest.required_registry_edges[{index}]"
        if isinstance(item, str):
            if "#" not in item or item.startswith("#") or item.endswith("#"):
                ctx.error(item_where, f"string form must be <path>#<anchor>, got {item!r}")
                continue
            edges.append(item)
            continue
        if not isinstance(item, dict):
            ctx.error(item_where, "must be a <path>#<anchor> string or a {from, to, kind} object")
            continue
        check_keys(ctx, item, item_where, ("from", "to", "kind"))
        edges.append(
            RegistryEdge(
                from_ref=read_str(ctx, item, item_where, "from"),
                to_ref=read_str(ctx, item, item_where, "to"),
                kind=read_str(ctx, item, item_where, "kind"),
            )
        )
    return tuple(edges)


def _parse_manifest_collections(
    ctx: Ctx, raw: Mapping[str, object]
) -> tuple[tuple[RegistryEdge | str, ...], tuple[TestOracle, ...], tuple[PromotionTarget, ...], tuple[ScopeLockEntry, ...]]:
    edges = _parse_registry_edges(ctx, raw)
    oracles: list[TestOracle] = []
    for item_where, item in read_object_items(ctx, raw, "manifest", "required_test_oracles"):
        check_keys(ctx, item, item_where, ("oracle_id", "kind", "locator"))
        oracles.append(
            TestOracle(
                oracle_id=read_str(ctx, item, item_where, "oracle_id"),
                kind=read_str(ctx, item, item_where, "kind"),
                locator=read_str(ctx, item, item_where, "locator"),
            )
        )
    targets: list[PromotionTarget] = []
    for item_where, item in read_object_items(ctx, raw, "manifest", "targets"):
        check_keys(ctx, item, item_where, ("path", "before_sha256", "after_sha256"))
        before = read_sha_or_null(ctx, item, item_where, "before_sha256")
        targets.append(
            PromotionTarget(
                path=read_str(ctx, item, item_where, "path"),
                before_sha256=before,
                after_sha256=read_sha(ctx, item, item_where, "after_sha256"),
            )
        )
    locks: list[ScopeLockEntry] = []
    for item_where, item in read_object_items(ctx, raw, "manifest", "scope_locks"):
        check_keys(ctx, item, item_where, ("scope_id", "locked_by_run", "fencing_token", "backend"))
        locks.append(
            ScopeLockEntry(
                scope_id=read_str(ctx, item, item_where, "scope_id"),
                locked_by_run=read_matched(
                    ctx, item, item_where, "locked_by_run", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL
                ),
                fencing_token=read_int(ctx, item, item_where, "fencing_token", minimum=1),
                backend=read_enum(ctx, item, item_where, "backend", Vocab.LOCK_BACKENDS),
            )
        )
    return tuple(edges), tuple(oracles), tuple(targets), tuple(locks)


def _parse_semantic_gates(ctx: Ctx, raw: Mapping[str, object]) -> tuple[SemanticGateEntry, ...]:
    gates: list[SemanticGateEntry] = []
    for item_where, item in read_object_items(ctx, raw, "manifest", "semantic_gates"):
        check_keys(ctx, item, item_where, ("gate", "status", "receipt_path", "blocking_scope_ids"))
        gates.append(
            SemanticGateEntry(
                gate=read_enum(ctx, item, item_where, "gate", Vocab.SEMANTIC_GATES),
                status=read_enum(ctx, item, item_where, "status", Vocab.SEMANTIC_GATE_STATUSES),
                receipt_path=read_optional_str(ctx, item, item_where, "receipt_path"),
                blocking_scope_ids=read_str_list(ctx, item, item_where, "blocking_scope_ids"),
            )
        )
    return tuple(gates)


def load_promotion_manifest(path: Path) -> tuple[PromotionManifest | None, list[Issue]]:
    """Load and validate the promotion manifest fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "manifest", MANIFEST_KEYS)
    edges, oracles, targets, locks = _parse_manifest_collections(ctx, raw)
    manifest = PromotionManifest(
        schema_version=read_semver(ctx, raw, "manifest"),
        run_id=read_matched(ctx, raw, "manifest", "run_id", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        base_revision=parse_base_revision(ctx, raw, "manifest"),
        scopes=_parse_scopes(ctx, raw),
        required_decision_ids=read_str_list(ctx, raw, "manifest", "required_decision_ids"),
        required_concept_ids=read_str_list(ctx, raw, "manifest", "required_concept_ids"),
        required_formal_ids=read_str_list(ctx, raw, "manifest", "required_formal_ids"),
        required_registry_edges=edges,
        required_support_paths=read_str_list(ctx, raw, "manifest", "required_support_paths"),
        required_test_oracles=oracles,
        targets=targets,
        receipts_dir=read_str(ctx, raw, "manifest", "receipts_dir"),
        scope_locks=locks,
        semantic_gates=_parse_semantic_gates(ctx, raw),
    )
    if ctx.issues:
        return None, ctx.issues
    return manifest, []


@dataclass(frozen=True)
class ReceiptTarget:
    """Target passage of a projection receipt.

    ``anchor`` is empty for whole-file and directory targets; markdown
    section receipts always carry the section anchor.
    """

    path: str
    anchor: str


@dataclass(frozen=True)
class ProjectionReceipt:
    """Validated ``promotion/receipts/<receipt_id>.json`` (FK-78 78.10)."""

    schema_version: str
    receipt_id: str
    atom_id: str
    target: ReceiptTarget
    target_mode: str
    selector: str | None
    source_digest: str
    target_section_digest: str
    writer_principal_id: str
    writer_session_ref: str
    reviewer_principal_id: str
    reviewer_session_ref: str
    verdict: str
    reviewed_at: str


def _receipt_keys() -> tuple[str, ...]:
    return (
        "schema_version",
        "receipt_id",
        "atom_id",
        "target",
        "target_mode",
        "selector",
        "source_digest",
        "target_section_digest",
        "writer_principal_id",
        "writer_session_ref",
        "reviewer_principal_id",
        "reviewer_session_ref",
        "verdict",
        "reviewed_at",
    )


RECEIPT_KEYS = _receipt_keys()


def load_projection_receipt(path: Path) -> tuple[ProjectionReceipt | None, list[Issue]]:
    """Load and validate one projection receipt fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "receipt", RECEIPT_KEYS)
    target_obj = read_sub_object(ctx, raw, "receipt", "target")
    target = ReceiptTarget(path="", anchor="")
    if target_obj is not None:
        check_keys(ctx, target_obj, Vocab.RECEIPT_TARGET_LOCATOR, ("path", "anchor"))
        target = ReceiptTarget(
            path=read_str(ctx, target_obj, Vocab.RECEIPT_TARGET_LOCATOR, "path"),
            anchor=read_str(ctx, target_obj, Vocab.RECEIPT_TARGET_LOCATOR, "anchor", allow_empty=True),
        )
    mode = read_enum(ctx, raw, "receipt", "target_mode", Vocab.TARGET_MODES)
    selector = read_optional_str(ctx, raw, "receipt", "selector")
    if mode == "structured-selector" and not selector:
        ctx.error("receipt.selector", "required for target_mode 'structured-selector'")
    if mode and mode != "structured-selector" and selector:
        ctx.error("receipt.selector", f"only allowed for target_mode 'structured-selector', not {mode!r}")
    if mode == "markdown-section" and not target.anchor:
        ctx.error("receipt.target.anchor", "required for target_mode 'markdown-section'")
    if mode in ("whole-file", "directory-tree") and target.anchor:
        ctx.error("receipt.target.anchor", f"must be empty for target_mode {mode!r}")
    receipt = ProjectionReceipt(
        schema_version=read_semver(ctx, raw, "receipt"),
        receipt_id=read_matched(
            ctx, raw, "receipt", "receipt_id", Vocab.RECEIPT_ID_RE, Vocab.RECEIPT_ID_LABEL
        ),
        atom_id=read_matched(ctx, raw, "receipt", "atom_id", Vocab.ATOM_ID_RE, Vocab.ATOM_ID_LABEL),
        target=target,
        target_mode=mode,
        selector=selector,
        source_digest=read_sha(ctx, raw, "receipt", "source_digest"),
        target_section_digest=read_sha(ctx, raw, "receipt", "target_section_digest"),
        writer_principal_id=read_matched(
            ctx, raw, "receipt", "writer_principal_id", Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL
        ),
        writer_session_ref=read_str(ctx, raw, "receipt", "writer_session_ref"),
        reviewer_principal_id=read_matched(
            ctx,
            raw,
            "receipt",
            "reviewer_principal_id",
            Vocab.PRINCIPAL_ID_RE,
            Vocab.PRINCIPAL_ID_LABEL,
        ),
        reviewer_session_ref=read_str(ctx, raw, "receipt", "reviewer_session_ref"),
        verdict=read_enum(ctx, raw, "receipt", "verdict", Vocab.RECEIPT_VERDICTS),
        reviewed_at=read_time(ctx, raw, "receipt", "reviewed_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []


@dataclass(frozen=True)
class DeclassificationReceipt:
    """Validated ``declassification/<receipt_id>.json`` (FK-78 78.13)."""

    schema_version: str
    receipt_id: str
    source_path: str
    source_digest: str
    output_path: str
    output_digest: str
    rules_applied: tuple[str, ...]
    target_class: str
    approved_by_principal: str
    approved_at: str


def _declassification_keys() -> tuple[str, ...]:
    return (
        "schema_version",
        "receipt_id",
        "source_path",
        "source_digest",
        "output_path",
        "output_digest",
        "rules_applied",
        "target_class",
        "approved_by_principal",
        "approved_at",
    )


DECLASSIFICATION_KEYS = _declassification_keys()


def load_declassification_receipt(path: Path) -> tuple[DeclassificationReceipt | None, list[Issue]]:
    """Load and validate one declassification receipt fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "receipt", DECLASSIFICATION_KEYS)
    receipt = DeclassificationReceipt(
        schema_version=read_semver(ctx, raw, "receipt"),
        receipt_id=read_matched(
            ctx, raw, "receipt", "receipt_id", Vocab.RECEIPT_ID_RE, Vocab.RECEIPT_ID_LABEL
        ),
        source_path=read_str(ctx, raw, "receipt", "source_path"),
        source_digest=read_sha(ctx, raw, "receipt", "source_digest"),
        output_path=read_str(ctx, raw, "receipt", "output_path"),
        output_digest=read_sha(ctx, raw, "receipt", "output_digest"),
        rules_applied=read_str_list(ctx, raw, "receipt", "rules_applied"),
        target_class=read_enum(ctx, raw, "receipt", "target_class", ("open", "internal")),
        approved_by_principal=read_matched(
            ctx,
            raw,
            "receipt",
            "approved_by_principal",
            Vocab.PRINCIPAL_ID_RE,
            Vocab.PRINCIPAL_ID_LABEL,
        ),
        approved_at=read_time(ctx, raw, "receipt", "approved_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []
