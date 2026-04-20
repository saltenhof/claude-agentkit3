from agentkit.telemetry_service import (
    Event,
    EventEmitter,
    EventType,
    MemoryEmitter,
    StateBackendEmitter,
)


def test_telemetry_service_namespace_exposes_public_types() -> None:
    assert Event.__name__ == "Event"
    assert EventType.__name__ == "EventType"
    assert EventEmitter.__name__ == "EventEmitter"
    assert MemoryEmitter.__name__ == "MemoryEmitter"
    assert StateBackendEmitter.__name__ == "StateBackendEmitter"
