"""Authority resolver / ranking policy (FK-13 §13.9.11).

The VectorDB returns semantic hits; authority resolution happens in the app
layer with DETERMINISTIC rules + a deterministic tie-break. The resolver ranks
hits against an EXPLICIT query scope / detail (the authority scope being asked
about and whether interface/test detail is wanted), traversing the scoped
``defers_to`` graph edges. Used by ``concept_search`` to rank results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.concept_corpus.graph import ConceptGraph

#: Query detail hints that activate the appendix interface boost (rule 3).
_INTERFACE_DETAILS: frozenset[str] = frozenset(
    {"interface", "interfaces", "test", "tests", "contract", "contracts", "api"}
)

#: Rule-5 module-match boost (FK-13 §13.9.11).
MODULE_MATCH_BOOST: Final[float] = 0.3

#: Rule-3 appendix interface/test boost (FK-13 §13.9.11).
APPENDIX_DETAIL_BOOST: Final[float] = 0.5


@dataclass(frozen=True)
class RankedHit:
    """A search hit with its computed authority score and applied rules.

    Attributes:
        hit_index: Position of the hit in the ranked INPUT sequence. This keeps a
            stable per-hit identity through ranking, so several section hits of
            the same ``concept_id`` stay distinct (N10).
    """

    concept_id: str
    score: float
    authority_score: float
    reasons: tuple[str, ...]
    hit_index: int = -1


@dataclass(frozen=True)
class RankContext:
    """Explicit query context the five rules rank against (R10).

    Attributes:
        query_scope: the authority scope being asked about (e.g. ``"vectordb"``).
            Empty means no scope is known -> rules 1/2 do not apply.
        query_module: the module the query originates from (rule 5).
        query_detail: a free-form detail hint (``"interface"``/``"test"``/...)
            that activates the appendix interface boost (rule 3).
    """

    query_scope: str = ""
    query_module: str = ""
    query_detail: str = ""


def _status_penalty(status: str) -> float:
    """Rule 4: archived/draft get a penalty."""
    if status == "archived":
        return -2.0
    if status == "draft":
        return -1.0
    return 0.0


def _is_scoped_authority_target(graph: ConceptGraph, concept_id: str, query_scope: str) -> bool:
    """Rule 2: True if ``concept_id`` is the TARGET of a scoped deferral FOR
    ``query_scope`` -- i.e. some other concept defers_to THIS concept for the
    query scope. The boost accrues to the authority TARGET, not the deferrer
    (R10 correction)."""
    if not query_scope:
        return False
    return any(
        e.target == concept_id
        and e.type == "defers_to"
        and e.scope == query_scope
        for e in graph.edges
    )


def rank_hits(
    graph: ConceptGraph,
    hits: Sequence[Mapping[str, object]],
    *,
    query_scope: str = "",
    query_module: str = "",
    query_detail: str = "",
) -> list[RankedHit]:
    """Rank semantic hits by the five authority rules + deterministic tie-break.

    Pass an explicit :class:`RankContext` (scope/module/detail); the rules are
    evaluated against it, not against the node's own scopes (R10).

    Rules (FK-13 §13.9.11):
    1. Direct ``authority_over`` match for the QUERY SCOPE beats adjacent match.
    2. The scoped authority TARGET (a concept that some other concept defers_to
       for the query scope) beats a generic local mention -- the boost accrues
       to the TARGET, not the deferring source (R10).
    3. An appendix can rank higher than a core doc ONLY for interface/test detail
       (a non-empty query_detail that signals interface/test); an empty
       query_detail grants NO appendix boost (R10).
    4. Archived/draft concepts receive a penalty.
    5. A module-match boosts ONLY when there is no stronger cross-module authority
       (a node owning the query scope in another module outranks a mere
       module-local match).

    Tie-break: higher authority score, then higher base score, then lexicographic
    concept_id (fully deterministic).
    """
    ctx = RankContext(query_scope=query_scope, query_module=query_module, query_detail=query_detail)
    # Does ANY node own the query scope in a DIFFERENT module? (rule 5 guard)
    cross_module_authority = _cross_module_authority_exists(graph, ctx)

    ranked: list[RankedHit] = []
    for hit_index, hit in enumerate(hits):
        concept_id = str(hit.get("concept_id", ""))
        node = graph.node(concept_id)
        raw_score = hit.get("score", 0.0)
        base = float(raw_score) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0.0
        if node is None:
            ranked.append(
                RankedHit(concept_id, base, base, ("no-graph-node",), hit_index=hit_index)
            )
            continue
        authority = base
        reasons: list[str] = []
        # Rule 1: direct authority_over match for the QUERY SCOPE.
        if ctx.query_scope and ctx.query_scope in node.authority_scopes:
            authority += 2.0
            reasons.append("authority_over-direct")
        # Rule 2: this node is the scoped authority TARGET for the query scope
        # (some other concept defers_to it for that scope) -> boost the TARGET.
        if _is_scoped_authority_target(graph, concept_id, ctx.query_scope):
            authority += 1.0
            reasons.append("scoped-authority-target")
        # Rule 3: appendix interface boost ONLY for interface/test detail
        # (non-empty query_detail signalling interface/test); empty -> no boost.
        if (
            node.is_appendix
            and bool(ctx.query_detail)
            and ctx.query_detail.lower() in _INTERFACE_DETAILS
        ):
            authority += APPENDIX_DETAIL_BOOST
            reasons.append("appendix-interface")
        # Rule 4: status penalty.
        penalty = _status_penalty(node.status)
        if penalty:
            authority += penalty
            reasons.append(f"status-penalty({node.status})")
        # Rule 5: module-match boost only without a stronger cross-module authority.
        if (
            ctx.query_module
            and node.module == ctx.query_module
            and ctx.query_scope not in node.authority_scopes
            and not cross_module_authority
        ):
            authority += MODULE_MATCH_BOOST
            reasons.append("module-match")
        ranked.append(
            RankedHit(concept_id, base, authority, tuple(reasons), hit_index=hit_index)
        )
    ranked.sort(key=lambda r: (-r.authority_score, -r.score, r.concept_id, r.hit_index))
    return ranked


def derive_query_detail(query: str) -> str:
    """Derive the interface/test DETAIL hint from the query text (rule 3, R10).

    FK-13 §13.9.11 rule 3 lets an appendix outrank a core document for
    interface/test detail. "Detail" is a property of what is being ASKED, and
    FK-13 §13.9.5 defines no separate detail parameter -- so the hint is derived
    deterministically from the query text itself: the FIRST interface/test token
    that appears as a word. Empty when the query asks for no such detail.
    """
    for token in re.findall(r"[a-z0-9]+", query.lower()):
        if token in _INTERFACE_DETAILS:
            return str(token)
    return ""


def _cross_module_authority_exists(graph: ConceptGraph, ctx: RankContext) -> bool:
    """True if some node OWNS the query scope in a module != query_module."""
    if not ctx.query_scope:
        return False
    return any(
        ctx.query_scope in node.authority_scopes
        and node.status == "active"
        and (not ctx.query_module or node.module != ctx.query_module)
        for node in graph.nodes.values()
    )


__all__ = [
    "APPENDIX_DETAIL_BOOST",
    "MODULE_MATCH_BOOST",
    "RankContext",
    "RankedHit",
    "derive_query_detail",
    "rank_hits",
]
