"""Public composition surface for the concept-authority prose check."""

from __future__ import annotations

from concept_governance.git_scope import GitScopeError, changed_concept_docs
from concept_governance.models import AuthorityFinding, AuthorityRunResult, ChunkClassification
from concept_governance.offline import OfflineAuthorityProseEvaluator
from concept_governance.render import render_result
from concept_governance.runner import run_authority_check
from concept_governance.scope_models import ScopeConsistencyFinding, ScopeConsistencyRunResult
from concept_governance.scope_render import render_scope_result
from concept_governance.scope_runner import run_scope_consistency
from concept_governance.scope_transport import build_hub_scope_evaluator
from concept_governance.transport import build_hub_evaluator

__all__ = [
    "AuthorityFinding",
    "AuthorityRunResult",
    "ChunkClassification",
    "GitScopeError",
    "OfflineAuthorityProseEvaluator",
    "ScopeConsistencyFinding",
    "ScopeConsistencyRunResult",
    "build_hub_evaluator",
    "build_hub_scope_evaluator",
    "changed_concept_docs",
    "render_result",
    "render_scope_result",
    "run_authority_check",
    "run_scope_consistency",
]
