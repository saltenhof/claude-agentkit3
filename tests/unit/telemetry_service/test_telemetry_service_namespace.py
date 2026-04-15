from agentkit.telemetry import Event as LegacyEvent
from agentkit.telemetry_service import Event


def test_telemetry_service_namespace_reexports_legacy_api() -> None:
    assert Event is LegacyEvent
