from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from agentkit.backend.auth.credentials import StrategistCredentialStore

if TYPE_CHECKING:
    from pathlib import Path


def test_empty_installation_has_productive_atomic_password_initialization(tmp_path: Path) -> None:
    store = StrategistCredentialStore(tmp_path / "auth.json")

    result = store.initialize_password("operator-known-secret")

    assert result.username == "admin"
    assert store.path.is_file()
    assert "operator-known-secret" not in store.path.read_text(encoding="utf-8")
def test_project_token_is_prepared_client_side_and_server_record_has_only_hash() -> None:
    tokens = importlib.import_module("agentkit.harness_client.projectedge.credentials")

    prepared = tokens.prepare_project_api_token(project_key="project-a", label="edge")

    assert prepared.plaintext_token.startswith(f"ak3_{prepared.record.token_id}_")
    assert prepared.plaintext_token not in prepared.record.model_dump_json()
    assert len(prepared.record.token_hash) == 64


def test_project_credential_file_is_a_typed_productive_surface(tmp_path: Path) -> None:
    credentials = importlib.import_module("agentkit.harness_client.projectedge.credentials")
    prepared = credentials.prepare_project_api_token(
        project_key="project-a",
        label="edge",
    )
    path = tmp_path / ".agentkit" / "credentials"

    credentials.write_pending_project_credentials(
        path,
        project_key="project-a",
        prepared_token=prepared,
        issuance_op_id="issue-project-a",
    )
    credentials.activate_project_credentials(path)
    loaded = credentials.load_active_project_credentials(path, project_key="project-a")

    assert loaded.project_api_token == prepared.plaintext_token
    assert loaded.status == "active"
