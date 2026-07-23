"""Authority resolver / ranking policy (FK-13 §13.9.11).

The VectorDB returns semantic hits; authority resolution happens in the app
layer (:class:`ConceptGraphResolver`) with DETERMINISTIC rules + a deterministic
tie-break. Used by ``concept_search`` to rank results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.concept_corpus.graph import ConceptGraph


@dataclass(frozen=True)
class RankedHit:
    """A search hit with its computed authority score and reason."""

    concept_id: str
    score: float
    authority_score: float
    reasons: tuple[str, ...]


def _status_penalty(status: str) -> float:
    """Rule 4: archived/draft get a penalty."""
    if status == "archived":
        return -2.0
    if status == "draft":
        return -1.0
    return 0.0


def rank_hits(
    graph: ConceptGraph,
    hits: Sequence[Mapping[str, object]],
    *,
    query_module: str = "",
) -> list[RankedHit]:
    """Rank semantic hits by the five authority rules + deterministic tie-break.

    Rules (FK-13 §13.9.11):
    1. Direct ``authority_over`` match beats adjacent match.
    2. Scoped deferral beats generic local mention.
    3. Appendix can rank higher than core for interface/test detail.
    4. Archived/draft get a penalty.
    5. Module-match boosts only without stronger cross-module authority.

    Tie-break: higher base score, then lexicographic concept_id (deterministic).
    """
    ranked: list[RankedHit] = []
    for hit in hits:
        concept_id = str(hit.get("concept_id", ""))
        node = graph.node(concept_id)
        raw_score = hit.get("score", 0.0)
        base = float(raw_score) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0.0
        authority = base
        reasons: list[str] = []
        if node is None:
            ranked.append(RankedHit(concept_id, base, authority, ("no-graph-node",)))
            continue
        # Rule 1: direct authority_over match.
        if node.authority_scopes:
            authority += 1.0
            reasons.append("authority_over-direct")
        # Rule 2: scoped deferral.
        if node.defers_to_targets:
            authority += 0.5
            reasons.append("scoped-deferral")
        # Rule 3: appendix interface boost.
        if node.is_appendix:
            authority += 0.3
            reasons.append("appendix-interface")
        # Rule 4: status penalty.
        penalty = _status_penalty(node.status)
        if penalty:
            authority += penalty
            reasons.append(f"status-penalty({node.status})")
        # Rule 5: module-match boost (only without stronger cross-module authority).
        if query_module and node.module == query_module and not node.authority_scopes:
            authority += 0.2
            reasons.append("module-match")
        ranked.append(RankedHit(concept_id, base, authority, tuple(reasons)))
    # Deterministic tie-break: higher authority, then higher base, then concept_id.
    ranked.sort(key=lambda r: (-r.authority_score, -r.score, r.concept_id))
    return ranked


__all__ = ["RankedHit", "rank_hits"]
