"""Bounded concurrent evaluation with deterministic policy aggregation."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError
from concept_governance.chunks import ChunkMetadataError
from concept_governance.evaluator import EvaluationParseError
from concept_governance.evaluator_pool import RoutedEvaluationError
from concept_governance.policy import evaluate_policy
from concept_governance.prompt import PromptVersionError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from concept_ingester.discovery import ConceptChunk

    from concept_governance.models import AuthorityFinding, ChunkClassification
    from concept_governance.port import AuthorityProseEvaluator


class EvaluationRunError(ValueError):
    """Named failure bound to the chunk whose evaluation failed."""

    def __init__(self, code: str, chunk: ConceptChunk, cause: Exception, model: str) -> None:
        super().__init__(str(cause))
        self.code = code
        self.chunk = chunk
        self.model = model


def collect_findings(
    chunks: tuple[ConceptChunk, ...],
    evaluator: AuthorityProseEvaluator,
    vocabulary: tuple[str, ...],
    parallelism: int,
) -> tuple[AuthorityFinding, ...]:
    """Evaluate bounded batches and return policy findings in chunk order."""
    if parallelism < 1:
        raise ValueError("parallelism must be positive")
    findings: list[AuthorityFinding] = []
    known_scopes = frozenset(vocabulary)
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        source = iter(chunks)
        pending: dict[Future[ChunkClassification], ConceptChunk] = {}
        for _ in range(parallelism):
            _submit_next(executor, evaluator, vocabulary, source, pending)
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                chunk = pending.pop(future)
                try:
                    findings.extend(evaluate_policy(chunk, future.result(), known_scopes))
                except RoutedEvaluationError as exc:
                    _raise_run_error(chunk, exc.cause, exc.model)
                except EvaluationParseError as exc:
                    raise EvaluationRunError("EVALUATION_PARSE_FAILURE", chunk, exc, evaluator.model) from exc
                except (LlmClientError, MultiLlmHubError, TimeoutError) as exc:
                    raise EvaluationRunError("EVALUATION_TRANSPORT_FAILURE", chunk, exc, evaluator.model) from exc
                except (ChunkMetadataError, PromptVersionError) as exc:
                    raise EvaluationRunError("DISCOVERY_FAILURE", chunk, exc, evaluator.model) from exc
                _submit_next(executor, evaluator, vocabulary, source, pending)
    return tuple(findings)


def _submit_next(
    executor: ThreadPoolExecutor,
    evaluator: AuthorityProseEvaluator,
    vocabulary: tuple[str, ...],
    source: Iterator[ConceptChunk],
    pending: dict[Future[ChunkClassification], ConceptChunk],
) -> None:
    try:
        chunk = next(source)
    except StopIteration:
        return
    pending[executor.submit(evaluator.evaluate, chunk, vocabulary)] = chunk


def _raise_run_error(chunk: ConceptChunk, cause: Exception, model: str) -> None:
    if isinstance(cause, EvaluationParseError):
        raise EvaluationRunError("EVALUATION_PARSE_FAILURE", chunk, cause, model) from cause
    if isinstance(cause, (LlmClientError, MultiLlmHubError, TimeoutError)):
        raise EvaluationRunError("EVALUATION_TRANSPORT_FAILURE", chunk, cause, model) from cause
    if isinstance(cause, (ChunkMetadataError, PromptVersionError)):
        raise EvaluationRunError("DISCOVERY_FAILURE", chunk, cause, model) from cause
    raise cause
