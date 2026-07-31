"""``concept_validate`` corpus integrity suite (FK-13 §13.9.7).

Table-driven, deterministic validation. The full error/warning catalog and the
exit-code mapping (0 valid / 1 warnings / 2 errors / 3 internal failure) live
here. The validator consumes the SSOT :class:`~agentkit.concepts.parser.DiscoveryResult`
and the :class:`~agentkit.backend.vectordb.concept_corpus.graph.ConceptGraph`.

``concept_validate`` is the hard sync precondition (FK-13 §13.9.5): a corpus
with errors is NOT indexed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.graph import (
    ConceptGraph,
    build_graph,
    detect_cycle,
)
from agentkit.concepts.chunking import split_into_sections
from agentkit.concepts.tokenizer import chunk_token_count

if TYPE_CHECKING:

    from agentkit.concepts.parser import DiscoveryResult

#: All blocking error codes (FK-13 §13.9.7).
ERROR_CODES: tuple[str, ...] = (
    "E-SCHEMA-001",
    "E-SCHEMA-002",
    "E-SCHEMA-003",
    "E-SCHEMA-004",
    "E-ID-001",
    "E-ID-002",
    "E-REF-001",
    "E-REF-002",
    "E-REF-003",
    "E-CYCLE-001",
    "E-CYCLE-002",
    "E-AUTH-001",
    "E-AUTH-002",
    "E-CHUNK-001",
)

#: All non-blocking warning codes.
WARNING_CODES: tuple[str, ...] = (
    "W-BIDIR-001",
    "W-CONTENT-001",
    "W-CONTENT-002",
    "W-CONTENT-003",
    "W-ORPHAN-001",
    "W-SCOPE-001",
)

#: Concept-id convention: an uppercase prefix (FK/DK/META/AF/...) followed by
#: dashed alphanumeric segments (FK-13, DK-07, META-DEC-2026-..., FK-A). A
#: concept_id that does not even match this shape violates E-ID-002.
_ID_CONVENTION_RE = re.compile(r"^[A-Z]{2,}(-[A-Za-z0-9]+)*$")
#: Extract the leading numeric component of a concept_id (FK-13 -> 13).
_ID_NUMBER_RE = re.compile(r"-(\d+)")
_BODY_ID_RE = re.compile(r"\b(TK|AF|FK|DK|META)-[A-Za-z0-9\-]+")


class ExitCode(IntEnum):
    """concept_validate exit codes (FK-13 §13.9.7)."""

    VALID = 0
    WARNINGS = 1
    ERRORS = 2
    INTERNAL_FAILURE = 3


@dataclass(frozen=True)
class Finding:
    """One validation finding (error or warning)."""

    code: str
    message: str
    concept_id: str = ""
    path: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """Result of ``concept_validate`` (FK-13 §13.9.7 output format)."""

    exit_code: ExitCode
    status: str
    corpus_revision: str
    errors: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    graph: dict[str, object]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "corpus_revision": self.corpus_revision,
            "exit_code": int(self.exit_code),
            "errors": [
                {"code": f.code, "message": f.message, "concept_id": f.concept_id, "path": f.path}
                for f in self.errors
            ],
            "warnings": [
                {"code": f.code, "message": f.message, "concept_id": f.concept_id, "path": f.path}
                for f in self.warnings
            ],
            "graph": self.graph,
        }


def validate_corpus(
    discovery: DiscoveryResult,
    *,
    max_tokens: int = 1000,
    strict: bool = False,
) -> ValidationReport:
    """Run the full validation suite against the SSOT discovery result.

    Args:
        discovery: The SSOT discovery result.
        max_tokens: Per-section token limit for E-CHUNK-001.
        strict: When True, warnings escalate to errors (Ring 3 ``--strict``).

    Any UNEXPECTED internal error maps to exit code 3 (INTERNAL_FAILURE) -- the
    validator never exits green on an internal fault (FK-13 §13.9.7).
    """
    try:
        return _validate_corpus_impl(discovery, max_tokens=max_tokens, strict=strict)
    except Exception as exc:  # noqa: BLE001 -- internal failure must be exit 3
        return _internal_failure(discovery, f"internal validation failure: {exc!r}")


def _internal_failure(discovery: DiscoveryResult, message: str) -> ValidationReport:
    return ValidationReport(
        exit_code=ExitCode.INTERNAL_FAILURE,
        status="internal_failure",
        corpus_revision=discovery.corpus_revision,
        errors=(
            Finding(
                code="E-INTERNAL",
                message=message,
            ),
        ),
        warnings=(),
        graph={"concept_count": len(discovery.documents), "active_count": 0, "acyclic": True},
    )


def _validate_corpus_impl(
    discovery: DiscoveryResult,
    *,
    max_tokens: int,
    strict: bool,
) -> ValidationReport:
    errors: list[Finding] = []
    warnings: list[Finding] = []

    # Discovery-level parse errors (E-SCHEMA-001/002/003 surfaced at parse).
    for parse_error in discovery.errors:
        errors.append(
            Finding(
                code=parse_error.code,
                message=parse_error.message,
                path=parse_error.path,
            )
        )

    graph = build_graph(discovery)

    # Per-document checks.
    _check_appendix_parent(discovery, errors)
    _check_filename_convention(discovery, errors)
    _check_chunk_size(discovery, errors, max_tokens=max_tokens)

    # Corpus-level reference checks.
    _check_defers_to_refs(graph, discovery, errors)
    _check_parent_refs(graph, discovery, errors)
    _check_superseded_by_refs(graph, discovery, errors)

    # Duplicate / authority checks.
    _check_duplicate_concept_id(discovery, errors)
    _check_authority_conflicts(discovery, errors)
    _check_authority_scope_disappearance(graph, errors)

    # Cycle checks.
    if detect_cycle(graph, "defers_to", same_scope=True):
        errors.append(
            Finding(
                code="E-CYCLE-001",
                message="cycle detected in defers_to graph (same scope)",
            )
        )
    if detect_cycle(graph, "superseded_by", same_scope=False):
        errors.append(
            Finding(
                code="E-CYCLE-002",
                message="cycle detected in superseded_by chain",
            )
        )

    # Warnings.
    _warn_bidir_defers(graph, discovery, warnings)
    _warn_h1_title_mismatch(discovery, warnings)
    _warn_body_unknown_refs(graph, discovery, warnings)
    _warn_defers_target_not_mentioned(discovery, warnings)
    _warn_scope_without_active_owner(graph, warnings)
    _warn_orphan_concepts(graph, discovery, warnings)

    if strict:
        for w in warnings:
            errors.append(Finding(code=w.code, message=w.message, concept_id=w.concept_id, path=w.path))
        warnings = []

    graph_info: dict[str, object] = {
        "concept_count": graph.concept_count,
        "active_count": graph.active_count,
        "acyclic": not errors or not any(
            f.code in ("E-CYCLE-001", "E-CYCLE-002") for f in errors
        ),
    }
    if errors:
        exit_code = ExitCode.ERRORS
        status = "errors"
    elif warnings:
        exit_code = ExitCode.WARNINGS
        status = "warnings"
    else:
        exit_code = ExitCode.VALID
        status = "valid"
    return ValidationReport(
        exit_code=exit_code,
        status=status,
        corpus_revision=discovery.corpus_revision,
        errors=tuple(errors),
        warnings=tuple(warnings),
        graph=graph_info,
    )


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #


def _check_appendix_parent(discovery: DiscoveryResult, errors: list[Finding]) -> None:
    for doc in discovery.documents:
        if doc.is_appendix and not doc.parent_concept_id:
            errors.append(
                Finding(
                    code="E-SCHEMA-004",
                    message=f"appendix {doc.concept_id!r} has no parent_concept_id",
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )


def _check_filename_convention(discovery: DiscoveryResult, errors: list[Finding]) -> None:
    """E-ID-002: the concept_id must agree with its filename (FK-13 §13.9.7).

    Two failures: (a) the id does not match the id-convention shape; (b) the
    id's leading numeric component does not match the filename's leading number
    (e.g. ``FK-13`` MUST live in ``13_*.md``).
    """
    for doc in discovery.documents:
        if not _ID_CONVENTION_RE.match(doc.concept_id):
            errors.append(
                Finding(
                    code="E-ID-002",
                    message=f"concept_id {doc.concept_id!r} does not match the id convention",
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )
            continue
        id_num = _id_number(doc.concept_id)
        filename = doc.rel_path.rsplit("/", 1)[-1].removesuffix(".md")
        if id_num is not None and not filename.startswith(f"{id_num}"):
            errors.append(
                Finding(
                    code="E-ID-002",
                    message=(
                        f"concept_id {doc.concept_id!r} (numeric {id_num}) does not "
                        f"agree with filename {filename!r}"
                    ),
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )


def _id_number(concept_id: str) -> str | None:
    match = _ID_NUMBER_RE.search(concept_id)
    return match.group(1) if match else None


def _check_chunk_size(
    discovery: DiscoveryResult, errors: list[Finding], *, max_tokens: int
) -> None:
    for doc in discovery.documents:
        for section in split_into_sections(doc.body):
            if chunk_token_count(section.body) > max_tokens:
                errors.append(
                    Finding(
                        code="E-CHUNK-001",
                        message=(
                            f"section {section.section_number} {section.heading!r} of "
                            f"{doc.concept_id!r} exceeds max token limit {max_tokens}"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )


def _check_defers_to_refs(
    graph: ConceptGraph, discovery: DiscoveryResult, errors: list[Finding]
) -> None:
    for doc in discovery.documents:
        for target in doc.defers_to_targets:
            if not graph.exists(target):
                errors.append(
                    Finding(
                        code="E-REF-001",
                        message=f"defers_to target {target!r} not in corpus",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )


def _check_parent_refs(
    graph: ConceptGraph, discovery: DiscoveryResult, errors: list[Finding]
) -> None:
    for doc in discovery.documents:
        if doc.is_appendix and doc.parent_concept_id:
            if not graph.exists(doc.parent_concept_id):
                errors.append(
                    Finding(
                        code="E-REF-002",
                        message=f"parent_concept_id {doc.parent_concept_id!r} not in corpus",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )
            elif not graph.is_core(doc.parent_concept_id):
                errors.append(
                    Finding(
                        code="E-REF-002",
                        message=f"parent_concept_id {doc.parent_concept_id!r} is not a core document",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )


def _check_superseded_by_refs(
    graph: ConceptGraph, discovery: DiscoveryResult, errors: list[Finding]
) -> None:
    for doc in discovery.documents:
        if doc.superseded_by and not graph.exists(doc.superseded_by):
            errors.append(
                Finding(
                    code="E-REF-003",
                    message=f"superseded_by {doc.superseded_by!r} not in corpus",
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )


def _check_duplicate_concept_id(discovery: DiscoveryResult, errors: list[Finding]) -> None:
    seen: dict[str, str] = {}
    for doc in discovery.documents:
        if doc.effective_status != "active":
            continue
        if doc.concept_id in seen:
            errors.append(
                Finding(
                    code="E-ID-001",
                    message=(
                        f"duplicate concept_id {doc.concept_id!r} in active corpus "
                        f"(also at {seen[doc.concept_id]!r})"
                    ),
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )
        else:
            seen[doc.concept_id] = doc.rel_path


def _check_authority_conflicts(discovery: DiscoveryResult, errors: list[Finding]) -> None:
    scope_owners: dict[str, list[str]] = {}
    for doc in discovery.documents:
        if doc.effective_status != "active":
            continue
        for scope in doc.authority_scopes:
            scope_owners.setdefault(scope, []).append(doc.concept_id)
    for scope, owners in scope_owners.items():
        if len(owners) > 1:
            errors.append(
                Finding(
                    code="E-AUTH-001",
                    message=(
                        f"scope {scope!r} claimed by multiple active concepts: {sorted(owners)}"
                    ),
                )
            )


def _check_authority_scope_disappearance(graph: ConceptGraph, errors: list[Finding]) -> None:
    # E-AUTH-002: an authority_over scope that was previously owned disappears.
    # In a single-pass validation we flag a scope referenced via defers_to that
    # has no active owner and no successor.
    referenced_scopes = {edge.scope for edge in graph.edges if edge.type == "defers_to" and edge.scope}
    owned_scopes = {
        scope for node in graph.nodes.values() if node.status == "active" for scope in node.authority_scopes
    }
    for scope in sorted(referenced_scopes - owned_scopes):
        errors.append(
            Finding(
                code="E-AUTH-002",
                message=f"authority_over scope {scope!r} referenced via defers_to has no active owner",
            )
        )


def _warn_bidir_defers(
    graph: ConceptGraph, discovery: DiscoveryResult, warnings: list[Finding]
) -> None:
    owned: dict[str, set[str]] = {}
    for node in graph.nodes.values():
        for scope in node.authority_scopes:
            owned.setdefault(scope, set()).add(node.concept_id)
    for doc in discovery.documents:
        for target, scope, _reason in doc.defers_to_full:
            if scope and target not in owned.get(scope, set()):
                warnings.append(
                    Finding(
                        code="W-BIDIR-001",
                        message=(
                            f"{doc.concept_id} defers_to {target} for scope {scope!r}, "
                            "but target has no matching authority_over"
                        ),
                        concept_id=doc.concept_id,
                    )
                )


def _warn_h1_title_mismatch(discovery: DiscoveryResult, warnings: list[Finding]) -> None:
    for doc in discovery.documents:
        heading = _first_h1_title(doc.body)
        if heading is not None and heading != doc.title.strip():
            warnings.append(
                Finding(
                    code="W-CONTENT-001",
                    message=f"H1 {heading!r} differs from frontmatter title {doc.title!r}",
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )


def _first_h1_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("#") and len(line) > 1 and line[1].isspace():
            title = line[2:].strip()
            return title or None
    return None


def _warn_body_unknown_refs(
    graph: ConceptGraph, discovery: DiscoveryResult, warnings: list[Finding]
) -> None:
    """W-CONTENT-002: body mentions TK-*/AF-*/FK-*/DK-* not in the graph."""
    known: set[str] = set(graph.nodes.keys())
    for doc in discovery.documents:
        mentioned = {m.group(0) for m in _BODY_ID_RE.finditer(doc.body)}
        unknown = sorted(mentioned - known)
        if unknown:
            warnings.append(
                Finding(
                    code="W-CONTENT-002",
                    message=(
                        f"body mentions concept id(s) not in the graph: {unknown}"
                    ),
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )


def _warn_defers_target_not_mentioned(
    discovery: DiscoveryResult, warnings: list[Finding]
) -> None:
    """W-CONTENT-003: frontmatter defers_to set but body does not mention target."""
    for doc in discovery.documents:
        for target in doc.defers_to_targets:
            if target not in doc.body:
                warnings.append(
                    Finding(
                        code="W-CONTENT-003",
                        message=(
                            f"frontmatter defers_to {target!r} but body does not mention it"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )


def _warn_scope_without_active_owner(graph: ConceptGraph, warnings: list[Finding]) -> None:
    """W-SCOPE-001: a scope declared only by non-active concepts (no active owner).

    A scope that had an authority owner but is now carried only by archived/draft
    concepts (no active successor) is at risk -- a warning, not a hard error.
    """
    active_scopes: set[str] = set()
    non_active_scopes: set[str] = set()
    for node in graph.nodes.values():
        if node.status == "active":
            active_scopes.update(node.authority_scopes)
        else:
            non_active_scopes.update(node.authority_scopes)
    for scope in sorted(non_active_scopes - active_scopes):
        warnings.append(
            Finding(
                code="W-SCOPE-001",
                message=(
                    f"authority scope {scope!r} has no active authority owner "
                    "(declared only by non-active concepts)"
                ),
            )
        )


def _warn_orphan_concepts(
    graph: ConceptGraph, discovery: DiscoveryResult, warnings: list[Finding]
) -> None:
    for doc in discovery.documents:
        if doc.effective_status != "active":
            continue
        has_out = any(e.source == doc.concept_id for e in graph.edges)
        has_in = any(e.target == doc.concept_id for e in graph.edges)
        if not has_out and not has_in:
            warnings.append(
                Finding(
                    code="W-ORPHAN-001",
                    message=f"active concept {doc.concept_id!r} has no in/out relationships",
                    concept_id=doc.concept_id,
                )
            )


__all__ = [
    "ERROR_CODES",
    "ExitCode",
    "Finding",
    "WARNING_CODES",
    "ValidationReport",
    "validate_corpus",
]
