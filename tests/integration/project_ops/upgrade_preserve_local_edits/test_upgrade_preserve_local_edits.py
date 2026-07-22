"""Integration: the engine-driven upgrade preserves local edits (AG3-089, FK-51).

Scenario-based, filesystem-real exercise of the FK-51 upgrade flow running
THROUGH the AG3-088 checkpoint engine (story §6 — not a second installer):

* §51.3.2 config-edited path: a user-edited config (registered digest != on-disk
  hash) is backed up to ``.bak`` and rewritten across a ``config_version`` jump —
  the human's old config is recoverable, never silently destroyed.
* §51.6.1 git-hook path: an unrecognised pre-commit customization is preserved as
  ``.bak`` before the dispatch hook is written.

Uses the real upgrade flow over ``tmp_path`` with an in-memory registration repo
(the productive ``run_checkpoint_upgrade`` wires the SQLite/Postgres repo; this
test isolates the flow + filesystem behaviour from a live state backend).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.paths import project_config_path
from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.backend.installer.upgrade._digest import config_file_digest
from agentkit.backend.installer.upgrade.config_migration import BACKUP_SUFFIX
from agentkit.backend.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from pathlib import Path


class _InMemoryRepo:
    """In-memory ``ProjectRegistrationRepository`` (no live state backend)."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        self.rows[project_key] = self.rows[project_key].model_copy(
            update={"last_verified_at": verified_at}
        )

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        self.rows[project_key] = self.rows[project_key].model_copy(
            update={"last_upgraded_at": upgraded_at, "config_digest": new_digest}
        )

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[k] for k in sorted(self.rows)]


def _write_valid_config(project_root: Path, *, config_version: str = "3.0") -> Path:
    """Write a minimal VALID project.yaml with pipeline.config_version (SSOT)."""
    path = project_config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {
                "project_key": "demo",
                "project_name": "demo",
                "repositories": [{"name": "backend", "path": "/opt/backend"}],
                "pipeline": {
                    "config_version": config_version,
                    "features": {"multi_llm": False},
            "vectordb": {"host": "weaviate.test.local", "port": 19903, "grpc_port": 50051},
                    "sonarqube": {"available": False, "enabled": False},
                    "ci": {"available": False, "enabled": False},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_upgrade_preserves_user_edited_config_via_bak(tmp_path: Path) -> None:
    """§51.3.2: a user-edited config is backed up to ``.bak`` and rewritten."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = _write_valid_config(project_root, config_version="3.0")
    old_content = config_path.read_text(encoding="utf-8")

    repo = _InMemoryRepo()
    repo.save(
        ProjectRegistration(
            project_key="demo",
            project_root=project_root,
            github_owner="acme",
            github_repo="demo",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            # Stale registered digest -> §51.3.2 CONFIG_EDITED is decided.
            config_digest="stale-registered-digest",
            registered_at=datetime.now(tz=UTC),
        )
    )

    result = run_upgrade(
        project_root,
        project_key="demo",
        target_config_version="4.0",
        registration_repo=repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
    )

    # The §51.3.2 path ran the prescribed `.bak` + write across the version jump.
    assert result.config_migrated is True
    backup = config_path.with_name("project.yaml" + BACKUP_SUFFIX)
    assert backup.is_file()
    # The user's OLD config is recoverable byte-for-byte (never silently lost).
    assert backup.read_text(encoding="utf-8") == old_content
    # The new config carries the migrated version at the AG3-070 SSOT location.
    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["config_version"] == "4.0"


def test_upgrade_preserves_unrecognised_pre_commit_via_bak(tmp_path: Path) -> None:
    """§51.6.1: an unrecognised pre-commit customization is preserved as ``.bak``."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = _write_valid_config(project_root, config_version="3.0")
    hook = project_root / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hand_rolled = "#!/bin/sh\n# hand-rolled custom hook\necho mine\n"
    hook.write_text(hand_rolled, encoding="utf-8")

    repo = _InMemoryRepo()
    repo.save(
        ProjectRegistration(
            project_key="demo",
            project_root=project_root,
            github_owner="acme",
            github_repo="demo",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            config_digest=config_file_digest(config_path),
            registered_at=datetime.now(tz=UTC),
        )
    )

    result = run_upgrade(
        project_root,
        project_key="demo",
        target_config_version="3.0",  # no config jump; exercise the git-hook path
        registration_repo=repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
    )

    assert result.git_hook_outcome is not None
    assert result.git_hook_outcome.migrated is True
    backup = hook.with_name("pre-commit" + BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == hand_rolled
