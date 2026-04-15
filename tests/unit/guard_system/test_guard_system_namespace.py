from agentkit.guard_system import GuardRunner
from agentkit.governance import GuardRunner as LegacyGuardRunner


def test_guard_system_namespace_reexports_legacy_api() -> None:
    assert GuardRunner is LegacyGuardRunner
