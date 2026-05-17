from __future__ import annotations

# ``pytest_plugins`` lebt in ``tests/conftest.py`` (Top-Level, pytest 8+
# Anforderung); hier nur Collection-Hook fuer Postgres-Bindung.


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        item.fixturenames.append("postgres_runtime_env")
