"""Unit tests for the installer CP 7 idempotency / upgrade wiring (AG3-039).

Drives ``_run_cp7_state_backend_registration`` against an in-memory
``ProjectRegistrationRepository`` so the idempotency
(``register_project_is_idempotent``) and upgrade decision is verified without
the full ``install_agentkit`` resource deploy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.installer.registration import (
    CP7_STATE_BACKEND_REGISTRATION,
    REASON_CONFIG_DIGEST_UNCHANGED,
    REASON_INVALID_GITHUB_COORDINATES,
    REASON_MISSING_GITHUB_COORDINATES,
    CheckpointStatus,
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.backend.installer.runner import (
    InstallConfig,
    _canonical_config_digest,
    _run_cp7_state_backend_registration,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


class _InMemoryRepo:
    """Minimal in-memory ProjectRegistrationRepository for the CP 7 unit path."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}
        self.save_calls = 0
        self.upgrade_calls = 0

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        if registration.project_key in self.rows:
            raise AssertionError("save called for an already-registered project")
        self.rows[registration.project_key] = registration
        self.save_calls += 1

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(update={"last_verified_at": verified_at})

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(
            update={"last_upgraded_at": upgraded_at, "config_digest": new_digest}
        )
        self.upgrade_calls += 1

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[k] for k in sorted(self.rows)]


def _config(repo: _InMemoryRepo, root: Path, *, owner: str | None = "acme") -> InstallConfig:
    return InstallConfig(
        project_key="demo",
        project_name="Demo",
        project_root=root,
        github_owner=owner,
        github_repo="demo" if owner is not None else None,
        registration_repo=repo,
        runtime_profile=RuntimeProfile.CORE,
            weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
)


def test_first_run_creates_registration(tmp_path: Path) -> None:
    repo = _InMemoryRepo()
    yaml_data: dict[str, object] = {"project_key": "demo", "x": 1}
    result = _run_cp7_state_backend_registration(
        _config(repo, tmp_path), tmp_path, yaml_data
    )
    assert result.checkpoint == CP7_STATE_BACKEND_REGISTRATION
    assert result.status is CheckpointStatus.CREATED
    assert repo.save_calls == 1
    stored = repo.get("demo")
    assert stored is not None
    assert stored.config_digest == _canonical_config_digest(yaml_data)
    assert stored.github_owner == "acme"
    assert stored.runtime_profile is RuntimeProfile.CORE


def test_rerun_same_digest_is_skipped_no_rewrite(tmp_path: Path) -> None:
    repo = _InMemoryRepo()
    yaml_data: dict[str, object] = {"project_key": "demo", "x": 1}
    _run_cp7_state_backend_registration(_config(repo, tmp_path), tmp_path, yaml_data)
    # Second run with the IDENTICAL config -> idempotent SKIP, no second write.
    result = _run_cp7_state_backend_registration(
        _config(repo, tmp_path), tmp_path, yaml_data
    )
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_CONFIG_DIGEST_UNCHANGED
    assert repo.save_calls == 1
    assert repo.upgrade_calls == 0


def test_rerun_divergent_digest_upgrades(tmp_path: Path) -> None:
    repo = _InMemoryRepo()
    first: dict[str, object] = {"project_key": "demo", "x": 1}
    _run_cp7_state_backend_registration(_config(repo, tmp_path), tmp_path, first)
    # Changed config -> different digest -> UPDATED + last_upgraded_at set.
    second: dict[str, object] = {"project_key": "demo", "x": 2}
    result = _run_cp7_state_backend_registration(
        _config(repo, tmp_path), tmp_path, second
    )
    assert result.status is CheckpointStatus.UPDATED
    assert repo.upgrade_calls == 1
    stored = repo.get("demo")
    assert stored is not None
    assert stored.config_digest == _canonical_config_digest(second)
    assert stored.last_upgraded_at is not None


