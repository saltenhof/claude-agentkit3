"""Contract test for the Postgres-only control-plane backend requirement (#3).

ERROR-3 (#3): the control-plane runtime store (operation/claim, session-binding
and lock records) is part of the canonical central PostgreSQL runtime persistence
(FK-22 §22.9) and has NO SQLite implementation -- the global control-plane row
methods exist ONLY on the postgres backend. The architecturally-correct behavior
is therefore Postgres-only-by-design: a productive ``ControlPlaneRuntimeService``
on a non-Postgres backend must fail CLOSED and CLEARLY at first store use with an
explicit "control-plane requires the Postgres backend" error -- NOT an opaque
``RuntimeError`` deep inside the atomic claim mid-call, and NEVER a silent no-op.

This is a pure, DB-free contract test (it only flips the backend env and asserts
the fail-closed error), so it stays off Docker/Postgres.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import PhaseMutationRequest
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _setup_request() -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id="op-backend-req-001",
    )


@pytest.mark.contract
def test_start_phase_on_sqlite_fails_closed_clearly(
    sqlite_backend_env: None,
) -> None:
    """#3: a default-store ``start_phase`` on SQLite fails closed with a clear error.

    The error must be an explicit, early ``ConfigError`` naming the Postgres
    requirement -- not an opaque ``RuntimeError`` deep inside the atomic claim, and
    not a silent no-op that skips the claim.
    """
    del sqlite_backend_env
    service = ControlPlaneRuntimeService()  # productive default repository

    with pytest.raises(ConfigError) as exc_info:
        service.start_phase(
            run_id="run-100", phase="setup", request=_setup_request()
        )

    message = str(exc_info.value)
    assert "control-plane" in message.lower()
    assert "postgres" in message.lower()
    assert "FK-22 §22.9" in message


@pytest.mark.contract
def test_every_default_store_entrypoint_fails_closed_on_sqlite(
    sqlite_backend_env: None,
) -> None:
    """#3: complete/fail/closure/get_operation all fail closed on SQLite too.

    The Postgres requirement is enforced consistently at every control-plane
    store entrypoint of the productive default service, never just ``start_phase``.
    """
    del sqlite_backend_env
    from agentkit.backend.control_plane.models import ClosureCompleteRequest

    service = ControlPlaneRuntimeService()

    with pytest.raises(ConfigError):
        service.complete_phase(
            run_id="run-100", phase="implementation", request=_setup_request()
        )
    with pytest.raises(ConfigError):
        service.fail_phase(
            run_id="run-100", phase="implementation", request=_setup_request()
        )
    with pytest.raises(ConfigError):
        service.complete_closure(
            run_id="run-100",
            request=ClosureCompleteRequest(
                project_key="tenant-a",
                story_id="AG3-100",
                session_id="sess-001",
                op_id="op-backend-req-closure",
            ),
        )
    with pytest.raises(ConfigError):
        service.get_operation("op-backend-req-001")
