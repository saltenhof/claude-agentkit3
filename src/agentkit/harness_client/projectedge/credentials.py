"""Project-local plaintext token preparation and secure storage."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentkit.harness_client.projectedge.private_files import (
    PrivateFileSecurityError,
    atomic_write_private_text,
    exclusive_private_file_lock,
    inspect_private_file_security,
)

PROJECT_CREDENTIALS_RELATIVE_PATH = Path(".agentkit") / "credentials"
_TOKEN_PREFIX = "ak3"


class ProjectCredentialError(RuntimeError):
    """Base class for project-local credential failures."""


class CredentialStateError(ProjectCredentialError):
    """A project credential exists but cannot safely join the lifecycle."""


class CredentialMissingError(ProjectCredentialError):
    """A project credential file is absent."""


class CredentialInvalidError(CredentialStateError):
    """A project credential file has invalid content or lifecycle state."""


class CredentialSecurityError(CredentialStateError):
    """A project credential lacks verifiable owner-only protection."""


class ProjectMismatchError(ProjectCredentialError):
    """Project credential material belongs to another project."""


class PreparedProjectApiTokenRecord(BaseModel):
    """Server-safe fields of one client-prepared project token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    token_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class PreparedProjectApiToken(BaseModel):
    """Client plaintext token paired with its server-safe record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: PreparedProjectApiTokenRecord
    plaintext_token: str = Field(min_length=1, repr=False)


def prepare_project_api_token(
    *,
    project_key: str,
    label: str,
    now: datetime | None = None,
) -> PreparedProjectApiToken:
    """Generate a project token locally without exposing plaintext to Core."""
    token_id = uuid.uuid4().hex
    plaintext = f"{_TOKEN_PREFIX}_{token_id}_{secrets.token_urlsafe(32)}"
    return PreparedProjectApiToken(
        record=PreparedProjectApiTokenRecord(
            token_id=token_id,
            project_key=project_key,
            label=label,
            token_hash=hash_project_api_token(plaintext),
            created_at=now or datetime.now(UTC),
        ),
        plaintext_token=plaintext,
    )


class ProjectCredentialFile(BaseModel):
    """Crash-recoverable client-side project API token materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    token_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    project_api_token: str = Field(min_length=1, repr=False)
    issuance_op_id: str | None = Field(default=None, min_length=1)
    status: Literal["pending", "active"]
    superseded_token_id: str | None = None

    @model_validator(mode="after")
    def require_pending_issuance_identity(self) -> Self:
        """Require recovery identity only for an in-flight server issuance."""
        if self.status == "pending" and self.issuance_op_id is None:
            raise ValueError("Pending project credentials require an issuance operation id")
        return self


def project_credentials_path(project_root: Path) -> Path:
    """Return the dedicated project credential file path."""
    return project_root / PROJECT_CREDENTIALS_RELATIVE_PATH


def pending_project_credentials_path(path: Path) -> Path:
    """Return the crash-recovery sidecar for an active credential path."""
    return path.with_name(f"{path.name}.pending")


def write_pending_project_credentials(
    path: Path,
    *,
    project_key: str,
    prepared_token: PreparedProjectApiToken,
    issuance_op_id: str,
    superseded_token_id: str | None = None,
) -> ProjectCredentialFile:
    """Persist a prepared token before its server registration starts.

    This order closes the response-loss gap: after a crash, the same plaintext,
    hash, and client-supplied operation id can be submitted again and the server
    replay completes without minting or losing a second token.
    """
    if prepared_token.record.project_key != project_key:
        raise ProjectMismatchError("Prepared token belongs to another project")
    credential = ProjectCredentialFile(
        project_key=project_key,
        token_id=prepared_token.record.token_id,
        label=prepared_token.record.label,
        project_api_token=prepared_token.plaintext_token,
        issuance_op_id=issuance_op_id,
        status="pending",
        superseded_token_id=superseded_token_id,
    )
    _write_project_credentials(pending_project_credentials_path(path), credential)
    return credential