def test_missing_github_coords_fails_closed_without_write(tmp_path: Path) -> None:
    """FK-50 §50.3 CP 7 / §50.6: missing mandatory GitHub coordinates is FAILED.

    A SKIP here would leave the project UNREGISTERED after a "successful" install
    (fail-open). CP 7 must fail closed: status FAILED, a machine-readable reason,
    and NO write (no partial row, no fabricated coordinates).
    """
    repo = _InMemoryRepo()
    yaml_data: dict[str, object] = {"project_key": "demo"}
    result = _run_cp7_state_backend_registration(
        _config(repo, tmp_path, owner=None), tmp_path, yaml_data
    )
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_MISSING_GITHUB_COORDINATES
    assert repo.save_calls == 0
    assert repo.get("demo") is None


def test_empty_github_coords_fail_closed_without_write(tmp_path: Path) -> None:
    """FK-50 §50.3 CP 7: empty/whitespace-only coordinates are FAILED, no write.

    ``is None`` is not the only invalid coordinate: ``""`` / ``"   "`` carry no
    GitHub identity. Treating them as present (fail-open) would persist a
    meaningless ``project_registry`` row. They must be handled like missing
    coordinates: FAILED + machine-readable reason + NO write.
    """
    yaml_data: dict[str, object] = {"project_key": "demo"}
    for owner, repo_name in (("", "demo"), ("acme", "   "), ("  ", "")):
        repo = _InMemoryRepo()
        config = InstallConfig(
            project_key="demo",
            project_name="Demo",
            project_root=tmp_path,
            github_owner=owner,
            github_repo=repo_name,
            registration_repo=repo,
            runtime_profile=RuntimeProfile.CORE,
                weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
)
        result = _run_cp7_state_backend_registration(config, tmp_path, yaml_data)
        assert result.status is CheckpointStatus.FAILED
        assert result.reason == REASON_MISSING_GITHUB_COORDINATES
        assert repo.save_calls == 0
        assert repo.get("demo") is None


@pytest.mark.parametrize(
    ("owner", "repo_name"),
    [
        ("..", "demo"),  # path-traversal owner
        ("acme", ".."),  # path-traversal repo
        ("acme", "."),  # current-dir repo token
        ("acme", ".git"),  # ".git"-style bare hidden name => leading dot
        ("-bad", "demo"),  # leading-hyphen owner
        ("bad-", "demo"),  # trailing-hyphen owner
        ("a--b", "demo"),  # consecutive hyphens owner
        ("ac me", "demo"),  # embedded space owner
        ("acme/evil", "demo"),  # slash in owner
        ("acme\n", "demo"),  # trailing newline owner (ERROR-1)
        ("acme", "demo\n"),  # trailing newline repo (ERROR-1)
        ("a" * 40, "demo"),  # owner too long
        ("acme", "r" * 101),  # repo too long
    ],
)
def test_invalid_github_coords_fail_closed_without_write(
    tmp_path: Path, owner: str, repo_name: str
) -> None:
    """AG3-039 R7 ERROR-2: PRESENT-but-malformed coordinates are FAILED, no write.

    A direct ``_run_cp7_state_backend_registration`` call must not bypass the
    SSOT ``validate_github_coordinate`` predicate and persist an invalid row.
    The coordinates pass the None/empty guard but are structurally invalid =>
    CP 7 FAILED + ``REASON_INVALID_GITHUB_COORDINATES`` + NO write.
    """
    repo = _InMemoryRepo()
    yaml_data: dict[str, object] = {"project_key": "demo"}
    config = InstallConfig(
        project_key="demo",
        project_name="Demo",
        project_root=tmp_path,
        github_owner=owner,
        github_repo=repo_name,
        registration_repo=repo,
        runtime_profile=RuntimeProfile.CORE,
            weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
)
    result = _run_cp7_state_backend_registration(config, tmp_path, yaml_data)
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == REASON_INVALID_GITHUB_COORDINATES
    assert repo.save_calls == 0
    assert repo.get("demo") is None


def test_canonical_digest_is_order_insensitive() -> None:
    a: dict[str, object] = {"a": 1, "b": 2}
    b: dict[str, object] = {"b": 2, "a": 1}
    assert _canonical_config_digest(a) == _canonical_config_digest(b)
