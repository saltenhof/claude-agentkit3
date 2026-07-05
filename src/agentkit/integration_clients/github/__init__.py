"""GitHub integration adapter — CodeBackendPort implementation (FK-12 §12.1).

Public API
----------
:class:`agentkit.integration_clients.github.adapter.GitHubCodeBackendAdapter`
implements :class:`agentkit.backend.code_backend.provider_port.CodeBackendPort`
— the ONLY way backend code reaches GitHub (AG3-146 AC1/AC6). The low-level
``gh`` CLI mechanics (``run_gh``/``run_gh_json``/``run_gh_graphql``, token
resolution) in :mod:`agentkit.integration_clients.github.client` are
ADAPTER-INTERNAL: they are no longer re-exported here as a generic "run any
gh command" surface (AG3-146 SOLL-182; import
``agentkit.integration_clients.github.client`` directly if adapter-internal
code within this package needs them).

GitHub is the code backend ONLY (FK-12 §12.1.1): branch / worktree / merge
mechanics via the ``gh`` / ``git`` client. GitHub Issues and Projects are
intentionally NOT exposed — story identity, status and attributes live in the
AK3 Story-Backend (FK-91 §91.2 rule 9), never on a GitHub issue or Project
board.
"""

from __future__ import annotations

from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter

__all__ = [
    "GitHubCodeBackendAdapter",
]
