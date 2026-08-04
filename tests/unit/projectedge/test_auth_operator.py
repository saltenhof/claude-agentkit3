from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest

from agentkit.harness_client.projectedge.auth_operator import (
    provision_project_credentials,
    revoke_project_token,
)
from agentkit.harness_client.projectedge.credentials import (
    CredentialInvalidError,
    CredentialMissingError,
    CredentialStateError,
    load_active_project_credentials,
    load_project_credentials,
    pending_project_credentials_path,
    project_credentials_path,
)
from agentkit.harness_client.projectedge.private_files import atomic_write_private_text

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        del headers, timeout
        self.calls.append((method, path, payload))
        return {"status": "committed", "token": {"token_id": "unexpected"}}


class _EchoTokenTransport(_RecordingTransport):
    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        del headers, timeout
        self.calls.append((method, path, payload))
        assert payload is not None
        if method == "DELETE":
            return {"status": "committed"}
        return {"status": "committed", "token": {"token_id": payload["token_id"]}}


class _LoseFirstResponseTransport(_EchoTokenTransport):
    def __init__(self) -> None:
        super().__init__()
        self._lose_response = True

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        if self._lose_response:
            self._lose_response = False
            del headers, timeout
            self.calls.append((method, path, payload))
            raise OSError("response lost after server commit")
        return super().send(
            method=method,
            path=path,
            payload=payload,
            headers=headers,
            timeout=timeout,
        )


def test_corrupt_pending_credential_fails_closed_without_registration_or_overwrite(
    tmp_path: Path,
) -> None:
    active_path = project_credentials_path(tmp_path)
    pending_path = pending_project_credentials_path(active_path)
    corrupt_content = '{"project_key":"tenant-a","project_api_token":"stranded-secret"}'
    atomic_write_private_text(pending_path, corrupt_content)
    transport = _RecordingTransport()

    with pytest.raises(CredentialInvalidError, match="invalid"):
        provision_project_credentials(
            transport,
            project_root=tmp_path,
            project_key="tenant-a",
            label="edge",
            op_id="must-not-create-another-token",
        )

    assert transport.calls == []
    assert pending_path.read_text(encoding="utf-8") == corrupt_content
    assert not active_path.exists()


def test_invalid_credential_never_retains_plaintext_in_exception_channels(
    tmp_path: Path,
) -> None:
    secret = "stranded-secret"
    path = project_credentials_path(tmp_path)
    atomic_write_private_text(
        path,
        f'{{"project_key":"tenant-a","project_api_token":"{secret}"}}',
    )

    with pytest.raises(CredentialInvalidError) as exc_info:
        load_project_credentials(path)

    error = exc_info.value
    formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    rendered_channels = (str(error), repr(error), formatted)
    assert all(secret not in rendered for rendered in rendered_channels)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_crash_after_active_publication_recovers_without_second_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_path = project_credentials_path(tmp_path)
    pending_path = pending_project_credentials_path(active_path)
    transport = _EchoTokenTransport()
    original_unlink = type(pending_path).unlink
    failures_remaining = 1

    def _fail_first_pending_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failures_remaining
        if path == pending_path and failures_remaining:
            failures_remaining -= 1
            raise OSError("simulated crash boundary")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(pending_path), "unlink", _fail_first_pending_cleanup)
    with pytest.raises(CredentialStateError, match="pending cleanup failed"):
        provision_project_credentials(
            transport,
            project_root=tmp_path,
            project_key="tenant-a",
            label="edge",
            op_id="op-publish-crash",
        )

    published = load_active_project_credentials(active_path, project_key="tenant-a")
    assert pending_path.is_file()
    recovered = provision_project_credentials(
        transport,
        project_root=tmp_path,
        project_key="tenant-a",
        label="edge",
        op_id="op-must-not-register-again",
        replace_active=True,
    )

    assert recovered.status == "already_active"
    assert recovered.token_id == published.token_id
    assert len(transport.calls) == 1
    assert not pending_path.exists()


def test_response_loss_retry_reuses_pending_label_and_complete_request(
    tmp_path: Path,
) -> None:
    transport = _LoseFirstResponseTransport()
    with pytest.raises(OSError, match="response lost"):
        provision_project_credentials(
            transport,
            project_root=tmp_path,
            project_key="tenant-a",
            label="custom-label",
            op_id="op-label-recovery",
        )

    recovered = provision_project_credentials(
        transport,
        project_root=tmp_path,
        project_key="tenant-a",
        label="different-cli-default",
        op_id="ignored-new-op-id",
    )

    assert recovered.status == "active"
    payloads = [call[2] for call in transport.calls]
    assert len(payloads) == 2
    assert all(isinstance(payload, dict) for payload in payloads)
    assert [payload["label"] for payload in payloads if isinstance(payload, dict)] == [
        "custom-label",
        "custom-label",
    ]
    assert [payload["op_id"] for payload in payloads if isinstance(payload, dict)] == [
        "op-label-recovery",
        "op-label-recovery",
    ]


def test_revoking_active_token_removes_its_local_credential(tmp_path: Path) -> None:
    transport = _EchoTokenTransport()
    provisioned = provision_project_credentials(
        transport,
        project_root=tmp_path,
        project_key="tenant-a",
        label="active-edge",
        op_id="op-active-issue",
    )

    revoke_project_token(
        transport,
        project_key="tenant-a",
        token_id=provisioned.token_id,
        op_id="op-active-revoke",
        credential_path=provisioned.credential_path,
    )

    with pytest.raises(CredentialMissingError):
        load_active_project_credentials(
            provisioned.credential_path,
            project_key="tenant-a",
        )
