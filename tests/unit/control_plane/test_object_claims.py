"""Unit tests for object-mutation-claim declaration, lock-set ordering and the
K4 wait-decision (AG3-141).

Blood-type A decision logic over an injectable port (no I/O, no database):
canonical acquisition order is structurally enforced at construction; the
lock-set orchestration acquires strictly in order and rolls back a partial
acquisition on conflict; a busy object returns the deterministic K4
409 + Retry-After decision, never a wait.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane import object_claims as oc

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# ObjectClaimKey / declaration
# ---------------------------------------------------------------------------


def test_story_claim_key_is_the_default_declaration() -> None:
    key = oc.story_claim_key("tenant-a", "AG3-100")
    assert key.project_key == "tenant-a"
    assert key.serialization_scope == oc.STORY_SCOPE
    assert key.scope_key == "AG3-100"


def test_project_claim_key_scope_key_is_the_project() -> None:
    key = oc.project_claim_key("tenant-a")
    assert key.serialization_scope == oc.PROJECT_SCOPE
    assert key.scope_key == "tenant-a"


@pytest.mark.parametrize(
    ("project_key", "serialization_scope", "scope_key"),
    [
        ("", "story", "AG3-100"),
        ("tenant-a", "story", ""),
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
    #: Pinned wire format (existing contract tests, e.g.
    #: tests/unit/control_plane/test_runtime.py): "project_key:story_id".
    assert (
        oc.format_declared_scope(oc.story_claim_key("tenant-a", "AG3-100"))
        == "tenant-a:AG3-100"
    )


def test_format_declared_scope_project_is_bare_project_key() -> None:
    assert oc.format_declared_scope(oc.project_claim_key("tenant-a")) == "tenant-a"


def test_parse_declared_scope_round_trips_story_and_project() -> None:
    story_key = oc.story_claim_key("tenant-a", "AG3-100")
    project_key = oc.project_claim_key("tenant-a")
    assert oc.parse_declared_scope("tenant-a", oc.format_declared_scope(story_key)) == story_key
    assert (
        oc.parse_declared_scope("tenant-a", oc.format_declared_scope(project_key))
        == project_key
    )


@pytest.mark.parametrize("declared", [None, "", "other-project:AG3-100"])
def test_parse_declared_scope_returns_none_for_absent_or_foreign(
    declared: str | None,
) -> None:
    #: A legacy/absent declaration (or one belonging to a DIFFERENT project --
    #: defense in depth) has nothing to release.
    assert oc.parse_declared_scope("tenant-a", declared) is None


# ---------------------------------------------------------------------------
# LockSet canonical acquisition order (SOLL-049, AC4)
# ---------------------------------------------------------------------------


def test_build_lock_set_orders_project_first_then_lexicographic_stories() -> None:
    #: Deliberately unsorted input -- the builder derives canonical order.
    lock_set = oc.build_lock_set(
        "tenant-a", story_ids=("AG3-200", "AG3-100"), include_project_claim=True
    )
    assert lock_set.claims == (
        oc.project_claim_key("tenant-a"),
        oc.story_claim_key("tenant-a", "AG3-100"),
        oc.story_claim_key("tenant-a", "AG3-200"),
    )
    assert lock_set.project_claim == oc.project_claim_key("tenant-a")
    assert lock_set.story_claims == (
        oc.story_claim_key("tenant-a", "AG3-100"),
        oc.story_claim_key("tenant-a", "AG3-200"),
    )


def test_single_story_lock_set_is_the_rule_13_default() -> None:
    lock_set = oc.single_story_lock_set("tenant-a", "AG3-100")
    assert lock_set.claims == (oc.story_claim_key("tenant-a", "AG3-100"),)
    assert lock_set.project_claim is None


def test_build_lock_set_deduplicates_story_ids() -> None:
    lock_set = oc.build_lock_set("tenant-a", story_ids=("AG3-100", "AG3-100"))
    assert lock_set.claims == (oc.story_claim_key("tenant-a", "AG3-100"),)


def test_lock_set_rejects_empty_claim_set() -> None:
    #: SOLL-048: every mutation declares its serialization object.
    with pytest.raises(oc.LockSetOrderError):
        oc.LockSet(project_key="tenant-a", claims=())


def test_lock_set_rejects_story_before_project_even_when_hand_built() -> None:
    """AC4: "story held, then project requested" is not expressible.

    A caller cannot bypass :func:`build_lock_set` and hand-assemble an illegal
    order -- the constructor validates unconditionally, fail-closed.
    """
    story = oc.story_claim_key("tenant-a", "AG3-100")
    project = oc.project_claim_key("tenant-a")
    with pytest.raises(oc.LockSetOrderError, match="FIRST"):
        oc.LockSet(project_key="tenant-a", claims=(story, project))


def test_lock_set_rejects_a_second_project_claim() -> None:
    project = oc.project_claim_key("tenant-a")
    with pytest.raises(oc.LockSetOrderError):
        oc.LockSet(project_key="tenant-a", claims=(project, project))


def test_lock_set_rejects_out_of_order_story_ids() -> None:
    with pytest.raises(oc.LockSetOrderError, match="lexicographic"):
        oc.LockSet(
            project_key="tenant-a",
            claims=(
                oc.story_claim_key("tenant-a", "AG3-200"),
                oc.story_claim_key("tenant-a", "AG3-100"),
            ),
        )


def test_lock_set_rejects_duplicate_story_ids() -> None:
    duplicate = oc.story_claim_key("tenant-a", "AG3-100")
    with pytest.raises(oc.LockSetOrderError, match="lexicographic"):
        oc.LockSet(project_key="tenant-a", claims=(duplicate, duplicate))


def test_lock_set_rejects_a_claim_outside_its_project() -> None:
    with pytest.raises(oc.LockSetOrderError, match="does not belong"):
        oc.LockSet(
            project_key="tenant-a",
            claims=(oc.story_claim_key("tenant-b", "AG3-100"),),
        )


# ---------------------------------------------------------------------------
# acquire_lock_set / release_lock_set orchestration over a fake port
# ---------------------------------------------------------------------------


@dataclass
class _FakePort:
    """In-memory object-claim port honoring the SAME cross-scope fairness
    contract as the productive Postgres-backed acquire (a project claim
    conflicts with any held story claim of the same project and vice versa).
    """

    held: dict[tuple[str, str, str], str] = field(default_factory=dict)
    acquire_calls: list[tuple[str, str, str]] = field(default_factory=list)
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
        self.acquire_calls.append((project_key, serialization_scope, scope_key))
        conflicting = "story" if serialization_scope == "project" else "project"
        #: Exclude THIS caller's own op_id: a lock-set's earlier-acquired
        #: project claim must not self-conflict with its own later story claim.
        if any(
            k[0] == project_key and k[1] == conflicting and v != op_id
            for k, v in self.held.items()
        ):
            return False
        key = (project_key, serialization_scope, scope_key)
        existing = self.held.get(key)
        if existing is not None:
            return existing == op_id
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


def test_acquire_lock_set_wins_when_free() -> None:
    port = _FakePort()
    lock_set = oc.single_story_lock_set("tenant-a", "AG3-100")
    result = oc.acquire_lock_set(
        port, lock_set, op_id="op-1", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )
    assert result is None
    assert port.held == {("tenant-a", "story", "AG3-100"): "op-1"}


def test_acquire_lock_set_returns_conflict_when_busy() -> None:
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-holder"
    lock_set = oc.single_story_lock_set("tenant-a", "AG3-100")

    result = oc.acquire_lock_set(
        port, lock_set, op_id="op-2", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert isinstance(result, oc.ObjectClaimConflict)
    assert result.key == oc.story_claim_key("tenant-a", "AG3-100")
    #: K4/IMPL-016: the pinned deterministic wait contract.
    assert result.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    assert result.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT


def test_acquire_lock_set_rolls_back_partial_acquisition_on_mid_set_conflict() -> None:
    """A multi-claim lock-set that wins its FIRST claim but loses its SECOND
    releases the first claim again -- no partial lock-set ever survives.
    """
    port = _FakePort()
    #: "AG3-200" is already held by a FOREIGN op -- the SECOND story claim in
    #: canonical order will conflict.
    port.held[("tenant-a", "story", "AG3-200")] = "op-holder"
    lock_set = oc.build_lock_set("tenant-a", story_ids=("AG3-100", "AG3-200"))

    result = oc.acquire_lock_set(
        port, lock_set, op_id="op-2", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert isinstance(result, oc.ObjectClaimConflict)
    assert result.key == oc.story_claim_key("tenant-a", "AG3-200")
    #: "AG3-100" was acquired by THIS attempt, then released again -- only the
    #: pre-existing foreign "AG3-200" claim remains.
    assert port.held == {("tenant-a", "story", "AG3-200"): "op-holder"}
    assert ("tenant-a", "story", "AG3-100", "op-2") in port.release_calls


def test_acquire_lock_set_own_project_claim_never_self_conflicts_with_own_stories() -> None:
    """A lock-set's project claim (acquired first) must not block its OWN
    subsequent story claims in the SAME set -- only a FOREIGN op_id conflicts.
    """
    port = _FakePort()
    lock_set = oc.build_lock_set(
        "tenant-a", story_ids=("AG3-100", "AG3-200"), include_project_claim=True
    )

    result = oc.acquire_lock_set(
        port, lock_set, op_id="op-1", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert result is None
    assert port.held == {
        ("tenant-a", "project", "tenant-a"): "op-1",
        ("tenant-a", "story", "AG3-100"): "op-1",
        ("tenant-a", "story", "AG3-200"): "op-1",
    }


def test_acquire_lock_set_acquires_strictly_in_canonical_order() -> None:
    """The project claim is attempted BEFORE any story claim (SOLL-049)."""
    port = _FakePort()
    lock_set = oc.build_lock_set(
        "tenant-a", story_ids=("AG3-100", "AG3-200"), include_project_claim=True
    )
    oc.acquire_lock_set(
        port, lock_set, op_id="op-1", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )
    assert port.acquire_calls == [
        ("tenant-a", "project", "tenant-a"),
        ("tenant-a", "story", "AG3-100"),
        ("tenant-a", "story", "AG3-200"),
    ]


def test_release_lock_set_releases_in_reverse_order() -> None:
    port = _FakePort()
    lock_set = oc.build_lock_set(
        "tenant-a", story_ids=("AG3-100", "AG3-200"), include_project_claim=True
    )
    oc.acquire_lock_set(
        port, lock_set, op_id="op-1", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )
    port.release_calls.clear()

    oc.release_lock_set(port, lock_set, op_id="op-1")

    assert [call[:3] for call in port.release_calls] == [
        ("tenant-a", "story", "AG3-200"),
        ("tenant-a", "story", "AG3-100"),
        ("tenant-a", "project", "tenant-a"),
    ]
    assert port.held == {}


def test_cross_scope_fairness_project_conflicts_with_held_story() -> None:
    """SOLL-050 crux: a project claim cannot be granted while ANY story claim
    of the same project is held -- different scope_keys never PK-collide, so
    this is an explicit cross-scope check, not a side effect of the identity.
    """
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-story"
    project_only = oc.build_lock_set("tenant-a", include_project_claim=True)

    result = oc.acquire_lock_set(
        port, project_only, op_id="op-project", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert isinstance(result, oc.ObjectClaimConflict)
    assert result.key == oc.project_claim_key("tenant-a")


def test_cross_scope_fairness_story_conflicts_with_held_project() -> None:
    """SOLL-050 crux (story wording): "acquiring a story claim must fail-closed
    while a project claim for the same project is pending/held".
    """
    port = _FakePort()
    port.held[("tenant-a", "project", "tenant-a")] = "op-project"
    story_only = oc.single_story_lock_set("tenant-a", "AG3-100")

    result = oc.acquire_lock_set(
        port, story_only, op_id="op-story", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert isinstance(result, oc.ObjectClaimConflict)
    assert result.key == oc.story_claim_key("tenant-a", "AG3-100")


def test_different_stories_never_conflict() -> None:
    """AC3: mutations of DIFFERENT stories in the same project never conflict."""
    port = _FakePort()
    port.held[("tenant-a", "story", "AG3-100")] = "op-1"
    other_story = oc.single_story_lock_set("tenant-a", "AG3-200")

    result = oc.acquire_lock_set(
        port, other_story, op_id="op-2", backend_instance_id="inst-1",
        instance_incarnation=1, now=_NOW,
    )

    assert result is None
    assert port.held[("tenant-a", "story", "AG3-200")] == "op-2"
