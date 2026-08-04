from __future__ import annotations

import os
import stat
import sys
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.boundary.filesystem import private_files as core_private_files
from agentkit.backend.boundary.filesystem.private_files import inspect_private_file_security
from agentkit.harness_client.projectedge import private_files as edge_private_files
from agentkit.harness_client.projectedge.credentials import (
    activate_project_credentials,
    prepare_project_api_token,
    write_pending_project_credentials,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def test_auth_and_project_token_files_have_measured_owner_only_protection(
    tmp_path: Path,
) -> None:
    auth_path = tmp_path / "auth.json"
    credential_path = tmp_path / "project" / ".agentkit" / "credentials"
    StrategistCredentialStore(auth_path).initialize_password("operator-known-secret")
    prepared = prepare_project_api_token(project_key="project-a", label="edge")
    write_pending_project_credentials(
        credential_path,
        project_key="project-a",
        prepared_token=prepared,
        issuance_op_id="op-file-security",
    )
    activate_project_credentials(credential_path)

    measurements = [
        inspect_private_file_security(auth_path),
        inspect_private_file_security(credential_path),
    ]

    for measured in measurements:
        assert measured.owner_only
        if sys.platform == "win32":
            assert measured.platform == "windows"
            assert measured.owner_sid is not None
            assert measured.access_entry_count == 1
        else:
            assert measured.platform == "posix"
            assert measured.mode == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission reality check")
def test_posix_secret_files_are_created_with_real_mode_0600(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    edge_path = tmp_path / "credentials"

    previous_umask = os.umask(0)
    try:
        core_private_files.atomic_write_private_text(auth_path, "core-secret")
        edge_private_files.atomic_write_private_text(edge_path, "edge-secret")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(auth_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(edge_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("module", [core_private_files, edge_private_files])
def test_failed_permission_measurement_does_not_publish_plaintext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
) -> None:
    destination = tmp_path / f"{module.__name__.replace('.', '-')}.secret"
    destination.write_text("previous-safe-content", encoding="utf-8")
    insecure = module.PrivateFileSecurity(
        platform="windows" if sys.platform == "win32" else "posix",
        owner_only=False,
    )
    monkeypatch.setattr(module, "inspect_private_file_security", lambda _path: insecure)

    with pytest.raises(module.PrivateFileSecurityError):
        module.atomic_write_private_text(destination, "must-never-be-published")

    assert destination.read_text(encoding="utf-8") == "previous-safe-content"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []
