from __future__ import annotations

pytest_plugins = ("tests.fixtures.postgres_backend",)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        item.fixturenames.append("postgres_runtime_env")
