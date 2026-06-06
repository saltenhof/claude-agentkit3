"""Jenkins CI Remote-API adapter boundary (thin, fail-closed).

Public surface of the ``integrations/jenkins`` adapter (AG3-056 §2.1.1).
Contains no binding/green/applicability business logic (CLAUDE.md:
integrations = thin adapters); that lives in
``agentkit.verify_system.pre_merge_runner``.
"""

from __future__ import annotations

from agentkit.integrations.jenkins.client import (
    JenkinsApiError,
    JenkinsClient,
    JenkinsHttpResponse,
)

__all__ = ["JenkinsApiError", "JenkinsClient", "JenkinsHttpResponse"]
