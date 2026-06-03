"""SonarQube Web-API adapter boundary (thin, fail-closed).

Public surface of the ``integrations/sonar`` adapter. Contains no
gate/applicability/green business logic (CLAUDE.md: integrations = thin
adapters); that lives in ``agentkit.verify_system.sonarqube_gate``.
"""

from __future__ import annotations

from agentkit.integrations.sonar.client import (
    SonarApiError,
    SonarClient,
    SonarHttpResponse,
)

__all__ = ["SonarApiError", "SonarClient", "SonarHttpResponse"]
