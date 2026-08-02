"""AC1-3 deterministic W2 policy and discovery tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import load_chunks
from concept_governance.evaluator import LlmAuthorityProseEvaluator
from concept_governance.models import PROMPT_VERSION, ChunkClassification, NormativeAssertion
from concept_governance.parser import parse_response
from concept_governance.runner import run_authority_check
from tests.unit.tools.concept_governance.helpers import (
    ScriptedEvaluator,
    ScriptedLlmClient,
    write_doc,
    write_empty_baseline,
)

BACKSLASH = chr(92)
#: A Windows path copied VERBATIM out of a markdown chunk. Inside a JSON
#: string ``\n`` is a RECOGNISED escape, so this is valid JSON that decodes
#: to ``C:`` + newline + ``ew`` — the quote is corrupted with no syntax
#: error anywhere for a parser to catch.
WINDOWS_PATH = "C:" + BACKSLASH + "new"

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _classification(scope: str, model: str = "fixed/v1") -> ChunkClassification:
    return ChunkClassification(
        has_normative_statements=True,
        assertions=(NormativeAssertion(assertion="The system must retain locks.", scopes=(scope,)),),
        prompt_version=PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model=model,
    )


def test_unauthorized_scope_and_scope_qualified_defers_to_counter_probe(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    # An UNQUALIFIED deferral (no scope) in the FK-13 §13.9.6 entry form: it names
    # a target but authorizes no scope, so the assertion stays unauthorized.
    write_doc(concept, "consumer.md", "CONSUMER", "[]", "[{target: OWNER}]")
    write_empty_baseline(baseline)
    evaluator = ScriptedEvaluator(lambda chunk: _classification("lock.lifecycle"))

    first = run_authority_check(concept, baseline, evaluator)

    assert [item.code for item in first.findings] == ["UNAUTHORIZED_SCOPE_ASSERTION"]
    assert first.findings[0].doc == "domain-design/consumer.md"
    assert first.findings[0].anchor == "rule-000"
    assert first.findings[0].assertion == "The system must retain locks."

    write_doc(
        concept,
        "consumer.md",
        "CONSUMER",
        "[]",
        "[{target: OWNER, scope: lock.lifecycle, reason: delegated contract}]",
    )
    second = run_authority_check(concept, baseline, evaluator, parallelism=2)
    assert second.ok
    assert second.findings == ()


def test_unknown_scope_is_named_fail_closed_finding(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)

    result = run_authority_check(
        concept,
        baseline,
        ScriptedEvaluator(lambda chunk: _classification("invented.scope")),
    )

    assert not result.ok
    assert [item.code for item in result.findings] == ["UNKNOWN_SCOPE_MENTION"]


def test_chunk_source_and_findings_are_deterministic_without_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_doc(concept, "consumer.md", "CONSUMER")
    write_empty_baseline(baseline)
    monkeypatch.setenv("AK3_WEAVIATE_HOST", "unreachable.invalid")
    first_chunks = load_chunks(concept)
    second_chunks = load_chunks(concept)
    evaluator = ScriptedEvaluator(lambda chunk: _classification("lock.lifecycle"))

    first = run_authority_check(concept, baseline, evaluator)
    second = run_authority_check(concept, baseline, evaluator)

    assert [item.chunk_id for item in first_chunks] == [item.chunk_id for item in second_chunks]
    assert first.findings == second.findings


def _response(quote_json: str) -> str:
    """Build the exact bytes a model would send for one quoted assertion."""
    return (
        '{"has_normative_statements":true,"assertions":'
        '[{"assertion":' + quote_json + ',"scopes":["lock.lifecycle"]}]}'
    )


def _corpus_quoting(content: str, tmp_path: Path) -> tuple[Path, Path]:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]", content=content)
    write_empty_baseline(baseline)
    return concept, baseline


def test_a_valid_json_escape_corrupts_a_quote_without_any_syntax_error() -> None:
    r"""Why no parser heuristic can prove verbatimness (AG3-179, R3).

    The earlier round repaired INVALID escapes (``\_``, ``\|``, ``\P``)
    so a verbatim quote would survive them. That is not the whole defect
    class: ``C:\new`` copied verbatim out of a chunk is SYNTACTICALLY
    VALID JSON, because ``\n`` is a recognised escape. The raw candidate
    is therefore accepted before any repair runs, and the assertion the
    schema hands on is silently a different string than the chunk holds.

    This test pins the corruption rather than a fix — it is the reason the
    fix has to live in the policy, where the chunk is still available.
    """
    parsed = parse_response(_response('"' + WINDOWS_PATH + '"'))

    assert parsed.assertions[0].assertion == "C:" + chr(10) + "ew"
    assert parsed.assertions[0].assertion != WINDOWS_PATH, "the parser cannot see that the quote drifted"


def test_a_quote_absent_from_the_chunk_is_rejected_fail_closed(tmp_path: Path) -> None:
    """W2 must compare the quote against the chunk, exactly as W3 does.

    The whole productive chain runs: pinned prompt, three-stage parser,
    escape repairs, deterministic policy. Only the transport is scripted,
    so these are the bytes a model really sent.
    """
    concept, baseline = _corpus_quoting(f"The lock file lives at {WINDOWS_PATH}.", tmp_path)
    client = ScriptedLlmClient([_response('"' + WINDOWS_PATH + '"')])

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert not result.ok
    assert result.findings[0].doc == "domain-design/owner.md"
    assert result.findings[0].anchor == "rule-000"
    assert client.calls == 1, "the response PARSED; the defect is only visible after parsing"


def test_a_correctly_escaped_verbatim_quote_stays_accepted(tmp_path: Path) -> None:
    """The counter-probe: the check must not reject a genuine quotation.

    Same chunk, same backslash, same model — only this time the model
    escaped it the way JSON requires. The decoded quote is character-for-
    character the chunk text, so the run passes through to the ordinary
    authorization policy and reports nothing.
    """
    concept, baseline = _corpus_quoting(f"The lock file lives at {WINDOWS_PATH}.", tmp_path)
    client = ScriptedLlmClient([_response('"C:' + BACKSLASH * 2 + 'new"')])

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert result.findings == ()
    assert result.ok


def test_a_paraphrased_assertion_is_rejected_like_a_corrupted_one(tmp_path: Path) -> None:
    """The contract is verbatimness, not escape hygiene.

    A model that summarises instead of quoting produces evidence the corpus
    does not contain — the same defect as a mangled escape, reached without
    a single backslash. One rule covers both.
    """
    concept, baseline = _corpus_quoting("The system must retain locks.", tmp_path)
    client = ScriptedLlmClient([_response('"the system retains locks"')])

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "reported quote is absent" in result.findings[0].message
