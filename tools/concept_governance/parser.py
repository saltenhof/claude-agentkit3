"""Three-stage fail-closed parser for W2 LLM responses."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from concept_governance.models import AuthorityProseResponse, NormativeAssertion


class ResponseParseError(ValueError):
    """Raised when all strict response parsing stages fail."""


def parse_response(raw_response: str) -> AuthorityProseResponse:
    """Run JSON extraction then a strict regex fallback, fail closed."""
    text = raw_response.strip()
    errors: list[str] = []
    for candidate in (text, _fenced_json(text), _embedded_json(text)):
        if candidate is None:
            continue
        try:
            return AuthorityProseResponse.model_validate_json(candidate)
        except ValidationError as exc:
            errors.append(str(exc.errors(include_url=False)))
    normalized = text.replace("\\_", "_")
    if normalized != text:
        try:
            return AuthorityProseResponse.model_validate_json(normalized)
        except ValidationError as exc:
            errors.append(f"normalized JSON: {exc.errors(include_url=False)}")
    try:
        return _regex_response(normalized)
    except (ResponseParseError, ValidationError, json.JSONDecodeError) as exc:
        errors.append(f"regex fallback: {exc}")
    raise ResponseParseError(f"JSON extraction: {'; '.join(errors)}")


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


def _regex_response(text: str) -> AuthorityProseResponse:
    if "{" in text or "}" in text or re.search(r"\b(PASS|ERROR|FAIL)\b", text, re.I):
        raise ResponseParseError("regex fallback rejects JSON fragments and verdict tokens")
    flags = re.findall(r"has_normative_statements[\"']?\s*[:=]\s*(true|false)", text, re.I)
    if len(flags) != 1:
        raise ResponseParseError("expected exactly one has_normative_statements flag")
    has_normative = flags[0].lower() == "true"
    if not has_normative:
        if re.search(r"[\"']?(assertion|scopes)[\"']?\s*[:=]", text, re.I):
            raise ResponseParseError("false classification contains assertion fields")
        return AuthorityProseResponse(has_normative_statements=False, assertions=())
    pattern = re.compile(
        r"[\"']assertion[\"']\s*:\s*[\"']([^\"'\r\n]+)[\"']\s*,\s*"
        r"[\"']scopes[\"']\s*:\s*(\[[^\]\r\n]+\])",
        re.I,
    )
    assertions = tuple(
        NormativeAssertion(assertion=match.group(1), scopes=tuple(json.loads(match.group(2))))
        for match in pattern.finditer(text)
    )
    if not assertions:
        raise ResponseParseError("normative response contains no parseable assertions")
    return AuthorityProseResponse(has_normative_statements=True, assertions=assertions)
