"""Control-plane wire models for third-system installer mediation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SonarValidationConfig(BaseModel):
    """Secret-reference-only SonarQube validation configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    available: bool
    enabled: bool
    base_url: str | None = None
    token_env: str | None = None
    user: str = ""
    min_version: str = "26.4"
    branch_plugin_min_version: str = "1.23.0"
    scanner_version: str | None = None


class CiValidationConfig(BaseModel):
    """Secret-reference-only Jenkins validation configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    available: bool
    enabled: bool
    base_url: str | None = None
    token_env: str | None = None
    user: str = ""
    pipeline: str | None = None


class AreValidationConfig(BaseModel):
    """Secret-reference-only ARE validation configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    base_url: str | None = None
    token_env: str | None = None


class ThirdPartyValidationRequest(BaseModel):
    """Synchronous light-validation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    op_id: str = Field(min_length=1)
    sonar: SonarValidationConfig
    ci: CiValidationConfig
    are: AreValidationConfig = AreValidationConfig()


class ThirdPartySystemResult(BaseModel):
    """One external system's fail-closed validation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    system: Literal["sonar", "jenkins", "are"]
    status: Literal["PASS", "FAILED", "SKIPPED"]
    error_code: str | None = None
    detail: str = ""


class ThirdPartyValidationResponse(BaseModel):
    """Aggregate synchronous light-validation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    op_id: str
    status: Literal["PASS", "FAILED"]
    error_code: str | None = None
    systems: tuple[ThirdPartySystemResult, ...]


class BranchPluginSelfTestRequest(BaseModel):
    """Explicit request for the side-effecting conformance self-test."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    op_id: str = Field(min_length=1)
    sonar: SonarValidationConfig
    ci: CiValidationConfig


class BranchPluginSelfTestOperation(BaseModel):
    """Pollable state of one conformance self-test operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    op_id: str
    operation_kind: Literal["branch_plugin_conformance_self_test"] = (
        "branch_plugin_conformance_self_test"
    )
    status: Literal["accepted", "succeeded", "failed"]
    error_code: str | None = None
    detail: str = ""


__all__ = [
    "AreValidationConfig",
    "BranchPluginSelfTestOperation",
    "BranchPluginSelfTestRequest",
    "CiValidationConfig",
    "SonarValidationConfig",
    "ThirdPartySystemResult",
    "ThirdPartyValidationRequest",
    "ThirdPartyValidationResponse",
]
