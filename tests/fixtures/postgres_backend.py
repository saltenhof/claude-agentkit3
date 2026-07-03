"""Postgres test-backend fixtures with worker-scoped schema isolation.

AG3-051: every Postgres-backed suite (integration, contract, e2e) shares a
disposable, worker-scoped test schema (``ak3test_<runtoken>_<worker>``) instead
of the production-versioned schema. Per-test hygiene (env -> cache clear ->
TRUNCATE -> yield -> TRUNCATE -> cache clear) guarantees fixed ids such as
``TEST-001`` are fresh in every test, so the previously shared-row coupling that
forced the heavy smoke tests to stay gated no longer exists.

Schema lifecycle (honest, three-tiered cleanup — story §2.1.5):

* **Worker-scoped** fixture: creates the schema once per xdist worker, bootstraps
  the canonical DDL once, records the schema in ``public.ak3_test_schema_registry``
  and DROPs it (``DROP SCHEMA ... CASCADE`` + registry delete) on a clean finalizer.
* **Session-start sweep**: drops only registry schemas older than 24h (DB-side
  clock) as a crash backstop.
* **Structural**: the default Docker path removes the container and its anonymous
  data volume via ``docker rm -f -v`` on clean teardown. It also labels test
  containers and runs a label/name-scoped TTL reaper at session start, so
  containers left behind by crashed sessions are removed on the next run.

The ``runtoken`` is the xdist-provided ``testrun_uid`` (identical across all
workers of ONE run, unique between runs) — no self-built controller->worker
propagation. ``<worker>`` comes from ``PYTEST_XDIST_WORKER`` (``_local`` when
running serially without xdist).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import psycopg
import pytest
from psycopg import sql

from agentkit.backend.state_backend.config import (
    SCHEMA_OVERRIDE_ALLOWED_ENV,
    SCHEMA_OVERRIDE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
)
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Iterator


# public registry table for crash-backstop sweeping (story §2.1.5).
_REGISTRY_TABLE = "ak3_test_schema_registry"
# matches the resolver's reserved namespace (config._TEST_SCHEMA_NAME_PATTERN).
_TEST_SCHEMA_PATTERN = re.compile(r"^ak3test_[a-z0-9_]+$")
_TTL_SWEEP_INTERVAL = "24 hours"
_PUBLIC_DDL_LOCK_KEY = "agentkit_postgres_test_public_ddl"
# Migration-cursor table that records the applied analytics schema versions
# (3.4/3.5/3.6, FK-62 §62.4.3). It is a schema/migration MARKER, not per-test
# data, so it is deliberately EXEMPT from the per-test TRUNCATE: keeping its rows
# lets the store's ``_schema_is_bootstrapped`` fast-path return True (its
# ``_analytics_versions_are_recorded`` probe stays satisfied), so the first store
# op of each Postgres test no longer replays the full ~55-table canonical DDL
# bootstrap. Emptying it (the prior coupling) forced a full re-bootstrap per test
# AND turned the analytics migration/fact-reconcile off — the exact regression this
# exemption avoids. Structural drift (a dropped table / mis-shaped fact_*) is still
# caught by the OTHER bootstrap canaries, so a genuinely stale schema still
# re-bootstraps. Test-data isolation is unaffected: schema_versions holds no
# per-test rows, and the value is identical for every test on the same schema.
_MIGRATION_MARKER_TABLES: frozenset[str] = frozenset({"schema_versions"})
_TEST_POSTGRES_CONTAINER_LABEL = "ak3-test-postgres"
_TEST_POSTGRES_CONTAINER_LABEL_VALUE = "1"
_TEST_POSTGRES_CONTAINER_NAME_PREFIX = "ak3-postgres-"
_TEST_POSTGRES_CONTAINER_NAME_PATTERN = re.compile(r"^ak3-postgres-[0-9a-f]{12}$")
_TEST_POSTGRES_CONTAINER_TTL_SECONDS = 2 * 60 * 60
_RESERVED_PRODUCTION_POSTGRES_PORT = 5432
_RESERVED_PRODUCTION_POSTGRES_PORT_ERROR = (
    "tests must not run against the reserved production standard port 5432; "
    f"point {STATE_DATABASE_URL_ENV} at a non-5432 ephemeral test instance"
)
# Connection-churn hardening: the SINGLE shared local Postgres instance. The docker
# path create-or-REUSES this one stable container (fixed name + host port, no
# ``--rm``, never removed on teardown) instead of spawning an ephemeral
# ``ak3-postgres-<uuid>`` per pytest session — so a machine runs at most ONE local
# test DB regardless of how many sessions/workers execute. It is strictly separate
# from the CI instance (``agentkit-postgres-ci``, docker-internal only): a distinct
# host port (55442, not the CI 55432) so the two never collide even while both run on
# one machine. It carries NO reapable test label and its name is not the ephemeral
# 12-hex form, so neither container reaper removes it (see _is_reapable_test_container).
# Per-run/per-worker isolation stays schema-level (ak3test_<runtoken>_<worker>).
_SHARED_LOCAL_POSTGRES_CONTAINER_NAME = "ak3-postgres-local"
_SHARED_LOCAL_POSTGRES_HOST_PORT = 55442
_SHARED_LOCAL_POSTGRES_USER = "agentkit"
_SHARED_LOCAL_POSTGRES_PASSWORD = "agentkit"
_SHARED_LOCAL_POSTGRES_DB = "agentkit_test"
_SHARED_LOCAL_POSTGRES_IMAGE = "postgres:17-alpine"
_EXPLICIT_BACKEND_AT_IMPORT = os.environ.get(STATE_BACKEND_ENV)
_EXPLICIT_URL_AT_IMPORT = os.environ.get(STATE_DATABASE_URL_ENV)
_DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<prefix>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})$",
)


def _ensure_non_reserved_test_postgres_port(port: int | None) -> int:
    """Return *port* unless it is the reserved production Postgres port."""
    if port is None:
        raise RuntimeError(
            "Postgres-backed tests must use an explicit non-5432 ephemeral port; "
            f"point {STATE_DATABASE_URL_ENV} at a non-5432 ephemeral test instance",
        )
    if port == _RESERVED_PRODUCTION_POSTGRES_PORT:
        raise RuntimeError(_RESERVED_PRODUCTION_POSTGRES_PORT_ERROR)
    return port


def _ensure_explicit_postgres_url_uses_test_port(url: str) -> None:
    """Fail closed if an explicit test Postgres URL targets production port 5432."""
    try:
        port = urlparse(url).port
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid {STATE_DATABASE_URL_ENV} port in explicit Postgres test URL.",
        ) from exc
    _ensure_non_reserved_test_postgres_port(port)


def _is_explicit_postgres_env() -> bool:
    return _EXPLICIT_BACKEND_AT_IMPORT == "postgres" and bool(_EXPLICIT_URL_AT_IMPORT)


def _is_reapable_test_container(
    name: str,
    label_value: str | None,
    age_seconds: float,
    ttl_seconds: float = _TEST_POSTGRES_CONTAINER_TTL_SECONDS,
) -> bool:
    """Return whether a Docker container belongs to this fixture and is stale."""
    has_test_label = label_value == _TEST_POSTGRES_CONTAINER_LABEL_VALUE
    has_legacy_test_name = _TEST_POSTGRES_CONTAINER_NAME_PATTERN.fullmatch(name) is not None
    return age_seconds > ttl_seconds and (has_test_label or has_legacy_test_name)


def _normalize_container_name(raw_name: object) -> str:
    return str(raw_name).removeprefix("/")


def _parse_docker_timestamp(raw_value: object) -> datetime | None:
    raw_text = str(raw_value)
    if not raw_text or raw_text.startswith("0001-"):
        return None

    match = _DOCKER_TIMESTAMP_PATTERN.fullmatch(raw_text)
    if match is None:
        return None

    timezone_suffix = "+00:00" if match["tz"] == "Z" else match["tz"]
    fraction = match["fraction"]
    if fraction is None:
        normalized = f"{match['prefix']}{timezone_suffix}"
    else:
        normalized = f"{match['prefix']}.{fraction[:6].ljust(6, '0')}{timezone_suffix}"
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _container_started_or_created_at(container: dict[str, Any]) -> datetime | None:
    state = container.get("State")
    state_data = state if isinstance(state, dict) else {}
    return _parse_docker_timestamp(state_data.get("StartedAt")) or _parse_docker_timestamp(
        container.get("Created"),
    )


def _docker_container_ids(docker: str, docker_filter: str) -> list[str]:
    result = subprocess.run(
        [
            docker,
            "ps",
            "-a",
            "--filter",
            docker_filter,
            "--format",
            "{{.ID}}\t{{.Names}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.split("\t", maxsplit=1)[0] for line in result.stdout.splitlines() if line.strip()]


def _inspect_container(docker: str, container_id: str) -> dict[str, Any] | None:
    result = subprocess.run(
        [docker, "inspect", container_id],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        containers = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(containers, list) or not containers or not isinstance(containers[0], dict):
        return None
    return containers[0]


def _container_label_value(container: dict[str, Any]) -> str | None:
    config = container.get("Config")
    config_data = config if isinstance(config, dict) else {}
    labels = config_data.get("Labels")
    labels_data = labels if isinstance(labels, dict) else {}
    value = labels_data.get(_TEST_POSTGRES_CONTAINER_LABEL)
    return str(value) if value is not None else None


def _sweep_stale_test_postgres_containers(docker: str) -> None:
    """Remove stale fixture-owned Postgres containers and anonymous volumes."""
    container_ids = {
        *_docker_container_ids(
            docker,
            f"label={_TEST_POSTGRES_CONTAINER_LABEL}={_TEST_POSTGRES_CONTAINER_LABEL_VALUE}",
        ),
        *_docker_container_ids(docker, f"name={_TEST_POSTGRES_CONTAINER_NAME_PREFIX}"),
    }
    now = datetime.now(UTC)

    for container_id in container_ids:
        container = _inspect_container(docker, container_id)
        if container is None:
            continue
        name = _normalize_container_name(container.get("Name", ""))
        created_or_started_at = _container_started_or_created_at(container)
        if created_or_started_at is None:
            continue
        age_seconds = (now - created_or_started_at).total_seconds()
        if not _is_reapable_test_container(
            name,
            _container_label_value(container),
            age_seconds,
        ):
            continue
        subprocess.run(
            [docker, "rm", "-f", "-v", container_id],
            check=False,
            capture_output=True,
            text=True,
        )


def _sanitize_schema_token(raw: str) -> str:
    """Reduce an arbitrary token to ``[a-z0-9_]`` so the schema name is valid."""
    return re.sub(r"[^a-z0-9_]", "_", raw.lower())


def _worker_schema_name(testrun_uid: str) -> str:
    """Build the reserved-namespace schema name for the current xdist worker.

    Args:
        testrun_uid: The xdist run token (identical across workers of one run).

    Returns:
        A ``ak3test_<runtoken>_<worker>`` name matching the resolver's
        ``^ak3test_[a-z0-9_]+$`` pattern.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "_local")
    name = f"ak3test_{_sanitize_schema_token(testrun_uid)}_{_sanitize_schema_token(worker)}"
    if _TEST_SCHEMA_PATTERN.fullmatch(name) is None:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Derived test schema {name!r} violates the reserved ak3test_ namespace.",
        )
    return name


