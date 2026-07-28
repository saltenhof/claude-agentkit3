"""Unit: the registered MCP entry really starts, and its env is complete.

This is the test that would have caught the near-miss in AG3-175's own planning
round. "The entry is well-formed" and "the entry starts a server" are different
claims, and AC 1 / AC 4 assert the second one.

It derives its truth from the PROCESS rather than from a restated key list, so it
cannot drift away from what the entry point actually requires:

* :func:`test_rendered_entry_reaches_the_connect_layer` starts the rendered
  command and asserts the failure comes from the Weaviate CONNECT layer — which
  sits immediately after every environment check in
  ``vectordb.engine.compose_runtime``. Reaching it proves the module is
  executable AND the environment is complete.
* :func:`test_missing_env_key_matrix` drops one key at a time and pins the named
  failure each produces.

Scope, honestly bounded: the tests execute the rendered ``args`` with
``sys.executable``. They therefore prove the ARGS name an executable module and
the ENV satisfies it. They do NOT prove that the rendered ``command``
(``"python"``) resolves on an arbitrary target project's ``PATH`` — that is an
installation precondition, and command resolution itself is AG3-164's tested
concern (``mcp_conformance.process.resolve_command``).

No network: the endpoints deliberately carry a non-``http(s)`` scheme, so the
connect layer fails on the endpoint FORM instead of waiting for a TCP timeout
(measured: ~0.4 s instead of ~3.2 s, and no socket is opened).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types.mcp_server_registration import REGISTERED_ENV_KEYS
from agentkit.backend.installer.mcp_conformance.process import build_minimal_env
from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    build_registration_env,
)

if TYPE_CHECKING:
    from pathlib import Path

#: Endpoint with a deliberately non-http scheme: accepted by ``RuntimeBinding``
#: (non-empty, not a forbidden localhost default) but rejected by the connect
#: layer immediately and without any socket operation.
_UNROUTABLE_HTTP = "ftp://vectors.invalid:1"
_UNROUTABLE_GRPC = "vectors.invalid:2"

#: The library module CP 10 used to register. Kept here so the contrast that
#: makes this test meaningful is explicit and checkable.
_LIBRARY_MODULE_ARGS: tuple[str, ...] = ("-m", "agentkit.backend.vectordb.mcp_server")

_PROCESS_TIMEOUT_SECONDS = 120


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "concepts").mkdir(parents=True)
    (root / "stories").mkdir(parents=True)
    return root


def _rendered_env(root: Path) -> dict[str, str]:
    return build_registration_env(
        project_id="AG3",
        weaviate_http_endpoint=_UNROUTABLE_HTTP,
        weaviate_grpc_endpoint=_UNROUTABLE_GRPC,
        concepts_dir=str(root / "concepts"),
        stories_dir=str(root / "stories"),
    )


def _run(
    root: Path,
    env: dict[str, str],
    args: tuple[str, ...] = STORY_KNOWLEDGE_BASE_ARGS,
) -> subprocess.CompletedProcess[str]:
    """Start the entry point the way the conformance probe would.

    The child environment is built with the PRODUCTION helper
    ``build_minimal_env``, so the base platform keys the process needs (``PATH``,
    ``USERPROFILE``, ...) are present exactly as they are in a real probe.
    """
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, *args],
        env=build_minimal_env(env),
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=_PROCESS_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    """Return the ``detail`` of the entry point's fail-closed JSON report."""
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["error"] == "composition_failed"
    detail = payload["detail"]
    assert isinstance(detail, str)
    return detail


def test_rendered_entry_reaches_the_connect_layer(tmp_path: Path) -> None:
    """The registered entry is executable AND its env is complete.

    Reaching the Weaviate connect layer proves both at once: the module runs a
    server composition (a library module would exit 0 doing nothing), and every
    environment check upstream of the connection passed.
    """
    root = _project(tmp_path)
    result = _run(root, _rendered_env(root))

    assert result.returncode == 1, result.stdout + result.stderr
    detail = _failure_detail(result)
    assert "WEAVIATE_HTTP_ENDPOINT" in detail
    assert "must be http(s)://host:port" in detail
    # Crucially NOT an environment complaint: nothing was missing.
    assert "is missing" not in detail
    assert "has no default" not in detail


def test_library_module_would_exit_zero_without_serving(tmp_path: Path) -> None:
    """The contrast that makes the test above meaningful.

    ``...vectordb.mcp_server`` is a library module: executing it as ``-m`` runs
    the module body and exits 0 with no output, which the AG3-164 gate reports as
    ``mcp_process_exited``. This pins the defect class so a future change back to
    the library module cannot pass silently.
    """
    root = _project(tmp_path)
    result = _run(root, _rendered_env(root), args=_LIBRARY_MODULE_ARGS)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.parametrize(
    ("dropped", "needle"),
    [
        ("PROJECT_ID", "required env key 'PROJECT_ID' is missing"),
        (
            "WEAVIATE_HTTP_ENDPOINT",
            "required env key 'WEAVIATE_HTTP_ENDPOINT' is missing",
        ),
        (
            "WEAVIATE_GRPC_ENDPOINT",
            "required env key 'WEAVIATE_GRPC_ENDPOINT' is missing",
        ),
        (
            "AGENTKIT_CONCEPTS_DIR",
            "AGENTKIT_CONCEPTS_DIR is missing/empty",
        ),
    ],
)
def test_missing_env_key_matrix(tmp_path: Path, dropped: str, needle: str) -> None:
    """Each mandatory key produces its own named, fail-closed failure.

    Note the split: three keys are enforced by ``RuntimeBinding``, while
    ``AGENTKIT_CONCEPTS_DIR`` is enforced by the entry point itself and is
    therefore absent from ``REQUIRED_ENV_KEYS``. That asymmetry is exactly why
    the registration must satisfy the process rather than the validator.
    """
    root = _project(tmp_path)
    env = _rendered_env(root)
    del env[dropped]

    result = _run(root, env)

    assert result.returncode == 1
    assert needle in _failure_detail(result)


def test_stories_dir_is_the_only_optional_registered_key(tmp_path: Path) -> None:
    """Counter-probe: omitting it still reaches the connect layer (it defaults).

    This proves the other four are genuinely mandatory rather than merely
    rendered, and it documents WHY we still render this one explicitly: the
    default resolves against the process ``cwd``, and D2 forbids ``cwd`` from
    being a second configuration source.
    """
    root = _project(tmp_path)
    env = _rendered_env(root)
    del env["AGENTKIT_STORIES_DIR"]

    result = _run(root, env)

    assert result.returncode == 1
    detail = _failure_detail(result)
    assert "must be http(s)://host:port" in detail
    assert "is missing" not in detail


def test_every_registered_key_is_exercised_by_this_module() -> None:
    """Guard against a new registered key slipping past the matrix above."""
    covered = {
        "PROJECT_ID",
        "WEAVIATE_HTTP_ENDPOINT",
        "WEAVIATE_GRPC_ENDPOINT",
        "AGENTKIT_CONCEPTS_DIR",
        "AGENTKIT_STORIES_DIR",
    }
    assert set(REGISTERED_ENV_KEYS) == covered
