"""Project-configuration vocabulary both machines read (FK-03 §3.1).

Membership follows
``architecture-conformance.symbol_boundary.config_models``. AG3-239 moved the
one symbol its bounded context needs; the remaining ``wire_exported_symbols`` of
that entry (``JenkinsConfig``, ``SonarQubeConfig`` and the SonarQube sub-models,
``SUPPORTED_CONFIG_VERSION``) follow in their owning bounded-context stories.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class TelemetryConfig(BaseModel):
    """Telemetry and web-call budget configuration (FK-03 §3.1, FK-08-019).

    Read on the edge by the hook process to resolve the web-call budget
    thresholds, and owned as configuration by the core.

    Attributes:
        web_call_limit: Hard limit on outbound web calls per story run,
            applicable only for Research-type stories (FK-08-019). Default
            ``200``.
        web_call_warning: Soft warning threshold for outbound web calls
            per story run (FK-08-019). Default ``180``. Must be less than
            ``web_call_limit``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    web_call_limit: int = 200
    web_call_warning: int = 180

    @model_validator(mode="after")
    def _validate_warning_below_limit(self) -> TelemetryConfig:
        """``web_call_warning`` must be less than ``web_call_limit``."""
        if self.web_call_warning >= self.web_call_limit:
            raise ValueError(
                f"telemetry.web_call_warning ({self.web_call_warning}) must be "
                f"less than telemetry.web_call_limit ({self.web_call_limit}) "
                "(FK-08-019)"
            )
        return self


__all__ = ["TelemetryConfig"]
