"""Generic frontmatter/authority contract check (FK-78 sections 78.2 and 78.14).

Applies the configured frontmatter contract to the ``domain`` and
``technical`` layers (the layers with configured concept-id grammars):
required fields, id grammar and corpus-wide uniqueness, classification
(``formal_refs`` XOR ``formal_scope: prose-only``), detail-parent rule,
deferral-target existence, supersession form and full-supersession
reciprocity, an acyclic authority graph (parent chain plus per-scope
``defers_to`` projections), and per-scope authority disjointness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .docmodel import ConceptDocument, scan_documents
from .findings import CheckResult, error

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "frontmatter"
_CONTRACT_LAYERS = ("domain", "technical")
_GRAMMAR_BY_LAYER = {"domain": "domain_doc", "technical": "technical_doc"}


def run_frontmatter_check(project_root: Path, config: GovernanceConfig) -> CheckResult:
    """Run the frontmatter/authority contract against the corpus."""
    result = CheckResult(check_id=CHECK_ID)
    missing = [
        config.concept_roots[layer] for layer in _CONTRACT_LAYERS if not config.root_path(project_root, layer).is_dir()
    ]
    if missing:
        result.complete = False
        result.incomplete_reason = f"missing concept root(s): {', '.join(missing)}"
        return result
    documents = scan_documents(project_root, config.concept_roots)
    contract_docs = [doc for doc in documents if doc.layer in _CONTRACT_LAYERS]
    known_ids = _collect_known_ids(documents, result)
    for doc in contract_docs:
        _check_document(doc, config, result)
    by_id = {doc.concept_id: doc for doc in contract_docs if doc.concept_id}
    _check_targets_and_reciprocity(contract_docs, by_id, known_ids, config, result)
    _check_supersession_ring(contract_docs, by_id, result)
    _check_parent_graph_acyclic(contract_docs, by_id, result)
    _check_scope_deferral_cycles(contract_docs, result)
    _check_authority_scope_disjoint(contract_docs, by_id, result)
    result.summary = f"{len(contract_docs)} documents checked"
    return result


def _collect_known_ids(documents: Sequence[ConceptDocument], result: CheckResult) -> frozenset[str]:
    known: dict[str, str] = {}
    for doc in documents:
        cid = doc.concept_id
        if not cid:
            continue
        if cid in known:
            result.findings.append(
                error(f"{CHECK_ID}.concept-id", doc.rel_path, "concept_id", f"concept_id {cid!r} is also used by {known[cid]}")
            )
            continue
        known[cid] = doc.rel_path
    return frozenset(known)


def _check_document(doc: ConceptDocument, config: GovernanceConfig, result: CheckResult) -> None:
    if doc.frontmatter_error is not None:
        result.findings.append(
            error(
                f"{CHECK_ID}.parse",
                doc.rel_path,
                f"L{doc.frontmatter_error_line}",
                f"frontmatter is not parseable SMY: {doc.frontmatter_error}",
            )
        )
        return
    if doc.frontmatter is None:
        result.findings.append(error(f"{CHECK_ID}.parse", doc.rel_path, "L1", "document has no frontmatter block"))
        return
    contract = config.frontmatter_contract
    for field_name in contract.required_fields:
        if field_name not in doc.frontmatter:
            message = f"required frontmatter field {field_name!r} is missing"
            result.findings.append(error(f"{CHECK_ID}.required-field", doc.rel_path, field_name, message))
    _check_concept_id_grammar(doc, config, result)
    _check_classification(doc, result)
    _check_detail_parent(doc, config, result)


def _check_concept_id_grammar(doc: ConceptDocument, config: GovernanceConfig, result: CheckResult) -> None:
    cid = doc.concept_id
    if not cid:
        result.findings.append(error(f"{CHECK_ID}.concept-id", doc.rel_path, "concept_id", "concept_id is missing or empty"))
        return
    grammar = config.id_grammars[_GRAMMAR_BY_LAYER[doc.layer]]
    if grammar.fullmatch(cid) is None:
        result.findings.append(
            error(
                f"{CHECK_ID}.concept-id",
                doc.rel_path,
                "concept_id",
                f"concept_id {cid!r} does not match the {doc.layer} grammar {grammar.pattern!r}",
            )
        )


def _check_classification(doc: ConceptDocument, result: CheckResult) -> None:
    frontmatter = doc.frontmatter or {}
    formal_refs = frontmatter.get("formal_refs")
    if formal_refs is not None and (
        not isinstance(formal_refs, list) or not all(isinstance(item, str) and item for item in formal_refs)
    ):
        result.findings.append(
            error(f"{CHECK_ID}.classification", doc.rel_path, "formal_refs", "formal_refs must be a list of non-empty strings")
        )
        return
    has_refs = isinstance(formal_refs, list) and bool(formal_refs)
    prose_only = frontmatter.get("formal_scope") == "prose-only"
    if has_refs and prose_only:
        result.findings.append(
            error(
                f"{CHECK_ID}.classification",
                doc.rel_path,
                "formal_scope",
                "document mixes non-empty formal_refs with formal_scope: prose-only",
            )
        )
    elif not has_refs and not prose_only:
        result.findings.append(
            error(
                f"{CHECK_ID}.classification",
                doc.rel_path,
                "formal_refs",
                "document must declare non-empty formal_refs or formal_scope: prose-only",
            )
        )


def _check_detail_parent(doc: ConceptDocument, config: GovernanceConfig, result: CheckResult) -> None:
    if not config.frontmatter_contract.detail_requires_parent:
        return
    frontmatter = doc.frontmatter or {}
    if frontmatter.get("doc_kind") != "detail":
        return
    parent = frontmatter.get("parent_concept_id")
    if not isinstance(parent, str) or not parent:
        result.findings.append(
            error(
                f"{CHECK_ID}.detail-parent",
                doc.rel_path,
                "parent_concept_id",
                "doc_kind: detail requires a non-empty parent_concept_id",
            )
        )


def _deferral_target(entry: object) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        target = entry.get("target")
        return target.strip() if isinstance(target, str) else ""
    return ""


def _deferral_scope(entry: object) -> str | None:
    if isinstance(entry, dict):
        scope = entry.get("scope")
        if isinstance(scope, str) and scope.strip():
            return scope.strip()
    return None


def _entries(frontmatter: dict[str, object] | None, field_name: str) -> list[object]:
    value = (frontmatter or {}).get(field_name)
    return value if isinstance(value, list) else []


def _check_targets_and_reciprocity(
    docs: Sequence[ConceptDocument],
    by_id: dict[str, ConceptDocument],
    known_ids: frozenset[str],
    config: GovernanceConfig,
    result: CheckResult,
) -> None:
    for doc in docs:
        if doc.frontmatter is None:
            continue
        _check_parent_target(doc, known_ids, result)
        for entry in _entries(doc.frontmatter, "defers_to"):
            target = _deferral_target(entry)
            if not target:
                result.findings.append(
                    error(f"{CHECK_ID}.defers-to", doc.rel_path, "defers_to", f"defers_to entry has no target: {entry!r}")
                )
            elif target not in known_ids:
                result.findings.append(
                    error(f"{CHECK_ID}.defers-to", doc.rel_path, "defers_to", f"defers_to target {target!r} does not exist")
                )
        _check_supersession(doc, by_id, known_ids, config, result)


def _check_parent_target(doc: ConceptDocument, known_ids: frozenset[str], result: CheckResult) -> None:
    parent = (doc.frontmatter or {}).get("parent_concept_id")
    if isinstance(parent, str) and parent and parent not in known_ids:
        result.findings.append(
            error(f"{CHECK_ID}.parent", doc.rel_path, "parent_concept_id", f"parent_concept_id {parent!r} does not exist")
        )


def _check_supersession(
    doc: ConceptDocument,
    by_id: dict[str, ConceptDocument],
    known_ids: frozenset[str],
    config: GovernanceConfig,
    result: CheckResult,
) -> None:
    reciprocity = config.frontmatter_contract.full_supersession_reciprocity
    for entry in _entries(doc.frontmatter, "supersedes"):
        target = _deferral_target(entry)
        if not target:
            result.findings.append(
                error(f"{CHECK_ID}.supersession", doc.rel_path, "supersedes", f"supersedes entry has no target: {entry!r}")
            )
            continue
        if target not in known_ids:
            result.findings.append(
                error(f"{CHECK_ID}.supersession", doc.rel_path, "supersedes", f"supersedes target {target!r} does not exist")
            )
            continue
        if _deferral_scope(entry) is not None or not reciprocity:
            continue
        other = by_id.get(target)
        other_sb = (other.frontmatter or {}).get("superseded_by") if other else None
        if other is not None and other_sb != doc.concept_id:
            result.findings.append(
                error(
                    f"{CHECK_ID}.supersession",
                    doc.rel_path,
                    "supersedes",
                    f"full supersession of {target} is not reciprocated "
                    f"(expected superseded_by: {doc.concept_id}, got {other_sb!r})",
                )
            )
    _check_superseded_by(doc, by_id, known_ids, reciprocity, result)


def _check_superseded_by(
    doc: ConceptDocument,
    by_id: dict[str, ConceptDocument],
    known_ids: frozenset[str],
    reciprocity: bool,
    result: CheckResult,
) -> None:
    superseded_by = (doc.frontmatter or {}).get("superseded_by")
    if superseded_by is None or superseded_by == "":
        return
    if not isinstance(superseded_by, str):
        result.findings.append(
            error(f"{CHECK_ID}.supersession", doc.rel_path, "superseded_by", "superseded_by must be a string or empty")
        )
        return
    if superseded_by not in known_ids:
        message = f"superseded_by target {superseded_by!r} does not exist"
        result.findings.append(error(f"{CHECK_ID}.supersession", doc.rel_path, "superseded_by", message))
        return
    if not reciprocity:
        return
    other = by_id.get(superseded_by)
    if other is None:
        return
    reciprocated = any(
        _deferral_target(entry) == doc.concept_id and _deferral_scope(entry) is None
        for entry in _entries(other.frontmatter, "supersedes")
    )
    if not reciprocated:
        result.findings.append(
            error(
                f"{CHECK_ID}.supersession",
                doc.rel_path,
                "superseded_by",
                f"superseded_by: {superseded_by} but {other.rel_path} has no full-supersession entry for {doc.concept_id}",
            )
        )


def _check_supersession_ring(docs: Sequence[ConceptDocument], by_id: dict[str, ConceptDocument], result: CheckResult) -> None:
    for doc in docs:
        chain = [doc.concept_id] if doc.concept_id else []
        current = (doc.frontmatter or {}).get("superseded_by")
        while isinstance(current, str) and current:
            if current in chain:
                result.findings.append(
                    error(
                        f"{CHECK_ID}.supersession",
                        doc.rel_path,
                        "superseded_by",
                        f"superseded_by ring detected via {' -> '.join([*chain, current])}",
                    )
                )
                break
            chain.append(current)
            next_doc = by_id.get(current)
            current = (next_doc.frontmatter or {}).get("superseded_by") if next_doc else None


def _check_parent_graph_acyclic(docs: Sequence[ConceptDocument], by_id: dict[str, ConceptDocument], result: CheckResult) -> None:
    edges: dict[str, tuple[str, ...]] = {}
    for doc in docs:
        if not doc.concept_id:
            continue
        parent = (doc.frontmatter or {}).get("parent_concept_id")
        edges[doc.concept_id] = (parent,) if isinstance(parent, str) and parent and parent in by_id else ()
    for component in strong_components(edges):
        result.findings.append(
            error(
                f"{CHECK_ID}.authority-cycle",
                "concept",
                "parent_concept_id",
                f"parent_concept_id cycle among {', '.join(component)}",
            )
        )


def _check_scope_deferral_cycles(docs: Sequence[ConceptDocument], result: CheckResult) -> None:
    scoped_edges: dict[str, dict[str, list[str]]] = {}
    for doc in docs:
        if not doc.concept_id:
            continue
        for entry in _entries(doc.frontmatter, "defers_to"):
            scope = _deferral_scope(entry)
            target = _deferral_target(entry)
            if scope is None or not target:
                continue
            scoped_edges.setdefault(scope, {}).setdefault(doc.concept_id, []).append(target)
    for scope in sorted(scoped_edges):
        graph = {source: tuple(targets) for source, targets in scoped_edges[scope].items()}
        for component in strong_components(graph):
            result.findings.append(
                error(
                    f"{CHECK_ID}.authority-cycle",
                    "concept",
                    f"scope:{scope}",
                    f"defers_to cycle within scope {scope!r} among {', '.join(component)}",
                )
            )


def _check_authority_scope_disjoint(
    docs: Sequence[ConceptDocument], by_id: dict[str, ConceptDocument], result: CheckResult
) -> None:
    holders: dict[str, list[ConceptDocument]] = {}
    for doc in docs:
        for entry in _entries(doc.frontmatter, "authority_over"):
            if not isinstance(entry, dict):
                message = f"authority_over entry must be a mapping with a scope: {entry!r}"
                result.findings.append(error(f"{CHECK_ID}.authority-scope", doc.rel_path, "authority_over", message))
                continue
            scope = entry.get("scope")
            if not isinstance(scope, str) or not scope:
                message = "authority_over entry has no non-empty scope"
                result.findings.append(error(f"{CHECK_ID}.authority-scope", doc.rel_path, "authority_over", message))
                continue
            holders.setdefault(scope, []).append(doc)
    for scope in sorted(holders):
        owners = holders[scope]
        if len(owners) <= 1 or _connected_by_full_supersession(owners, by_id):
            continue
        ids = ", ".join(sorted(owner.concept_id or owner.rel_path for owner in owners))
        result.findings.append(
            error(
                f"{CHECK_ID}.authority-scope",
                "concept",
                f"scope:{scope}",
                f"authority_over scope {scope!r} is held by multiple non-superseded documents: {ids}",
            )
        )


def _connected_by_full_supersession(owners: list[ConceptDocument], by_id: dict[str, ConceptDocument]) -> bool:
    if len(owners) != 2:
        return False
    first, second = owners
    return (
        _fully_supersedes(first, second.concept_id)
        or _fully_supersedes(second, first.concept_id)
        or (first.frontmatter or {}).get("superseded_by") == second.concept_id
        or (second.frontmatter or {}).get("superseded_by") == first.concept_id
    )


def _fully_supersedes(doc: ConceptDocument, target: str) -> bool:
    return bool(target) and any(
        _deferral_target(entry) == target and _deferral_scope(entry) is None
        for entry in _entries(doc.frontmatter, "supersedes")
    )


class _Tarjan:
    """Iterative Tarjan SCC computation over a string adjacency graph."""

    def __init__(self, edges: dict[str, tuple[str, ...]]) -> None:
        self.adjacency: dict[str, list[str]] = {node: [] for node in edges}
        for source, targets in edges.items():
            for target in targets:
                self.adjacency.setdefault(source, []).append(target)
                self.adjacency.setdefault(target, [])
        self.counter = 0
        self.indices: dict[str, int] = {}
        self.lowlinks: dict[str, int] = {}
        self.stack: list[str] = []
        self.on_stack: set[str] = set()
        self.components: list[tuple[str, ...]] = []
        self.work: list[tuple[str, int]] = []

    def run(self) -> tuple[tuple[str, ...], ...]:
        for start in sorted(self.adjacency):
            if start not in self.indices:
                self.work.append((start, 0))
                self._drain()
        return tuple(sorted(self.components))

    def _drain(self) -> None:
        while self.work:
            node, child_index = self.work.pop()
            if child_index == 0:
                self.indices[node] = self.lowlinks[node] = self.counter
                self.counter += 1
                self.stack.append(node)
                self.on_stack.add(node)
            if self._advance(node, child_index):
                continue
            if self.lowlinks[node] == self.indices[node]:
                self._pop_component(node)
            if self.work:
                parent = self.work[-1][0]
                self.lowlinks[parent] = min(self.lowlinks[parent], self.lowlinks[node])

    def _advance(self, node: str, child_index: int) -> bool:
        targets = sorted(self.adjacency[node])
        for position in range(child_index, len(targets)):
            target = targets[position]
            if target not in self.indices:
                self.work.append((node, position + 1))
                self.work.append((target, 0))
                return True
            if target in self.on_stack:
                self.lowlinks[node] = min(self.lowlinks[node], self.indices[target])
        return False

    def _pop_component(self, node: str) -> None:
        component: list[str] = []
        while self.stack:
            member = self.stack.pop()
            self.on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        canonical = tuple(sorted(component))
        if len(canonical) > 1 or node in self.adjacency[node]:
            self.components.append(canonical)


def strong_components(edges: dict[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    """Return sorted non-trivial strongly connected components."""
    return _Tarjan(edges).run()
