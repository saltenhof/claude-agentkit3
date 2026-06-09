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
import socket
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from psycopg import sql

from agentkit.state_backend.config import (
    SCHEMA_OVERRIDE_ALLOWED_ENV,
    SCHEMA_OVERRIDE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
)
from agentkit.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Iterator


# public registry table for crash-backstop sweeping (story §2.1.5).
_REGISTRY_TABLE = "ak3_test_schema_registry"
# matches the resolver's reserved namespace (config._TEST_SCHEMA_NAME_PATTERN).
_TEST_SCHEMA_PATTERN = re.compile(r"^ak3test_[a-z0-9_]+$")
_TTL_SWEEP_INTERVAL = "24 hours"
_PUBLIC_DDL_LOCK_KEY = "agentkit_postgres_test_public_ddl"
_TEST_POSTGRES_CONTAINER_LABEL = "ak3-test-postgres"
_TEST_POSTGRES_CONTAINER_LABEL_VALUE = "1"
_TEST_POSTGRES_CONTAINER_NAME_PREFIX = "ak3-postgres-"
_TEST_POSTGRES_CONTAINER_NAME_PATTERN = re.compile(r"^ak3-postgres-[0-9a-f]{12}$")
_TEST_POSTGRES_CONTAINER_TTL_SECONDS = 2 * 60 * 60
_DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<prefix>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})$",
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_explicit_postgres_env() -> bool:
    return os.environ.get(STATE_BACKEND_ENV) == "postgres" and bool(
        os.environ.get(STATE_DATABASE_URL_ENV),
    )


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
    """Return the BASE TABLE names of *schema* (registry lives in public)."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (schema,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _truncate_schema(url: str, schema: str) -> None:
    """TRUNCATE every base table of *schema* (RESTART IDENTITY CASCADE)."""
    with psycopg.connect(url, autocommit=True) as conn:
        tables = _base_tables(conn, schema)
        if not tables:
            return
        target = sql.SQL(", ").join(
            sql.Identifier(schema, table) for table in tables
        )
        conn.execute(
            sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(target),
        )


@pytest.fixture(scope="session")
def postgres_container_url() -> Iterator[str]:
    if _is_explicit_postgres_env():
        url = str(os.environ[STATE_DATABASE_URL_ENV])
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

    _sweep_stale_test_postgres_containers(docker)

    port = _find_free_port()
    container_name = f"ak3-postgres-{uuid.uuid4().hex[:12]}"
    user = "agentkit"
    password = "agentkit"
    database = "agentkit_test"
    url = f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}"

    subprocess.run(
        [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "--label",
            f"{_TEST_POSTGRES_CONTAINER_LABEL}={_TEST_POSTGRES_CONTAINER_LABEL_VALUE}",
            "-e",
            f"POSTGRES_USER={user}",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-e",
            f"POSTGRES_DB={database}",
            "-p",
            f"{port}:5432",
            "postgres:17-alpine",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    try:
        ready = False
        for _ in range(60):
            probe = subprocess.run(
                [
                    docker,
                    "exec",
                    container_name,
                    "pg_isready",
                    "-U",
                    user,
                    "-d",
                    database,
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                try:
                    with psycopg.connect(url) as conn, conn.cursor() as cur:
                        cur.execute("select 1")
                        cur.fetchone()
                    ready = True
                    break
                except psycopg.Error:
                    pass
            time.sleep(0.5)

        if not ready:
            raise RuntimeError(
                "postgres test container did not become ready in time",
            )

        _sweep_stale_test_schemas(url)
        yield url
    finally:
        subprocess.run(
            [docker, "rm", "-f", "-v", container_name],
            check=False,
            capture_output=True,
            text=True,
        )


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
        from agentkit.state_backend import postgres_store

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
    _truncate_schema(url, schema)
    try:
        yield url
    finally:
        _truncate_schema(url, schema)
        reset_backend_cache_for_tests()


@pytest.fixture()
def postgres_backend_env(postgres_isolated_schema: str) -> Iterator[str]:
    """Backward-compatible alias for tests that bind the isolation fixture by name.

    Existing contract tests reference ``postgres_backend_env`` as a parameter and
    only need the per-test isolated Postgres backend (they ignore the yielded
    value). It now delegates to :func:`postgres_isolated_schema`.
    """
    yield postgres_isolated_schema
