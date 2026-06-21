from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.errors import AuthFailedError, ProjectMismatchError
from agentkit.backend.auth.tokens import (
    hash_project_api_token,
    issue_project_api_token,
    validate_project_api_token,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken


class _InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.tokens.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [token for token in self.tokens.values() if token.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.tokens[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        token = self.tokens[token_id]
        assert token.project_key == project_key
        self.tokens[token_id] = token.model_copy(
            update={"revoked_at": datetime(2026, 5, 4, 10, 0, tzinfo=UTC)},
        )


def test_issue_token_persists_hash_and_returns_plaintext_once() -> None:
    repository = _InMemoryTokenRepository()

    issued = issue_project_api_token(
        project_key="tenant-a",
        label="thin-client",
        repository=repository,
    )

    assert issued.plaintext_token.startswith("ak3_")
    assert issued.record.token_hash == hash_project_api_token(issued.plaintext_token)
    assert repository.get(issued.record.token_id) == issued.record


def test_validate_token_enforces_project_and_revocation() -> None:
    repository = _InMemoryTokenRepository()
    issued = issue_project_api_token(
        project_key="tenant-a",
        label="thin-client",
        repository=repository,
    )

    validated = validate_project_api_token(
        plaintext_token=issued.plaintext_token,
        project_key="tenant-a",
        repository=repository,
    )
    assert validated.token_id == issued.record.token_id
    with pytest.raises(ProjectMismatchError):
        validate_project_api_token(
            plaintext_token=issued.plaintext_token,
            project_key="tenant-b",
            repository=repository,
        )
    repository.revoke("tenant-a", issued.record.token_id)
    with pytest.raises(AuthFailedError):
        validate_project_api_token(
            plaintext_token=issued.plaintext_token,
            project_key="tenant-a",
            repository=repository,
        )
