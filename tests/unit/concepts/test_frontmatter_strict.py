"""Strict frontmatter negative matrix (AG3-174 AC 10)."""

from __future__ import annotations

import pytest

from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError
from agentkit.backend.concept_catalog.corpus.frontmatter import parse_frontmatter_yaml, split_frontmatter_bytes


def test_invalid_utf8_fails() -> None:
    with pytest.raises(ConceptParseError, match="UTF-8"):
        split_frontmatter_bytes(b"---\n\xff\n---\nbody")


def test_duplicate_keys_fail() -> None:
    yaml_bytes = b"concept_id: A\nconcept_id: B\ntitle: T\nstatus: active\ndoc_kind: core\n"
    with pytest.raises(ConceptParseError, match="duplicate|parseable|YAML"):
        parse_frontmatter_yaml(yaml_bytes)


def test_non_finite_number_fails() -> None:
    yaml_bytes = b"concept_id: A\ntitle: T\nstatus: active\ndoc_kind: core\nscore: .nan\n"
    with pytest.raises(ConceptParseError):
        parse_frontmatter_yaml(yaml_bytes)


def test_wrong_container_type_fails() -> None:
    yaml_bytes = b"- just a list\n"
    with pytest.raises(ConceptParseError, match="mapping"):
        parse_frontmatter_yaml(yaml_bytes)
