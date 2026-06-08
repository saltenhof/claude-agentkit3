"""Unit tests for PhaseEnvelopeStore (AK 3, AK 6).

Tests use a real in-memory stub repository -- no mocks.
"""

from __future__ import annotations

from tests.phase_state_factory import make_phase_state

from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.pipeline_engine.phase_envelope.repository import PhaseEnvelopeRepository
from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import PhaseName, PhaseState, PhaseStatus


class _InMemoryRepository:
    """Minimal in-memory stub satisfying PhaseEnvelopeRepository.

    Using a real stub (not a mock) in accordance with project guardrails.
    """

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], PhaseState] = {}

    def load_state(self, story_id: str, phase: PhaseName) -> PhaseState | None:
        return self._states.get((story_id, phase.value))

    def save_state(self, state: PhaseState) -> None:
        self._states[(state.story_id, state.phase)] = state

    def exists_state(self, story_id: str, phase: PhaseName) -> bool:
        return (story_id, phase.value) in self._states


assert isinstance(_InMemoryRepository(), PhaseEnvelopeRepository)


def _fresh_state(
    story_id: str = "AG3-024",
    phase: str = "setup",
) -> PhaseState:
    return make_phase_state(
        story_id=story_id,
        phase=phase,
        status=PhaseStatus.PENDING,
    )


def test_load_returns_none_when_no_state() -> None:
    """load() returns None when nothing has been saved."""
    repo = _InMemoryRepository()
    store = PhaseEnvelopeStore(repo)
    result = store.load("AG3-024", PhaseName.SETUP)
    assert result is None


def test_load_returns_envelope_with_origin_loaded() -> None:
    """load() returns an envelope with origin=LOADED."""
    repo = _InMemoryRepository()
    state = _fresh_state()
    repo.save_state(state)

    store = PhaseEnvelopeStore(repo)
    envelope = store.load("AG3-024", PhaseName.SETUP)

    assert envelope is not None
    assert envelope.runtime.origin is PhaseOrigin.LOADED
    assert envelope.state.story_id == "AG3-024"


def test_save_persists_only_state_not_runtime() -> None:
    """save() writes state to the repo; runtime is NOT persisted (AK 6)."""
    repo = _InMemoryRepository()
    store = PhaseEnvelopeStore(repo)

    # Create an envelope with origin=NEW and save it
    state = _fresh_state()
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)
    assert envelope.runtime.origin is PhaseOrigin.NEW

    store.save(envelope)

    # Load it back -- the origin must be LOADED (not NEW), proving
    # that runtime was NOT persisted
    loaded = store.load("AG3-024", PhaseName.SETUP)
    assert loaded is not None
    assert loaded.runtime.origin is PhaseOrigin.LOADED
    assert loaded.state.story_id == state.story_id


def test_roundtrip_runtime_not_persisted() -> None:
    """Roundtrip: save(NEW) -> load() => origin==LOADED (AK 6 invariant)."""
    repo = _InMemoryRepository()
    store = PhaseEnvelopeStore(repo)

    state = make_phase_state(
        story_id="ROUND-1",
        phase="setup",
        status=PhaseStatus.PENDING,
    )
    # Wrap with NEW origin
    fresh_envelope = PhaseEnvelopeStore.make_fresh_envelope(state)
    assert fresh_envelope.runtime.origin is PhaseOrigin.NEW

    store.save(fresh_envelope)

    loaded = store.load("ROUND-1", PhaseName.SETUP)
    assert loaded is not None
    # Key invariant: runtime is reconstructed, origin=LOADED
    assert loaded.runtime.origin is PhaseOrigin.LOADED
    # Durable state is preserved
    assert loaded.state.story_id == "ROUND-1"
    assert loaded.state.status is PhaseStatus.PENDING


def test_exists_false_before_save() -> None:
    """exists() returns False when nothing has been saved."""
    repo = _InMemoryRepository()
    store = PhaseEnvelopeStore(repo)
    assert store.exists("AG3-024", PhaseName.SETUP) is False


def test_exists_true_after_save() -> None:
    """exists() returns True after a state is saved."""
    repo = _InMemoryRepository()
    state = _fresh_state()
    repo.save_state(state)
    store = PhaseEnvelopeStore(repo)
    assert store.exists("AG3-024", PhaseName.SETUP) is True


def test_make_fresh_envelope_has_origin_new() -> None:
    """make_fresh_envelope creates an envelope with origin=NEW."""
    state = _fresh_state()
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)
    assert isinstance(envelope, PhaseEnvelope)
    assert envelope.runtime.origin is PhaseOrigin.NEW
