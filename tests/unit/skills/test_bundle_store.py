"""Unit tests for SkillBundleStore, SkillBundle, SkillBundleVersion (AG3-027)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.skills.binding import SkillProfile
from agentkit.skills.bundle_store import (
    SkillBundle,
    SkillBundleStore,
    SkillBundleVersion,
)
from agentkit.skills.errors import SkillBundleNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# SkillBundleVersion
# ---------------------------------------------------------------------------

class TestSkillBundleVersion:
    def test_valid_construction(self) -> None:
        v = SkillBundleVersion(version="1.2.3", pinned_at=datetime(2026, 1, 1, tzinfo=UTC))
        assert v.version == "1.2.3"

    def test_frozen(self) -> None:
        v = SkillBundleVersion(version="1.0.0", pinned_at=datetime(2026, 1, 1, tzinfo=UTC))
        with pytest.raises((TypeError, ValidationError)):
            v.version = "2.0.0"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            SkillBundleVersion(
                version="1.0.0",
                pinned_at=datetime(2026, 1, 1, tzinfo=UTC),
                unknown="x",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# SkillBundle
# ---------------------------------------------------------------------------

class TestSkillBundle:
    def test_valid_construction(self, tmp_path: Path) -> None:
        bundle = SkillBundle(
            bundle_id="core-bundle",
            bundle_version="1.0.0",
            bundle_root=tmp_path,
            manifest_digest="deadbeef",
            variants={SkillProfile.CORE: "implement"},
        )
        assert bundle.bundle_id == "core-bundle"
        assert bundle.variants[SkillProfile.CORE] == "implement"

    def test_empty_variants_allowed(self, tmp_path: Path) -> None:
        bundle = SkillBundle(
            bundle_id="b",
            bundle_version="0.1",
            bundle_root=tmp_path,
            manifest_digest="",
            variants={},
        )
        assert bundle.variants == {}

    def test_frozen(self, tmp_path: Path) -> None:
        bundle = SkillBundle(
            bundle_id="b",
            bundle_version="1.0",
            bundle_root=tmp_path,
            manifest_digest="abc",
        )
        with pytest.raises((TypeError, ValidationError)):
            bundle.bundle_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SkillBundleStore
# ---------------------------------------------------------------------------

class TestSkillBundleStore:
    def test_custom_store_root(self, tmp_path: Path) -> None:
        store = SkillBundleStore(store_root=tmp_path)
        assert store.store_root == tmp_path

    def test_register_and_get_bundle(self, tmp_path: Path) -> None:
        store = SkillBundleStore(store_root=tmp_path)
        bundle = SkillBundle(
            bundle_id="myskill",
            bundle_version="2.0.0",
            bundle_root=tmp_path,
            manifest_digest="ff00",
        )
        store.register_bundle(bundle)
        result = store.get_bundle("myskill")
        assert result.bundle_id == "myskill"

    def test_get_bundle_missing_raises(self, tmp_path: Path) -> None:
        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleNotFoundError, match="not found"):
            store.get_bundle("nonexistent")

    def test_get_bundle_error_has_detail(self, tmp_path: Path) -> None:
        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleNotFoundError) as exc_info:
            store.get_bundle("missing-id")
        assert exc_info.value.detail["bundle_id"] == "missing-id"

    def test_register_overwrites(self, tmp_path: Path) -> None:
        store = SkillBundleStore(store_root=tmp_path)
        b1 = SkillBundle(
            bundle_id="x", bundle_version="1.0", bundle_root=tmp_path, manifest_digest="aa"
        )
        b2 = SkillBundle(
            bundle_id="x", bundle_version="2.0", bundle_root=tmp_path, manifest_digest="bb"
        )
        store.register_bundle(b1)
        store.register_bundle(b2)
        result = store.get_bundle("x")
        assert result.bundle_version == "2.0"
