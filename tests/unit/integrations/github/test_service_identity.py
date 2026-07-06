"""Unit tests: GitHub service identity + ref-protection capabilities (AG3-147).

Covers AC8 (story/* write credential selection -- never the personal developer
token) and the AC9 basis (ref-protection capability reporting + fail-closed
administration) via the adapter's injectable seams.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    RefProtectionResult,
    StoryRefWriteCredentialClass,
)
from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter
from agentkit.integration_clients.github.service_identity import (
    DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR,
    DEFAULT_SERVICE_BYPASS_ACTOR_TYPE_ENV_VAR,
    DEFAULT_SERVICE_IDENTITY_ENV_VAR,
    EnvVarServiceIdentitySource,
    GhRulesetRefProtectionAdministrator,
)

if TYPE_CHECKING:
    import pytest


@dataclass(frozen=True)
class _ScriptedAdministrator:
    """A scripted ref-protection administrator double (isolated-unit-test seam)."""

    available: bool
    administered: bool

    def is_available(self) -> bool:
        return self.available

    def administer(self, ref_pattern: str) -> RefProtectionResult:
        return RefProtectionResult(
            ref_pattern=ref_pattern,
            administered=self.administered,
            blocks_direct_developer_push=self.administered,
            blocks_fast_forward=self.administered,
            detail="scripted",
        )


class _AvailableServiceIdentity:
    def is_available(self) -> bool:
        return True

    def resolve_write_credential(self) -> object:
        from agentkit.backend.code_backend.provider_port import (
            StoryRefWriteCredentialResult,
        )

        return StoryRefWriteCredentialResult(
            resolved=True,
            credential_class=StoryRefWriteCredentialClass.SERVICE_IDENTITY,
            credential_ref=f"env:{DEFAULT_SERVICE_IDENTITY_ENV_VAR}",
            detail="service",
        )


# ---------------------------------------------------------------------------
# AC8: service-identity credential selection (never the personal token)
# ---------------------------------------------------------------------------


def test_ac8_service_identity_resolves_when_backend_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_SERVICE_IDENTITY_ENV_VAR, "svc-secret-xyz")
    adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")

    credential = adapter.resolve_story_ref_write_credential()

    assert credential.resolved is True
    assert credential.credential_class is StoryRefWriteCredentialClass.SERVICE_IDENTITY
    # The opaque handle is the env-var NAME, never the secret value.
    assert credential.credential_ref == f"env:{DEFAULT_SERVICE_IDENTITY_ENV_VAR}"
    assert "svc-secret-xyz" not in (credential.credential_ref or "")
    assert "svc-secret-xyz" not in credential.detail


def test_ac8_no_service_identity_fails_closed_without_personal_token_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEFAULT_SERVICE_IDENTITY_ENV_VAR, raising=False)
    adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")

    credential = adapter.resolve_story_ref_write_credential()

    assert credential.resolved is False
    # Fail-closed: the personal developer token is NEVER substituted (AC8).
    assert credential.credential_class is not (
        StoryRefWriteCredentialClass.PERSONAL_DEVELOPER_TOKEN
    )
    assert credential.credential_class is None


def test_env_var_source_is_unavailable_for_empty_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEFAULT_SERVICE_IDENTITY_ENV_VAR, "   ")
    source = EnvVarServiceIdentitySource()
    assert source.is_available() is False
    assert source.resolve_write_credential().resolved is False


# ---------------------------------------------------------------------------
# AC9 basis: ref-protection capability + fail-closed administration
# ---------------------------------------------------------------------------


def test_capability_supported_true_when_administrator_available() -> None:
    adapter = GitHubCodeBackendAdapter(
        owner="acme",
        repo="widgets",
        ref_protection_administrator=_ScriptedAdministrator(
            available=True, administered=True
        ),
    )
    assert (
        adapter.capability_supported(
            CodeBackendCapability.REF_PROTECTION_ADMINISTRATION
        )
        is True
    )
    result = adapter.administer_ref_protection("story/*")
    assert result.administered is True
    assert result.blocks_fast_forward is True


def test_capability_supported_false_when_administrator_unavailable() -> None:
    adapter = GitHubCodeBackendAdapter(
        owner="acme",
        repo="widgets",
        ref_protection_administrator=_ScriptedAdministrator(
            available=False, administered=False
        ),
    )
    assert (
        adapter.capability_supported(
            CodeBackendCapability.REF_PROTECTION_ADMINISTRATION
        )
        is False
    )
    # Administration is fail-closed, never raises.
    result = adapter.administer_ref_protection("story/*")
    assert result.administered is False


def test_gh_ruleset_administration_patches_existing_story_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def _run(
        args: list[str],
        *,
        input: str | None = None,  # noqa: A002 - mirrors subprocess.run
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, input))
        if "--method" in args and args[args.index("--method") + 1] == "GET":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    [{"id": 42, "name": "agentkit-story-ref-protection"}]
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(
        "agentkit.integration_clients.github.service_identity.shutil.which",
        lambda _name: "gh",
    )
    monkeypatch.setattr(
        "agentkit.integration_clients.github.service_identity.subprocess.run",
        _run,
    )
    monkeypatch.setenv(DEFAULT_SERVICE_IDENTITY_ENV_VAR, "svc-token")
    monkeypatch.setenv(DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR, "12345")
    monkeypatch.setenv(DEFAULT_SERVICE_BYPASS_ACTOR_TYPE_ENV_VAR, "Integration")
    admin = GhRulesetRefProtectionAdministrator(
        owner="acme", repo="widgets", service_source=_AvailableServiceIdentity()
    )

    result = admin.administer("story/*")

    assert result.administered is True
    assert calls[1][0][calls[1][0].index("--method") + 1] == "PATCH"
    assert calls[1][0][4] == "repos/acme/widgets/rulesets/42"
    assert calls[1][1] is not None
    payload = json.loads(calls[1][1])
    assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/story/*"]
    assert payload["bypass_actors"] == [
        {
            "actor_id": 12345,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    assert all(
        actor["actor_type"] not in {"RepositoryRole", "OrganizationAdmin"}
        for actor in payload["bypass_actors"]
    )


def test_gh_ruleset_administration_requires_service_bypass_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integration_clients.github.service_identity.shutil.which",
        lambda _name: "gh",
    )
    monkeypatch.setenv(DEFAULT_SERVICE_IDENTITY_ENV_VAR, "svc-token")
    monkeypatch.delenv(DEFAULT_SERVICE_BYPASS_ACTOR_ID_ENV_VAR, raising=False)
    admin = GhRulesetRefProtectionAdministrator(
        owner="acme", repo="widgets", service_source=_AvailableServiceIdentity()
    )

    result = admin.administer("story/*")

    assert result.administered is False
    assert "bypass actor" in result.detail
