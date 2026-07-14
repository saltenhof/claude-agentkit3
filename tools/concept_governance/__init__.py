"""Public composition surface for the concept-authority prose check."""

from __future__ import annotations

from concept_governance.git_scope import GitScopeError, changed_concept_docs
from concept_governance.models import AuthorityFinding, AuthorityRunResult, ChunkClassification
from concept_governance.offline import OfflineAuthorityProseEvaluator
from concept_governance.render import render_result
from concept_governance.runner import run_authority_check
from concept_governance.transport import build_hub_evaluator

__all__ = [
    "AuthorityFinding",
    "AuthorityRunResult",
    "ChunkClassification",
    "GitScopeError",
    "OfflineAuthorityProseEvaluator",
    "build_hub_evaluator",
    "changed_concept_docs",
    "render_result",
    "run_authority_check",
]
