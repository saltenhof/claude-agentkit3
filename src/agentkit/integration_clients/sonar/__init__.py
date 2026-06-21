"""SonarQube Web-API adapter boundary (thin, fail-closed).

Public surface of the ``integrations/sonar`` adapter. Contains no
gate/applicability/green business logic (CLAUDE.md: integrations = thin
adapters); that lives in ``agentkit.backend.verify_system.sonarqube_gate``.
"""

from __future__ import annotations

from agentkit.integration_clients.sonar.client import (
    SonarApiError,
    SonarClient,
    SonarHttpResponse,
)

__all__ = ["SonarApiError", "SonarClient", "SonarHttpResponse"]
