"""Core service for backend-owned third-system validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.third_party_models import (
    BranchPluginSelfTestOperation,
    BranchPluginSelfTestRequest,
    ThirdPartyValidationResponse,
)
from agentkit.backend.installer.third_party_errors import (
    ThirdPartyOperationConflictError,
    ThirdPartyServiceUnavailableError,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    AbortedOutcome,
    FreshClaim,
    IdempotencyRequest,
    InFlightOutcome,
    MismatchOutcome,
    ReplayOutcome,
    compute_body_hash,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
    from agentkit.backend.control_plane.third_party_models import ThirdPartyValidationRequest
    from agentkit.backend.installer.third_party_clients import (
        SecretResolver,
        ThirdPartyClientFactory,
    )
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        InflightIdempotencyGuard,
    )

_SELF_TEST_KIND = "branch_plugin_conformance_self_test"


class AsyncExecutor(Protocol):
    """Bounded backend execution seam for long-running self-tests."""

    def submit(self, fn: Callable[[], None]) -> Future[None]: ...


class ThirdPartyPreflightService:
    """Own light validation and the explicit heavy operation lifecycle."""

    def __init__(
        self,
        *,
        resolver: SecretResolver,
        clients: ThirdPartyClientFactory,
        guard: InflightIdempotencyGuard,
        operation_loader: Callable[[str], ControlPlaneOperationRecord | None],
        executor: AsyncExecutor,
    ) -> None:
        self._resolver = resolver
        self._clients = clients
        self._guard = guard
        self._operation_loader = operation_loader
        self._executor = executor

    def validate(self, request: ThirdPartyValidationRequest) -> ThirdPartyValidationResponse:
        """Run synchronous read-only external-system probes."""
        from agentkit.backend.installer.third_party_light import run_light_validation

        return run_light_validation(request, self._resolver, self._clients)

    def validate_idempotent(
        self,
        project_key: str,
        request: ThirdPartyValidationRequest,
        correlation_id: str,
    ) -> ThirdPartyValidationResponse:
        """Persist and replay one synchronous typed validation verdict."""
        identity = _validation_identity(project_key, request, correlation_id)
        outcome = self._guard.claim(identity)
        if isinstance(outcome, ReplayOutcome):
            return ThirdPartyValidationResponse.model_validate(outcome.result_payload)
        if isinstance(outcome, InFlightOutcome):
            raise ThirdPartyOperationConflictError(
                "operation_in_flight", "validation operation is already running"
            )
        if isinstance(outcome, MismatchOutcome):
            raise ThirdPartyOperationConflictError(
                "idempotency_mismatch", "op_id body mismatch"
            )
        if isinstance(outcome, AbortedOutcome):
            raise ThirdPartyOperationConflictError(
                "operation_conflict", "operation is terminal but uncommitted"
            )
        if not isinstance(outcome, FreshClaim):
            raise ThirdPartyServiceUnavailableError("unexpected operation-claim outcome")
        try:
            result = self.validate(request)
        except Exception:
            self._guard.release(identity, outcome)
            raise
        if not self._guard.finalize(identity, outcome, result.model_dump(mode="json")):
            raise ThirdPartyServiceUnavailableError("validation finalize lost its claim")
        return result

    def start_self_test(
        self, project_key: str, request: BranchPluginSelfTestRequest
    ) -> BranchPluginSelfTestOperation:
        """Claim and enqueue the explicit side-effecting conformance operation."""
        identity = _identity(project_key, request)
        outcome = self._guard.claim(identity)
        if isinstance(outcome, ReplayOutcome):
            return BranchPluginSelfTestOperation.model_validate(outcome.result_payload)
        if isinstance(outcome, InFlightOutcome):
            return _accepted(request.op_id)
        if isinstance(outcome, MismatchOutcome):
            raise ThirdPartyOperationConflictError("idempotency_mismatch", "op_id body mismatch")
        if isinstance(outcome, AbortedOutcome):
            raise ThirdPartyOperationConflictError(
                "operation_conflict", "operation is terminal but uncommitted"
            )
        if not isinstance(outcome, FreshClaim):
            raise ThirdPartyServiceUnavailableError("unexpected operation-claim outcome")
        try:
            self._executor.submit(lambda: self._complete_self_test(identity, outcome, request))
        except RuntimeError as exc:
            self._guard.release(identity, outcome)
            raise ThirdPartyServiceUnavailableError("self-test executor unavailable") from exc
        return _accepted(request.op_id)

    def get_self_test_operation(self, op_id: str) -> BranchPluginSelfTestOperation | None:
        """Read a self-test operation without claiming or mutating it."""
        record = self._operation_loader(op_id)
        if record is None or record.operation_kind != _SELF_TEST_KIND:
            return None
        if record.status == "claimed":
            return _accepted(op_id)
        return BranchPluginSelfTestOperation.model_validate(record.response_payload)

    def _complete_self_test(
        self,
        identity: IdempotencyRequest,
        claim: FreshClaim,
        request: BranchPluginSelfTestRequest,
    ) -> None:
        from agentkit.backend.installer.third_party_self_test import (
            execute_branch_plugin_self_test,
        )

        result = execute_branch_plugin_self_test(request, self._resolver, self._clients)
        self._guard.finalize(identity, claim, result.model_dump(mode="json"))


def _identity(project_key: str, request: BranchPluginSelfTestRequest) -> IdempotencyRequest:
    body = request.model_dump(mode="json")
    body["project_key"] = project_key
    return IdempotencyRequest(
        op_id=request.op_id,
        operation_kind=_SELF_TEST_KIND,
        body_hash=compute_body_hash(body),
        project_key=project_key,
    )


def _validation_identity(
    project_key: str,
    request: ThirdPartyValidationRequest,
    correlation_id: str,
) -> IdempotencyRequest:
    body = request.model_dump(mode="json")
    body["project_key"] = project_key
    return IdempotencyRequest(
        op_id=request.op_id,
        operation_kind="third_party_validation",
        body_hash=compute_body_hash(body),
        project_key=project_key,
        correlation_id=correlation_id,
    )


def _accepted(op_id: str) -> BranchPluginSelfTestOperation:
    return BranchPluginSelfTestOperation(op_id=op_id, status="accepted", detail="self-test is running")


__all__ = ["AsyncExecutor", "ThirdPartyPreflightService"]
