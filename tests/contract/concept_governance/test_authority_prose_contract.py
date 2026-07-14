"""Contract pins for the W2 prompt and strict schemas."""

from __future__ import annotations

import hashlib

import pytest
from concept_governance.baseline import BaselineEntry
from concept_governance.models import PROMPT_VERSION, AuthorityFinding, AuthorityProseResponse
from concept_governance.prompt import PROMPT_PATH, PROMPT_TEMPLATE_SHA256
from pydantic import ValidationError


def test_prompt_version_and_template_hash_are_pinned() -> None:
    assert PROMPT_VERSION == "authority-prose/v1"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(template.encode("utf-8")).hexdigest() == PROMPT_TEMPLATE_SHA256
    assert "has_normative_statements" in template
    assert "assertions" in template
    assert "\\u0022" in template


def test_response_and_baseline_contracts_forbid_extra_keys() -> None:
    with pytest.raises(ValidationError):
        AuthorityProseResponse.model_validate(
            {"has_normative_statements": False, "assertions": [], "verdict": "PASS"}
        )
    with pytest.raises(ValidationError):
        BaselineEntry.model_validate(
            {
                "code": "X", "doc": "d", "anchor": "a", "assertion": "x",
                "scope": "s", "prompt_version": "v1", "model": "m",
                "reason": "specific reason", "prompt_sha256": "forbidden",
            }
        )


def test_finding_and_baseline_key_contract_is_exact() -> None:
    assert set(AuthorityFinding.model_fields) == {
        "code", "doc", "anchor", "assertion", "scope", "prompt_version",
        "model", "prompt_sha256", "message", "severity", "baselined",
    }
    assert set(BaselineEntry.model_fields) == {
        "code", "doc", "anchor", "assertion", "scope", "prompt_version", "model", "reason",
    }
    finding = AuthorityFinding(
        code="UNAUTHORIZED_SCOPE_ASSERTION", doc="d.md", anchor="a", assertion="x",
        scope="lock.lifecycle", prompt_version="authority-prose/v1", model="fixed/v1",
        prompt_sha256="a" * 64, message="unauthorized",
    )
    assert finding.key == (
        "UNAUTHORIZED_SCOPE_ASSERTION", "d.md", "a", "x", "lock.lifecycle",
        "authority-prose/v1", "fixed/v1",
    )
    entry = BaselineEntry(
        code=finding.code, doc=finding.doc, anchor=finding.anchor,
        assertion=finding.assertion, scope=finding.scope,
        prompt_version=finding.prompt_version, model=finding.model,
        reason="Legacy prose remains documented pending its owning concept revision.",
    )
    assert entry.key == finding.key
