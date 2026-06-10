from __future__ import annotations

# ``pytest_plugins`` lebt in ``tests/conftest.py`` (Top-Level, pytest 8+
# Anforderung); hier nur Collection-Hook fuer Postgres-Bindung.
#
# AG3-051 (Codex-Fix): OPT-IN statt Suite-Wholesale. Frueher haengte dieser Hook
# ``postgres_isolated_schema`` an JEDES ``/integration/`` item. Das zog Docker
# auch auf Integration-Tests, die KEIN Postgres brauchen:
#   * ``project_management/`` pinnt selbst SQLite (eigene autouse-Fixture,
#     ``AGENTKIT_STATE_BACKEND=sqlite`` + ``tmp_path``-DB).
#   * ``telemetry/`` sind reine Import-/Buildability-Smoke-Tests ohne DB-Zugriff.
# Das ist derselbe AK4-Verstoss wie bei der Contract-Deny-List ("Pure-in-memory-
# /SQLite-Tests ziehen kein Docker/Postgres").
#
# Modell jetzt: eine EXPLIZITE ALLOW-LIST der Postgres-nutzenden Integration-
# Subtrees. Die function-scoped Isolationsfixture (per-test TRUNCATE) wird nur an
# Items dieser Subtrees gebunden; alles andere bleibt Docker-frei. Ein neu
# hinzugefuegter pure/SQLite-Subtree kann so nie versehentlich Postgres anziehen.
_POSTGRES_INTEGRATION_ALLOW_PATHS: tuple[str, ...] = (
    "/integration/installer/",
    "/integration/pipeline_engine/",
    "/integration/project_ops/",
    "/integration/state_backend/",
    "/integration/failure_corpus/",
)
# AG3-051 (Codex-r2): subtree-granular allow is NOT precise enough. Two
# allow-listed files MIX Postgres-using tests with host-independent
# early-abort tests that raise BEFORE any StateBackend/DB access:
#   * ``install_agentkit`` validates ``project_root.is_dir()`` and runs the
#     skill-bundle PREFLIGHT (``_resolve_mandatory_skill_bundles``) up front;
#     both reject BEFORE any project write or DB roundtrip
#     (``runner.py`` install_agentkit / _resolve_mandatory_skill_bundles).
# Such a test must stay Docker-free (AK4: pure/precondition tests never pull
# Postgres). A whole-FILE exclusion (like the contract conftest uses) would be
# wrong here — it would also strip isolation from the genuine DB tests in the
# same file. So the exception is NODE-ID granular: the fixture binds to a
# Postgres-using subtree item UNLESS its node id ends with one of these
# explicit early-abort node-id suffixes.
_POSTGRES_INDEPENDENT_INTEGRATION_NODEIDS: tuple[str, ...] = (
    # project_root missing -> ProjectError at the very first is_dir() check.
    "project_ops/install_fresh/test_install_fresh.py::"
    "TestInstallFreshFailClosed::test_install_fails_if_root_missing",
    # Partial DI -> InvalidConfig in _resolve_skills_and_store (preflight).
    "installer/test_skills_binding.py::test_partial_skill_injection_rejected",
    # Missing mandatory bundle -> BundleNotFound in the preflight resolution,
    # before any project write or DB access (injected InMemory repo, never hit).
    "installer/test_skills_binding.py::"
    "test_fail_closed_missing_bundle_no_partial_install",
    # Default store has no provisioned bundles -> BundleNotFound in the
    # preflight resolution, before the StateBackend repo is ever exercised.
    "installer/test_skills_binding.py::"
    "test_no_skill_config_fails_closed_when_bundles_unprovisioned",
)
_POSTGRES_INDEPENDENT_INTEGRATION_FILES: tuple[str, ...] = (
    "/integration/pipeline_engine/test_blocked_exit.py",
    "/integration/pipeline_engine/test_orchestrator_trennlinie.py",
)


def _is_postgres_integration_item(path: str, nodeid: str) -> bool:
    """Return True if the collected item genuinely exercises Postgres.

    Args:
        path: The forward-slash-normalised filesystem path of the item.
        nodeid: The pytest node id of the item (``file::Class::test``), with
            backslashes normalised to forward slashes.

    Returns:
        True iff the item lives in a Postgres-using integration subtree and is
        not one of the explicit host-independent early-abort tests that reject
        before any StateBackend/DB access.
    """
    if not any(allow in path for allow in _POSTGRES_INTEGRATION_ALLOW_PATHS):
        return False
    if any(skip in path for skip in _POSTGRES_INDEPENDENT_INTEGRATION_FILES):
        return False
    return not any(
        nodeid.endswith(skip) for skip in _POSTGRES_INDEPENDENT_INTEGRATION_NODEIDS
    )


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        nodeid = item.nodeid.replace("\\", "/")
        if _is_postgres_integration_item(path, nodeid):
            item.fixturenames.append("postgres_isolated_schema")
