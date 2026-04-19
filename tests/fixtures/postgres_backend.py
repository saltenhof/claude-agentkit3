from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from typing import TYPE_CHECKING

import psycopg
import pytest

from agentkit.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Iterator


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_explicit_postgres_env() -> bool:
    return (
        os.environ.get("AGENTKIT_STATE_BACKEND") == "postgres"
        and bool(os.environ.get("AGENTKIT_STATE_DATABASE_URL"))
    )


@pytest.fixture(scope="session")
def postgres_container_url() -> Iterator[str]:
    if _is_explicit_postgres_env():
        yield str(os.environ["AGENTKIT_STATE_DATABASE_URL"])
        return

    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(
            "Postgres-backed contract/integration/e2e tests require either "
            "AGENTKIT_STATE_BACKEND=postgres with AGENTKIT_STATE_DATABASE_URL set "
            "or a local docker installation.",
        )

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

        yield url
    finally:
        subprocess.run(
            [docker, "rm", "-f", container_name],
            check=False,
            capture_output=True,
            text=True,
        )


@pytest.fixture()
def postgres_backend_env(
    monkeypatch: pytest.MonkeyPatch,
    postgres_container_url: str,
) -> Iterator[str]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "postgres")
    monkeypatch.setenv("AGENTKIT_STATE_DATABASE_URL", postgres_container_url)
    reset_backend_cache_for_tests()
    try:
        yield postgres_container_url
    finally:
        reset_backend_cache_for_tests()
        if "AGENTKIT_STATE_BACKEND" not in os.environ:
            monkeypatch.delenv("AGENTKIT_STATE_BACKEND", raising=False)
        if "AGENTKIT_STATE_DATABASE_URL" not in os.environ:
            monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)


@pytest.fixture(scope="session", autouse=False)
def postgres_runtime_env(postgres_container_url: str) -> Iterator[str]:
    previous_backend = os.environ.get("AGENTKIT_STATE_BACKEND")
    previous_url = os.environ.get("AGENTKIT_STATE_DATABASE_URL")
    os.environ["AGENTKIT_STATE_BACKEND"] = "postgres"
    os.environ["AGENTKIT_STATE_DATABASE_URL"] = postgres_container_url
    reset_backend_cache_for_tests()
    try:
        yield postgres_container_url
    finally:
        reset_backend_cache_for_tests()
        if previous_backend is None:
            os.environ.pop("AGENTKIT_STATE_BACKEND", None)
        else:
            os.environ["AGENTKIT_STATE_BACKEND"] = previous_backend

        if previous_url is None:
            os.environ.pop("AGENTKIT_STATE_DATABASE_URL", None)
        else:
            os.environ["AGENTKIT_STATE_DATABASE_URL"] = previous_url