def activate_project_credentials(path: Path) -> ProjectCredentialFile:
    """Atomically mark a successfully registered pending token active."""
    pending_path = pending_project_credentials_path(path)
    credential = load_project_credentials(pending_path)
    active = credential.model_copy(update={"status": "active"})
    _write_project_credentials(path, active)
    _remove_activated_pending(pending_path)
    return active


def store_active_project_credentials(
    path: Path,
    *,
    project_key: str,
    project_api_token: str,
    label: str,
    replace_active: bool = False,
) -> ProjectCredentialFile:
    """Store an already-issued token without performing strategist authentication.

    The caller proves the token against Core before invoking this filesystem
    transition. This owner only validates the closed token format and publishes
    the active credential with measured owner-only protection.
    """
    token_id = project_api_token_id(project_api_token)
    with exclusive_private_file_lock(path):
        pending_path = pending_project_credentials_path(path)
        if pending_path.exists():
            raise CredentialStateError(
                "A pending project credential must be resolved before storing a handed-off token",
            )
        if path.exists():
            active = load_active_project_credentials(path, project_key=project_key)
            if not replace_active:
                raise CredentialStateError(
                    "An active project credential already exists; request explicit replacement",
                )
            if active.token_id == token_id:
                return active
        credential = ProjectCredentialFile(
            project_key=project_key,
            token_id=token_id,
            label=label,
            project_api_token=project_api_token,
            status="active",
        )
        _write_project_credentials(path, credential)
        return load_active_project_credentials(path, project_key=project_key)


def reconcile_activated_pending_credentials(
    path: Path,
    *,
    active: ProjectCredentialFile,
    pending: ProjectCredentialFile,
) -> None:
    """Remove only the exact pending sidecar already published as ``active``.

    Publication and sidecar cleanup cannot be one filesystem transaction.  A
    crash between them leaves both files.  That state is recoverable only when
    every lifecycle field identifies the same issuance; any disagreement is an
    ambiguous credential state and remains fail-closed.
    """
    if pending.model_copy(update={"status": "active"}) != active:
        raise CredentialStateError(
            "Active and pending project credentials describe different issuances",
        )
    _remove_activated_pending(pending_project_credentials_path(path))


def reconcile_pending_for_active_credentials(
    path: Path,
    *,
    active: ProjectCredentialFile,
) -> None:
    """Remove an exact crash sidecar or reject every ambiguous pending state.

    Runtime and installer entry points must not silently use an active token while
    a different pending issuance exists.  An absent sidecar is normal; an exact
    duplicate is the recoverable post-publication crash state; every other
    present state remains fail-closed.
    """
    try:
        pending = load_pending_project_credentials(path)
    except CredentialMissingError:
        return
    reconcile_activated_pending_credentials(path, active=active, pending=pending)


def load_reconciled_active_project_credentials(
    path: Path,
    *,
    project_key: str,
) -> ProjectCredentialFile:
    """Load one usable active credential under the lifecycle process lock."""
    with exclusive_private_file_lock(path):
        active = load_active_project_credentials(path, project_key=project_key)
        reconcile_pending_for_active_credentials(path, active=active)
        return active


def _remove_activated_pending(pending_path: Path) -> None:
    try:
        pending_path.unlink()
    except OSError as exc:
        raise CredentialStateError(
            "Active credential was published but pending cleanup failed; retry recovery",
        ) from exc


def load_project_credentials(path: Path) -> ProjectCredentialFile:
    """Load and cryptographically self-check one project credential file."""
    if not path.is_file():
        raise CredentialMissingError(f"Project credential file is missing: {path}")
    try:
        security = inspect_private_file_security(path)
    except PrivateFileSecurityError as exc:
        raise CredentialSecurityError(
            f"Project credential file protection cannot be verified: {path}",
        ) from exc
    if not security.owner_only:
        raise CredentialSecurityError(f"Project credential file is not owner-only: {path}")
    credential = _read_validated_project_credential(path)
    if credential is None:
        raise CredentialInvalidError(f"Project credential file is invalid: {path}")
    expected_prefix = f"ak3_{credential.token_id}_"
    if not credential.project_api_token.startswith(expected_prefix):
        raise CredentialInvalidError("Project credential token id does not match its plaintext")
    return credential


