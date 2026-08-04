"""Project API token generation, hashing, and validation."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.auth.entities import ProjectApiToken
from agentkit.backend.auth.errors import AuthFailedError, ProjectMismatchError

if TYPE_CHECKING:
    from agentkit.backend.auth.repository import ProjectApiTokenRepository

_AUTH_FAILED_MESSAGE = "Authentication failed"


def register_prepared_project_api_token(
    *,
    project_key: str,
    label: str,
    token_id: str,
    token_hash: str,
    repository: ProjectApiTokenRepository,
    now: datetime | None = None,
) -> ProjectApiToken:
    """Persist the server-safe half of a client-prepared project API token."""
    record = ProjectApiToken(
        token_id=token_id,
        project_key=project_key,
        label=label,
        token_hash=token_hash,
        created_at=now or datetime.now(UTC),
    )
    repository.insert(record)
    return record


def hash_project_api_token(plaintext_token: str) -> str:
    """Hash a plaintext API token for storage."""

    return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()


def validate_project_api_token(
    *,
    plaintext_token: str,
    project_key: str,
    repository: ProjectApiTokenRepository,
    now: datetime | None = None,
) -> ProjectApiToken:
    """Validate a bearer token and ensure it belongs to the requested project."""

    token_hash = hash_project_api_token(plaintext_token)
    record = repository.get_by_hash(token_hash)
    if record is None or record.revoked_at is not None:
        raise AuthFailedError(_AUTH_FAILED_MESSAGE)
    if record.project_key != project_key:
        raise ProjectMismatchError(_AUTH_FAILED_MESSAGE)
    used_at = now or datetime.now(UTC)
    updated = record.model_copy(update={"last_used_at": used_at})
    repository.mark_used(updated.token_id, used_at=used_at)
    if not hmac.compare_digest(updated.token_hash, token_hash):
        raise AuthFailedError(_AUTH_FAILED_MESSAGE)
    return updated


__all__ = [
    "hash_project_api_token",
    "register_prepared_project_api_token",
    "validate_project_api_token",
]
