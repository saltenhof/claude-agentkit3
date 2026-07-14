"""Complete sequential W3 sweep execution with fail-closed accounting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError
from concept_governance.scope_parser import ScopeResponseParseError
from concept_governance.scope_policy import ScopeEvaluationContractError, evaluate_scope_policy
from concept_governance.scope_port import BatchScopeConsistencyEvaluator
from concept_governance.scope_prompt import ScopePromptVersionError

if TYPE_CHECKING:
    from concept_governance.scope_models import ScopeConsistencyFinding, ScopePartition
    from concept_governance.scope_port import ScopeConsistencyEvaluator


class ScopeSweepError(ValueError):
    """Named failure with exact partition and completed-call accounting."""

    def __init__(
        self,
        code: str,
        partition: ScopePartition,
        completed: int,
        cause: Exception,
        model: str,
    ) -> None:
        super().__init__(str(cause))
        self.code = code
        self.partition = partition
        self.completed = completed
        self.model = model


def collect_scope_findings(
    partitions: tuple[ScopePartition, ...],
    evaluator: ScopeConsistencyEvaluator,
) -> tuple[ScopeConsistencyFinding, ...]:
    """Evaluate each partition exactly once and return only a complete sweep."""
    findings: list[ScopeConsistencyFinding] = []
    completed = 0
    for partition in partitions:
        try:
            evaluation = evaluator.evaluate(partition)
            findings.extend(evaluate_scope_policy(partition, evaluation))
            if isinstance(evaluator, BatchScopeConsistencyEvaluator):
                evaluator.checkpoint(partition.partition_id)
            completed += 1
        except ScopeResponseParseError as exc:
            raise ScopeSweepError("UNPARSEABLE_RESPONSE", partition, completed, exc, evaluator.model) from exc
        except (LlmClientError, MultiLlmHubError, TimeoutError) as exc:
            raise ScopeSweepError("HUB_UNREACHABLE", partition, completed, exc, evaluator.model) from exc
        except OSError as exc:
            raise ScopeSweepError("DISCOVERY_FAILURE", partition, completed, exc, evaluator.model) from exc
        except (ScopePromptVersionError, ScopeEvaluationContractError) as exc:
            raise ScopeSweepError("INVALID_EVALUATION_RESPONSE", partition, completed, exc, evaluator.model) from exc
    return tuple(findings)