def load_pending_project_credentials(path: Path) -> ProjectCredentialFile:
    """Load the pending sidecar associated with an active credential path."""
    credential = load_project_credentials(pending_project_credentials_path(path))
    if credential.status != "pending":
        raise CredentialInvalidError("Pending project credential has an invalid state")
    return credential


def acknowledge_project_token_revocation(path: Path, *, token_id: str) -> None:
    """Apply a confirmed revocation to the matching local credential state."""
    credential = load_project_credentials(path)
    if credential.status != "active":
        raise CredentialInvalidError("Project credential is not active")
    if credential.token_id == token_id:
        try:
            path.unlink()
        except OSError as exc:
            raise CredentialStateError(
                "Active token was revoked but local credential cleanup failed; retry",
            ) from exc
        return
    if credential.superseded_token_id != token_id:
        return
    _write_project_credentials(
        path,
        credential.model_copy(update={"superseded_token_id": None}),
    )


def load_active_project_credentials(
    path: Path,
    *,
    project_key: str,
) -> ProjectCredentialFile:
    """Load an active credential for exactly ``project_key``."""
    credential = load_project_credentials(path)
    if credential.project_key != project_key:
        raise ProjectMismatchError("Project credential belongs to another project")
    if credential.status != "active":
        raise CredentialInvalidError(
            "Project credential registration is pending; complete the auth token issue command",
        )
    return credential


def prepared_token_from_credentials(
    credential: ProjectCredentialFile,
) -> PreparedProjectApiToken:
    """Rebuild a pending client preparation for an idempotent retry."""
    record = PreparedProjectApiTokenRecord(
        token_id=credential.token_id,
        project_key=credential.project_key,
        label=credential.label,
        token_hash=hash_project_api_token(credential.project_api_token),
        created_at=datetime.now(UTC),
    )
    return PreparedProjectApiToken(
        record=record,
        plaintext_token=credential.project_api_token,
    )


def _write_project_credentials(path: Path, credential: ProjectCredentialFile) -> None:
    atomic_write_private_text(
        path,
        credential.model_dump_json(exclude_none=True),
    )


def hash_project_api_token(plaintext_token: str) -> str:
    """Return the server-safe SHA-256 digest for a ProjectEdge bearer token."""
    return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()


def project_api_token_id(project_api_token: str) -> str:
    """Extract the opaque token id from one closed-format ProjectEdge token."""
    prefix, separator, remainder = project_api_token.partition("_")
    token_id, second_separator, secret = remainder.partition("_")
    if (
        prefix != _TOKEN_PREFIX
        or separator != "_"
        or second_separator != "_"
        or not token_id
        or not secret
    ):
        raise CredentialInvalidError("Project API token format is invalid")
    return token_id


def _read_validated_project_credential(path: Path) -> ProjectCredentialFile | None:
    """Parse secret-bearing content without retaining parser errors in a chain."""
    try:
        content = path.read_text(encoding="utf-8")
        raw = json.loads(content)
        return ProjectCredentialFile.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


__all__ = [
    "PROJECT_CREDENTIALS_RELATIVE_PATH",
    "CredentialInvalidError",
    "CredentialMissingError",
    "CredentialSecurityError",
    "CredentialStateError",
    "PreparedProjectApiToken",
    "PreparedProjectApiTokenRecord",
    "ProjectCredentialError",
    "ProjectCredentialFile",
    "ProjectMismatchError",
    "acknowledge_project_token_revocation",
    "activate_project_credentials",
    "hash_project_api_token",
    "load_active_project_credentials",
    "load_reconciled_active_project_credentials",
    "load_project_credentials",
    "load_pending_project_credentials",
    "pending_project_credentials_path",
    "prepared_token_from_credentials",
    "prepare_project_api_token",
    "project_api_token_id",
    "project_credentials_path",
    "reconcile_activated_pending_credentials",
    "reconcile_pending_for_active_credentials",
    "store_active_project_credentials",
    "write_pending_project_credentials",
]
