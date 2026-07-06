"""GitHub service-identity + ref-protection mechanics (FK-12/FK-15, AG3-147, blood T).

The provider-specific mechanic behind two ``CodeBackendPort`` capabilities the
GitHub adapter backs in AG3-147:

* **Service identity** (FK-15 §15.5.1, AC8): the backend-managed credential
  class used for ``story/*`` writes. It is resolved from a backend-managed
  source (an env-var handle by default) and is a DISTINCT class from the
  personal developer token (``gh auth token`` / ``~/.git-credentials-{owner}``);
  the personal token is never substituted for a ``story/*`` write. The secret
  VALUE never crosses the contract -- only an opaque source handle does.
* **Ref-protection administration** (FK-12 §12.1.3, AC7): the ``gh api`` ruleset
  mechanic that blocks direct developer pushes to ``story/*`` (including
  fast-forward). Encapsulated behind the :class:`RefProtectionAdministrator`
  seam so a unit test injects a scripted double instead of touching live GitHub
  (the sanctioned isolated-unit-test seam, mirroring AG3-146's ``RefReader``).

These are adapter internals (thin ``gh``/env mechanics); the capability model
and decision logic live in the backend ``code_backend`` / ``control_plane``
BCs (CLAUDE.md architecture rule).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agentkit.backend.code_backend.provider_port import (
    RefProtectionResult,
    StoryRefWriteCredentialClass,
    StoryRefWriteCredentialResult,
)

__all__ = [
    "DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR",
    "DEFAULT_SERVICE_BYPASS_ACTOR_TYPE_ENV_VAR",
    "DEFAULT_SERVICE_IDENTITY_ENV_VAR",
    "EnvVarServiceIdentitySource",
    "GhRulesetRefProtectionAdministrator",
    "RefProtectionAdministrator",
    "ServiceIdentitySource",
]

#: The backend-managed env-var handle carrying the GitHub service-identity token.
#: Backend-managed, never committed to the repo/worktree (FK-15 §15.5.1). The
#: handle NAME is public; the token VALUE is the secret and never surfaces.
DEFAULT_SERVICE_IDENTITY_ENV_VAR = "AGENTKIT_GITHUB_SERVICE_TOKEN"

#: GitHub rulesets need an explicit actor entry for the service identity that may
#: bypass ``story/*`` protection. For GitHub Apps this is the app ID with actor
#: type ``Integration``; service-account deployments may configure ``User``.
DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR = "AGENTKIT_GITHUB_SERVICE_BYPASS_ACTOR_ID"
DEFAULT_SERVICE_BYPASS_ACTOR_TYPE_ENV_VAR = (
    "AGENTKIT_GITHUB_SERVICE_BYPASS_ACTOR_TYPE"
)

#: Default per-invocation timeout for the ``gh api`` ruleset subprocess.
_DEFAULT_GH_TIMEOUT_SECONDS = 30

#: The ruleset name AK3 administers for story-ref protection (idempotent by name).
_STORY_REF_RULESET_NAME = "agentkit-story-ref-protection"
_SUPPORTED_BYPASS_ACTOR_TYPES = frozenset({"Integration", "User"})


@runtime_checkable
class ServiceIdentitySource(Protocol):
    """A backend-managed ``story/*`` write-credential source (FK-15 §15.5.1)."""

    def is_available(self) -> bool:
        """Whether a usable backend-managed service credential is configured."""
        ...

    def resolve_write_credential(self) -> StoryRefWriteCredentialResult:
        """Resolve the service-identity credential (never the personal token)."""
        ...


@dataclass(frozen=True)
class EnvVarServiceIdentitySource:
    """Resolve the service identity from a backend-managed env-var handle.

    Attributes:
        env_var: The env-var NAME holding the service token. The name is an
            opaque, non-secret handle; the token value is never returned.
    """

    env_var: str = DEFAULT_SERVICE_IDENTITY_ENV_VAR

    def is_available(self) -> bool:
        """Whether the backend-managed service token env var is set non-empty."""
        return bool(os.environ.get(self.env_var, "").strip())

    def resolve_write_credential(self) -> StoryRefWriteCredentialResult:
        """Resolve the service-identity credential handle (fail-closed).

        Returns ``SERVICE_IDENTITY`` with an opaque ``env:{name}`` handle when
        the backend-managed token is configured; otherwise ``resolved=False``.
        It NEVER returns the personal developer token class -- there is no
        fallback path to the personal token for a ``story/*`` write (AC8).
        """
        if not self.is_available():
            return StoryRefWriteCredentialResult(
                resolved=False,
                credential_class=None,
                credential_ref=None,
                detail=(
                    f"no backend-managed service identity configured (env "
                    f"{self.env_var!r} unset); the personal developer token is "
                    "never substituted for a story/* write (fail-closed)"
                ),
            )
        return StoryRefWriteCredentialResult(
            resolved=True,
            credential_class=StoryRefWriteCredentialClass.SERVICE_IDENTITY,
            credential_ref=f"env:{self.env_var}",
            detail="resolved the backend-managed GitHub service identity",
        )


@runtime_checkable
class RefProtectionAdministrator(Protocol):
    """A ``story/*`` ref-protection administration mechanic (FK-12 §12.1.3)."""

    def is_available(self) -> bool:
        """Whether this administrator can perform real ref-protection work."""
        ...

    def administer(self, ref_pattern: str) -> RefProtectionResult:
        """Administer ref protection for ``ref_pattern`` (fail-closed, no raise)."""
        ...


@dataclass(frozen=True)
class GhRulesetRefProtectionAdministrator:
    """Administer story-ref protection via a ``gh api`` GitHub ruleset (blood T).

    Blocks direct developer pushes to ``story/*`` -- including fast-forward --
    by applying a branch ruleset (``non_fast_forward`` + ``pull_request`` rules).
    Real productive mechanic; fail-closed and never raises. Not exercised against
    live GitHub in CI (like ``repo_probe``'s ``gh`` call) -- unit tests inject a
    scripted :class:`RefProtectionAdministrator` double at the adapter seam.

    Attributes:
        owner: GitHub owner/organisation login (adapter-internal binding).
        repo: GitHub repository name (adapter-internal binding).
        service_source: The backend-managed service identity used to authorise
            the admin call; ref protection needs the service credential, never
            the personal developer token.
        gh_timeout_seconds: Per-invocation timeout for the ``gh api`` subprocess.
    """

    owner: str
    repo: str
    service_source: ServiceIdentitySource
    gh_timeout_seconds: int = _DEFAULT_GH_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        """Whether ``gh`` is installed AND a backend service identity exists."""
        return (
            shutil.which("gh") is not None
            and self.service_source.is_available()
            and self._service_bypass_actor() is not None
        )

    def administer(self, ref_pattern: str) -> RefProtectionResult:
        """Apply the story-ref protection ruleset (fail-closed, never raises)."""
        if not self.is_available():
            return RefProtectionResult(
                ref_pattern=ref_pattern,
                administered=False,
                blocks_direct_developer_push=False,
                blocks_fast_forward=False,
                detail=(
                    "ref-protection administration unavailable (missing gh CLI "
                    "or no backend-managed service identity/bypass actor); caller "
                    "raises the FK-12 §12.1.3 degradation WARNING (never a "
                    "silent pass)"
                ),
            )
        include_ref = f"refs/heads/{ref_pattern}"
        bypass_actor = self._service_bypass_actor()
        if bypass_actor is None:
            return RefProtectionResult(
                ref_pattern=ref_pattern,
                administered=False,
                blocks_direct_developer_push=False,
                blocks_fast_forward=False,
                detail=(
                    "ref-protection administration unavailable: no valid "
                    "service-identity bypass actor configured"
                ),
            )
        payload = self._ruleset_payload(include_ref, bypass_actor=bypass_actor)
        existing_ruleset_id = self._existing_ruleset_id()
        method = "PATCH" if existing_ruleset_id is not None else "POST"
        path = (
            f"repos/{self.owner}/{self.repo}/rulesets/{existing_ruleset_id}"
            if existing_ruleset_id is not None
            else f"repos/{self.owner}/{self.repo}/rulesets"
        )
        try:
            completed = subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "gh", "api", "--method", method,
                    path,
                    "--input", "-",
                ],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.gh_timeout_seconds,
                check=False,
                env={**os.environ, "GH_TOKEN": self._service_token()},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RefProtectionResult(
                ref_pattern=ref_pattern,
                administered=False,
                blocks_direct_developer_push=False,
                blocks_fast_forward=False,
                detail=f"gh api ruleset upsert failed to execute: {exc}",
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return RefProtectionResult(
                ref_pattern=ref_pattern,
                administered=False,
                blocks_direct_developer_push=False,
                blocks_fast_forward=False,
                detail=f"gh api ruleset upsert failed: {stderr or 'non-zero exit'}",
            )
        return RefProtectionResult(
            ref_pattern=ref_pattern,
            administered=True,
            blocks_direct_developer_push=True,
            blocks_fast_forward=True,
            detail=(
                f"upserted story-ref-protection ruleset for {ref_pattern!r} "
                "(blocks direct + fast-forward developer pushes)"
            ),
        )

    def _existing_ruleset_id(self) -> int | None:
        """Return the administered ruleset id when it already exists."""
        try:
            completed = subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "gh", "api", "--method", "GET",
                    f"repos/{self.owner}/{self.repo}/rulesets",
                ],
                capture_output=True,
                text=True,
                timeout=self.gh_timeout_seconds,
                check=False,
                env={**os.environ, "GH_TOKEN": self._service_token()},
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        try:
            raw = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError:
            return None
        rulesets = raw.get("rulesets", []) if isinstance(raw, dict) else raw
        if not isinstance(rulesets, list):
            return None
        for ruleset in rulesets:
            if not isinstance(ruleset, dict):
                continue
            if ruleset.get("name") != _STORY_REF_RULESET_NAME:
                continue
            ruleset_id = ruleset.get("id")
            if isinstance(ruleset_id, int):
                return ruleset_id
        return None

    @staticmethod
    def _ruleset_payload(
        include_ref: str, *, bypass_actor: dict[str, object]
    ) -> str:
        """Build the GitHub ruleset payload for the protected ref pattern."""
        return json.dumps(
            {
                "name": _STORY_REF_RULESET_NAME,
                "target": "branch",
                "enforcement": "active",
                "bypass_actors": [bypass_actor],
                "conditions": {
                    "ref_name": {"include": [include_ref], "exclude": []}
                },
                "rules": [
                    {"type": "non_fast_forward"},
                    {"type": "deletion"},
                    {"type": "pull_request"},
                ],
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _service_bypass_actor() -> dict[str, object] | None:
        """Return the configured GitHub ruleset bypass actor for the service."""
        raw_actor_id = os.environ.get(
            DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR, ""
        ).strip()
        actor_type = os.environ.get(
            DEFAULT_SERVICE_BYPASS_ACTOR_TYPE_ENV_VAR, "Integration"
        ).strip()
        if actor_type not in _SUPPORTED_BYPASS_ACTOR_TYPES:
            return None
        try:
            actor_id = int(raw_actor_id)
        except ValueError:
            return None
        if actor_id <= 0:
            return None
        return {
            "actor_id": actor_id,
            "actor_type": actor_type,
            "bypass_mode": "always",
        }

    def _service_token(self) -> str:
        """Resolve the service token env-var VALUE for the authorised admin call.

        The value is used ONLY to authorise the subprocess and never returned /
        logged (it stays inside the subprocess env).
        """
        credential = self.service_source.resolve_write_credential()
        ref = credential.credential_ref or ""
        if ref.startswith("env:"):
            return os.environ.get(ref.removeprefix("env:"), "")
        return ""
