"""Domain errors for third-party mediation."""

from __future__ import annotations


class ThirdPartyOperationConflictError(RuntimeError):
    """An operation id cannot be accepted under the requested body."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ThirdPartyServiceUnavailableError(RuntimeError):
    """The backend service could not durably start the requested operation."""


__all__ = ["ThirdPartyOperationConflictError", "ThirdPartyServiceUnavailableError"]
