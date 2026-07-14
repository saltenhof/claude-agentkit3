"""Single-call W3 evaluator and strict parser tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.scope_evaluator import LlmScopeConsistencyEvaluator
from concept_governance.scope_parser import ScopeResponseParseError, parse_scope_response
from concept_governance.scope_sets import build_scope_sets, partition_scope_sets
from concept_governance.vocabulary import load_scope_vocabulary
from tests.unit.tools.concept_governance.helpers import write_doc

if TYPE_CHECKING:
    from pathlib import Path

    from concept_governance.scope_models import ScopePartition


class _OneResponseClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0
        self.roles: list[str] = []

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        self.calls += 1
        self.roles.append(role)
        return self.response


def test_evaluator_makes_exactly_one_call_per_partition(tmp_path: Path) -> None:
    partition = _partition(tmp_path)
    client = _OneResponseClient('{"contradictions":[]}')

    result = LlmScopeConsistencyEvaluator(client, "fixed/v1").evaluate(partition)

    assert result.response.contradictions == ()
    assert client.calls == 1
    assert client.roles == ["concept_scope_consistency"]


def test_unparseable_response_is_not_retried(tmp_path: Path) -> None:
    client = _OneResponseClient("not JSON")

    with pytest.raises(ScopeResponseParseError):
        LlmScopeConsistencyEvaluator(client, "fixed/v1").evaluate(_partition(tmp_path))

    assert client.calls == 1


def test_parser_rejects_llm_verdict_fields() -> None:
    with pytest.raises(ScopeResponseParseError):
        parse_scope_response('{"contradictions":[],"verdict":"PASS"}')


def test_parser_normalizes_escaped_schema_underscores_then_revalidates() -> None:
    raw = (
        '{"contradictions":[{"loci":['
        '{"chunk\\_id":"one","doc":"a.md","anchor":"a","assertion":"first"},'
        '{"chunk\\_id":"two","doc":"b.md","anchor":"b","assertion":"second"}'
        '],"explanation":"conflict"}]}'
    )
    parsed = parse_scope_response(raw)
    assert parsed.contradictions[0].loci[0].chunk_id == "one"


def _partition(tmp_path: Path) -> ScopePartition:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    sets = build_scope_sets(load_chunks(concept), load_scope_vocabulary(concept))
    return partition_scope_sets(sets)[0]
