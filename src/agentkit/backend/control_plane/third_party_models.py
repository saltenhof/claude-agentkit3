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

    def applicable_systems(self) -> frozenset[str]:
        """Return the systems this request declares as applicable.

        Applicability lives in the request, never in the verdict: a system that
        answers ``SKIPPED`` says nothing about whether it was allowed to skip.
        The three conditions are deliberately not the same one, so they must not
        be guessed:

        * ``sonar`` is applicable exactly when ``sonar.available`` holds
          (``sonar_preflight.check_sonarqube_preconditions``: ``available ==
          false`` is the only skip);
        * ``jenkins`` is applicable exactly when ``ci.available`` holds
          (``ci_preflight.check_ci_preconditions``, same discipline);
        * ``are`` is applicable exactly when ``are.enabled`` holds -- it is
          feature-gated by ``features.are`` and carries no ``available`` field
          at all.

        ``sonar.enabled`` and ``ci.enabled`` are NOT applicability: they gate
        pipeline use, not the precondition probe.

        Returns:
            The subset of :data:`VALIDATED_SYSTEMS` that must be probed.
        """
        applicable: set[str] = set()
        if self.sonar.available:
            applicable.add("sonar")
        if self.ci.available:
            applicable.add("jenkins")
        if self.are.enabled:
            applicable.add("are")
        return frozenset(applicable)


class ThirdPartySystemResult(BaseModel):
    """One external system's fail-closed validation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    system: Literal["sonar", "jenkins", "are"]
    status: Literal["PASS", "FAILED", "SKIPPED"]
    error_code: str | None = None
    detail: str = ""


class ThirdPartyValidationResponse(BaseModel):
    """Aggregate synchronous light-validation verdict.

    The aggregate is not an independent field the producer may choose freely.
    Without the enforcement the contract was fail-open in two ways at once -- a
    verdict could carry ``status="PASS"`` next to a failed system, and it could
    omit a system entirely. The installer reads only the aggregate
    (``runner.py`` ``_run_cp10d_sonarqube``), so either defect turned a failed
    precondition into a green checkpoint.

    Only the fail-open direction is enforced here, because only it is anchored:
    ``installer.invariant.third_party_validation_fails_closed`` requires that a
    failed system produce a visible failed checkpoint. The converse -- an
    aggregate ``FAILED`` must point at a failed system -- is deliberately NOT
    enforced. The same invariant names "an unreachable backend" as a second,
    independent cause of a failed outcome, and the decision record
    ``2026-07-14-third-party-backend-mediation`` section 2 repeats it: "Bei
    Backend- oder Dritt-System-Ausfall bricht der Installer sichtbar
    fail-closed ab". A backend-level failure has no per-system ``FAILED`` to
    point at, so rejecting that verdict would discard an answer the concept
    provides for.

    Applicability is not enforceable here either, and for a structural reason:
    it is stated in the REQUEST, which this model never sees. A system that is
    applicable and answers ``SKIPPED`` is the silent skip the same invariant
    forbids -- see :func:`silently_skipped_systems`, which the consumer applies
    where both request and response are in hand.
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
        if any(result.status == "FAILED" for result in self.systems) and self.status != "FAILED":
            failed = sorted(
                result.system for result in self.systems if result.status == "FAILED"
            )
            raise ValueError(
                f"third-party validation aggregate is {self.status!r} while "
                f"{failed} FAILED -- at least one FAILED system always makes the "
                "aggregate FAILED"
            )
        return self


def silently_skipped_systems(
    request: ThirdPartyValidationRequest,
    response: ThirdPartyValidationResponse,
) -> tuple[str, ...]:
    """Return the applicable systems whose verdict is ``SKIPPED``.

    ``installer.invariant.third_party_validation_fails_closed`` states that "any
    applicable unreachable or invalid third system produces a visible failed
    checkpoint [...]; no dev-side fallback, bypass, or silent skip is legal". An
    applicable system that reports ``SKIPPED`` was never probed, so the verdict
    proves nothing about it -- that is the silent skip, and it is the one
    fail-open path the response model cannot close on its own, because
    applicability is a property of the request.

    Args:
        request: The validation request that declared what is applicable.
        response: The verdict returned for that request.

    Returns:
        The offending system names, sorted; empty when the verdict is complete.
    """
    applicable = request.applicable_systems()
    return tuple(
        sorted(
            result.system
            for result in response.systems
            if result.system in applicable and result.status == "SKIPPED"
        )
    )


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
    "silently_skipped_systems",
]
