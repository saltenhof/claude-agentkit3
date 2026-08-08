"""Control-plane wire models for third-system installer mediation."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The external systems a light validation always reports on. The set is closed:
#: a verdict that omits one of them says nothing about it, and a preflight that
#: says nothing is not a preflight.
VALIDATED_SYSTEMS: Final = ("sonar", "jenkins", "are")


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
    """Aggregate synchronous light-validation verdict.

    The aggregate is not an independent field the producer may choose freely: it
    is a function of the per-system results, and the model enforces that. Without
    the enforcement the contract was fail-open in two ways at once -- a verdict
    could carry ``status="PASS"`` next to a failed system, and it could omit a
    system entirely. The installer reads only the aggregate
    (``runner.py`` ``_run_cp10d_sonarqube``), so either defect turned a failed
    precondition into a green checkpoint.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    op_id: str
    status: Literal["PASS", "FAILED"]
    error_code: str | None = None
    systems: tuple[ThirdPartySystemResult, ...]

    @model_validator(mode="after")
    def _verdict_is_total_and_fail_closed(self) -> ThirdPartyValidationResponse:
        """Reject an incomplete, ambiguous or self-contradicting verdict.

        Returns:
            The validated response.

        Raises:
            ValueError: When a system is missing or reported twice, or when the
                aggregate status disagrees with the per-system results.
        """
        reported = [result.system for result in self.systems]
        expected = set(VALIDATED_SYSTEMS)
        if len(reported) != len(set(reported)):
            raise ValueError(
                "third-party validation verdict reports a system more than once: "
                f"{sorted(reported)} -- exactly one result per system is required"
            )
        if set(reported) != expected:
            missing = sorted(expected - set(reported))
            raise ValueError(
                "third-party validation verdict is incomplete: no result for "
                f"{missing}. Every system in {list(VALIDATED_SYSTEMS)} must be "
                "reported; a system without a verdict is not a passing system"
            )
        any_failed = any(result.status == "FAILED" for result in self.systems)
        if any_failed and self.status != "FAILED":
            failed = sorted(
                result.system for result in self.systems if result.status == "FAILED"
            )
            raise ValueError(
                f"third-party validation aggregate is {self.status!r} while "
                f"{failed} FAILED -- the aggregate is FAILED if and only if at "
                "least one system FAILED"
            )
        if self.status == "FAILED" and not any_failed:
            raise ValueError(
                "third-party validation aggregate is 'FAILED' while no system "
                "FAILED -- the aggregate is FAILED if and only if at least one "
                "system FAILED"
            )
        return self


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
    "VALIDATED_SYSTEMS",
    "AreValidationConfig",
    "BranchPluginSelfTestOperation",
    "BranchPluginSelfTestRequest",
    "CiValidationConfig",
    "SonarValidationConfig",
    "ThirdPartySystemResult",
    "ThirdPartyValidationRequest",
    "ThirdPartyValidationResponse",
]