def _ensure_registry_table(conn: psycopg.Connection[Any]) -> None:
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (_PUBLIC_DDL_LOCK_KEY,))
    try:
        conn.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS public.{} ("
                "schema_name TEXT PRIMARY KEY, "
                "run_token TEXT, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")",
            ).format(sql.Identifier(_REGISTRY_TABLE)),
        )
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_PUBLIC_DDL_LOCK_KEY,))


def _sweep_stale_test_schemas(url: str) -> None:
    """Drop registry schemas older than the TTL (crash backstop, story §2.1.5).

    WARNING (deferrable, story §2.1.5 / Codex WARNING 1): the TTL sweep is NOT a
    race-freedom guarantee. A run > 24h, a paused debugger or a hung worker on a
    SHARED persistent CI Postgres could in theory drop a still-live schema. The
    primary reaper is the worker finalizer plus a disposable DB per run. If the
    CI is pinned to a shared persistent instance, a heartbeat/last_seen ownership
    model is required as a follow-up story.
    """
    with psycopg.connect(url, autocommit=True) as conn:
        _ensure_registry_table(conn)
        stale = conn.execute(
            sql.SQL(
                "SELECT schema_name FROM public.{} "
                "WHERE created_at < now() - interval {}",
            ).format(
                sql.Identifier(_REGISTRY_TABLE),
                sql.Literal(_TTL_SWEEP_INTERVAL),
            ),
        ).fetchall()
        for (schema_name,) in stale:
            if _TEST_SCHEMA_PATTERN.fullmatch(str(schema_name)) is None:
                continue
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(str(schema_name)),
                ),
            )
            conn.execute(
                sql.SQL("DELETE FROM public.{} WHERE schema_name = %s").format(
                    sql.Identifier(_REGISTRY_TABLE),
                ),
                (schema_name,),
            )


