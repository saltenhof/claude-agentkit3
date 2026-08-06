"""Local strategist password storage.

The default credential file is ``~/.config/agentkit/auth.json`` and can be
overridden with ``AGENTKIT_AUTH_CONFIG``. It stores only an Argon2id password
hash; plaintext passwords never enter repository state.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import local
from typing import TYPE_CHECKING, BinaryIO, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.backend.auth.errors import (
    AuthFailedError,
    BootstrapAlreadyCompletedError,
    CredentialStateError,
)
from agentkit.backend.boundary.filesystem.private_files import (
    PrivateFileSecurityError,
    atomic_write_private_text,
    inspect_private_file_security,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from agentkit.backend.auth.entities import StrategistCredentials

_AUTH_CONFIG_ENV = "AGENTKIT_AUTH_CONFIG"
_DEFAULT_USERNAME = "admin"
_AUTH_FAILED_MESSAGE = "Authentication failed"
_THREAD_LOCK_STATE = local()


class CredentialVerification(BaseModel):
    """Result of a strategist credential check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    needs_rehash: bool = False


class _StoredStrategistCredential(BaseModel):
    """Closed owner-private representation of the single strategist account."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: Literal["admin"]
    #: ``repr=False``: a model that carries a secret must not reveal it in ANY
    #: representation. Two channels of this same class were already closed --
    #: the HTTP validation response and the Pydantic exception chain -- and both
    #: fixes were per-channel. This is the third: ``repr()`` reaches tracebacks,
    #: logs and telemetry without anyone writing the field out. The value stays
    #: reachable through the attribute; only its DISPLAY is suppressed.
    password_hash: str = Field(min_length=1, pattern=r"^\$argon2id\$", repr=False)
    hash_algorithm: Literal["argon2id"]
    last_rotation_op_id: str | None = Field(default=None, min_length=1)


class StrategistCredentialStore:
    """Read and write the local strategist password hash."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._path = path or _default_auth_config_path()
        self._password_hasher = password_hasher or PasswordHasher()

    @property
    def path(self) -> Path:
        """Return the credential file path."""

        return self._path

    def initialize_password(
        self,
        password: str,
    ) -> CredentialVerification:
        """Atomically establish the one-time strategist password.

        The operator chooses ``password`` before this call, so a process or
        transport failure after publication cannot leave an unknown password.
        Cross-process exclusion is an operating-system file lock; the final
        file appears only through an atomic replace of a complete private file.

        Raises:
            BootstrapAlreadyCompletedError: If a password already exists.
        """
        with self._mutation_lock():
            if self._path.exists():
                raise BootstrapAlreadyCompletedError(
                    "Strategist bootstrap has already completed",
                )
            self._write_password(password)
        return CredentialVerification(username=_DEFAULT_USERNAME)

    def rotate_password(
        self,
        password: str,
        *,
        op_id: str,
        before_publish: Callable[[], None] | None = None,
    ) -> CredentialVerification:
        """Atomically replace an existing strategist password hash."""
        with self._mutation_lock():
            if not self._path.is_file():
                raise CredentialStateError("Strategist password is not configured")
            self._write_password(
                password,
                last_rotation_op_id=op_id,
                before_publish=before_publish,
            )
        return CredentialVerification(username=_DEFAULT_USERNAME)

    def is_configured(self) -> bool:
        """Return whether a complete strategist credential file exists."""
        if not self._path.is_file():
            return False
        try:
            self._load_payload()
        except AuthFailedError:
            return False
        return True

    @contextmanager
    def transition_lock(self) -> Iterator[None]:
        """Serialize one password/session transition across Core processes."""
        with self._mutation_lock():
            yield

    def verify(self, credentials: StrategistCredentials) -> CredentialVerification:
        """Validate submitted credentials against the local hash."""

        payload = self._load_payload()
        return self._verify_payload(payload, credentials)

    def verify_applied_rotation(
        self,
        credentials: StrategistCredentials,
        *,
        op_id: str,
    ) -> CredentialVerification:
        """Verify both the password and the operation marker of one rotation."""
        payload = self._load_payload()
        if payload.last_rotation_op_id != op_id:
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        return self._verify_payload(payload, credentials)

    def session_generation(self) -> str | None:
        """Return the credential generation to which new sessions must bind."""
        return self._load_payload().last_rotation_op_id

    def _verify_payload(
        self,
        payload: _StoredStrategistCredential,
        credentials: StrategistCredentials,
    ) -> CredentialVerification:
        """Verify one already schema-validated credential document."""
        username = payload.username
        if credentials.username != username:
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        password_hash = payload.password_hash
        verification = self._verify_password_hash(password_hash, credentials.password)
        if verification is None:
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        verified, needs_rehash = verification
        if not verified:
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        return CredentialVerification(
            username=username,
            needs_rehash=needs_rehash,
        )

    def _load_payload(self) -> _StoredStrategistCredential:
        if not self._path.exists():
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        payload = self._read_validated_payload()
        if payload is None:
            raise AuthFailedError(_AUTH_FAILED_MESSAGE)
        return payload

    def _read_validated_payload(self) -> _StoredStrategistCredential | None:
        """Read secret-bearing auth state without retaining parser exceptions."""
        try:
            if not inspect_private_file_security(self._path).owner_only:
                return None
            return _StoredStrategistCredential.model_validate_json(
                self._path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, PrivateFileSecurityError):
            return None

    def _verify_password_hash(
        self,
        password_hash: str,
        password: str,
    ) -> tuple[bool, bool] | None:
        """Verify without attaching hash- or password-bearing library errors."""
        try:
            return (
                self._password_hasher.verify(password_hash, password),
                self._password_hasher.check_needs_rehash(password_hash),
            )
        except (InvalidHashError, VerificationError):
            return None

    def _write_password(
        self,
        password: str,
        *,
        last_rotation_op_id: str | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> None:
        # Argon2 hashing is intentionally completed before the commit-near fence:
        # it can be expensive, so a writer that loses its lease while hashing must
        # be rejected before the resulting credential is atomically published.
        payload = _StoredStrategistCredential(
            username=_DEFAULT_USERNAME,
            password_hash=self._password_hasher.hash(password),
            hash_algorithm="argon2id",
            last_rotation_op_id=last_rotation_op_id,
        )
        if before_publish is not None:
            before_publish()
        atomic_write_private_text(
            self._path,
            json.dumps(payload.model_dump(), sort_keys=True),
        )

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        lock_key = str(self._path.resolve())
        depths = _thread_lock_depths()
        if depths.get(lock_key, 0) > 0:
            depths[lock_key] += 1
            try:
                yield
            finally:
                depths[lock_key] -= 1
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_name(f"{self._path.name}.lock")
        with lock_path.open("a+b") as handle:
            _lock_file(handle)
            depths[lock_key] = 1
            try:
                yield
            finally:
                depths.pop(lock_key, None)
                _unlock_file(handle)


def _thread_lock_depths() -> dict[str, int]:
    depths = getattr(_THREAD_LOCK_STATE, "auth_lock_depths", None)
    if depths is None:
        depths = {}
        _THREAD_LOCK_STATE.auth_lock_depths = depths
    return depths


def _default_auth_config_path() -> Path:
    configured = os.environ.get(_AUTH_CONFIG_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".config" / "agentkit" / "auth.json"


def _lock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["CredentialVerification", "StrategistCredentialStore"]
