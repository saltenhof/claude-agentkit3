"""SkillBundleStore, SkillBundle, SkillBundleVersion (AG3-027, FK-43 §43.5.2).

The bundle store is systemwide and canonical — analogous to
``PromptBundleStore`` from AG3-015. Each bundle lives exactly once on the
filesystem; project bindings point to it via symlink.
"""

from __future__ import annotations

import os
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import NewType

from pydantic import BaseModel, ConfigDict

from agentkit.skills.errors import SkillBundleNotFoundError

# LogicalSkillId is a NewType alias for str, preserving FK-43 vocabulary.
# In this story bind_skill accepts ``skill_name: str``; LogicalSkillId is
# the internal semantic alias.
LogicalSkillId = NewType("LogicalSkillId", str)

SKILL_BUNDLE_STORE_ENV: str = "AGENTKIT_SKILL_BUNDLE_STORE_ROOT"


class SkillProfile(StrEnum):
    """Skill profiles corresponding to FK-43 §43.3.

    Defined in ``bundle_store`` (layer 0 in BC 11 intra-layer order) because
    the profile is a bundle-variant selector; ``SkillBinding`` (layer 1)
    imports it from here to avoid a layer-violation.

    * ``CORE`` — profile without ARE integration.
    * ``ARE``  — profile with ARE-enabled variant selected.
    """

    CORE = "CORE"
    ARE = "ARE"


class SkillBundleVersion(BaseModel):
    """Pinned version record for a skill bundle (FK-43 §43.5.2).

    Attributes:
        version: Semver or opaque version string.
        pinned_at: UTC timestamp of when this version was pinned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    pinned_at: datetime


class SkillBundle(BaseModel):
    """Systemwide skill bundle record (FK-43, formal.skills-and-bundles.entity.bundle).

    Attributes:
        bundle_id: Stable bundle identifier.
        bundle_version: Current pinned version string.
        bundle_root: Absolute filesystem path to the bundle directory.
        manifest_digest: SHA-256 hex digest of the bundle manifest file.
        variants: Mapping from ``SkillProfile`` to skill name within that
            variant (i.e. the filename or subdirectory name relevant to
            the harness).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str
    bundle_version: str
    bundle_root: Path
    manifest_digest: str
    variants: dict[SkillProfile, str] = {}


def _default_skill_bundle_store_root() -> Path:
    """Return the platform default root for the systemwide skill bundle store."""
    override = os.environ.get(SKILL_BUNDLE_STORE_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "AgentKit" / "skill-bundles"
    return Path.home() / ".agentkit" / "skills"


class SkillBundleStore:
    """Systemwide, canonical store for skill bundles (FK-43 §43.5.2).

    Bundles are stored under ``{store_root}/{bundle_id}/{bundle_version}/``.
    Each installed bundle is registered by calling ``register_bundle``.

    Args:
        store_root: Override the default store root. Pass ``None`` to use
            the platform default (``~/.agentkit/skills/`` on POSIX or
            ``%PROGRAMDATA%\\AgentKit\\skill-bundles\\`` on Windows).
    """

    def __init__(self, store_root: Path | None = None) -> None:
        self._store_root: Path = store_root or _default_skill_bundle_store_root()
        self._bundles: dict[str, SkillBundle] = {}

    @property
    def store_root(self) -> Path:
        """Return the filesystem root of the bundle store."""
        return self._store_root

    def register_bundle(self, bundle: SkillBundle) -> None:
        """Register a bundle in the in-memory index.

        Args:
            bundle: The bundle to register.
        """
        self._bundles[bundle.bundle_id] = bundle

    def get_bundle(self, bundle_id: str) -> SkillBundle:
        """Retrieve a registered bundle by its ID.

        Args:
            bundle_id: The bundle identifier.

        Returns:
            The matching ``SkillBundle``.

        Raises:
            SkillBundleNotFoundError: When no bundle with ``bundle_id``
                is registered in this store.
        """
        bundle = self._bundles.get(bundle_id)
        if bundle is None:
            raise SkillBundleNotFoundError(
                f"Skill bundle '{bundle_id}' not found in store",
                detail={"bundle_id": bundle_id, "store_root": str(self._store_root)},
            )
        return bundle
