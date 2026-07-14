"""AC6 transport failure behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.runner import run_authority_check
from tests.unit.tools.concept_governance.helpers import ScriptedEvaluator, write_doc, write_empty_baseline

from agentkit.integration_clients.multi_llm_hub.errors import HubUnavailableError

if TYPE_CHECKING:
    from pathlib import Path


def test_transport_failure_is_named_and_baseline_is_not_mutated(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    before = baseline.read_bytes()
    evaluator = ScriptedEvaluator(
        lambda chunk: (_ for _ in ()).throw(AssertionError(chunk)),
        error=HubUnavailableError("hub unavailable"),
    )

    result = run_authority_check(concept, baseline, evaluator)

    assert not result.ok
    assert [item.code for item in result.findings] == ["EVALUATION_TRANSPORT_FAILURE"]
    assert baseline.read_bytes() == before
