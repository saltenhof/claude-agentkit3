"""Unit tests for the productive ``StateBackendAnalyticsSource`` (AG3-082, FIX 1/2/4).

The adapter is the productive ``AnalyticsSourcePort`` the composition root injects
into the real ``RefreshWorker``. These tests exercise each method over the real
SQLite-backed ``ProjectionAccessor`` (story/corpus/pipeline read-models + the
run-scoped ``purge_run``) and over an injected event-facade for the event-driven
methods (watermark/delta/pool/guard) — the §5 MOCKS-AUSNAHME boundary, since the
project-global event stream is Postgres-canonical (FK-60 §60.3.2) and the
Docker-free harness has no global SQLite event store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.analytics_source import StateBackendAnalyticsSource
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "tenant-s"
_NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
_WEEK = "2026-06-08"  # ISO week of 2026-06-11 (Thursday)


@pytest.fixture(autouse=True)
def _pin_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _accessor(tmp_path: Path) -> ProjectionAccessor:
    return ProjectionAccessor(build_projection_repositories(tmp_path))


def _seed_metrics(
    accessor: ProjectionAccessor,
    *,
    story_id: str,
    completed_at: str,
    final_status: str = "DONE",
    qa_rounds: int = 2,
) -> None:
    accessor.write_projection(
        ProjectionKind.STORY_METRICS,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=f"run-{story_id}",
            story_type="implementation",
            story_size="M",
            mode="execution",
            processing_time_min=10.0,
            qa_rounds=qa_rounds,
            increments=2,
            final_status=final_status,
            completed_at=completed_at,
            files_changed=3,
            agentkit_version="3.20.0",
            agentkit_commit="abc",
        ),
    )


#: AG3-117 (R3): the canonical pool-identity wire key PER event type (mirrors the
#: production ``_POOL_PAYLOAD_KEY_BY_TYPE`` so the test fixtures are producer-shaped:
#: ``llm_call`` -> ``pool``, ``llm_call_complete`` -> ``role``, ``review_*`` ->
#: ``reviewer_role``). A pool event type absent here carries no scalar pool key.
_POOL_KEY_FOR_EVENT: dict[str, str] = {
    EventType.LLM_CALL.value: "pool",
    EventType.LLM_CALL_COMPLETE.value: "role",
    EventType.REVIEW_REQUEST.value: "reviewer_role",
    EventType.REVIEW_RESPONSE.value: "reviewer_role",
    EventType.REVIEW_COMPLIANT.value: "reviewer_role",
}


def _event(
    event_id: str,
    *,
    event_type: str,
    occurred_at: datetime = _NOW,
    pool_key: str | None = None,
    guard_key: str | None = None,
    story_id: str = "AG3-300",
) -> ExecutionEventRecord:
    # Real-producer-shaped payloads: each pool event type carries the pool identity
    # under its OWN canonical telemetry wire key (``_POOL_KEY_FOR_EVENT``);
    # ``integrity_violation`` carries the emitting guard under ``guard``
    # (prompt_integrity_guard.py et al.). The analytics source translates the
    # per-type key -> ``pool_key`` / ``guard_key`` fact dimensions at the read
    # boundary (AG3-117: event-type-aware, not a single uniform key).
    payload: dict[str, object] = {}
    if pool_key is not None:
        payload[_POOL_KEY_FOR_EVENT[event_type]] = pool_key
    if guard_key is not None:
        payload["guard"] = guard_key
    return ExecutionEventRecord(
        project_key=_PROJECT,
        story_id=story_id,
        run_id="run-1",
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        source_component="test",
        severity="info",
        payload=payload,
    )


def _source_with_events(
    accessor: ProjectionAccessor,
    monkeypatch: pytest.MonkeyPatch,
    events: list[ExecutionEventRecord],
) -> StateBackendAnalyticsSource:
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)
    monkeypatch.setattr(
        source, "_load_project_events", lambda project_key: list(events)
    )
    return source


# ---------------------------------------------------------------------------
# story read-models
# ---------------------------------------------------------------------------


def test_recompute_fact_story_maps_metrics(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    fact = source.recompute_fact_story(_PROJECT, "AG3-300")

    assert fact is not None
    assert fact.story_id == "AG3-300"
    assert fact.story_type == "implementation"
    assert fact.qa_round_count == 2
    assert fact.closed_at == _NOW


def test_recompute_fact_story_none_for_open_story(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)
    assert source.recompute_fact_story(_PROJECT, "UNKNOWN") is None


def test_get_story_closed_at_returns_metrics_completed_at(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    assert source.get_story_closed_at(_PROJECT, "AG3-300") == _NOW


def test_get_story_closed_at_none_for_missing_metrics(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)
    assert source.get_story_closed_at(_PROJECT, "UNKNOWN") is None


# ---------------------------------------------------------------------------
# period recomputes from read-models (SQLite-capable)
# ---------------------------------------------------------------------------


def test_recompute_fact_pipeline_period_from_story_metrics(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    # Two completed + one escalated in week 2026-06-08; one in a different week.
    _seed_metrics(accessor, story_id="A", completed_at=_NOW.isoformat(), qa_rounds=2)
    _seed_metrics(accessor, story_id="B", completed_at=_NOW.isoformat(), qa_rounds=4)
    _seed_metrics(
        accessor,
        story_id="C",
        completed_at=_NOW.isoformat(),
        final_status="ESCALATED",
        qa_rounds=6,
    )
    _seed_metrics(
        accessor,
        story_id="D",
        completed_at=datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
    )
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    row = source.recompute_fact_pipeline_period(_PROJECT, _WEEK)

    assert row.story_count == 3  # A, B, C in the week
    assert row.story_count_closed == 2  # A, B (C is escalated)
    assert row.qa_round_avg == pytest.approx((2 + 4 + 6) / 3)


def test_recompute_fact_corpus_period_empty(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)

    row = source.recompute_fact_corpus_period(_PROJECT, "2026-06-01")

    assert row.new_incident_count == 0
    assert row.period_start == datetime(2026, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# event-driven methods (watermark / delta / pool / guard)
# ---------------------------------------------------------------------------


def test_get_watermark_returns_last_event_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.AGENT_START.value),
        _event("evt-2", event_type=EventType.AGENT_END.value),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    assert source.get_watermark(_PROJECT) == "evt-2"


def test_get_watermark_none_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_with_events(_accessor(tmp_path), monkeypatch, [])
    assert source.get_watermark(_PROJECT) is None


def test_read_delta_events_respects_cursor_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.AGENT_START.value),
        _event("evt-2", event_type=EventType.LLM_CALL.value, pool_key="qa"),
        _event("evt-3", event_type=EventType.AGENT_END.value),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    delta = source.read_delta_events(
        _PROJECT, after_event_id="evt-1", through_event_id="evt-2"
    )

    assert [d.event_id for d in delta] == ["evt-2"]
    assert delta[0].pool_key == "qa"  # payload classification


def test_recompute_fact_pool_period_counts_pool_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.LLM_CALL.value, pool_key="qa"),
        _event("evt-2", event_type=EventType.REVIEW_RESPONSE.value, pool_key="qa"),
        _event("evt-3", event_type=EventType.LLM_CALL.value, pool_key="review"),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_pool_period(_PROJECT, "qa", _WEEK)

    assert row.pool_key == "qa"
    assert row.call_count == 2  # two qa-pool events in the week


def test_recompute_fact_guard_period_counts_violation_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event(
            "evt-1",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="orchestrator_guard",
        ),
        _event(
            "evt-2",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="orchestrator_guard",
        ),
        _event(
            "evt-3",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="other_guard",
        ),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_guard_period(_PROJECT, "orchestrator_guard", _WEEK)

    assert row.guard_key == "orchestrator_guard"
    assert row.invocation_count == 2
    assert row.violation_count == 2


# ---------------------------------------------------------------------------
# AG3-117 (Finding 1, R2): pool/guard dirty-sets read the CANONICAL telemetry
# payload keys ``role`` (llm_call_complete, FK-61 §61.12.2 / composition_root
# producer) and ``guard`` (integrity_violation, prompt_integrity_guard et al.)
# and translate them to the ``pool_key`` / ``guard_key`` FK-62 §62.2 fact
# dimensions. R1 over-corrected by reading the bare fact-column names
# (``pool_key``/``guard_key``) off the event payload, which producers never emit,
# so the rollups silently captured NOTHING. These tests feed REAL-producer-shaped
# payloads and fail if the bare fact-column name is read instead.
# ---------------------------------------------------------------------------


def _delta_one(record: ExecutionEventRecord) -> tuple[str | None, str | None]:
    from agentkit.backend.state_backend.store.analytics_source import _to_delta_event

    delta = _to_delta_event(record)
    return delta.pool_key, delta.guard_key


def _producer_event(
    event_id: str,
    *,
    event_type: str,
    payload: dict[str, object],
) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key=_PROJECT,
        story_id="AG3-300",
        run_id="run-1",
        event_id=event_id,
        event_type=event_type,
        occurred_at=_NOW,
        source_component="test",
        severity="info",
        payload=payload,
    )


def test_pool_dirty_set_reads_producer_role_key() -> None:
    """``llm_call_complete`` ``{"role": ...}`` -> ``pool_key`` fact dimension."""
    # Real composition_root.py producer shape: payload={"role": <reviewer>, ...}.
    pool, _ = _delta_one(
        _producer_event(
            "evt-1",
            event_type=EventType.LLM_CALL_COMPLETE.value,
            payload={"role": "qa", "artifact_filename": "handover.md"},
        )
    )
    assert pool == "qa"  # fails if the reader looks for the bare ``pool_key`` key


def test_guard_dirty_set_reads_producer_guard_key() -> None:
    """``integrity_violation`` ``{"guard": ...}`` -> ``guard_key`` fact dim."""
    # Real prompt_integrity_guard.py producer shape: payload={"guard": <name>,...}.
    _, guard = _delta_one(
        _producer_event(
            "evt-1",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            payload={"guard": "prompt_integrity_guard", "detail": "block"},
        )
    )
    assert guard == "prompt_integrity_guard"


def test_bare_fact_column_keys_on_payload_are_not_read() -> None:
    """The R1 over-correction must NOT resurrect: bare fact-column names ignored.

    No producer writes ``pool_key`` / ``guard_key`` onto the event payload (those
    are the FK-62 §62.2 FACT-COLUMN names, not telemetry wire keys). Reading them
    is the bug this round fixes, so a payload carrying ONLY them yields nothing.
    """
    pool, guard = _delta_one(
        _producer_event(
            "evt-1",
            event_type=EventType.LLM_CALL_COMPLETE.value,
            payload={"pool_key": "qa", "guard_key": "orchestrator_guard"},
        )
    )
    assert pool is None
    assert guard is None


def test_fact_pool_period_populates_from_producer_role_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end rollup across HETEROGENEOUS pool keys -> populated fact_pool_period.

    AG3-117 (R3): the three events below use THREE different authoritative wire keys
    for the SAME ``qa`` pool — ``llm_call_complete`` -> ``role``, ``review_response``
    -> ``reviewer_role``, ``llm_call`` -> ``pool``. All three must bin under ``qa``;
    the count would be < 3 if the reader used one fixed key for the whole class.
    """
    events = [
        _producer_event(
            "evt-1",
            event_type=EventType.LLM_CALL_COMPLETE.value,
            payload={"role": "qa", "artifact_filename": "a.md"},
        ),
        _producer_event(
            "evt-2",
            event_type=EventType.REVIEW_RESPONSE.value,
            payload={"reviewer_role": "qa", "verdict": "PASS"},
        ),
        _producer_event(
            "evt-3",
            event_type=EventType.LLM_CALL.value,
            payload={"pool": "qa", "role": "adversarial_sparring"},
        ),
        _producer_event(
            "evt-4",
            event_type=EventType.LLM_CALL_COMPLETE.value,
            payload={"role": "review", "artifact_filename": "b.md"},
        ),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_pool_period(_PROJECT, "qa", _WEEK)

    assert row.pool_key == "qa"
    # All three qa-pool events captured across three different wire keys; would be
    # < 3 if the reader used a single fixed key for the whole pool class.
    assert row.call_count == 3


def test_fact_guard_period_populates_from_producer_guard_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end rollup: real ``{"guard": ...}`` events -> populated fact_guard_period."""
    events = [
        _producer_event(
            "evt-1",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            payload={"guard": "prompt_integrity_guard", "detail": "block-1"},
        ),
        _producer_event(
            "evt-2",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            payload={"guard": "prompt_integrity_guard", "detail": "block-2"},
        ),
        _producer_event(
            "evt-3",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            payload={"guard": "skill_usage_check", "detail": "block-3"},
        ),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_guard_period(_PROJECT, "prompt_integrity_guard", _WEEK)

    assert row.guard_key == "prompt_integrity_guard"
    # Both matching guard events captured; would be 0 if reading ``guard_key``.
    assert row.invocation_count == 2
    assert row.violation_count == 2


# ---------------------------------------------------------------------------
# AG3-117 (R3): EXHAUSTIVE per-event-type pool/guard key mapping. Each pool/guard
# event type carries its pool/guard identity under a DIFFERENT canonical wire key
# (``llm_call`` -> ``pool``, ``llm_call_complete`` -> ``role``, ``review_*`` ->
# ``reviewer_role``, ``integrity_violation`` -> ``guard``). R2 read ONE fixed key
# (``role``) for the whole pool class, so ``llm_call`` (real key ``pool``) and the
# three ``review_*`` events (real key ``reviewer_role``) were SILENTLY MISSED in
# ``fact_pool_period``. These tests feed REAL-producer-shaped payloads for EVERY
# event type in the rollup sets and fail if the wrong key is read.
# ---------------------------------------------------------------------------

#: REAL producer payload shape per pool event type (pool identity under the
#: authoritative wire key) + the two reviewer-PAIR/coverage events that carry NO
#: single scalar pool dimension (explicit ``None`` expectation).
#: (event_type, producer-shaped payload, expected pool_key)
_POOL_PRODUCER_CASES: list[tuple[str, dict[str, object], str | None]] = [
    # llm_call: structured_evaluator.py / sparring.py emit BOTH pool + role; pool
    # is authoritative (telemetry_contract.py:239-241). The role here is a DECOY:
    # if the reader fell back to ``role`` it would mis-bin under "decoy-role".
    (
        EventType.LLM_CALL.value,
        {"pool": "qa", "role": "decoy-role", "retry": 0, "status": "ok"},
        "qa",
    ),
    # llm_call_complete: composition_root.py:1464 emits ONLY role.
    (
        EventType.LLM_CALL_COMPLETE.value,
        {"role": "qa", "artifact_filename": "handover.md"},
        "qa",
    ),
    # review_request / review_response / review_compliant: review_sentinel_hook.py
    # emits the reviewer pool under ``reviewer_role`` (NOT role / pool).
    (
        EventType.REVIEW_REQUEST.value,
        {"reviewer_role": "qa", "review_round": 1, "template_name": "t"},
        "qa",
    ),
    (
        EventType.REVIEW_RESPONSE.value,
        {
            "reviewer_role": "qa",
            "review_round": 1,
            "template_name": "t",
            "verdict": "PASS",
        },
        "qa",
    ),
    (
        EventType.REVIEW_COMPLIANT.value,
        {"reviewer_role": "qa", "review_round": 1, "template_name": "t"},
        "qa",
    ),
    # review_guard_intervention: review_guard.py carries LISTS, no scalar pool.
    (
        EventType.REVIEW_GUARD_INTERVENTION.value,
        {
            "story_id": "AG3-300",
            "run_id": "run-1",
            "missing_roles": ["qa"],
            "required_roles": ["qa", "review"],
            "reason": "missing",
        },
        None,
    ),
    # review_divergence: divergence_hook.py carries a reviewer PAIR, no scalar pool.
    (
        EventType.REVIEW_DIVERGENCE.value,
        {
            "story_id": "AG3-300",
            "reviewer_a": "qa",
            "reviewer_b": "review",
            "divergent": True,
            "quorum_triggered": False,
            "final_verdict": None,
        },
        None,
    ),
]

#: REAL producer payload shape per guard event type.
#: (event_type, producer-shaped payload, expected guard_key)
_GUARD_PRODUCER_CASES: list[tuple[str, dict[str, object], str | None]] = [
    (
        EventType.INTEGRITY_VIOLATION.value,
        {"guard": "prompt_integrity_guard", "detail": "block"},
        "prompt_integrity_guard",
    ),
]


@pytest.mark.parametrize(
    ("event_type", "payload", "expected_pool"), _POOL_PRODUCER_CASES
)
def test_pool_key_per_event_type_reads_authoritative_key(
    event_type: str, payload: dict[str, object], expected_pool: str | None
) -> None:
    """Each pool event type classifies under its OWN authoritative wire key."""
    pool, _ = _delta_one(
        _producer_event("evt-1", event_type=event_type, payload=payload)
    )
    assert pool == expected_pool


@pytest.mark.parametrize(
    ("event_type", "payload", "expected_guard"), _GUARD_PRODUCER_CASES
)
def test_guard_key_per_event_type_reads_authoritative_key(
    event_type: str, payload: dict[str, object], expected_guard: str | None
) -> None:
    """Each guard event type classifies under its OWN authoritative wire key."""
    _, guard = _delta_one(
        _producer_event("evt-1", event_type=event_type, payload=payload)
    )
    assert guard == expected_guard


@pytest.mark.parametrize(
    ("event_type", "payload", "expected_pool"),
    [c for c in _POOL_PRODUCER_CASES if c[2] is not None],
)
def test_fact_pool_period_populated_per_event_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    payload: dict[str, object],
    expected_pool: str | None,
) -> None:
    """Every scalar-pool event type populates ``fact_pool_period.call_count`` > 0.

    Fails (call_count == 0) if ``_pool_of`` reads the wrong key — the exact AG3-117
    bug for ``llm_call`` (real key ``pool``) and ``review_*`` (real ``reviewer_role``).
    """
    assert expected_pool is not None  # parametrization guarantees this
    events = [_producer_event("evt-1", event_type=event_type, payload=payload)]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_pool_period(_PROJECT, expected_pool, _WEEK)

    assert row.pool_key == expected_pool
    assert row.call_count > 0


@pytest.mark.parametrize(
    ("event_type", "payload", "expected_guard"), _GUARD_PRODUCER_CASES
)
def test_fact_guard_period_populated_per_event_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    payload: dict[str, object],
    expected_guard: str | None,
) -> None:
    """Every guard event type populates ``fact_guard_period`` counts > 0."""
    assert expected_guard is not None
    events = [_producer_event("evt-1", event_type=event_type, payload=payload)]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_guard_period(_PROJECT, expected_guard, _WEEK)

    assert row.guard_key == expected_guard
    assert row.invocation_count > 0
    assert row.violation_count > 0


def test_every_rollup_event_type_has_a_key_mapping() -> None:
    """Drift guard: the rollup SETS and the key-MAPS stay in lock-step (fail-closed).

    Every event type in ``_POOL_EVENT_TYPES`` / ``_GUARD_EVENT_TYPES`` MUST have an
    entry in ``_POOL_PAYLOAD_KEY_BY_TYPE`` / ``_GUARD_PAYLOAD_KEY_BY_TYPE`` (an
    explicit key or an explicit ``None``). A future event added to a set without a
    mapping entry would otherwise silently capture nothing — this test makes that a
    hard failure at CI time, and ``_resolve_payload_key`` makes it fail-closed at
    runtime.
    """
    from agentkit.backend.state_backend.store.analytics_source import (
        _GUARD_EVENT_TYPES,
        _GUARD_PAYLOAD_KEY_BY_TYPE,
        _POOL_EVENT_TYPES,
        _POOL_PAYLOAD_KEY_BY_TYPE,
    )

    pool_mapped = {et.value for et in _POOL_PAYLOAD_KEY_BY_TYPE}
    guard_mapped = {et.value for et in _GUARD_PAYLOAD_KEY_BY_TYPE}
    assert pool_mapped == _POOL_EVENT_TYPES
    assert guard_mapped == _GUARD_EVENT_TYPES
    # And every test producer-case set covers exactly the rollup set (no gaps).
    assert {c[0] for c in _POOL_PRODUCER_CASES} == _POOL_EVENT_TYPES
    assert {c[0] for c in _GUARD_PRODUCER_CASES} == _GUARD_EVENT_TYPES


def test_resolve_payload_key_fails_closed_for_unmapped_event_type() -> None:
    """``_resolve_payload_key`` raises for a set-member with no key-map entry.

    A future addition to the rollup set that forgot its key-map entry must NOT
    silently default to ``None`` (that re-creates the AG3-117 data bug).
    """
    from agentkit.backend.state_backend.store.analytics_source import (
        _POOL_PAYLOAD_KEY_BY_TYPE,
        _resolve_payload_key,
    )

    # AGENT_START is NOT in the pool key-map -> KeyError (fail-closed).
    with pytest.raises(KeyError):
        _resolve_payload_key(EventType.AGENT_START.value, _POOL_PAYLOAD_KEY_BY_TYPE)


# ---------------------------------------------------------------------------
# reset purge consumes the REAL run-scoped purge_run (FIX 2)
# ---------------------------------------------------------------------------


def test_purge_run_read_models_delegates_to_accessor_purge_run(
    tmp_path: Path,
) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    # Pre-condition: the run-bound story_metrics row exists.
    assert (
        len(
            accessor.read_projection(
                ProjectionKind.STORY_METRICS,
                ProjectionFilter(
                    project_key=_PROJECT, story_id="AG3-300", run_id="run-AG3-300"
                ),
            )
        )
        == 1
    )

    purged = source.purge_run_read_models(_PROJECT, "AG3-300", "run-AG3-300")

    # The REAL purge_run removed the run-bound FK-69 read model.
    assert purged >= 1
    assert (
        accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(
                project_key=_PROJECT, story_id="AG3-300", run_id="run-AG3-300"
            ),
        )
        == []
    )