def _base_tables(conn: psycopg.Connection[Any], schema: str) -> list[str]:
    """Return the BASE TABLE names of *schema* (registry lives in public).

    Reads column ``table_name`` by NAME (not positional ``row[0]``): this runs on
    the shared pooled connection, whose ``row_factory`` is ``dict_row``, so rows are
    mappings keyed by column name.
    """
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (schema,),
    ).fetchall()
    return [str(row["table_name"]) for row in rows]


def _truncate_schema(schema: str) -> None:
    """TRUNCATE every base table of *schema* (RESTART IDENTITY CASCADE).

    Runs on the SHARED pooled connection (the ``postgres_store`` process pool)
    instead of opening a fresh connect-per-call connection, so per-test truncation
    adds no connection churn and a worker holds exactly ONE physical DB connection.
    Uses the bootstrap-SKIPPING borrow (``_borrow_pooled_connection_raw``): running
    the schema bootstrap here would cache the schema as "bootstrapped" BEFORE this
    TRUNCATE, wrongly suppressing the re-bootstrap the next store operation must
    perform after a structural change. Tables are referenced by qualified
    ``schema.table`` identifiers, so the result is independent of the connection's
    ``search_path``.

    The migration-marker tables (``schema_versions``) are EXEMPT
    (:data:`_MIGRATION_MARKER_TABLES`): they carry no per-test data, and keeping
    their rows lets the store's ``_schema_is_bootstrapped`` fast-path hold, so the
    full canonical DDL bootstrap no longer re-runs on every Postgres test.
    """
    from agentkit.backend.state_backend import postgres_store

    with postgres_store._borrow_pooled_connection_raw() as conn:
        tables = [
            table
            for table in _base_tables(conn, schema)
            if table not in _MIGRATION_MARKER_TABLES
        ]
        if not tables:
            return
        target = sql.SQL(", ").join(sql.Identifier(schema, table) for table in tables)
        conn.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(target),
        )


