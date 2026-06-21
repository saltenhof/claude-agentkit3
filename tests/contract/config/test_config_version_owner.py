"""Contract test: ``config_version`` ownership in the Pipeline-Config area.

FK-03 §3.3.4 defines two independent versioning areas:

1. **Pipeline-Config** (``project.yaml`` → ``config_version``) — owned by
   ``PipelineConfig`` in ``agentkit.backend.config.models``. This is the ONLY
   ``config_version`` owner in the config BC. ``ProjectConfig`` reaches it via
   ``ProjectConfig.pipeline.config_version`` and carries no second version field.

2. **QA-Artefact** (JSON envelopes → ``schema_version``) — owned by
   ``ArtifactEnvelope`` (``artifacts/envelope.py``) and ``ChangeFrame``
   (``exploration/change_frame.py``). These are **explicitly out of this test's
   scope** — they have their own contract tests in
   ``tests/contract/artifacts/test_envelope_schema.py`` and
   ``tests/contract/exploration/test_change_frame.py``.

This contract test fixes the Config-BC versioning inventory so that:

- a NEW ``config_version`` owner added to ``config/models.py`` without updating
  this list turns the test red (drift detected);
- a SECOND config-version field added to ``ProjectConfig`` turns the test red;
- the ``SUPPORTED_CONFIG_VERSION`` constant is pinned to ``"3.0"``;
- ``load_project_config`` surfaces ``PipelineConfig.config_version`` to callers
  (migration anchor — AG3-089 depends on this).
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

import agentkit.backend.config.models as config_models
from agentkit.backend.config import (
    SUPPORTED_CONFIG_VERSION,
    PipelineConfig,
    ProjectConfig,
    load_project_config,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# The COMPLETE and authoritative list of Pydantic config-BC models that carry
# a ``config_version`` field.
#
# FK-03 §3.3.4 Pipeline-Config versioning area:
#   - ``PipelineConfig`` is the ONLY config_version owner.
#   - ``ProjectConfig`` reaches it via ``pipeline.config_version``; it MUST
#     NOT carry a second ``config_version`` field (SSOT).
#
# Artefact-``schema_version`` owners (out of scope — own contract tests):
#   - ArtifactEnvelope (artifacts/envelope.py)
#   - ChangeFrame (exploration/change_frame.py)
# ---------------------------------------------------------------------------

#: Authoritative inventory: model class name → field name it owns.
#: A new config-version owner without an entry here → test red.
#: A second config-version field on ProjectConfig → test red.
_CONFIG_VERSION_OWNER_INVENTORY: dict[str, str] = {
    "PipelineConfig": "config_version",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_supported_config_version_is_3_0() -> None:
    """``SUPPORTED_CONFIG_VERSION`` must be pinned to ``"3.0"`` (FK-03 §3.2.1)."""
    assert SUPPORTED_CONFIG_VERSION == "3.0", (
        f"SUPPORTED_CONFIG_VERSION drift: expected '3.0', got '{SUPPORTED_CONFIG_VERSION}'"
    )


def test_pipeline_config_carries_config_version() -> None:
    """``PipelineConfig`` is the sole config-version owner (FK-03 §3.2.1 / §3.3.4)."""
    assert hasattr(PipelineConfig.model_fields, "__iter__"), (
        "PipelineConfig.model_fields must be iterable"
    )
    assert "config_version" in PipelineConfig.model_fields, (
        "PipelineConfig must carry a 'config_version' field (FK-03 §3.2.1)"
    )


def test_project_config_does_not_carry_config_version() -> None:
    """``ProjectConfig`` must NOT carry a direct ``config_version`` field.

    The root model reaches the version via ``pipeline.config_version``
    (no duplicate owner — SSOT, FK-03 §3.3.4).
    """
    assert "config_version" not in ProjectConfig.model_fields, (
        "ProjectConfig must NOT have a 'config_version' field; the only owner "
        "is PipelineConfig (FK-03 §3.3.4). Reach it via pipeline.config_version."
    )


def test_config_version_owner_inventory_is_complete() -> None:
    """Exactly the models in ``_CONFIG_VERSION_OWNER_INVENTORY`` carry ``config_version``.

    If you add a NEW Pydantic model to ``agentkit.backend.config.models`` that also
    carries a ``config_version`` field, this test will fail — add it to the
    inventory dict (if intentional) or remove the field (if accidental).

    This prevents silent drift in the config-versioning ownership area
    (FK-03 §3.3.4 / AG3-070 §5 contract obligation).
    """
    # Discover all Pydantic BaseModel subclasses in agentkit.backend.config.models
    # that carry a field named 'config_version'.
    found_owners: dict[str, str] = {}
    for name, obj in inspect.getmembers(config_models, inspect.isclass):
        if not issubclass(obj, BaseModel) or obj is BaseModel:
            continue
        if "config_version" in (obj.model_fields or {}):
            found_owners[name] = "config_version"

    assert found_owners == _CONFIG_VERSION_OWNER_INVENTORY, (
        f"Config-version owner inventory mismatch.\n"
        f"Expected: {_CONFIG_VERSION_OWNER_INVENTORY!r}\n"
        f"Found:    {found_owners!r}\n"
        "If you intentionally added a new config-version owner, update "
        "_CONFIG_VERSION_OWNER_INVENTORY in this contract test."
    )


def test_pipeline_config_explicit_version_is_supported() -> None:
    """``PipelineConfig`` accepts ``SUPPORTED_CONFIG_VERSION`` as ``config_version``.

    config_version is now a mandatory field (no silent default); passing the
    supported version explicitly must succeed (FK-03 §3.2.1).
    """
    from agentkit.backend.config.models import Features

    cfg = PipelineConfig(
        config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
    )
    assert cfg.config_version == SUPPORTED_CONFIG_VERSION, (
        f"PipelineConfig config_version should be '{SUPPORTED_CONFIG_VERSION}', "
        f"got '{cfg.config_version}'"
    )


def test_loader_exposes_config_version(tmp_path: Path) -> None:
    """``load_project_config`` surfaces ``config_version`` to callers.

    This is the migration anchor for AG3-089: the installer reads
    ``config.pipeline.config_version`` to decide whether migration is needed.
    """
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    data: dict[str, Any] = {
        "project_key": "test",
        "project_name": "test",
        "repositories": [],
        "story_types": ["concept"],
        "pipeline": {
            "config_version": "3.0",
            "features": {"multi_llm": False},
        },
    }
    (config_dir / "project.yaml").write_text(yaml.dump(data), encoding="utf-8")

    cfg = load_project_config(tmp_path)
    assert cfg.pipeline.config_version == SUPPORTED_CONFIG_VERSION, (
        "load_project_config must expose pipeline.config_version (AG3-089 "
        "migration anchor)"
    )
