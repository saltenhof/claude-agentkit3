from __future__ import annotations

pytest_plugins = ("tests.fixtures.postgres_backend",)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        # Only add postgres_runtime_env to contract tests, not unit tests.
        # When tests/unit and tests/contract are collected together, this hook
        # fires for all items. Limiting to contract tests prevents the
        # session-scoped postgres fixture from contaminating unit-test state.
        if "/contract/" in str(item.fspath).replace("\\", "/"):
            item.fixturenames.append("postgres_runtime_env")