#: Process-local memo of the reachability probe. Reachability of the shared test
#: instance is stable for the lifetime of a test process (the shared local
#: container persists across sessions), so the probe runs at most ONCE per process
#: instead of once per opt-in Postgres unit test — a suite where the DB is down then
#: skips its whole Postgres branch after a single short-timeout probe, not one
#: probe per parametrised test.
_SHARED_POSTGRES_REACHABLE: bool | None = None


def shared_postgres_reachable(connect_timeout: float = 2.0) -> bool:
    """Return whether the shared test Postgres accepts a connection quickly.

    Fast, fail-closed reachability probe for opt-in Postgres UNIT tests. It
    resolves the SAME DSN the session fixture would use — an explicit
    ``AGENTKIT_STATE_DATABASE_URL`` when set, otherwise the single shared local
    instance (only when a docker binary is present) — and attempts ONE
    short-timeout connect. Returning ``False`` lets a unit test ``pytest.skip``
    cleanly and immediately, instead of driving the heavy session fixture
    (container start + up-to-30s readiness poll) into a ``RuntimeError`` when no
    instance is up. The PG-available path is unaffected: a reachable instance
    returns ``True`` and the test runs the real driver. Integration / contract
    suites keep using the full fixture chain unchanged.

    The result is memoised per process (:data:`_SHARED_POSTGRES_REACHABLE`): the
    connect probe fires at most once, so the whole Postgres branch of a unit suite
    skips fast when the DB is down instead of paying the timeout on every
    parametrised test.

    Args:
        connect_timeout: Per-attempt connect timeout in seconds (bounds an
            unreachable host so the probe never blocks on the OS default). Only
            honoured on the first (uncached) call.

    Returns:
        ``True`` when a ``SELECT 1`` round-trips within the timeout, else
        ``False``.
    """
    global _SHARED_POSTGRES_REACHABLE
    if _SHARED_POSTGRES_REACHABLE is not None:
        return _SHARED_POSTGRES_REACHABLE
    _SHARED_POSTGRES_REACHABLE = _probe_shared_postgres(connect_timeout)
    return _SHARED_POSTGRES_REACHABLE


def _probe_shared_postgres(connect_timeout: float) -> bool:
    if _is_explicit_postgres_env():
        url = str(_EXPLICIT_URL_AT_IMPORT)
    elif shutil.which("docker") is not None:
        url = _shared_local_postgres_url()
    else:
        return False
    try:
        with psycopg.connect(url, connect_timeout=connect_timeout) as conn:
            conn.execute("SELECT 1")
    except (psycopg.Error, OSError):
        return False
    return True


