"""Unit tests for per-Story object-mutation-claim declaration and the K4
wait-decision (AG3-141).

Blood-type A decision logic over an injectable port (no I/O, no database): the
per-Story claim is acquired when the Story object is free and busy when already
held; a busy object returns the deterministic K4 409 + Retry-After decision,
never a wait. The project-scope / lock-set / cross-scope apparatus was removed
as speculative (PO decision, two independent reviews).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane import object_claims as oc

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# ObjectClaimKey / declaration (Rule 13 default (project_key, story_id))
# ---------------------------------------------------------------------------


def test_story_claim_key_is_the_default_declaration() -> None:
    key = oc.story_claim_key("tenant-a", "AG3-100")
    assert key.project_key == "tenant-a"
    assert key.serialization_scope == oc.STORY_SCOPE
    assert key.scope_key == "AG3-100"


@pytest.mark.parametrize(
    ("project_key", "serialization_scope", "scope_key"),
    [
        ("", "story", "AG3-100"),
        ("tenant-a", "story", ""),
        # Project-scope was removed as speculative -> only 'story' is valid now.
        ("tenant-a", "project", "tenant-a"),
        ("tenant-a", "unknown-scope", "AG3-100"),
    ],
)
def test_object_claim_key_rejects_invalid_values(
    project_key: str, serialization_scope: str, scope_key: str
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        oc.ObjectClaimKey(
            project_key=project_key,
            serialization_scope=serialization_scope,
            scope_key=scope_key,
        )


# ---------------------------------------------------------------------------
# format_declared_scope / parse_declared_scope round-trip
# ---------------------------------------------------------------------------


def test_format_declared_scope_pins_the_ag3_138_story_format() -> None:
    #: Pinned wire format (existing contract tests): "project_key:story_id".
    assert (
        oc.format_declared_scope(oc.story_claim_key("tenant-a", "AG3-100"))
        == "tenant-a:AG3-100"
    )


def test_parse_declared_scope_round_trips_a_story() -> None:
    key = oc.story_claim_key("tenant-a", "AG3-100")
    assert oc.parse_declared_scope("tenant-a", oc.format_declared_scope(key)) == key


@pytest.mark.parametrize(
    "declared", [None, "", "other-project:AG3-100", "tenant-a"]
)
def test_parse_declared_scope_returns_none_for_absent_or_foreign(
    declared: str | None,
) -> None:
    #: A legacy/absent declaration, one belonging to a DIFFERENT project, or a
    #: bare project_key (the removed project-scope form) has nothing to release.
    assert oc.parse_declared_scope("tenant-a", declared) is None


# ---------------------------------------------------------------------------
# K4 wait-decision (IMPL-016): 409 + Retry-After, never a blocking wait
# ---------------------------------------------------------------------------


def test_object_claim_conflict_pins_the_k4_wait_contract() -> None:
    conflict = oc.ObjectClaimConflict(key=oc.story_claim_key("tenant-a", "AG3-100"))
    assert conflict.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    assert conflict.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT


def test_retry_after_budget_is_pinned_below_the_frontend_timeout() -> None:
    assert 0 < oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS < 12


# ---------------------------------------------------------------------------
# acquire_story_claim / release_story_claim over a fake per-Story port
# ---------------------------------------------------------------------------


@dataclass
class _FakePort:
    """In-memory per-Story object-claim port: an object PK collision IS the
    serialization -- the Story cannot be acquired while already held (busy),
    and release is ownership-scoped (op_id-CAS).
    """

    held: dict[tuple[str, str, str], str] = field(default_factory=dict)
    release_calls: list[tuple[str, str, str, str]] = field(default_factory=list)

    def acquire_claim(
        self,
        *,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
        backend_instance_id: str,
        instance_incarnation: int,
        acquired_at: datetime,
    ) -> bool:
        del backend_instance_id, instance_incarnation, acquired_at
        key = (project_key, serialization_scope, scope_key)
        if key in self.held:
            return False
        self.held[key] = op_id
        return True

    def release_claim(
        self, project_key: str, serialization_scope: str, scope_key: str, op_id: str
    ) -> bool:
        key = (project_key, serialization_scope, scope_key)
        self.release_calls.append((project_key, serialization_scope, scope_key, op_id))
        if self.held.get(key) != op_id:
            return False
        del self.held[key]
        return True


def _acquire(
    port: _FakePort, key: oc.ObjectClaimKey, op_id: str
) -> oc.ObjectClaimConflict | None:
    return oc.acquire_story_claim(
        port,
        key,
        op_id=op_id,
        backend_instance_id="inst-1",
        instance_incarnation=1,
        now=_NOW,
    )


def test_acquire_story_claim_wins_when_free() -> None:
    port = _FakePort()
    result = _acquire(port, oc.story_claim_key("tenant-a", "AG3-100"), "op-1")
    assert result is None
    assert port.held == {("tenant-a", "story", "AG3-100"): "op-1"}


def test_acquire_story_claim_returns_conflict_when_busy() -> None:
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-holder"

    result = _acquire(port, oc.story_claim_key("tenant-a", "AG3-100"), "op-2")

    assert isinstance(result, oc.ObjectClaimConflict)
    assert result.key == oc.story_claim_key("tenant-a", "AG3-100")
    assert result.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    assert result.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    #: The busy attempt did NOT overwrite the holder.
    assert port.held == {("tenant-a", "story", "AG3-100"): "op-holder"}


def test_different_stories_never_conflict() -> None:
    """AC3: mutations of DIFFERENT stories in the same project never conflict."""
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-1"

    result = _acquire(port, oc.story_claim_key("tenant-a", "AG3-200"), "op-2")

    assert result is None
    assert port.held[("tenant-a", "story", "AG3-200")] == "op-2"


def test_release_story_claim_is_ownership_scoped() -> None:
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-1"

    oc.release_story_claim(
        port, oc.story_claim_key("tenant-a", "AG3-100"), op_id="op-1"
    )
    assert port.held == {}

    #: A release by a DIFFERENT op_id is a no-op (never frees a foreign holder).
    port.held[("tenant-a", "story", "AG3-100")] = "op-1"
    oc.release_story_claim(
        port, oc.story_claim_key("tenant-a", "AG3-100"), op_id="op-foreign"
    )
    assert port.held == {("tenant-a", "story", "AG3-100"): "op-1"}
