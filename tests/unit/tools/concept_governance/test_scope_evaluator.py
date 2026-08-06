"""Single-call W3 evaluator and strict parser tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.scope_evaluator import LlmScopeConsistencyEvaluator
from concept_governance.scope_parser import ScopeResponseParseError, parse_scope_response
from concept_governance.scope_prompt import render_scope_prompt
from concept_governance.scope_sets import build_scope_sets, partition_scope_sets
from concept_governance.transport_retry import EvaluationTransportExhaustedError
from concept_governance.vocabulary import load_scope_vocabulary
from tests.unit.tools.concept_governance.helpers import ScriptedLlmClient, write_doc

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError

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


def test_w3_transport_failure_retries_same_prompt_then_returns_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ScriptedLlmClient(
        [LlmClientError("page not ready"), '{"contradictions":[]}']
    )
    delays: list[float] = []
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", delays.append)

    result = LlmScopeConsistencyEvaluator(client, "gemini").evaluate(_partition(tmp_path))

    assert result.response.contradictions == ()
    assert client.prompts[0] == client.prompts[1]
    assert delays == [5.0]


def test_w3_exhausted_transport_retry_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partition = _partition(tmp_path)
    client = ScriptedLlmClient([LlmClientError("session lost")] * 4)
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", lambda _: None)

    with pytest.raises(EvaluationTransportExhaustedError) as raised:
        LlmScopeConsistencyEvaluator(client, "grok").evaluate(partition)

    assert client.calls == 4
    assert raised.value.backend == "grok"
    assert raised.value.item_kind == "partition"
    assert raised.value.item_id == partition.partition_id
    assert raised.value.attempts == 4


def test_parser_rejects_llm_verdict_fields() -> None:
    with pytest.raises(ScopeResponseParseError):
        parse_scope_response('{"contradictions":[],"verdict":"PASS"}')


def test_parser_normalizes_escaped_schema_underscores_then_revalidates() -> None:
    raw = (
        '{"contradictions":[{"loci":['
        '{"source\\_id":"one","start\\_id":"s000001","end\\_id":"s000002"},'
        '{"source\\_id":"two","start\\_id":"s000003","end\\_id":"s000004"}'
        '],"explanation":"conflict"}]}'
    )
    parsed = parse_scope_response(raw)
    assert parsed.contradictions[0].loci[0].source_id == "one"


def test_w3_prompt_exposes_only_annotated_source_ranges(tmp_path: Path) -> None:
    partition = _partition(tmp_path)

    prompt, _ = render_scope_prompt(partition)
    payload = json.loads(prompt.split("## Evaluation input\n", maxsplit=1)[1])

    assert "assertions" not in payload
    assert set(payload["sources"][0]) == {
        "source_id",
        "doc",
        "anchor",
        "annotated_content",
    }
    assert "<s000000>" in payload["sources"][0]["annotated_content"]


def _partition(tmp_path: Path) -> ScopePartition:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    sets = build_scope_sets(load_chunks(concept), load_scope_vocabulary(concept))
    return partition_scope_sets(sets)[0]


def test_two_keys_for_one_field_end_as_a_named_rejection_in_w3_too() -> None:
    """The same collision, the same named rejection on the W3 side.

    W2 and W3 share ``normalize_schema_keys``; a fix that only one of the
    two gates handles leaves the identical trap in the other.
    """
    backslash = chr(92)
    alias = '"contra' + backslash * 2 + 'dictions"'
    raw = '{"contradictions":[{"loci":[]}],' + alias + ":[]}"

    with pytest.raises(ScopeResponseParseError, match="carries two keys for field 'contradictions'"):
        parse_scope_response(raw)
