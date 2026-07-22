"""Authority ranking policy (FK-13 §13.9.11).

Rules (deterministic tie-break by concept_id, then score descending):

1. Direct ``authority_over`` match beats adjacent match
2. Scoped deferral beats generic local mention
3. Appendix may rank higher for interface/test detail than core
4. Archived/draft concepts receive a penalty
5. Module match boosts only without stronger cross-module authority
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class RankedHit:
    """A search hit after authority ranking."""

    hit: dict[str, Any]
    rank_score: float
    reasons: tuple[str, ...]


class ConceptGraphResolver:
    """Deterministic authority ranking over concept search hits."""

    def __init__(self, graph: Mapping[str, Any] | None = None) -> None:
        self._graph = dict(graph or {})
        self._nodes: dict[str, dict[str, Any]] = dict(self._graph.get("nodes") or {})
        self._edges: list[dict[str, Any]] = list(self._graph.get("edges") or [])
        self._authority: dict[str, set[str]] = {}
        for cid, node in self._nodes.items():
            # authority scopes may also be inferred from edges later
            del node  # nodes carry status/module/doc_kind
            self._authority.setdefault(cid, set())
        for edge in self._edges:
            if edge.get("type") == "defers_to":
                # target is authority for scope
                target = str(edge.get("target") or "")
                scope = str(edge.get("scope") or "")
                if target and scope:
                    self._authority.setdefault(target, set()).add(scope)

    def rank(
        self,
        hits: Sequence[Mapping[str, object]],
        *,
        query_scopes: Sequence[str] = (),
        query_module: str = "",
        prefer_appendix_detail: bool = False,
    ) -> list[RankedHit]:
        """Rank hits; returns a new list sorted by rank_score desc, concept_id asc."""
        ranked: list[RankedHit] = []
        scopes = set(query_scopes)
        for raw in hits:
            hit = dict(raw)
            score_raw = hit.get("score")
            base = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
            reasons: list[str] = []
            score = base
            concept_id = str(hit.get("concept_id") or "")
            auth_raw = hit.get("authority_over")
            auth_list = (
                [str(x) for x in auth_raw]
                if isinstance(auth_raw, (list, tuple))
                else []
            )
            authority = set(auth_list) | self._authority.get(concept_id, set())
            module = str(hit.get("module") or "")
            status = str(hit.get("concept_status") or "active")
            is_appendix = bool(hit.get("is_appendix"))

            # Rule 1: direct authority_over match
            if scopes and authority & scopes:
                score += 1.0
                reasons.append("direct_authority")
            elif scopes:
                # adjacent: module or deferral neighborhood
                if module and query_module and module == query_module:
                    score += 0.2
                    reasons.append("adjacent_module")
            # Rule 2: scoped deferral (this hit is a deferral target with scope)
            if scopes and authority & scopes:
                # already boosted; mark scoped deferral preference vs generic
                reasons.append("scoped_deferral")
                score += 0.15
            # Rule 3: appendix for interface/test detail
            if prefer_appendix_detail and is_appendix:
                score += 0.25
                reasons.append("appendix_detail")
            # Rule 4: archived/draft penalty
            if status == "archived":
                score -= 0.5
                reasons.append("archived_penalty")
            elif status == "draft":
                score -= 0.25
                reasons.append("draft_penalty")
            # Rule 5: module match only without stronger cross-module authority
            has_direct = bool(scopes and authority & scopes)
            if query_module and module == query_module and not has_direct:
                score += 0.1
                reasons.append("module_boost")

            ranked.append(
                RankedHit(hit=hit, rank_score=score, reasons=tuple(reasons))
            )

        ranked.sort(
            key=lambda r: (
                -r.rank_score,
                str(r.hit.get("concept_id") or ""),
                str(r.hit.get("section_heading") or ""),
            )
        )
        return ranked


__all__ = [
    "ConceptGraphResolver",
    "RankedHit",
]
