"""Project API token generation, hashing, and validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.auth.entities import ProjectApiToken
from agentkit.auth.errors import AuthFailedError, ProjectMismatchError

if TYPE_CHECKING:
    from agentkit.auth.repository import ProjectApiTokenRepository

_TOKEN_PREFIX = "ak3"


@dataclass(frozen=True)
class IssuedProjectApiToken:
    """One-time plaintext token issue result."""

    record: ProjectApiToken
    plaintext_token: str


def issue_project_api_token(
    *,
    project_key: str,
    label: str,
    repository: ProjectApiTokenRepository,
    now: datetime | None = None,
) -> IssuedProjectApiToken:
    """Create, hash, persist, and return one project API token."""

    token_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(32)
    plaintext = f"{_TOKEN_PREFIX}_{token_id}_{secret}"
    record = ProjectApiToken(
        token_id=token_id,
        project_key=project_key,
        label=label,
        token_hash=hash_project_api_token(plaintext),
        created_at=now or datetime.now(UTC),
    )
    repository.save(record)
    return IssuedProjectApiToken(record=record, plaintext_token=plaintext)


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
        raise AuthFailedError("Authentication failed")
    if record.project_key != project_key:
        raise ProjectMismatchError("Authentication failed")
    updated = record.model_copy(update={"last_used_at": now or datetime.now(UTC)})
    repository.save(updated)
    if not hmac.compare_digest(updated.token_hash, token_hash):
        raise AuthFailedError("Authentication failed")
    return updated
