"""Unit tests for SkillBundleStore, SkillBundle, SkillBundleVersion (AG3-027)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.backend.skills.binding import SkillProfile
from agentkit.backend.skills.bundle_store import (
    SkillBundle,
    SkillBundleStore,
    SkillBundleVersion,
)
from agentkit.backend.skills.errors import (
    SkillBundleCorruptError,
    SkillBundleNotFoundError,
)

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


# ---------------------------------------------------------------------------
# Fail-CLOSED discovery (AG3-048 Codex-r3 — no masking, no silent downgrade)
# ---------------------------------------------------------------------------

def _write_manifest(version_dir: Path, *, bundle_id: str, version: str) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "manifest.json").write_text(
        '{"bundle_id": "' + bundle_id + '", "bundle_version": "' + version + '"}',
        encoding="utf-8",
    )


class TestDiscoveryFailClosed:
    def test_corrupt_requested_manifest_raises_corruption_not_notfound(
        self, tmp_path: Path
    ) -> None:
        """A REQUESTED bundle whose only manifest is malformed JSON fails closed
        with ``SkillBundleCorruptError`` naming the path + parse error — NOT a
        generic ``SkillBundleNotFoundError`` that would hide the corruption.
        """
        bundle_dir = tmp_path / "mandatory-core" / "4.0.0"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "manifest.json").write_text("{ this is not json", encoding="utf-8")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle("mandatory-core")

        detail = exc_info.value.detail
        assert detail["bundle_id"] == "mandatory-core"
        assert "manifest.json" in str(detail["manifest_path"])
        assert detail["parse_error"]
        # It must NOT be a NotFound (which would mask corruption as "not shipped").
        assert not isinstance(exc_info.value, SkillBundleNotFoundError)

    def test_corrupt_highest_version_does_not_silently_downgrade(
        self, tmp_path: Path
    ) -> None:
        """When the HIGHEST version's manifest is corrupt but an older version
        is valid, the store fails closed for the requested id — it does NOT
        silently fall back to (downgrade to) the older parseable version.
        """
        bundle_id = "mandatory-core"
        # Valid older version.
        _write_manifest(tmp_path / bundle_id / "3.0.0", bundle_id=bundle_id, version="3.0.0")
        # Corrupt highest version.
        high = tmp_path / bundle_id / "4.0.0"
        high.mkdir(parents=True)
        (high / "manifest.json").write_text("}{ broken", encoding="utf-8")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle(bundle_id)
        # The error points at the HIGHEST (corrupt) version, proving no downgrade.
        assert "4.0.0" in str(exc_info.value.detail["manifest_path"])

    def test_missing_manifest_at_highest_version_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """Codex-r7 FINDING: a CONFORMANT highest version directory WITHOUT a
        manifest is an incomplete/corrupt bundle — the store must fail closed for
        the requested id and must NOT silently downgrade to a lower version that
        DOES have a manifest.
        """
        bundle_id = "mandatory-core"
        # Valid older version with a manifest.
        _write_manifest(tmp_path / bundle_id / "3.0.0", bundle_id=bundle_id, version="3.0.0")
        # Highest version directory exists but has NO manifest.json (incomplete).
        (tmp_path / bundle_id / "4.0.0").mkdir(parents=True)

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle(bundle_id)
        # Points at the missing-manifest HIGHEST version — proves no downgrade.
        assert "4.0.0" in str(exc_info.value.detail["manifest_path"])

    def test_unrelated_corrupt_dir_is_fail_soft_for_other_lookups(
        self, tmp_path: Path
    ) -> None:
        """Fail-soft skipping is still allowed for ENTIRELY UNRELATED dirs: a
        corrupt 'junk' bundle dir must not break the lookup of a valid,
        explicitly-requested 'good' bundle.
        """
        # Unrelated corrupt directory.
        junk = tmp_path / "junk-bundle" / "1.0.0"
        junk.mkdir(parents=True)
        (junk / "manifest.json").write_text("not json at all", encoding="utf-8")
        # Valid, requested bundle.
        _write_manifest(tmp_path / "good" / "1.0.0", bundle_id="good", version="1.0.0")

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle("good")
        assert bundle.bundle_id == "good"
        assert bundle.bundle_version == "1.0.0"

    def test_absent_requested_bundle_still_raises_notfound(self, tmp_path: Path) -> None:
        """When the requested bundle directory does not exist at all, the honest
        ``SkillBundleNotFoundError`` is raised (not a corruption error)."""
        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleNotFoundError):
            store.get_bundle("never-shipped")

    def test_structurally_invalid_requested_manifest_raises_corruption(
        self, tmp_path: Path
    ) -> None:
        """A REQUESTED bundle whose manifest parses as JSON but is structurally
        invalid (missing bundle_id) fails closed as corruption, not NotFound.
        """
        bundle_dir = tmp_path / "mandatory-core" / "4.0.0"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "manifest.json").write_text('{"bundle_version": "4.0.0"}', encoding="utf-8")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle("mandatory-core")
        assert exc_info.value.detail["bundle_id"] == "mandatory-core"


# ---------------------------------------------------------------------------
# SemVer ordering (AG3-048 Codex-r4 FINDING 2 — no lexicographic downgrade)
# ---------------------------------------------------------------------------

class TestSemVerVersionSelection:
    def test_double_digit_version_wins_over_single_digit(self, tmp_path: Path) -> None:
        """``10.0.0`` is semantically higher than ``9.0.0`` — a lexicographic
        string sort would wrongly pick ``9.0.0`` ("9" > "1"). The store must
        select ``10.0.0``.
        """
        bundle_id = "mandatory-core"
        _write_manifest(tmp_path / bundle_id / "9.0.0", bundle_id=bundle_id, version="9.0.0")
        _write_manifest(tmp_path / bundle_id / "10.0.0", bundle_id=bundle_id, version="10.0.0")

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_version == "10.0.0"

    def test_corrupt_semver_highest_does_not_downgrade_to_lower(
        self, tmp_path: Path
    ) -> None:
        """A corrupt SEMANTICALLY-highest version (``10.0.0``) must fail closed —
        it must NOT silently downgrade to a valid lower version (``9.0.0``). A
        lexicographic sort would have ranked ``9.0.0`` highest and masked this.
        """
        bundle_id = "mandatory-core"
        _write_manifest(tmp_path / bundle_id / "9.0.0", bundle_id=bundle_id, version="9.0.0")
        high = tmp_path / bundle_id / "10.0.0"
        high.mkdir(parents=True)
        (high / "manifest.json").write_text("}{ broken", encoding="utf-8")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle(bundle_id)
        # Points at the semantically-highest (corrupt) version -> no downgrade.
        assert "10.0.0" in str(exc_info.value.detail["manifest_path"])

    def test_nonconformant_two_component_does_not_outrank_release(
        self, tmp_path: Path
    ) -> None:
        """AG3-048 Codex-r5 FINDING 2: a non-conformant 2-component dir (``4.0``)
        must NOT outrank a conformant release (``3.9.9``). The store selects the
        valid release ``3.9.9``, never the malformed ``4.0``.
        """
        bundle_id = "mandatory-core"
        _write_manifest(tmp_path / bundle_id / "3.9.9", bundle_id=bundle_id, version="3.9.9")
        _write_manifest(tmp_path / bundle_id / "4.0", bundle_id=bundle_id, version="4.0")

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_version == "3.9.9"

    def test_four_component_does_not_outrank_release(self, tmp_path: Path) -> None:
        """AG3-048 Codex-r5 FINDING 2: a 4-component dir (``4.0.0.1``) is NOT a
        conformant SemVer core and must NOT outrank the conformant ``4.0.0``.
        """
        bundle_id = "mandatory-core"
        _write_manifest(tmp_path / bundle_id / "4.0.0", bundle_id=bundle_id, version="4.0.0")
        _write_manifest(
            tmp_path / bundle_id / "4.0.0.1", bundle_id=bundle_id, version="4.0.0.1"
        )

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_version == "4.0.0"

    def test_prerelease_does_not_outrank_release(self, tmp_path: Path) -> None:
        """AG3-048 Codex-r5 FINDING 2: per SemVer precedence a prerelease
        (``4.0.0-rc1``) ranks BELOW the corresponding release (``4.0.0``). The
        store selects the release, never the prerelease.
        """
        bundle_id = "mandatory-core"
        _write_manifest(tmp_path / bundle_id / "4.0.0", bundle_id=bundle_id, version="4.0.0")
        _write_manifest(
            tmp_path / bundle_id / "4.0.0-rc1", bundle_id=bundle_id, version="4.0.0-rc1"
        )

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_version == "4.0.0"

    def test_semver_sort_key_total_order(self) -> None:
        """Direct unit check of the strict-SemVer key tiers (AG3-048 Codex-r5
        FINDING 2): release > prerelease > non-conformant, and double-digit
        majors order numerically. Non-semver names never crash.
        """
        from agentkit.backend.skills.bundle_store import _semver_sort_key as key

        def highest(names: list[str]) -> str:
            return sorted(names, key=lambda n: (key(n), n))[-1]

        assert highest(["3.9.9", "4.0"]) == "3.9.9"
        assert highest(["4.0.0", "4.0.0.1"]) == "4.0.0"
        assert highest(["4.0.0", "4.0.0-rc1"]) == "4.0.0"
        assert highest(["9.0.0", "10.0.0"]) == "10.0.0"
        assert highest(["garbage", "1.2.3"]) == "1.2.3"
        assert highest(["", "1.0.0"]) == "1.0.0"
        # STRICT (Codex-r7): a leading 'v' is NOT a conformant core; a clean
        # release always wins over the 'v'-prefixed sibling, never the reverse.
        assert highest(["v1.2.3", "1.2.3"]) == "1.2.3"
        # Does not raise on arbitrary directory names.
        assert key("not-a-version") < key("0.0.1")

    def test_semver_strict_ascii_numeric_components(self) -> None:
        """AG3-048 Codex-r6 FINDING 2: a conformant release core requires THREE
        strict ASCII numeric components (``^(0|[1-9][0-9]*)$`` each). Reject
        ``str.isdigit()`` forms: leading zeros (``01``/``099``) and Unicode
        digits (Arabic-Indic ``٤``). None of these may outrank a conformant
        release; a ``v`` prefix and build metadata are non-conformant
        (Codex-r7); nothing crashes.
        """
        from agentkit.backend.skills.bundle_store import (
            _SEMVER_TIER_NONCONFORMANT,
            _SEMVER_TIER_RELEASE,
        )
        from agentkit.backend.skills.bundle_store import _semver_sort_key as key

        def highest(names: list[str]) -> str:
            return sorted(names, key=lambda n: (key(n), n))[-1]

        # Leading-zero forms are NON-conformant (must not be a release).
        assert key("01.2.3")[0] == _SEMVER_TIER_NONCONFORMANT
        assert key("099.0.0")[0] == _SEMVER_TIER_NONCONFORMANT
        # Arabic-Indic digits (str.isdigit() == True) are NON-conformant.
        assert key("٤.٠.٠")[0] == _SEMVER_TIER_NONCONFORMANT
        # A conformant release IS a release tier.
        assert key("4.0.0")[0] == _SEMVER_TIER_RELEASE
        # None of the rejected forms outrank a conformant release.
        assert highest(["01.2.3", "1.0.0"]) == "1.0.0"
        assert highest(["٤.٠.٠", "1.0.0"]) == "1.0.0"
        # The classic downgrade trap: 099.0.0 must NOT outrank 10.0.0.
        assert highest(["099.0.0", "10.0.0"]) == "10.0.0"
        # Conformant numeric ordering still holds.
        assert highest(["9.0.0", "10.0.0"]) == "10.0.0"
        # STRICT (Codex-r7): build metadata in a DIRECTORY name is non-conformant
        # (SemVer §10 makes it precedence-equal to the bare version, so allowing
        # it would tie/outrank the clean release). The clean release always wins.
        assert key("4.0.0+build")[0] == _SEMVER_TIER_NONCONFORMANT
        assert highest(["4.0.0+build", "4.0.0"]) == "4.0.0"
        # STRICT (Codex-r7): a leading 'v' is non-conformant.
        assert key("v4.0.0")[0] == _SEMVER_TIER_NONCONFORMANT
        assert highest(["v4.0.0", "4.0.0"]) == "4.0.0"
        # Empty / non-numeric never crash and stay non-conformant.
        assert key("")[0] == _SEMVER_TIER_NONCONFORMANT
        assert key("not-numeric")[0] == _SEMVER_TIER_NONCONFORMANT

    def test_semver_prerelease_precedence_and_validation(self) -> None:
        """AG3-048 Codex-r7-r3 FINDING: prerelease identifiers are ordered per
        SemVer §11.4 (numeric identifiers compared numerically, alphanumeric
        lexically, numeric < alphanumeric, more fields > fewer) and validated per
        §9 (invalid prerelease -> non-conformant, never outranks a clean release).
        """
        from agentkit.backend.skills.bundle_store import _SEMVER_TIER_NONCONFORMANT
        from agentkit.backend.skills.bundle_store import _semver_sort_key as key

        def highest(names: list[str]) -> str:
            return sorted(names, key=lambda n: (key(n), n))[-1]

        # Numeric prerelease identifiers compare NUMERICALLY (not lexically):
        # rc.10 > rc.2 — the bug this fixes (string tiebreak ranked rc.2 higher).
        assert highest(["4.0.0-rc.2", "4.0.0-rc.10"]) == "4.0.0-rc.10"
        # A release outranks any prerelease of the same core.
        assert highest(["4.0.0-rc.10", "4.0.0"]) == "4.0.0"
        # Numeric identifier ranks BELOW an alphanumeric one (§11.4.3).
        assert highest(["4.0.0-1", "4.0.0-alpha"]) == "4.0.0-alpha"
        # A larger set of fields ranks higher when the prefix is equal (§11.4.4).
        assert highest(["4.0.0-rc", "4.0.0-rc.1"]) == "4.0.0-rc.1"
        # INVALID prerelease identifiers (§9) are non-conformant and must NOT
        # outrank a clean lower release.
        assert key("4.0.0-01")[0] == _SEMVER_TIER_NONCONFORMANT  # leading-zero numeric
        assert key("4.0.0-rc..1")[0] == _SEMVER_TIER_NONCONFORMANT  # empty identifier
        assert key("4.0.0-rc.@")[0] == _SEMVER_TIER_NONCONFORMANT  # bad character
        assert highest(["4.0.0-01", "3.9.9"]) == "3.9.9"

    def test_prerelease_ordering_resolves_highest_via_store(self, tmp_path: Path) -> None:
        """End-to-end: with only prereleases present, the store selects the
        SemVer-highest one (rc.10 over rc.2), not the lexicographically-highest.
        """
        bundle_id = "mandatory-core"
        _write_manifest(
            tmp_path / bundle_id / "4.0.0-rc.2", bundle_id=bundle_id, version="4.0.0-rc.2"
        )
        _write_manifest(
            tmp_path / bundle_id / "4.0.0-rc.10", bundle_id=bundle_id, version="4.0.0-rc.10"
        )

        store = SkillBundleStore(store_root=tmp_path)
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_version == "4.0.0-rc.10"


# ---------------------------------------------------------------------------
# Manifest bundle_id vs directory id (AG3-048 Codex-r4 FINDING 2)
# ---------------------------------------------------------------------------

class TestManifestBundleIdValidation:
    def test_mismatched_manifest_id_raises_corruption_for_requested_dir(
        self, tmp_path: Path
    ) -> None:
        """A directory ``requested-core`` whose manifest declares
        ``bundle_id=different-core`` is CORRUPTION for ``requested-core`` —
        a ``SkillBundleCorruptError`` naming the dir + mismatching id, NOT a
        generic NotFound.
        """
        bundle_dir = tmp_path / "requested-core" / "4.0.0"
        _write_manifest(bundle_dir, bundle_id="different-core", version="4.0.0")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleCorruptError) as exc_info:
            store.get_bundle("requested-core")
        detail = exc_info.value.detail
        assert detail["bundle_id"] == "requested-core"
        assert detail["manifest_bundle_id"] == "different-core"
        assert not isinstance(exc_info.value, SkillBundleNotFoundError)

    def test_mismatched_manifest_id_does_not_resolve_other_id(
        self, tmp_path: Path
    ) -> None:
        """The manifest's mismatching ``bundle_id`` must NOT resolve a DIFFERENT
        bundle from the wrong directory: ``different-core`` does not resolve from
        ``requested-core/`` — it raises NotFound (the directory name is the
        authoritative id).
        """
        bundle_dir = tmp_path / "requested-core" / "4.0.0"
        _write_manifest(bundle_dir, bundle_id="different-core", version="4.0.0")

        store = SkillBundleStore(store_root=tmp_path)
        with pytest.raises(SkillBundleNotFoundError):
            store.get_bundle("different-core")
