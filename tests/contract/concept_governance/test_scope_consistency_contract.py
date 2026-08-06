"""Contract pins for W3 prompt, response, P4, and finding schemas."""

from __future__ import annotations

import hashlib

import pytest
from concept_governance.scope_contracts import QuotedAssertion, ScopeConsistencyResponse
from concept_governance.scope_models import SCOPE_PROMPT_VERSION, ScopeConsistencyFinding
from concept_governance.scope_prompt import SCOPE_PROMPT_PATH, SCOPE_PROMPT_TEMPLATE_SHA256
from pydantic import ValidationError


def test_scope_prompt_version_hash_and_no_verdict_contract_are_pinned() -> None:
    assert SCOPE_PROMPT_VERSION == "scope-consistency/v2"
    template = SCOPE_PROMPT_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(template.encode()).hexdigest() == SCOPE_PROMPT_TEMPLATE_SHA256
    assert "contradictions" in template
    assert "source_id" in template
    assert "start_id" in template
    assert "end_id" in template
    assert "Never copy assertion text" in template
    assert "Never return PASS, ERROR" in template


def test_scope_response_forbids_policy_verdict() -> None:
    assert set(QuotedAssertion.model_fields) == {"source_id", "start_id", "end_id"}
    with pytest.raises(ValidationError):
        QuotedAssertion.model_validate(
            {
                "chunk_id": "chunk-1",
                "doc": "a.md",
                "anchor": "rule-000",
                "assertion": "copied text",
            }
        )
    with pytest.raises(ValidationError):
        ScopeConsistencyResponse.model_validate({"contradictions": [], "verdict": "PASS"})


def test_scope_finding_requires_explicit_p4_field_even_when_untriaged() -> None:
    fields = {
        "code": "SCOPE_CONTRADICTION",
        "doc": "manual.md",
        "anchor": "rule-000",
        "assertion": "Manual rebinding is required.",
        "related_loci": [],
        "scope": "lock.lifecycle",
        "prompt_version": SCOPE_PROMPT_VERSION,
        "model": "fixed/v1",
        "message": "contradiction",
    }
    with pytest.raises(ValidationError, match="formalization_check"):
        ScopeConsistencyFinding.model_validate(fields)
    fields["formalization_check"] = None
    assert ScopeConsistencyFinding.model_validate(fields).formalization_check is None
