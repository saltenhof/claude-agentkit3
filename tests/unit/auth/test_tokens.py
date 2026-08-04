from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.errors import AuthFailedError, ProjectMismatchError
from agentkit.backend.auth.tokens import (
    hash_project_api_token,
    register_prepared_project_api_token,
    validate_project_api_token,
)
from agentkit.harness_client.projectedge.credentials import prepare_project_api_token

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

    def insert(self, token: ProjectApiToken) -> None:
        if token.token_id in self.tokens:
            raise ValueError("duplicate token id")
        self.tokens[token.token_id] = token

    def mark_used(self, token_id: str, *, used_at: datetime) -> None:
        self.tokens[token_id] = self.tokens[token_id].model_copy(
            update={"last_used_at": used_at},
        )

    def revoke(self, project_key: str, token_id: str) -> None:
        token = self.tokens[token_id]
        assert token.project_key == project_key
        self.tokens[token_id] = token.model_copy(
            update={"revoked_at": datetime(2026, 5, 4, 10, 0, tzinfo=UTC)},
        )


def test_client_prepares_plaintext_and_server_persists_only_hash() -> None:
    repository = _InMemoryTokenRepository()

    issued = prepare_project_api_token(
        project_key="tenant-a",
        label="thin-client",
    )
    registered = register_prepared_project_api_token(
        project_key="tenant-a",
        label="thin-client",
        token_id=issued.record.token_id,
        token_hash=issued.record.token_hash,
        repository=repository,
    )

    assert issued.plaintext_token.startswith("ak3_")
    assert issued.record.token_hash == hash_project_api_token(issued.plaintext_token)
    assert repository.get(issued.record.token_id) == registered
    assert issued.plaintext_token not in registered.model_dump_json()


def test_validate_token_enforces_project_and_revocation() -> None:
    repository = _InMemoryTokenRepository()
    issued = prepare_project_api_token(
        project_key="tenant-a",
        label="thin-client",
    )
    repository.insert(issued.record)

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
