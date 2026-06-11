"""Install-manifest producer (`.installed-manifest.json`, FK-31 §31.7.4, AG3-110).

The install-time PRODUCER of the project-root ``.installed-manifest.json`` that the
AG3-086 prompt-integrity guard CONSUMES at Stage 2 (``story_execution`` spawn-schema
validation). The guard reads the top-level key ``agent_spawn_skill_proof`` to obtain
the authoritative spawn skill-proof token (``governance/runner.py``
``_installed_skill_proof`` / ``_MANIFEST_SKILL_PROOF_KEY``); without this producer
every ``story_execution`` worker spawn fails Stage 2 fail-closed.

Owner discipline (FIX THE MODEL): this module ADAPTS to the consumer's pinned schema
(one manifest path, one key, the exact reader). It introduces NO second operative
truth — the path (``.installed-manifest.json``) is already the canonical, self-
protection-guarded governance artifact (``core_types/plane_artifact_names.py``); only
its writer was missing.

Token derivation (Q1 — orchestrator decision, overrides the story §7 HMAC proposal):
the ``agent_spawn_skill_proof`` token is a per-install RANDOM high-entropy token
(``secrets.token_hex``), generated ONCE at first install and persisted in the manifest.
On every idempotent re-install / upgrade the EXISTING token is read back and REUSED
UNCHANGED — it is NEVER re-rolled (FK-51 §51.1/§51.2 install-stability: a re-roll would
invalidate every already-bound/composed spawn header). A random stored token is
unpredictable, so a forging prompt cannot derive it from repo/bundle-known inputs.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.core_types.plane_artifact_names import AGENT_SPAWN_SKILL_PROOF_KEY
from agentkit.installer.paths import installed_manifest_path
from agentkit.utils.io import read_json_object

if TYPE_CHECKING:
    from pathlib import Path

#: Top-level manifest key carrying the authoritative spawn skill-proof token. Sourced
#: from the BC-neutral ``core_types`` contract constant (SINGLE SOURCE OF TRUTH); it is
#: byte-identical to the AG3-086 consumer's ``_MANIFEST_SKILL_PROOF_KEY``
#: (``governance/runner.py``) — pinned by a contract test.
SKILL_PROOF_KEY = AGENT_SPAWN_SKILL_PROOF_KEY

#: Number of random bytes behind the skill-proof token (``token_hex`` yields twice
#: as many hex chars — 32 bytes -> 64 hex chars, 256 bits of entropy).
_SKILL_PROOF_ENTROPY_BYTES = 32


class InstalledManifest(BaseModel):
    """Typed install-manifest content (FK-31 §31.7.4, English keys per ARCH-55).

    Serialised to the project-root ``.installed-manifest.json`` deterministically
    (``json.dumps(..., sort_keys=True)``). The ``agent_spawn_skill_proof`` key is the
    only one the AG3-086 consumer reads today; ``authorized_prompt_paths`` and
    ``template_manifest_hash`` materialise the remaining FK-31 §31.7.4 manifest
    obligations (the authorized prompt paths and the template-manifest hash).

    Attributes:
        agent_spawn_skill_proof: The authoritative, install-stable spawn skill-proof
            token (Q1: per-install random, reused unchanged across re-installs).
        authorized_prompt_paths: The install-known authorized prompt template paths of
            the bound prompt bundle (FK-31 §31.7.4 "the authorized prompt paths").
        template_manifest_hash: The folded SHA-256 over the bound skill-bundle SKILL.md
            template digests AND the prompt-bundle template digests (FK-31 §31.7.4
            "template files ... are included in the manifest hash at install time").
            Binds the proof to the installed template integrity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_spawn_skill_proof: str = Field(min_length=1)
    authorized_prompt_paths: tuple[str, ...] = ()
    template_manifest_hash: str = Field(min_length=1)

    def to_canonical_json(self) -> str:
        """Return the deterministic on-disk JSON (sorted keys, trailing newline).

        Mirrors the existing idempotent root-JSON pattern ``_write_control_plane_config``
        (``installer/runner.py``): ``json.dumps(..., sort_keys=True)`` so the content is
        stable under key ordering and an unchanged install yields byte-identical output.
        """
        payload = {
            SKILL_PROOF_KEY: self.agent_spawn_skill_proof,
            "authorized_prompt_paths": list(self.authorized_prompt_paths),
            "template_manifest_hash": self.template_manifest_hash,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _read_existing_skill_proof(manifest_path: Path) -> str | None:
    """Return the persisted ``agent_spawn_skill_proof`` token, or ``None``.

    Reads through the same ``utils.io`` truth-boundary helper the consumer uses, so
    producer and consumer never diverge on parsing. A missing manifest / missing or
    empty token yields ``None`` (the token must then be freshly generated). A broken
    JSON file raises (fail-closed via ``read_json_object``); the install must not
    silently overwrite a corrupt manifest with a NEW token (that would re-roll and
    break bound headers).
    """
    data = read_json_object(manifest_path)
    token = data.get(SKILL_PROOF_KEY)
    if isinstance(token, str) and token:
        return token
    return None


def _generate_skill_proof() -> str:
    """Generate a fresh per-install random spawn skill-proof token (Q1).

    High-entropy and unpredictable (``secrets.token_hex``): a forging prompt that can
    read the repo/bundle cannot derive it. Generated exactly ONCE per install and then
    persisted + reused unchanged.
    """
    return secrets.token_hex(_SKILL_PROOF_ENTROPY_BYTES)


def resolve_install_stable_skill_proof(project_root: Path) -> str:
    """Resolve the install-stable token: reuse-if-present, else generate once (Q1).

    Args:
        project_root: The target-project root (the manifest lives at its root).

    Returns:
        The existing persisted token when a valid one is already installed (FK-51
        re-install stability — NEVER re-rolled), otherwise a freshly generated one.
    """
    manifest_path = installed_manifest_path(project_root)
    existing = _read_existing_skill_proof(manifest_path)
    if existing is not None:
        return existing
    return _generate_skill_proof()


def _file_sha256(path: Path) -> str:
    """Return the hex SHA-256 of *path*'s bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fold_template_manifest_hash(
    *,
    prompt_template_digests: dict[str, str],
    skill_bundle_roots: list[tuple[str, Path]],
) -> str:
    """Fold skill-bundle + prompt-bundle template digests into ONE manifest hash.

    FK-31 §31.7.4: "template files live in the skill directory and are included in
    the manifest hash at install time." We do NOT invent a new hash — we
    fold the digests the install path already has:

    * the prompt-bundle template ``sha256`` digests (from the CP 8 prompt-bundle
      manifest, ``_load_prompt_bundle_manifest`` ``templates[*].sha256``), and
    * the SHA-256 of each bound skill bundle's ``SKILL.md`` template file (the skill
      directory templates).

    The inputs are sorted by a stable key before hashing so the result is order-
    independent and deterministic across installs.

    Args:
        prompt_template_digests: ``template_name -> sha256`` from the prompt-bundle
            manifest.
        skill_bundle_roots: ``(skill_name, bundle_root)`` pairs of the bound mandatory
            skills; each bundle root's ``SKILL.md`` is folded in when present.

    Returns:
        The hex SHA-256 over the canonicalised, sorted digest set.
    """
    components: dict[str, str] = {}
    for name, digest in prompt_template_digests.items():
        components[f"prompt:{name}"] = digest
    for skill_name, bundle_root in skill_bundle_roots:
        skill_md = bundle_root / "SKILL.md"
        if skill_md.is_file():
            components[f"skill:{skill_name}"] = _file_sha256(skill_md)
    canonical = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_installed_manifest(
    project_root: Path,
    *,
    prompt_template_digests: dict[str, str],
    authorized_prompt_paths: list[str],
    skill_bundle_roots: list[tuple[str, Path]],
) -> InstalledManifest:
    """Build the typed manifest content (install-stable token + folded hash).

    Args:
        project_root: The target-project root.
        prompt_template_digests: ``template_name -> sha256`` from the prompt-bundle
            manifest (folded into the template-manifest hash).
        authorized_prompt_paths: The install-known authorized prompt template paths.
        skill_bundle_roots: ``(skill_name, bundle_root)`` of the bound mandatory skills.

    Returns:
        The :class:`InstalledManifest` (token reused if already installed, else fresh).
    """
    token = resolve_install_stable_skill_proof(project_root)
    template_hash = fold_template_manifest_hash(
        prompt_template_digests=prompt_template_digests,
        skill_bundle_roots=skill_bundle_roots,
    )
    return InstalledManifest(
        agent_spawn_skill_proof=token,
        authorized_prompt_paths=tuple(sorted(authorized_prompt_paths)),
        template_manifest_hash=template_hash,
    )


__all__ = [
    "SKILL_PROOF_KEY",
    "InstalledManifest",
    "build_installed_manifest",
    "fold_template_manifest_hash",
    "resolve_install_stable_skill_proof",
]
