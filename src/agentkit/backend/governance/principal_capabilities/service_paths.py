"""Official service-path validation for FK-55 capability enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.governance.principal_capabilities.principals import Principal

if TYPE_CHECKING:
    from agentkit.backend.governance.guard_evaluation import HookEvent


@dataclass(frozen=True)
class OfficialServicePath:
    """One attested official service path."""

    service_path: str
    principals: frozenset[Principal]


OFFICIAL_SERVICE_PATHS: tuple[OfficialServicePath, ...] = (
    OfficialServicePath(
        service_path="agentkit run-phase closure",
        principals=frozenset({Principal.PIPELINE_DETERMINISTIC}),
    ),
    OfficialServicePath(
        service_path="agentkit reset-story",
        principals=frozenset({Principal.ADMIN_SERVICE, Principal.HUMAN_CLI}),
    ),
    OfficialServicePath(
        service_path="agentkit split-story",
        principals=frozenset({Principal.ADMIN_SERVICE, Principal.HUMAN_CLI}),
    ),
    OfficialServicePath(
        service_path="agentkit resolve-conflict",
        principals=frozenset({Principal.ADMIN_SERVICE, Principal.HUMAN_CLI}),
    ),
)


def is_official_service_path(event: HookEvent, principal: Principal) -> bool:
    """Return whether ``event`` carries an attested FK-55 official service path.

    The path is read only from structural service attestation fields. Free Bash
    command strings, tool args named ``command``/``cmd`` and prompt content are
    deliberately ignored so an agent cannot spoof the service path by typing the
    same command text.
    """
    raw = event.operation_args.get("service_path")
    if not isinstance(raw, str):
        return False
    service_path = raw.strip()
    if not service_path:
        return False
    return any(
        service_path == official.service_path and principal in official.principals
        for official in OFFICIAL_SERVICE_PATHS
    )


__all__ = [
    "OFFICIAL_SERVICE_PATHS",
    "OfficialServicePath",
    "is_official_service_path",
]
