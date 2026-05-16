from __future__ import annotations

pytest_plugins = ("tests.fixtures.postgres_backend",)

# Contract test suites that operate on pure in-memory types and do NOT
# require the Postgres backend fixture. Adding the session-scoped
# ``postgres_runtime_env`` fixture to these tests would switch the global
# AGENTKIT_STATE_BACKEND env var to postgres for the rest of the pytest
# session and break interleaved unit tests that rely on the default
# SQLite backend (e.g. ``tests/unit/verify_system/structural/``).
_POSTGRES_INDEPENDENT_CONTRACT_PATHS: tuple[str, ...] = (
    "/contract/core_types/",
)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        # Only add postgres_runtime_env to contract tests, not unit tests.
        # When tests/unit and tests/contract are collected together, this hook
        # fires for all items. Limiting to contract tests prevents the
        # session-scoped postgres fixture from contaminating unit-test state.
        path = str(item.fspath).replace("\\", "/")
        if "/contract/" not in path:
            continue
        if any(skip in path for skip in _POSTGRES_INDEPENDENT_CONTRACT_PATHS):
            continue
        item.fixturenames.append("postgres_runtime_env")