def _shared_local_postgres_url() -> str:
    """Return the DSN of the single shared local Postgres instance (fail-closed port)."""
    port = _ensure_non_reserved_test_postgres_port(_SHARED_LOCAL_POSTGRES_HOST_PORT)
    return (
        f"postgresql://{_SHARED_LOCAL_POSTGRES_USER}:{_SHARED_LOCAL_POSTGRES_PASSWORD}"
        f"@127.0.0.1:{port}/{_SHARED_LOCAL_POSTGRES_DB}"
    )


def _container_state(docker: str, name: str) -> str | None:
    """Return a container's ``.State.Status`` (e.g. ``running``), or None if absent."""
    result = subprocess.run(
        [docker, "inspect", "--format", "{{.State.Status}}", name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _start_shared_local_container(docker: str) -> None:
    """Create-or-reuse the single stable shared local Postgres container.

    Fixed name + host port, no ``--rm``, NO reapable test label — so it survives
    across pytest sessions and neither container reaper removes it. Race-safe for
    concurrent xdist workers: a name collision on ``docker run`` means a concurrent
    worker created it first, and the container is reused.
    """
    name = _SHARED_LOCAL_POSTGRES_CONTAINER_NAME
    status = _container_state(docker, name)
    if status == "running":
        return
    if status is not None:
        subprocess.run([docker, "start", name], check=False, capture_output=True, text=True)
        return
    result = subprocess.run(
        [
            docker,
            "run",
            "-d",
            "--name",
            name,
            "-e",
            f"POSTGRES_USER={_SHARED_LOCAL_POSTGRES_USER}",
            "-e",
            f"POSTGRES_PASSWORD={_SHARED_LOCAL_POSTGRES_PASSWORD}",
            "-e",
            f"POSTGRES_DB={_SHARED_LOCAL_POSTGRES_DB}",
            "-p",
            f"{_SHARED_LOCAL_POSTGRES_HOST_PORT}:5432",
            _SHARED_LOCAL_POSTGRES_IMAGE,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return
    # A concurrent worker may have won the name (create race) — reuse if now present.
    status = _container_state(docker, name)
    if status == "running":
        return
    if status is not None:
        subprocess.run([docker, "start", name], check=False, capture_output=True, text=True)
        return
    raise RuntimeError(
        f"failed to start shared local Postgres container {name!r}: "
        f"{result.stderr.strip() or result.stdout.strip()}",
    )


def _wait_for_shared_local_postgres_ready(docker: str, url: str) -> None:
    """Block until the shared local Postgres accepts connections (fail-closed)."""
    for _ in range(60):
        probe = subprocess.run(
            [
                docker,
                "exec",
                _SHARED_LOCAL_POSTGRES_CONTAINER_NAME,
                "pg_isready",
                "-U",
                _SHARED_LOCAL_POSTGRES_USER,
                "-d",
                _SHARED_LOCAL_POSTGRES_DB,
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            try:
                with psycopg.connect(url) as conn, conn.cursor() as cur:
                    cur.execute("select 1")
                    cur.fetchone()
                return
            except psycopg.Error:
                pass
        time.sleep(0.5)
    raise RuntimeError(
        "shared local postgres container did not become ready in time",
    )


def _ensure_shared_local_postgres(docker: str) -> str:
    """Ensure the single shared local Postgres instance is up and return its DSN."""
    url = _shared_local_postgres_url()
    _start_shared_local_container(docker)
    _wait_for_shared_local_postgres_ready(docker, url)
    return url


@pytest.fixture(scope="session")
def postgres_container_url() -> Iterator[str]:
    if _is_explicit_postgres_env():
        url = str(_EXPLICIT_URL_AT_IMPORT)
        _ensure_explicit_postgres_url_uses_test_port(url)
        _sweep_stale_test_schemas(url)
        yield url
        return

    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(
            "Postgres-backed contract/integration/e2e tests require either "
            "AGENTKIT_STATE_BACKEND=postgres with AGENTKIT_STATE_DATABASE_URL set "
            "or a local docker installation.",
        )

    # Reap only pre-change ephemeral ``ak3-postgres-<uuid>`` leftovers; the shared
    # local instance is protected (no reapable label, name is not the 12-hex form).
    _sweep_stale_test_postgres_containers(docker)

    url = _ensure_shared_local_postgres(docker)
    _sweep_stale_test_schemas(url)
    # No teardown: the shared local instance is STABLE and reused across sessions —
    # never removed here (that reuse is the whole point of AC2 / two-instance model).
    yield url


@pytest.fixture(scope="session")
def postgres_worker_schema(
    postgres_container_url: str,
    testrun_uid: str,
) -> Iterator[tuple[str, str]]:
    """Create a worker-scoped test schema, bootstrap its DDL once, drop on exit.

    Yields the ``(database_url, schema_name)`` pair. The schema is created, the
    canonical DDL is bootstrapped exactly once (via the production schema owner,
    so test and production DDL never diverge), and the schema is registered in
    ``public.ak3_test_schema_registry``. The finalizer drops the schema CASCADE
    and removes its registry row.

    Args:
        postgres_container_url: The session Postgres DSN.
        testrun_uid: xdist run token (identical across this run's workers).
    """
    schema = _worker_schema_name(testrun_uid)
    url = postgres_container_url

    with psycopg.connect(url, autocommit=True) as conn:
        _ensure_registry_table(conn)
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)),
        )
        conn.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)),
        )
        conn.execute(
            sql.SQL(
                "INSERT INTO public.{} (schema_name, run_token) VALUES (%s, %s) "
                "ON CONFLICT (schema_name) DO UPDATE SET run_token = EXCLUDED.run_token",
            ).format(sql.Identifier(_REGISTRY_TABLE)),
            (schema, testrun_uid),
        )

    # Bootstrap the canonical DDL ONCE into the test schema, via the production
    # connection path under the override gate (so the schema resolves to ``schema``).
    previous = {
        STATE_BACKEND_ENV: os.environ.get(STATE_BACKEND_ENV),
        STATE_DATABASE_URL_ENV: os.environ.get(STATE_DATABASE_URL_ENV),
        SCHEMA_OVERRIDE_ENV: os.environ.get(SCHEMA_OVERRIDE_ENV),
        SCHEMA_OVERRIDE_ALLOWED_ENV: os.environ.get(SCHEMA_OVERRIDE_ALLOWED_ENV),
    }
    os.environ[STATE_BACKEND_ENV] = "postgres"
    os.environ[STATE_DATABASE_URL_ENV] = url
    os.environ[SCHEMA_OVERRIDE_ENV] = schema
    os.environ[SCHEMA_OVERRIDE_ALLOWED_ENV] = "1"
    reset_backend_cache_for_tests()
    try:
        from agentkit.backend.state_backend import postgres_store

        with postgres_store._connect_global():
            # _connect_global runs ensure_versioned_schema + _ensure_schema,
            # creating the full canonical DDL inside the test schema.
            pass
    finally:
        reset_backend_cache_for_tests()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    try:
        yield url, schema
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema),
                ),
            )
            _ensure_registry_table(conn)
            conn.execute(
                sql.SQL("DELETE FROM public.{} WHERE schema_name = %s").format(
                    sql.Identifier(_REGISTRY_TABLE),
                ),
                (schema,),
            )


