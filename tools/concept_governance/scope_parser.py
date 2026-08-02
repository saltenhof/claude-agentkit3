"""Strict fail-closed JSON parser for W3 contradiction reports."""

from __future__ import annotations

from pydantic import ValidationError

from concept_governance.json_escapes import repair_markdown_escapes
from concept_governance.scope_contracts import ScopeConsistencyResponse


class ScopeResponseParseError(ValueError):
    """Raised when no strict structured W3 response can be extracted."""


def parse_scope_response(raw_response: str) -> ScopeConsistencyResponse:
    """Parse raw, fenced, or embedded JSON and reject every invalid schema."""
    text = raw_response.strip()
    errors: list[str] = []
    for variant in _variants(text):
        for candidate in (variant, _fenced_json(variant), _embedded_json(variant)):
            if candidate is None:
                continue
            try:
                return ScopeConsistencyResponse.model_validate_json(candidate)
            except ValidationError as exc:
                errors.append(str(exc.errors(include_url=False)))
    raise ScopeResponseParseError(f"structured response is invalid: {'; '.join(errors)}")


def _variants(text: str) -> tuple[str, ...]:
    """Return the raw text plus, if it differs, the escape-repaired one.

    W3 reads the same markdown tables as W2, so it hits the same leaked
    markdown escapes; repairing only one of the two gates would leave the
    identical trap in the other.
    """
    normalized = repair_markdown_escapes(text)
    return (text,) if normalized == text else (text, normalized)


def _fenced_json(text: str) -> str | None:
    marker = "```json"
    start = text.lower().find(marker)
    if start < 0:
        return None
    content_start = start + len(marker)
    end = text.find("```", content_start)
    return text[content_start:end].strip() if end >= 0 else None


def _embedded_json(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else None
