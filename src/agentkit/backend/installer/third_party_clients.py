"""Backend composition adapters for third-party preflight clients."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.backend.control_plane.third_party_models import (
        AreValidationConfig,
        CiValidationConfig,
        SonarValidationConfig,
    )
    from agentkit.integration_clients.are import ArePreflightClient
    from agentkit.integration_clients.jenkins import JenkinsClient
    from agentkit.integration_clients.sonar import SonarClient


class SecretResolver(Protocol):
    """Resolve a secret reference inside the backend environment."""

    def resolve(self, reference: str) -> str | None:
        """Resolve one environment-variable reference."""
        ...


class EnvironmentSecretResolver:
    """Production backend environment secret resolver."""

    def resolve(self, reference: str) -> str | None:
        """Resolve via :func:`os.environ.get` in this backend process."""
        return os.environ.get(reference)


class ThirdPartyClientFactory(Protocol):
    """Create thin external-system clients from resolved backend secrets."""

    def sonar(self, config: SonarValidationConfig, token: str) -> SonarClient: ...

    def sonar_permissions(self, config: SonarValidationConfig) -> frozenset[str]: ...

    def jenkins(self, config: CiValidationConfig, token: str) -> JenkinsClient: ...

    def are(self, config: AreValidationConfig, token: str) -> ArePreflightClient: ...


class DefaultThirdPartyClientFactory:
    """Production construction of existing thin integration clients."""

    def sonar(self, config: SonarValidationConfig, token: str) -> SonarClient:
        from agentkit.integration_clients.sonar import SonarClient

        user = config.user or os.environ.get("SONAR_USER", "")
        return SonarClient(config.base_url or "", token, user=user)

    def sonar_permissions(self, config: SonarValidationConfig) -> frozenset[str]:
        user = config.user or os.environ.get("SONAR_USER", "")
        configured = os.environ.get("SONAR_TOKEN_PERMISSIONS", "")
        permissions = {item.strip() for item in configured.split(",") if item.strip()}
        if user.lower() == "admin":
            permissions.add("Administer Issues")
        return frozenset(permissions)

    def jenkins(self, config: CiValidationConfig, token: str) -> JenkinsClient:
        from agentkit.integration_clients.jenkins import JenkinsClient

        user = config.user or os.environ.get("JENKINS_USER", "")
        return JenkinsClient(config.base_url or "", token, user=user)

    def are(self, config: AreValidationConfig, token: str) -> ArePreflightClient:
        from agentkit.integration_clients.are import ArePreflightClient

        return ArePreflightClient(config.base_url or "", token)


__all__ = [
    "DefaultThirdPartyClientFactory",
    "EnvironmentSecretResolver",
    "SecretResolver",
    "ThirdPartyClientFactory",
]
