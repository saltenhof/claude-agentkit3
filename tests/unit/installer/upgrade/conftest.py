"""Shared fixtures for the installer upgrade unit tests (AG3-089).

Provides an in-memory ``ProjectRegistrationRepository`` and a project.yaml
writer so the footprint / scenario / upgrade-flow tests run against ``tmp_path``
without a live state backend (unit-level isolation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile

if TYPE_CHECKING:
    from pathlib import Path


class InMemoryRegistrationRepo:
    """In-memory ``ProjectRegistrationRepository`` for unit isolation."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}
        self.upgrade_calls = 0

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(
            update={"last_verified_at": verified_at}
        )

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


def write_project_yaml(project_root: Path, data: dict[str, object]) -> Path:
    """Write ``.agentkit/config/project.yaml`` under ``project_root`` and return it."""
    from agentkit.backend.installer.paths import project_config_path

    path = project_config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


def valid_project_config_dict(
    *,
    config_version: str = "3.0",
    extra_pipeline: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Build a minimal VALID ``project.yaml`` mapping (AG3-070 SSOT shape).

    The version lives at the AG3-070 owner location ``pipeline.config_version``
    (not a top-level key). The mapping passes ``load_project_config`` so the
    footprint's owner-surface read (FK-51 §51.8 / FIX 5) accepts it. ``overrides``
    merge into the top level; ``extra_pipeline`` merges into the ``pipeline``
    stanza (e.g. a customised threshold for the digest-mismatch signal).
    """
    pipeline: dict[str, object] = {
        "config_version": config_version,
        "features": {"multi_llm": False},
        "sonarqube": {"available": False, "enabled": False},
        "ci": {"available": False, "enabled": False},
    }
    if extra_pipeline:
        pipeline.update(extra_pipeline)
    data: dict[str, object] = {
        "project_key": "demo",
        "project_name": "demo",
        "repositories": [{"name": "backend", "path": "/opt/backend"}],
        "pipeline": pipeline,
    }
    data.update(overrides)
    return data


def write_valid_project_yaml(
    project_root: Path,
    *,
    config_version: str = "3.0",
    extra_pipeline: dict[str, object] | None = None,
    **overrides: object,
) -> Path:
    """Write a minimal VALID ``project.yaml`` (AG3-070 SSOT shape) and return it."""
    return write_project_yaml(
        project_root,
        valid_project_config_dict(
            config_version=config_version,
            extra_pipeline=extra_pipeline,
            **overrides,
        ),
    )


def register_project(
    repo: InMemoryRegistrationRepo,
    *,
    project_root: Path,
    project_key: str,
    config_digest: str,
    config_version: str = "1",
) -> ProjectRegistration:
    """Insert a registration row with a given ``config_digest`` and return it."""
    registration = ProjectRegistration(
        project_key=project_key,
        project_root=project_root,
        github_owner="acme",
        github_repo="demo",
        runtime_profile=RuntimeProfile.CORE,
        config_version=config_version,
        config_digest=config_digest,
        registered_at=datetime.now(tz=UTC),
    )
    repo.save(registration)
    return registration


@pytest.fixture
def registration_repo() -> InMemoryRegistrationRepo:
    """A fresh in-memory registration repo."""
    return InMemoryRegistrationRepo()
