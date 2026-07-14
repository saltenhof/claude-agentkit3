"""Deterministic W2 authorization policy; the LLM never decides."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import authorization_scopes
from concept_governance.models import AuthorityFinding, ChunkClassification

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk


def evaluate_policy(
    chunk: ConceptChunk,
    classification: ChunkClassification,
    vocabulary: frozenset[str],
) -> tuple[AuthorityFinding, ...]:
    """Compare classified scopes with vocabulary and document authority."""
    authorized = authorization_scopes(chunk)
    findings: list[AuthorityFinding] = []
    for statement in classification.assertions:
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