@pytest.fixture()
def postgres_isolated_schema(
    postgres_worker_schema: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Per-test Postgres isolation against the worker-scoped test schema.

    Order (story §2.1.3): set env (backend=postgres, URL, override) ->
    clear backend cache -> TRUNCATE base tables -> yield -> TRUNCATE ->
    clear backend cache. Fixed ids such as ``TEST-001`` are therefore fresh in
    every test.

    Yields the database URL (so call sites that bind it as a parameter keep
    working).
    """
    url, schema = postgres_worker_schema
    monkeypatch.setenv(STATE_BACKEND_ENV, "postgres")
    monkeypatch.setenv(STATE_DATABASE_URL_ENV, url)
    monkeypatch.setenv(SCHEMA_OVERRIDE_ENV, schema)
    monkeypatch.setenv(SCHEMA_OVERRIDE_ALLOWED_ENV, "1")
    reset_backend_cache_for_tests()
    _truncate_schema(schema)
    try:
        yield url
    finally:
        _truncate_schema(schema)
        reset_backend_cache_for_tests()


@pytest.fixture()
def postgres_backend_env(postgres_isolated_schema: str) -> Iterator[str]:
    """Backward-compatible alias for tests that bind the isolation fixture by name.

    Existing contract tests reference ``postgres_backend_env`` as a parameter and
    only need the per-test isolated Postgres backend (they ignore the yielded
    value). It now delegates to :func:`postgres_isolated_schema`.
    """
    yield postgres_isolated_schema
