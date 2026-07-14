"""Deterministic multi-backend routing tests for productive W2 acquisition."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from concept_governance.chunks import load_chunks
from concept_governance.evaluator_pool import RoutedAuthorityProseEvaluator
from concept_governance.models import PROMPT_VERSION, ChunkClassification
from concept_governance.runner import run_authority_check
from concept_governance.transport import MODEL_ENV, build_hub_evaluator
from tests.unit.tools.concept_governance.helpers import write_doc, write_empty_baseline

from agentkit.integration_clients.multi_llm_hub.errors import HubUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from concept_ingester.discovery import ConceptChunk


class _ModelEvaluator:
    def __init__(self, model: str) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        del chunk, vocabulary
        return ChunkClassification(
            has_normative_statements=False,
            assertions=(),
            prompt_version=PROMPT_VERSION,
            prompt_sha256="a" * 64,
            model=self._model,
        )


class _FailEvaluator(_ModelEvaluator):
    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        del chunk, vocabulary
        raise HubUnavailableError("backend unavailable")


def test_chunk_uuid_routes_to_same_backend_family(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    chunk = load_chunks(concept)[0]
    routed = RoutedAuthorityProseEvaluator(
        {model: (_ModelEvaluator(model),) for model in ("chatgpt", "grok", "kimi")},
        ("chatgpt", "grok", "kimi"),
    )

    models = [
        routed.evaluate(replace(chunk, chunk_id=str(uuid.UUID(int=index))), ()).model
        for index in range(3)
    ]

    assert models == ["chatgpt", "grok", "kimi"]


def test_default_pool_uses_stable_non_gemini_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MODEL_ENV, raising=False)
    evaluator = build_hub_evaluator()
    assert evaluator.parallelism == 1
    assert evaluator.model == "chatgpt"


def test_routed_failure_reports_actual_backend(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    routed = RoutedAuthorityProseEvaluator({"grok": (_FailEvaluator("grok"),)}, ("grok",))

    result = run_authority_check(concept, baseline, routed)

    assert result.findings[0].code == "EVALUATION_TRANSPORT_FAILURE"
    assert result.findings[0].model == "grok"
