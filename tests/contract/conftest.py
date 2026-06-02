from __future__ import annotations

# ``pytest_plugins`` lebt in ``tests/conftest.py`` (Top-Level, pytest 8+
# Anforderung); hier nur Collection-Hook fuer Postgres-Bindung.
#
# AG3-051 (Codex-Fix): OPT-IN statt DENY-LIST. Die fruehere Mechanik haengte
# ``postgres_isolated_schema`` an FAST JEDES ``/contract/`` item und schloss nur
# eine handgepflegte 3-Eintrag-Deny-List aus. Das *unter*-deckte: pure
# in-memory-Contract-Tests (z. B. ``artifacts/``, ``telemetry/``, Signature-/
# Scaffold-Surfaces) wurden ungewollt auf Docker/Postgres gezwungen und ein
# neuer pure Contract-Test haette stillschweigend wieder Docker angezogen
# (Verstoss gegen AK4: "Pure-in-memory-Tests ziehen kein Docker/Postgres").
#
# Modell jetzt: eine EXPLIZITE ALLOW-LIST der Postgres-nutzenden Contract-
# Subtrees. Die Isolationsfixture wird ausschliesslich an Items gebunden, die
# echt das State-Backend gegen eine DB ausueben (StateBackend*-Repository,
# save+load von DB-Zeilen). Alles ausserhalb der Allow-List bleibt Docker-frei.
# Ein neu hinzugefuegter pure Contract-Test kann so nie mehr versehentlich
# Postgres anziehen.
#
# Subtree-granular genuegt, ausser in ``state_backend/``: dort ist
# ``test_schema_resolver.py`` ein reiner Resolver-Vertragstest (nur
# ``state_backend.config`` + monkeypatch, KEINE DB) und wird per Datei-Ausschluss
# herausgehalten.
_POSTGRES_CONTRACT_ALLOW_PATHS: tuple[str, ...] = (
    "/contract/state_backend/",
)
# Dateien innerhalb eines Allow-Subtrees, die TROTZDEM Docker-frei sind
# (reine, DB-lose Vertragstests).
_POSTGRES_INDEPENDENT_CONTRACT_FILES: tuple[str, ...] = (
    "/contract/state_backend/test_schema_resolver.py",
)


def _is_postgres_contract_item(path: str) -> bool:
    """Return True if *path* is a contract test that genuinely exercises Postgres.

    Args:
        path: The forward-slash-normalised filesystem path of the collected item.

    Returns:
        True iff the item lives in a Postgres-using contract subtree and is not
        one of the explicitly DB-free files inside such a subtree.
    """
    if not any(allow in path for allow in _POSTGRES_CONTRACT_ALLOW_PATHS):
        return False
    return not any(skip in path for skip in _POSTGRES_INDEPENDENT_CONTRACT_FILES)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        # The hook fires for ALL collected items in a full run, not just this
        # suite's. The explicit allow-list keeps unit + pure in-memory contract
        # tests off Docker/Postgres and binds the function-scoped
        # ``postgres_isolated_schema`` (per-test TRUNCATE) ONLY to Postgres-using
        # contract items.
        path = str(item.fspath).replace("\\", "/")
        if _is_postgres_contract_item(path):
            item.fixturenames.append("postgres_isolated_schema")
