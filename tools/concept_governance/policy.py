"""Deterministic W2 authorization policy; the LLM never decides."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import authorization_scopes
from concept_governance.models import AuthorityFinding, ChunkClassification

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk


class EvaluationContractError(ValueError):
    """Raised when a classification does not quote the chunk it evaluated."""


def evaluate_policy(
    chunk: ConceptChunk,
    classification: ChunkClassification,
    vocabulary: frozenset[str],
) -> tuple[AuthorityFinding, ...]:
    """Compare classified scopes with vocabulary and document authority.

    Raises:
        EvaluationContractError: If a reported assertion is not a verbatim
            substring of the evaluated chunk.
    """
    authorized = authorization_scopes(chunk)
    findings: list[AuthorityFinding] = []
    for statement in classification.assertions:
        _require_verbatim_quote(chunk, statement.assertion)
        for scope in sorted(set(statement.scopes)):
            code, message = _violation(scope, vocabulary, authorized)
            if code is None:
                continue
            findings.append(
                AuthorityFinding(
                    code=code,
                    doc=chunk.rel_path,
                    anchor=chunk.section_anchor,
                    assertion=statement.assertion,
                    scope=scope,
                    prompt_version=classification.prompt_version,
                    prompt_sha256=classification.prompt_sha256,
                    model=classification.model,
                    message=message,
                )
            )
    return tuple(findings)


def _require_verbatim_quote(chunk: ConceptChunk, assertion: str) -> None:
    """Reject an assertion that is not literally in the chunk it quotes.

    ``authority-prose/v1`` asks for "ein kurzes woertliches Zitat aus dem
    Abschnitt", and every W2 finding carries that quote as its evidence and
    as part of its baseline key. Nothing enforced it: W2 read the response
    and never looked at the chunk again, so an assertion that had drifted —
    paraphrased by the model, or corrupted by a repair in the parse chain —
    became a finding indistinguishable from a correct one.

    No parser heuristic can close this. ``C:\\new`` copied verbatim out of a
    chunk is SYNTACTICALLY VALID JSON, because ``\\n`` is a recognised
    escape; the raw candidate is accepted before any repair runs and decodes
    to ``C:`` + newline + ``ew``. Only the comparison against the source
    text sees the difference — which is why W3 has done exactly this
    comparison since AG3-159 (``scope_policy._validate_locus``) and W2 now
    does too.

    The check is deliberately identical to W3's: an exact substring test
    against the chunk text that was sent to the model, no normalization of
    whitespace or case. Anything softer would accept a quote that the
    corpus does not contain.

    Args:
        chunk: The chunk that was handed to the evaluator.
        assertion: The quote the evaluator reported.

    Raises:
        EvaluationContractError: If the quote is absent from the chunk.
    """
    if assertion not in chunk.content:
        raise EvaluationContractError(
            f"reported quote is absent from {chunk.rel_path}#{chunk.section_anchor}"
        )


def _violation(
    scope: str,
    vocabulary: frozenset[str],
    authorized: frozenset[str],
) -> tuple[str | None, str]:
    if scope not in vocabulary:
        return "UNKNOWN_SCOPE_MENTION", f"classified scope {scope!r} is outside the live authority vocabulary"
    if scope not in authorized:
        return "UNAUTHORIZED_SCOPE_ASSERTION", f"document has no authority or scope-qualified defers_to edge for {scope!r}"
    return None, ""
