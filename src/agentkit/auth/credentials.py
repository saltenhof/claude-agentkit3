"""Local strategist password storage.

The default credential file is ``~/.config/agentkit/auth.json`` and can be
overridden with ``AGENTKIT_AUTH_CONFIG``. It stores only an Argon2id password
hash; plaintext passwords never enter repository state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from agentkit.auth.errors import AuthFailedError

if TYPE_CHECKING:
    from agentkit.auth.entities import StrategistCredentials

_AUTH_CONFIG_ENV = "AGENTKIT_AUTH_CONFIG"
_DEFAULT_USERNAME = "strategist"


@dataclass(frozen=True)
class CredentialVerification:
    """Result of a strategist credential check."""

    username: str
    needs_rehash: bool = False


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

    def set_password(self, password: str, *, username: str = _DEFAULT_USERNAME) -> None:
        """Hash and persist a strategist password."""

        payload = {
            "username": username,
            "password_hash": self._password_hasher.hash(password),
            "hash_algorithm": "argon2id",
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        if os.name != "nt":
            self._path.chmod(0o600)

    def verify(self, credentials: StrategistCredentials) -> CredentialVerification:
        """Validate submitted credentials against the local hash."""

        payload = self._load_payload()
        username = str(payload.get("username", _DEFAULT_USERNAME))
        if credentials.username != username:
            raise AuthFailedError("Authentication failed")
        password_hash = payload.get("password_hash")
        if not isinstance(password_hash, str) or not password_hash:
            raise AuthFailedError("Authentication failed")
        try:
            verified = self._password_hasher.verify(password_hash, credentials.password)
        except VerifyMismatchError as exc:
            raise AuthFailedError("Authentication failed") from exc
        if not verified:
            raise AuthFailedError("Authentication failed")
        return CredentialVerification(
            username=username,
            needs_rehash=self._password_hasher.check_needs_rehash(password_hash),
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self._path.exists():
            raise AuthFailedError("Authentication failed")
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthFailedError("Authentication failed") from exc
        if not isinstance(payload, dict):
            raise AuthFailedError("Authentication failed")
        return cast("dict[str, Any]", payload)


def _default_auth_config_path() -> Path:
    configured = os.environ.get(_AUTH_CONFIG_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".config" / "agentkit" / "auth.json"
