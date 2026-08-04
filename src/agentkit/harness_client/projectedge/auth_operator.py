"""Official remote operator orchestration for authentication and credentials."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.harness_client.projectedge.credentials import (
    CredentialMissingError,
    CredentialStateError,
    PreparedProjectApiToken,
    ProjectCredentialFile,
    acknowledge_project_token_revocation,
    activate_project_credentials,
    load_active_project_credentials,
    load_pending_project_credentials,
    prepare_project_api_token,
    prepared_token_from_credentials,
    project_credentials_path,
    reconcile_activated_pending_credentials,
    reconcile_pending_for_active_credentials,
    write_pending_project_credentials,
)
from agentkit.harness_client.projectedge.private_files import (
    exclusive_private_file_lock,
)

if TYPE_CHECKING:
    from agentkit.harness_client.projectedge.client import (
        ControlPlaneTransport,
        HttpsJsonTransport,
    )


class ProjectCredentialProvisionResult(BaseModel):
    """Result of crash-safe project credential provisioning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    credential_path: Path
    token_id: str
    project_api_token: str = Field(repr=False)
    superseded_token_id: str | None = None


class IssuedProjectTokenResult(BaseModel):
    """One-time plaintext returned only to the authenticated backend admin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_id: str
    project_api_token: str = Field(repr=False)


def authenticate_strategist(
    transport: HttpsJsonTransport,
    *,
    password: str,
    project_key: str,
) -> HttpsJsonTransport:
    """Create an authenticated cookie/CSRF transport for one operator action."""
    return transport.authenticate_strategist(
        username="admin",
        password=password,
        project_key=project_key,
    )


def provision_project_credentials(
    transport: ControlPlaneTransport,
    *,
    project_root: Path,
    project_key: str,
    label: str,
    op_id: str,
    replace_active: bool = False,
) -> ProjectCredentialProvisionResult:
    """Register and activate one client-generated project token crash-safely.

    A pending credential is written before the server mutation. A retry reuses
    its plaintext, hash, and ``op_id``; a response-loss crash therefore cannot
    strand an unknown token or require direct database/file repair.
    """
    path = project_credentials_path(project_root)
    with exclusive_private_file_lock(path):
        return _provision_project_credentials_locked(
            transport,
            path=path,
            project_key=project_key,
            label=label,
            op_id=op_id,
            replace_active=replace_active,
        )


def _provision_project_credentials_locked(
    transport: ControlPlaneTransport,
    *,
    path: Path,
    project_key: str,
    label: str,
    op_id: str,
    replace_active: bool,
) -> ProjectCredentialProvisionResult:
    """Execute one credential transition while holding its process lock."""
    active, pending = _load_credential_transition(path, project_key=project_key)
    pending, recovered_activation = _reconcile_credential_transition(
        path,
        active=active,
        pending=pending,
        replace_active=replace_active,
    )
    active_result = _active_provision_result(
        path,
        active=active,
        replace_active=replace_active,
        recovered_activation=recovered_activation,
    )
    if active_result is not None:
        return active_result
    if active is not None and active.superseded_token_id is not None:
        raise CredentialStateError(
            "Revoke the previously superseded token before issuing another token",
        )

    prepared, effective_label, effective_op_id = _prepare_credential_issuance(
        path,
        active=active,
        pending=pending,
        project_key=project_key,
        label=label,
        op_id=op_id,
    )
    response = transport.send(
        method="POST",
        path=f"/v1/projects/{project_key}/api-tokens",
        payload={
            "label": effective_label,
            "op_id": effective_op_id,
            "token_id": prepared.record.token_id,
            "token_hash": prepared.record.token_hash,
        },
    )
    token_payload = response.get("token")
    if (
        not isinstance(token_payload, dict)
        or token_payload.get("token_id") != prepared.record.token_id
    ):
        raise RuntimeError("project token registration response is malformed")
    activated = activate_project_credentials(path)
    return _provision_result("active", path=path, credential=activated)


def _load_credential_transition(
    path: Path,
    *,
    project_key: str,
) -> tuple[ProjectCredentialFile | None, ProjectCredentialFile | None]:
    """Load the active and pending sides of one credential transition."""
    try:
        active = load_active_project_credentials(path, project_key=project_key)
    except CredentialMissingError:
        active = None
    try:
        pending = load_pending_project_credentials(path)
    except CredentialMissingError:
        pending = None
    return active, pending


def _reconcile_credential_transition(
    path: Path,
    *,
    active: ProjectCredentialFile | None,
    pending: ProjectCredentialFile | None,
    replace_active: bool,
) -> tuple[ProjectCredentialFile | None, bool]:
    """Reconcile a crash boundary or validate an in-flight rotation."""
    recovered_activation = False
    if active is not None and pending is not None and pending.token_id == active.token_id:
        reconcile_activated_pending_credentials(path, active=active, pending=pending)
        pending = None
        recovered_activation = True
    elif active is not None and pending is not None:
        if pending.superseded_token_id != active.token_id:
            raise CredentialStateError(
                "Active and pending project credentials cannot be reconciled",
            )
        if not replace_active:
            raise CredentialStateError(
                "A pending token rotation must be resumed before using the active credential",
            )
    return pending, recovered_activation


def _active_provision_result(
    path: Path,
    *,
    active: ProjectCredentialFile | None,
    replace_active: bool,
    recovered_activation: bool,
) -> ProjectCredentialProvisionResult | None:
    """Return the terminal active state when no issuance transition is needed."""
    if active is not None and (not replace_active or recovered_activation):
        return _provision_result(
            "already_active",
            path=path,
            credential=active,
        )
    return None


def _prepare_credential_issuance(
    path: Path,
    *,
    active: ProjectCredentialFile | None,
    pending: ProjectCredentialFile | None,
    project_key: str,
    label: str,
    op_id: str,
) -> tuple[PreparedProjectApiToken, str, str]:
    """Create a pending issuance or resume its exact persisted identity."""
    if pending is None:
        prepared = prepare_project_api_token(project_key=project_key, label=label)
        write_pending_project_credentials(
            path,
            project_key=project_key,
            prepared_token=prepared,
            issuance_op_id=op_id,
            superseded_token_id=active.token_id if active is not None else None,
        )
        return prepared, label, op_id
    if pending.project_key != project_key or pending.status != "pending":
        raise CredentialStateError(
            "Existing project credential cannot be resumed for this project",
        )
    if active is None and pending.superseded_token_id is not None:
        raise CredentialStateError(
            "Pending rotation has no matching active project credential",
        )
    prepared = prepared_token_from_credentials(pending)
    effective_op_id = pending.issuance_op_id
    if effective_op_id is None:
        raise CredentialStateError("Pending project credential has no issuance identity")
    return prepared, pending.label, effective_op_id


def _provision_result(
    status: str,
    *,
    path: Path,
    credential: ProjectCredentialFile,
) -> ProjectCredentialProvisionResult:
    """Render one active credential state as a provisioning result."""
    return ProjectCredentialProvisionResult(
        status=status,
        credential_path=path,
        token_id=credential.token_id,
        project_api_token=credential.project_api_token,
        superseded_token_id=credential.superseded_token_id,
    )


def issue_project_token(
    transport: ControlPlaneTransport,
    *,
    project_key: str,
    label: str,
    op_id: str,
    prepared_token: PreparedProjectApiToken | None = None,
) -> IssuedProjectTokenResult:
    """Register one admin-issued project token without writing an Edge file."""
    prepared = prepared_token or prepare_project_api_token(
        project_key=project_key,
        label=label,
    )
    if prepared.record.project_key != project_key or prepared.record.label != label:
        raise CredentialStateError("Prepared project token does not match its issuance request")
    response = transport.send(
        method="POST",
        path=f"/v1/projects/{project_key}/api-tokens",
        payload={
            "label": label,
            "op_id": op_id,
            "token_id": prepared.record.token_id,
            "token_hash": prepared.record.token_hash,
        },
    )
    _require_complete_issuance_confirmation(response, prepared=prepared, project_key=project_key)
    return IssuedProjectTokenResult(
        token_id=prepared.record.token_id,
        project_api_token=prepared.plaintext_token,
    )


def _require_complete_issuance_confirmation(
    response: Mapping[str, object],
    *,
    prepared: PreparedProjectApiToken,
    project_key: str,
) -> None:
    """Fail closed unless the core confirmed every fact the token depends on.

    The plaintext token is shown exactly once (FK-15 §15.10.4). Handing it out
    on an incomplete confirmation is therefore irreversible: the operator walks
    away believing a credential exists, and only its first real use reveals that
    the core never stored a usable record.

    Matching the echoed ``token_id`` alone does not carry that weight -- a
    partially applied write can echo the id it was given while binding the wrong
    project or landing already revoked. Both are checked here, and anything
    unexpected is a hard error rather than a tolerated shape.

    **The stored verifier is deliberately NOT confirmed.** The core excludes
    ``token_hash`` from its response on purpose (``auth/http/routes.py``,
    ``_token_payload``), and echoing a verifier back would be the wrong fix: it
    would turn a write-only value into a readable one. That the core stored the
    right hash is therefore proven by USING the token, not by reading the
    confirmation -- which is exactly what the client-side ``store-token`` path
    does before it persists anything.

    Args:
        response: The core's registration response.
        prepared: The locally prepared token whose plaintext is about to be
            emitted.
        project_key: The project the token is being issued for.

    Raises:
        RuntimeError: If the confirmation is absent, malformed, or contradicts
            any fact of the prepared token.
    """
    token_payload = response.get("token")
    if not isinstance(token_payload, Mapping):
        raise RuntimeError("project token registration returned no token confirmation")
    mismatches = [
        f"{field}={token_payload.get(field)!r} (expected {expected!r})"
        for field, expected in (
            ("token_id", prepared.record.token_id),
            ("project_key", project_key),
        )
        if token_payload.get(field) != expected
    ]
    if token_payload.get("revoked_at") is not None:
        mismatches.append("revoked_at is set on a freshly issued token")
    if mismatches:
        raise RuntimeError(
            "project token registration confirmation is incomplete or contradictory: "
            + "; ".join(mismatches)
        )


def validate_project_token(
    transport: ControlPlaneTransport,
    *,
    project_key: str,
) -> None:
    """Prove a handed-off bearer token with a read-only project request."""
    response = transport.send(
        method="GET",
        path=f"/v1/projects/{project_key}/stories",
    )
    if not isinstance(response.get("stories"), list):
        raise RuntimeError("project token validation response is malformed")


def rotate_strategist_password(
    transport: ControlPlaneTransport,
    *,
    new_password: str,
    op_id: str,
) -> None:
    """Rotate the strategist password and invalidate every active session."""
    response = transport.send(
        method="POST",
        path="/v1/auth/password",
        payload={"new_password": new_password, "op_id": op_id},
    )
    if response.get("status") != "rotated":
        raise RuntimeError("password rotation response did not confirm rotation")


def revoke_project_token(
    transport: ControlPlaneTransport,
    *,
    project_key: str,
    token_id: str,
    op_id: str,
    credential_path: Path | None = None,
) -> None:
    """Revoke one project API token through its authenticated HTTP surface."""
    if credential_path is not None:
        with exclusive_private_file_lock(credential_path):
            _revoke_project_token_locked(
                transport,
                project_key=project_key,
                token_id=token_id,
                op_id=op_id,
                credential_path=credential_path,
            )
        return
    _revoke_project_token_locked(
        transport,
        project_key=project_key,
        token_id=token_id,
        op_id=op_id,
        credential_path=None,
    )


def _revoke_project_token_locked(
    transport: ControlPlaneTransport,
    *,
    project_key: str,
    token_id: str,
    op_id: str,
    credential_path: Path | None,
) -> None:
    """Commit and acknowledge one revocation inside its credential lock."""
    if credential_path is not None:
        active = load_active_project_credentials(
            credential_path,
            project_key=project_key,
        )
        reconcile_pending_for_active_credentials(credential_path, active=active)
    response = transport.send(
        method="DELETE",
        path=f"/v1/projects/{project_key}/api-tokens/{token_id}",
        payload={"op_id": op_id},
    )
    if response.get("status") != "committed":
        raise RuntimeError("project token revocation response did not confirm revocation")
    if credential_path is not None:
        acknowledge_project_token_revocation(credential_path, token_id=token_id)


__all__ = [
    "IssuedProjectTokenResult",
    "ProjectCredentialProvisionResult",
    "authenticate_strategist",
    "issue_project_token",
    "provision_project_credentials",
    "revoke_project_token",
    "rotate_strategist_password",
    "validate_project_token",
]
