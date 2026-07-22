"""SkillBundleStore, SkillBundle, SkillBundleVersion (AG3-027, FK-43 §43.5.2).

The bundle store is systemwide and canonical — analogous to
``PromptBundleStore`` from AG3-015. Each bundle lives exactly once on the
filesystem; project bindings point to it via a thin link (symlink on POSIX,
directory junction on Windows; FK-43 §43.4.1.1).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import NewType

from pydantic import BaseModel, ConfigDict

from agentkit.backend.skills.errors import (
    SkillBundleCorruptError,
    SkillBundleNotFoundError,
)

#: Manifest filename inside a ``{bundle_id}/{bundle_version}/`` bundle directory.
BUNDLE_MANIFEST_FILENAME: str = "manifest.json"

# LogicalSkillId is a NewType alias for str, preserving FK-43 vocabulary.
# In this story bind_skill accepts ``skill_name: str``; LogicalSkillId is
# the internal semantic alias.
LogicalSkillId = NewType("LogicalSkillId", str)

SKILL_BUNDLE_STORE_ENV: str = "AGENTKIT_SKILL_BUNDLE_STORE_ROOT"


# Sort-key tier ranks (higher = selected first as "highest version").
# A conformant ``MAJOR.MINOR.PATCH`` release ALWAYS outranks a prerelease of the
# same (or any) core, which in turn ALWAYS outranks a non-conformant directory
# name. The tier is the FIRST tuple element so it dominates the numeric core.
_SEMVER_TIER_RELEASE: int = 2
_SEMVER_TIER_PRERELEASE: int = 1
_SEMVER_TIER_NONCONFORMANT: int = 0


def _is_semver_numeric_component(component: str) -> bool:
    """Return ``True`` for a STRICT SemVer numeric identifier.

    AG3-048 Codex-r6 FINDING 2: ``str.isdigit()`` is WRONG for SemVer — it
    accepts Unicode digits (Arabic-Indic ``٤``, superscripts, ...) and
    leading-zero forms (``01``, ``099``). SemVer §2/§9 require ASCII decimal
    digits and forbid leading zeros (except the literal ``0``). This enforces
    exactly ``^(0|[1-9][0-9]*)$`` without a regex: ASCII-only digits, and no
    leading zero unless the component IS the single character ``0``.
    """
    if not component:
        return False
    # ASCII digits only — reject Unicode digit forms that ``str.isdigit`` allows.
    if not all("0" <= ch <= "9" for ch in component):
        return False
    # No leading zeros except the literal "0".
    return not (len(component) > 1 and component[0] == "0")


#: Empty prerelease component of a sort key (a release has no prerelease).
_EMPTY_PRERELEASE: tuple[tuple[int, int, str], ...] = ()


def _is_valid_prerelease_identifier(identifier: str) -> bool:
    """Return ``True`` for a STRICT SemVer §9 prerelease identifier.

    Each dot-separated identifier must be non-empty and consist only of ASCII
    alphanumerics and hyphen ``[0-9A-Za-z-]``. A purely-numeric identifier must
    not carry a leading zero (except the literal ``0``).
    """
    if not identifier:
        return False
    if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in identifier):
        return False
    if all("0" <= ch <= "9" for ch in identifier):  # numeric identifier
        return not (len(identifier) > 1 and identifier[0] == "0")
    return True


def _prerelease_sort_key(prerelease: str) -> tuple[tuple[int, int, str], ...] | None:
    """Return a SemVer §11.4 comparison key for a prerelease string, or ``None``.

    ``None`` signals an INVALID prerelease (any malformed identifier per §9) so the
    caller can demote the whole version to the non-conformant tier. Otherwise each
    dot-separated identifier maps to ``(rank, numeric_value, alpha_value)`` where:

    * numeric identifiers -> ``(0, int, "")`` (rank 0, compared numerically);
    * alphanumeric identifiers -> ``(1, 0, str)`` (rank 1, compared lexically by
      ASCII).

    The leading rank guarantees a numeric identifier always orders BELOW an
    alphanumeric one (§11.4.3), and Python tuple comparison gives "a larger set of
    fields ranks higher when all preceding identifiers are equal" (§11.4.4) for
    free (a shorter tuple is the smaller prefix).
    """
    key: list[tuple[int, int, str]] = []
    for identifier in prerelease.split("."):
        if not _is_valid_prerelease_identifier(identifier):
            return None
        if all("0" <= ch <= "9" for ch in identifier):
            key.append((0, int(identifier), ""))
        else:
            key.append((1, 0, identifier))
    return tuple(key)


def _semver_sort_key(
    name: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]:
    """Return a strict-SemVer ordering key for a version DIRECTORY name.

    AG3-048 Codex-r4 FINDING 2: directory names must be ordered SEMANTICALLY,
    not lexicographically. Lexicographic string sort makes ``"9.0.0" > "10.0.0"``,
    which would silently downgrade to ``9.0.0`` when ``10.0.0`` is the real
    highest version.

    AG3-048 Codex-r5 FINDING 2: the "highest version" selection enforces a STRICT
    3-component SemVer core (``MAJOR.MINOR.PATCH``, all integers). The key is a
    tuple ``(tier, major, minor, patch, prerelease_key)`` where ``tier`` dominates:

    * ``_SEMVER_TIER_RELEASE`` — conformant ``MAJOR.MINOR.PATCH`` release
      (``prerelease_key`` is empty).
    * ``_SEMVER_TIER_PRERELEASE`` — conformant core WITH a VALID prerelease suffix
      (``4.0.0-rc.1``). Per SemVer precedence a prerelease ranks BELOW the
      corresponding release (``4.0.0 > 4.0.0-rc.1``); among prereleases of the
      same core, ``prerelease_key`` orders them by SemVer §11.4 identifier
      precedence (``rc.10 > rc.2``). An INVALID prerelease (§9) is non-conformant.
    * ``_SEMVER_TIER_NONCONFORMANT`` — anything else: wrong component count
      (``4.0``, ``4.0.0.1``), a component that is not a STRICT ASCII numeric
      identifier (leading zeros like ``01``/``099``, Unicode digits like
      ``٤``), non-numeric, empty, a leading-``v`` form (``v1.2.3``) or a name
      carrying build metadata (``4.0.0+build``). These rank BELOW every
      conformant release/prerelease so a stray/garbage/decorated directory never
      masquerades as the highest version (the discovery layer then falls back to
      a lower well-formed version or fails closed per the requested-id rules).

    AG3-048 Codex-r7 FINDING (strict-resolution 2026-06-01): a precedence-bearing
    version DIRECTORY name is EXACTLY ``MAJOR.MINOR.PATCH`` (release) or
    ``MAJOR.MINOR.PATCH-prerelease``. A leading ``v`` and build metadata are NO
    longer tolerated:

    * ``v``-prefix — SemVer §2 versions carry no ``v``; ``v4.0.0`` and ``4.0.0``
      would otherwise both land on ``(release, 4, 0, 0)`` and tie, with the name
      tiebreak arbitrarily selecting ``v4.0.0`` over the clean ``4.0.0``.
    * build metadata — per SemVer §10 it is IGNORED for precedence, so
      ``4.0.0+build`` is precedence-equal to ``4.0.0``; tolerating it as a
      directory name would let the name tiebreak select the decorated sibling
      over the clean release.

    Treating both as non-conformant guarantees a clean release directory ALWAYS
    wins and is never tied or outranked. Non-conformant names yield a
    ``(0, 0, 0, 0)`` core; the caller's trailing ``p.name`` tiebreak keeps the
    sort total and deterministic among them (they are never selected over a
    conformant release).
    """
    # Build metadata anywhere in the name (``4.0.0+build``, ``4.0.0-rc1+x``) is
    # non-conformant for a precedence-bearing directory name (SemVer §10: equal
    # precedence to the bare version — would tie/outrank the clean release).
    if "+" in name:
        return (_SEMVER_TIER_NONCONFORMANT, 0, 0, 0, _EMPTY_PRERELEASE)
    core, sep, prerelease = name.partition("-")
    has_prerelease = sep == "-" and prerelease != ""
    # A ``-`` separator with an EMPTY prerelease (``4.0.0-``) is malformed.
    if sep == "-" and prerelease == "":
        return (_SEMVER_TIER_NONCONFORMANT, 0, 0, 0, _EMPTY_PRERELEASE)
    parts = core.split(".")
    # STRICT: exactly three ASCII-numeric components (``^(0|[1-9][0-9]*)$`` each).
    # AG3-048 Codex-r6 FINDING 2: reject ``str.isdigit()`` Unicode/leading-zero
    # forms — ``01.2.3``, ``٤.٠.٠`` and ``099.0.0`` are NON-conformant and must
    # fall to the bottom tier so they never outrank a conformant release. The
    # leading-``v`` form (``v4.0.0``) lands here too: ``v4`` is not ASCII-numeric.
    if len(parts) != 3 or not all(_is_semver_numeric_component(p) for p in parts):
        return (_SEMVER_TIER_NONCONFORMANT, 0, 0, 0, _EMPTY_PRERELEASE)
    major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    if not has_prerelease:
        return (_SEMVER_TIER_RELEASE, major, minor, patch, _EMPTY_PRERELEASE)
    # AG3-048 Codex-r7-r3 FINDING: validate AND order prerelease identifiers
    # (SemVer §9/§11.4). An invalid prerelease (empty, leading-zero numeric, or
    # non-alphanumeric identifier — ``4.0.0-``, ``4.0.0-01``, ``4.0.0-rc..1``)
    # demotes the whole version to non-conformant so it never outranks a clean
    # release. A valid prerelease ranks below the release of the same core and is
    # ordered among prereleases by identifier precedence (so ``rc.10`` > ``rc.2``,
    # NOT the lexicographic name tiebreak which ranked ``rc.2`` higher).
    prerelease_key = _prerelease_sort_key(prerelease)
    if prerelease_key is None:
        return (_SEMVER_TIER_NONCONFORMANT, 0, 0, 0, _EMPTY_PRERELEASE)
    return (_SEMVER_TIER_PRERELEASE, major, minor, patch, prerelease_key)


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


def shipped_skill_bundles_root() -> Path:
    """Return the packaged, read-only root of the shipped skill bundles.

    AgentKit ships the FK-43 §43.3.1 mandatory skill bundles inside the
    Python-free bundles tree (``src/agentkit/bundles/skill_bundles/``).
    The bundle content is the SINGLE SOURCE OF TRUTH inside AgentKit 3 — it
    is copied once from the AK2 source repo at provisioning time and carries
    NO runtime reference back to that source location.

    Layout (mirrors the ``SkillBundleStore`` convention):
    ``{root}/{bundle_id}/{bundle_version}/{SKILL.md, manifest.json}``.
    """
    package_dir = Path(__file__).resolve().parent.parent.parent  # .../agentkit
    return package_dir / "bundles" / "skill_bundles"


def _default_skill_bundle_store_root() -> Path:
    """Return the default root for the systemwide skill bundle store.

    Resolution order (FK-43 §43.5.2):

    1. ``AGENTKIT_SKILL_BUNDLE_STORE_ROOT`` env override (operator/test pin).
    2. The packaged, shipped bundles root (``shipped_skill_bundles_root``).

    AG3-048 (Codex-r2 ERROR 1): a default-built store MUST resolve the four
    shipped mandatory bundles in a real ``agentkit install`` — without a
    test monkeypatch and without a separate provisioning step. The shipped
    resources root is therefore the canonical default; filesystem discovery
    (``_discover_bundles``) materialises the bundles from it on first lookup.
    The previous ``%PROGRAMDATA%`` / ``~/.agentkit`` default is retained only
    as an env override for operators who provision bundles out-of-tree.
    """
    override = os.environ.get(SKILL_BUNDLE_STORE_ENV)
    if override:
        return Path(override)
    return shipped_skill_bundles_root()


class SkillBundleStore:
    """Systemwide, canonical store for skill bundles (FK-43 §43.5.2).

    Bundles live under ``{store_root}/{bundle_id}/{bundle_version}/`` and are
    discovered from that layout on the filesystem; an explicit
    ``register_bundle`` call additionally seeds the in-memory index (used by
    tests and by out-of-tree provisioning).

    AG3-048 (Codex-r2 ERROR 1): the store performs **persistent discovery
    from ``store_root``** — it scans the shipped resources layout on the first
    lookup so that a default-built store resolves the FK-43 §43.3.1 mandatory
    bundles in a real ``agentkit install`` (no test monkeypatch, no separate
    register step). Explicitly registered bundles take precedence over
    discovered ones for the same ``bundle_id``.

    Args:
        store_root: Override the default store root. Pass ``None`` to use the
            default (env ``AGENTKIT_SKILL_BUNDLE_STORE_ROOT`` if set, otherwise
            the packaged shipped-bundles root, ``shipped_skill_bundles_root``).
    """

    def __init__(self, store_root: Path | None = None) -> None:
        self._store_root: Path = store_root or _default_skill_bundle_store_root()
        self._bundles: dict[str, SkillBundle] = {}
        self._discovered: bool = False

    @property
    def store_root(self) -> Path:
        """Return the filesystem root of the bundle store."""
        return self._store_root

    def register_bundle(self, bundle: SkillBundle) -> None:
        """Register a bundle in the in-memory index.

        Explicitly registered bundles shadow any same-id bundle discovered
        from ``store_root``.

        Args:
            bundle: The bundle to register.
        """
        self._bundles[bundle.bundle_id] = bundle

    def get_bundle(self, bundle_id: str) -> SkillBundle:
        """Retrieve a bundle by its ID (registered or discovered from disk).

        On the first call the store discovers every bundle present under
        ``store_root`` (``{bundle_id}/{bundle_version}/manifest.json``) and
        caches it. Explicitly registered bundles win over discovered ones.

        Args:
            bundle_id: The bundle identifier.

        Returns:
            The matching ``SkillBundle``.

        Raises:
            SkillBundleNotFoundError: When no bundle with ``bundle_id`` is
                registered in this store or discoverable under ``store_root``.
            SkillBundleCorruptError: When the ``store_root/{bundle_id}/``
                directory IS present but its highest-version manifest is
                unreadable/malformed, OR declares a ``bundle_id`` that does not
                match the directory name (the directory is authoritative)
                (fail-closed; never silently downgrades to an older version,
                never masks corruption as NotFound, never lets a mismatched
                manifest resolve a different id — AG3-048 Codex-r3/r4).
        """
        bundle = self._bundles.get(bundle_id)
        if bundle is not None:
            return bundle
        self._ensure_discovered()
        bundle = self._bundles.get(bundle_id)
        if bundle is not None:
            return bundle
        # Fail-CLOSED for the REQUESTED id: a present bundle directory whose
        # highest-version manifest is corrupt must raise a specific corruption
        # error (naming the path + parse error), NOT a generic NotFound and
        # NOT a silent downgrade to an older parseable version. Fail-soft
        # skipping in ``_ensure_discovered`` is only acceptable for entirely
        # unrelated directories.
        self._discover_requested_or_raise(bundle_id)
        raise SkillBundleNotFoundError(
            f"Skill bundle '{bundle_id}' not found in store",
            detail={"bundle_id": bundle_id, "store_root": str(self._store_root)},
        )

    def list_bundle_ids(self) -> list[str]:
        """Return all known bundle ids (registered + discovered), sorted."""
        self._ensure_discovered()
        return sorted(self._bundles)

    # ------------------------------------------------------------------
    # Filesystem discovery (persistent resolution from store_root)
    # ------------------------------------------------------------------

    def _ensure_discovered(self) -> None:
        """Scan ``store_root`` once and register every well-formed bundle.

        Discovery is fail-soft per directory: a malformed ``manifest.json``
        is skipped (it cannot be a valid bundle), but a successfully parsed
        manifest is registered. The whole scan never raises — a missing
        ``store_root`` simply yields no bundles.

        Fail-soft here is NOT a license to mask corruption of a REQUESTED
        bundle: ``get_bundle`` re-checks the specific ``store_root/{bundle_id}/``
        directory fail-closed via ``_discover_requested_or_raise`` when the scan
        produced no match (AG3-048 Codex-r3). The scan's fail-soft behaviour
        only covers entirely-unrelated directories.
        """
        if self._discovered:
            return
        self._discovered = True
        if not self._store_root.is_dir():
            return
        for bundle_dir in sorted(p for p in self._store_root.iterdir() if p.is_dir()):
            discovered = self._discover_one(bundle_dir)
            # Registered bundles win — never overwrite an explicit registration.
            if discovered is not None and discovered.bundle_id not in self._bundles:
                self._bundles[discovered.bundle_id] = discovered

    def _discover_requested_or_raise(self, bundle_id: str) -> None:
        """Fail-closed discovery for a SPECIFICALLY REQUESTED ``bundle_id``.

        The matching directory is ``store_root/{bundle_id}/``. When that
        directory is present (the bundle WAS shipped) but its highest-version
        manifest is unreadable/malformed, raise ``SkillBundleCorruptError``
        naming the offending manifest path + parse error — never a generic
        NotFound, and never a silent downgrade to an older parseable version.

        When the directory is absent, this returns quietly so the caller raises
        the honest ``SkillBundleNotFoundError``.
        """
        if not self._store_root.is_dir():
            return
        bundle_dir = self._store_root / bundle_id
        if not bundle_dir.is_dir():
            return
        bundle = self._load_highest_version(bundle_dir, fail_closed_bundle_id=bundle_id)
        # When parseable, register so a repeat lookup is served from memory.
        if bundle is not None and bundle.bundle_id not in self._bundles:
            self._bundles[bundle.bundle_id] = bundle

    @classmethod
    def _discover_one(cls, bundle_dir: Path) -> SkillBundle | None:
        """Discover the highest-version bundle in ``{store_root}/{bundle_id}/``.

        Fail-soft: returns ``None`` when the directory contains no parseable
        manifest (used by the whole-tree scan over possibly-unrelated dirs).
        """
        return cls._load_highest_version(bundle_dir, fail_closed_bundle_id=None)

    @classmethod
    def _load_highest_version(
        cls,
        bundle_dir: Path,
        *,
        fail_closed_bundle_id: str | None,
    ) -> SkillBundle | None:
        """Load the highest-version bundle from ``bundle_dir``.

        The highest version directory is authoritative: if its manifest is
        corrupt the method does NOT fall back to an older parseable version.
        It either returns the highest-version bundle, raises (fail-closed mode),
        or returns ``None`` (fail-soft mode).

        Args:
            bundle_dir: The ``store_root/{bundle_id}/`` directory.
            fail_closed_bundle_id: When not ``None``, a corrupt highest-version
                manifest raises ``SkillBundleCorruptError`` for this id instead
                of being skipped (no silent downgrade). When ``None`` the load
                is fail-soft and returns ``None`` on any problem.
        """
        # AG3-048 Codex-r4 FINDING 2: order versions SEMANTICALLY (SemVer
        # major/minor/patch as ints), NOT by lexicographic directory-name sort
        # (which makes "9.0.0" > "10.0.0" and would silently downgrade). Sort
        # DESCENDING so the highest version is processed first (Codex-r7-r2:
        # ``sorted(reverse=True)`` instead of ``reversed(sorted(...))``).
        version_dirs = sorted(
            (p for p in bundle_dir.iterdir() if p.is_dir()),
            key=lambda p: (_semver_sort_key(p.name), p.name),
            reverse=True,
        )
        directory_bundle_id = bundle_dir.name
        # Each failure branch routes through ``_corrupt_or_none`` (raise in
        # fail-closed mode, ``None`` in fail-soft) so this loop stays within the
        # cognitive-complexity budget (Codex-r7-r2, Sonar S3776).
        for version_dir in version_dirs:  # highest version is authoritative
            manifest_path = version_dir / BUNDLE_MANIFEST_FILENAME
            if not manifest_path.is_file():
                # AG3-048 Codex-r7 FINDING: a CONFORMANT highest version directory
                # WITHOUT a manifest is an incomplete/corrupt bundle, NOT "no
                # signal"; never downgrade past it. A NON-conformant trailing dir
                # (a stray ``docs``/``latest`` that is not a version) is skipped.
                if _semver_sort_key(version_dir.name)[0] == _SEMVER_TIER_NONCONFORMANT:
                    continue
                return cls._corrupt_or_none(
                    fail_closed_bundle_id,
                    manifest_path,
                    "highest version directory has no manifest.json",
                )
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return cls._corrupt_or_none(fail_closed_bundle_id, manifest_path, str(exc))
            # AG3-048 Codex-r4 FINDING 2: the DIRECTORY name is authoritative for
            # the bundle id; a mismatching manifest bundle_id is corruption and
            # must never resolve a DIFFERENT id from this directory.
            id_mismatch = cls._manifest_bundle_id_mismatch(manifest, directory_bundle_id)
            if id_mismatch is not None:
                return cls._corrupt_or_none(
                    fail_closed_bundle_id,
                    manifest_path,
                    "manifest bundle_id does not match directory",
                    extra={
                        "directory_bundle_id": directory_bundle_id,
                        "manifest_bundle_id": id_mismatch,
                    },
                )
            bundle = cls._bundle_from_manifest(manifest, version_dir)
            if bundle is not None:
                return bundle
            return cls._corrupt_or_none(
                fail_closed_bundle_id,
                manifest_path,
                "manifest is not a valid bundle object",
            )
        return None

    @staticmethod
    def _corrupt_or_none(
        fail_closed_bundle_id: str | None,
        manifest_path: Path,
        parse_error: str,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        """Raise ``SkillBundleCorruptError`` (fail-closed) or return ``None`` (fail-soft).

        Centralises the 'highest version is corrupt' decision shared by every
        failure branch of ``_load_highest_version`` so that method stays within
        the cognitive-complexity budget (Codex-r7-r2, Sonar S3776). In fail-soft
        mode (``fail_closed_bundle_id is None``) a problem returns ``None`` (the
        bundle stays undiscovered so the requested-id path reports it honestly);
        in fail-closed mode it raises a corruption error naming the offending
        manifest path + parse error — never a silent downgrade, never a generic
        NotFound.
        """
        if fail_closed_bundle_id is None:
            return None
        detail: dict[str, str] = {
            "bundle_id": fail_closed_bundle_id,
            "manifest_path": str(manifest_path),
            "parse_error": parse_error,
        }
        if extra:
            detail.update(extra)
        raise SkillBundleCorruptError(
            f"Skill bundle '{fail_closed_bundle_id}' is present but its highest "
            f"version is corrupt ({parse_error}): {manifest_path}",
            detail=detail,
        )

    @staticmethod
    def _manifest_bundle_id_mismatch(
        manifest: object,
        directory_bundle_id: str,
    ) -> str | None:
        """Return the manifest's ``bundle_id`` when it MISMATCHES the directory.

        The directory name is the authoritative bundle id. Returns ``None`` when
        the manifest carries no usable ``bundle_id`` (that case is handled by
        ``_bundle_from_manifest`` as a structurally-invalid manifest) or when it
        matches the directory. Returns the offending string only on a genuine
        mismatch (AG3-048 Codex-r4 FINDING 2).
        """
        if not isinstance(manifest, dict):
            return None
        manifest_bundle_id = manifest.get("bundle_id")
        if not isinstance(manifest_bundle_id, str) or not manifest_bundle_id:
            return None
        if manifest_bundle_id == directory_bundle_id:
            return None
        return manifest_bundle_id

    @staticmethod
    def _bundle_from_manifest(
        manifest: object,
        version_dir: Path,
    ) -> SkillBundle | None:
        """Build a ``SkillBundle`` from a parsed manifest, or ``None`` if the
        manifest is structurally invalid (missing/blank id or version)."""
        if not isinstance(manifest, dict):
            return None
        bundle_id = manifest.get("bundle_id")
        bundle_version = manifest.get("bundle_version")
        if not isinstance(bundle_id, str) or not bundle_id:
            return None
        if not isinstance(bundle_version, str) or not bundle_version:
            return None
        digest = manifest.get("manifest_digest")
        if not isinstance(digest, str) or not digest:
            from agentkit.backend.skills.manifest_digest import compute_manifest_digest

            digest = compute_manifest_digest(manifest)
        variants_raw = manifest.get("variants")
        variants: dict[SkillProfile, str] = {}
        if isinstance(variants_raw, dict):
            for key, value in variants_raw.items():
                if key in SkillProfile.__members__ and isinstance(value, str):
                    variants[SkillProfile[key]] = value
        return SkillBundle(
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            bundle_root=version_dir,
            manifest_digest=digest,
            variants=variants,
        )
