"""Authority resolver / ranking policy (FK-13 §13.9.11).

The VectorDB returns semantic hits; authority resolution happens in the app layer
with DETERMINISTIC rules + a deterministic tie-break.

Two properties are load-bearing (N23):

1. **``module`` and the authority SCOPE are separate inputs.** FK-13 models the
   document's ``module`` and its ``authority_over`` scopes as different things, so
   the resolver never derives one from the other. ``query_authority_scope`` carries
   the ratified ``authority_scope`` parameter of §13.9.5 (D7) straight from the
   caller; when it is empty, rules 1 and 2 simply do not apply while 3/4/5 stay
   unchanged.
2. **Normative precedence cannot be outscored.** Rules 1/2/4 decide a PRECEDENCE
   TIER that is compared before any similarity value, so a high BM25 score can
   never lift a non-authoritative (or archived) concept above one that normatively
   "beats" it. Rules 3 and 5 are bounded WITHIN-tier boosts on a normalised score.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.concept_corpus.graph import ConceptGraph, GraphNode

#: Query detail hints that activate the appendix interface boost (rule 3).
_INTERFACE_DETAILS: frozenset[str] = frozenset(
    {"interface", "interfaces", "test", "tests", "contract", "contracts", "api"}
)

#: Rule-5 module-match boost (bounded, within-tier).
MODULE_MATCH_BOOST: Final[float] = 0.3

#: Rule-3 appendix interface/test boost (bounded, within-tier).
APPENDIX_DETAIL_BOOST: Final[float] = 0.5

#: Precedence tiers (LOWER wins). Compared BEFORE any score (N23).
TIER_DIRECT_AUTHORITY: Final[int] = 0
"""Rule 1: the concept is authoritative for the queried scope."""

TIER_SCOPED_TARGET: Final[int] = 1
"""Rule 2: another concept defers TO this one for the queried scope."""

TIER_ORDINARY: Final[int] = 2
"""No authority relation to the queried scope (or no scope was asked about)."""

#: Rule 4: non-active concepts are demoted by whole tiers, so no similarity score
#: can lift an archived/draft document above an active one.
TIER_PENALTY_DRAFT: Final[int] = 4
TIER_PENALTY_ARCHIVED: Final[int] = 8


@dataclass(frozen=True)
class RankedHit:
    """A search hit with its precedence tier, within-tier score and applied rules.

    Attributes:
        concept_id: Concept the hit belongs to.
        score: The raw similarity value the transport returned.
        authority_score: The WITHIN-TIER value (normalised score + bounded
            rule-3/rule-5 boosts). It never crosses a tier boundary.
        tier: Precedence tier (lower = stronger). Compared before any score.
        reasons: The applied rule markers, in rule order.
        hit_index: Position of the hit in the ranked INPUT sequence. This keeps a
            stable per-hit identity through ranking, so several section hits of the
            same ``concept_id`` stay distinct (N10).
    """

    concept_id: str
    score: float
    authority_score: float
    reasons: tuple[str, ...]
    tier: int = TIER_ORDINARY
    hit_index: int = -1


@dataclass(frozen=True)
class RankContext:
    """Explicit query context the five rules rank against (R10/N23).

    Attributes:
        query_authority_scope: the ``authority_over`` SCOPE being asked about
            (e.g. ``"vectordb"``). Empty means no scope is known -> rules 1/2 do
            not apply. It is NEVER derived from ``query_module``: FK-13 models the
            two separately (N23).
        query_module: the module the query is about (rule 5).
        query_detail: a free-form detail hint (``"interface"``/``"test"``/...)
            that activates the appendix interface boost (rule 3).
    """

    query_authority_scope: str = ""
    query_module: str = ""
    query_detail: str = ""


def _status_tier_penalty(status: str) -> int:
    """Rule 4: archived/draft are demoted by whole tiers."""
    if status == "archived":
        return TIER_PENALTY_ARCHIVED
    if status == "draft":
        return TIER_PENALTY_DRAFT
    return 0


def _normalised(score: float) -> float:
    """Map a raw similarity value onto ``[0, 1)`` so boosts stay meaningful.

    BM25 scores are unbounded; without normalisation a bounded rule-3/rule-5 boost
    would be arithmetic noise next to a large score (N23).
    """
    if score <= 0.0:
        return 0.0
    return score / (1.0 + score)


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
    query_authority_scope: str = "",
    query_module: str = "",
    query_detail: str = "",
) -> list[RankedHit]:
    """Rank semantic hits by the five authority rules + deterministic tie-break.

    Rules (FK-13 §13.9.11):

    1. A direct ``authority_over`` match for the QUERIED SCOPE beats an adjacent
       match -- implemented as the strongest precedence TIER, not as a bonus.
    2. The scoped authority TARGET (a concept another concept defers_to for the
       queried scope) beats a generic local mention -- the next tier; the credit
       accrues to the TARGET, never to the deferring source.
    3. An appendix may rank higher than a core doc ONLY for interface/test detail
       (a non-empty ``query_detail`` naming such detail) -- a bounded within-tier
       boost.
    4. Archived/draft concepts are demoted by whole tiers, so no similarity score
       can raise them above an active concept.
    5. A module match boosts ONLY when no stronger cross-module authority exists --
       a bounded within-tier boost.

    Order: precedence tier, then the within-tier authority score, then the raw
    score, then ``concept_id``, then the input position (fully deterministic).
    """
    ctx = RankContext(
        query_authority_scope=query_authority_scope,
        query_module=query_module,
        query_detail=query_detail,
    )
    # Does ANY node own the queried scope in a DIFFERENT module? (rule 5 guard)
    cross_module_authority = _cross_module_authority_exists(graph, ctx)

    ranked: list[RankedHit] = []
    for hit_index, hit in enumerate(hits):
        concept_id, base = _strict_hit(hit)
        node = graph.node(concept_id)
        if node is None:
            ranked.append(
                RankedHit(
                    concept_id,
                    base,
                    _normalised(base),
                    ("no-graph-node",),
                    tier=TIER_ORDINARY,
                    hit_index=hit_index,
                )
            )
            continue
        ranked.append(_rank_known_node(graph, node, base, ctx, cross_module_authority, hit_index))
    ranked.sort(key=lambda r: (r.tier, -r.authority_score, -r.score, r.concept_id, r.hit_index))
    return ranked


def _strict_hit(hit: Mapping[str, object]) -> tuple[str, float]:
    """Validate the external retrieval hit without defaults or coercive repair."""
    try:
        concept_id = hit["concept_id"]
        raw_score = hit["score"]
    except KeyError as exc:
        raise ValueError(f"retrieval hit is missing mandatory field {exc.args[0]!r}") from exc
    if not isinstance(concept_id, str) or not concept_id:
        raise ValueError("retrieval hit concept_id must be a non-empty string")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise ValueError("retrieval hit score must be numeric")
    score = float(raw_score)
    if not math.isfinite(score):
        raise ValueError("retrieval hit score must be finite")
    return concept_id, score


def _rank_known_node(
    graph: ConceptGraph,
    node: GraphNode,
    base: float,
    ctx: RankContext,
    cross_module_authority: bool,
    hit_index: int,
) -> RankedHit:
    tier, reasons, owns_scope = _precedence(graph, node, ctx)
    authority = _authority_score(
        node,
        base,
        ctx,
        owns_scope=owns_scope,
        cross_module_authority=cross_module_authority,
        reasons=reasons,
    )
    return RankedHit(
        node.concept_id,
        base,
        authority,
        tuple(reasons),
        tier=tier,
        hit_index=hit_index,
    )


def _precedence(
    graph: ConceptGraph,
    node: GraphNode,
    ctx: RankContext,
) -> tuple[int, list[str], bool]:
    reasons: list[str] = []
    owns_scope = bool(
        ctx.query_authority_scope
        and ctx.query_authority_scope in node.authority_scopes
    )
    if owns_scope:
        tier = TIER_DIRECT_AUTHORITY
        reasons.append("authority_over-direct")
    elif _is_scoped_authority_target(graph, node.concept_id, ctx.query_authority_scope):
        tier = TIER_SCOPED_TARGET
        reasons.append("scoped-authority-target")
    else:
        tier = TIER_ORDINARY
    penalty = _status_tier_penalty(node.status)
    if penalty:
        tier += penalty
        reasons.append(f"status-penalty({node.status})")
    return tier, reasons, owns_scope


def _authority_score(
    node: GraphNode,
    base: float,
    ctx: RankContext,
    *,
    owns_scope: bool,
    cross_module_authority: bool,
    reasons: list[str],
) -> float:
    authority = _normalised(base)
    if node.is_appendix and ctx.query_detail.lower() in _INTERFACE_DETAILS:
        authority += APPENDIX_DETAIL_BOOST
        reasons.append("appendix-interface")
    if (
        ctx.query_module
        and node.module == ctx.query_module
        and not owns_scope
        and not cross_module_authority
    ):
        authority += MODULE_MATCH_BOOST
        reasons.append("module-match")
    return authority


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
    """True if some node OWNS the queried scope in a module != query_module."""
    if not ctx.query_authority_scope:
        return False
    return any(
        ctx.query_authority_scope in node.authority_scopes
        and node.status == "active"
        and (not ctx.query_module or node.module != ctx.query_module)
        for node in graph.nodes.values()
    )


__all__ = [
    "APPENDIX_DETAIL_BOOST",
    "MODULE_MATCH_BOOST",
    "TIER_DIRECT_AUTHORITY",
    "TIER_ORDINARY",
    "TIER_PENALTY_ARCHIVED",
    "TIER_PENALTY_DRAFT",
    "TIER_SCOPED_TARGET",
    "RankContext",
    "RankedHit",
    "derive_query_detail",
    "rank_hits",
]
