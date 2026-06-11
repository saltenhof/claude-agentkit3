"""Unit tests for the install-manifest producer (AG3-110, FK-31 §31.7.4).

Covers the typed model, the Q1 install-stable random token (reuse-if-present,
never re-roll), the folded template-manifest hash and the canonical JSON shape.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.installer.installed_manifest import (
    SKILL_PROOF_KEY,
    InstalledManifest,
    build_installed_manifest,
    fold_template_manifest_hash,
    resolve_install_stable_skill_proof,
)

if TYPE_CHECKING:
    from pathlib import Path


def _bundle_with_skill(root: Path, name: str, body: str = "# skill\n") -> Path:
    bundle = root / name
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(body, encoding="utf-8")
    return bundle


def _write_manifest(root: Path, token: str) -> None:
    (root / ".installed-manifest.json").write_text(
        json.dumps({SKILL_PROOF_KEY: token}), encoding="utf-8"
    )


class TestTokenDerivation:
    def test_fresh_token_is_high_entropy(self, tmp_path: Path) -> None:
        token = resolve_install_stable_skill_proof(tmp_path)
        # 32 random bytes -> 64 hex chars.
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_two_fresh_installs_differ(self, tmp_path: Path) -> None:
        # No persisted manifest => each call rolls a fresh random token (per-install).
        a = resolve_install_stable_skill_proof(tmp_path / "a")
        b = resolve_install_stable_skill_proof(tmp_path / "b")
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)
        assert a != b

    def test_reuses_persisted_token_unchanged(self, tmp_path: Path) -> None:
        # FK-51: an existing manifest token is reused unchanged (never re-rolled).
        _write_manifest(tmp_path, "feedface00112233")
        assert resolve_install_stable_skill_proof(tmp_path) == "feedface00112233"

    def test_empty_persisted_token_triggers_fresh(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "")
        token = resolve_install_stable_skill_proof(tmp_path)
        assert len(token) == 64

    def test_broken_manifest_json_fails_closed(self, tmp_path: Path) -> None:
        # A corrupt manifest must NOT be silently overwritten with a new token.
        (tmp_path / ".installed-manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            resolve_install_stable_skill_proof(tmp_path)


class TestTemplateManifestHash:
    def test_deterministic_and_order_independent(self, tmp_path: Path) -> None:
        b1 = _bundle_with_skill(tmp_path, "execute-userstory")
        b2 = _bundle_with_skill(tmp_path, "create-userstory")
        digests = {"worker": "aaa", "bugfix": "bbb"}
        h1 = fold_template_manifest_hash(
            prompt_template_digests=digests,
            skill_bundle_roots=[("execute-userstory", b1), ("create-userstory", b2)],
        )
        h2 = fold_template_manifest_hash(
            prompt_template_digests={"bugfix": "bbb", "worker": "aaa"},
            skill_bundle_roots=[("create-userstory", b2), ("execute-userstory", b1)],
        )
        assert h1 == h2
        assert len(h1) == 64

    def test_changed_skill_template_changes_hash(self, tmp_path: Path) -> None:
        b1 = _bundle_with_skill(tmp_path, "execute-userstory", body="# v1\n")
        before = fold_template_manifest_hash(
            prompt_template_digests={}, skill_bundle_roots=[("execute-userstory", b1)]
        )
        (b1 / "SKILL.md").write_text("# v2 changed\n", encoding="utf-8")
        after = fold_template_manifest_hash(
            prompt_template_digests={}, skill_bundle_roots=[("execute-userstory", b1)]
        )
        assert before != after

    def test_changed_prompt_digest_changes_hash(self, tmp_path: Path) -> None:
        before = fold_template_manifest_hash(
            prompt_template_digests={"w": "aaa"}, skill_bundle_roots=[]
        )
        after = fold_template_manifest_hash(
            prompt_template_digests={"w": "bbb"}, skill_bundle_roots=[]
        )
        assert before != after


class TestInstalledManifestModel:
    def test_canonical_json_round_trips_key(self, tmp_path: Path) -> None:
        bundle = _bundle_with_skill(tmp_path, "execute-userstory")
        manifest = build_installed_manifest(
            tmp_path,
            prompt_template_digests={"w": "aaa"},
            authorized_prompt_paths=["internal/prompts/w.md"],
            skill_bundle_roots=[("execute-userstory", bundle)],
        )
        parsed = json.loads(manifest.to_canonical_json())
        assert parsed[SKILL_PROOF_KEY] == manifest.agent_spawn_skill_proof
        assert parsed["authorized_prompt_paths"] == ["internal/prompts/w.md"]
        assert parsed["template_manifest_hash"] == manifest.template_manifest_hash

    def test_canonical_json_is_sorted_and_stable(self, tmp_path: Path) -> None:
        manifest = InstalledManifest(
            agent_spawn_skill_proof="tok",
            authorized_prompt_paths=("b", "a"),
            template_manifest_hash="hash",
        )
        text = manifest.to_canonical_json()
        # sort_keys -> keys appear alphabetically; trailing newline present.
        assert text.endswith("\n")
        idx_proof = text.index(SKILL_PROOF_KEY)
        idx_paths = text.index("authorized_prompt_paths")
        idx_hash = text.index("template_manifest_hash")
        assert idx_proof < idx_paths < idx_hash

    def test_empty_token_rejected_by_model(self) -> None:
        with pytest.raises(ValidationError):
            InstalledManifest(
                agent_spawn_skill_proof="",
                template_manifest_hash="hash",
            )

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            InstalledManifest(
                agent_spawn_skill_proof="tok",
                template_manifest_hash="hash",
                unexpected="x",  # type: ignore[call-arg]
            )

    def test_build_reuses_persisted_token(self, tmp_path: Path) -> None:
        bundle = _bundle_with_skill(tmp_path, "execute-userstory")
        first = build_installed_manifest(
            tmp_path,
            prompt_template_digests={"w": "aaa"},
            authorized_prompt_paths=["p"],
            skill_bundle_roots=[("execute-userstory", bundle)],
        )
        (tmp_path / ".installed-manifest.json").write_text(
            first.to_canonical_json(), encoding="utf-8"
        )
        second = build_installed_manifest(
            tmp_path,
            prompt_template_digests={"w": "aaa"},
            authorized_prompt_paths=["p"],
            skill_bundle_roots=[("execute-userstory", bundle)],
        )
        assert second.agent_spawn_skill_proof == first.agent_spawn_skill_proof
