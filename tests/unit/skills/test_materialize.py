"""Unit tests for the materialized harness-variant surface (AG3-111, FK-43 §43.4.1.1).

Covers the agent-skills Fachlogik directly (NO stub of the substitution): placeholder
detection, the substituted-variant materialization + link at the variant, the five-
placeholder resolution, fail-closed on a missing manifest token, byte-stable
idempotent re-materialization, the digest-keyed immutable-variant property, the link-
only invariant, and the self-atomic transactional rollback on a provoked failure.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.core_types.plane_artifact_names import (
    AGENT_SPAWN_SKILL_PROOF_KEY,
    INSTALLED_MANIFEST_FILENAME,
)
from agentkit.installer.paths import (
    materialized_skill_variant_dir,
    materialized_skill_variant_input_digest,
)
from agentkit.skills import (
    bundle_has_placeholders,
    is_directory_link,
    read_directory_link_target,
)
from agentkit.skills.errors import (
    SkillBindingFailedError,
    SkillBindingPartialStateError,
    UnknownPlaceholderError,
)
from agentkit.skills.materialize import bind_skill_materialized
from agentkit.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from pathlib import Path

_TOKEN = "deadbeefcafef00d"
_PLACEHOLDER_MD = (
    "owner={{gh_owner}} repo={{gh_repo}} key={{project_key}} "
    "pre={{project_prefix}} proof={{AGENT_SPAWN_SKILL_PROOF}} story=<STORY-ID> round=<ROUND>"
)


def _project_config(root: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key="proj",
        project_name="Proj",
        repositories=[RepositoryConfig(name="app", path=root)],
        github_owner="acme",
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


def _write_manifest(root: Path, token: str | None) -> None:
    payload: dict[str, object] = {
        "authorized_prompt_paths": [],
        "template_manifest_hash": "x" * 64,
    }
    if token is not None:
        payload[AGENT_SPAWN_SKILL_PROOF_KEY] = token
    (root / INSTALLED_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _bundle(root: Path, content: str = _PLACEHOLDER_MD) -> Path:
    bundle = root / "bundle"
    bundle.mkdir()
    (bundle / "SKILL.md").write_text(content, encoding="utf-8")
    return bundle


def _variant_dir(root: Path, *, token: str = _TOKEN) -> Path:
    digest = materialized_skill_variant_input_digest(
        project_key="proj",
        skill_proof_token=token,
        gh_owner="acme",
        gh_repo="app",
        project_prefix="PROJ",
        bundle_id="b",
        bundle_version="4.0.0",
    )
    return materialized_skill_variant_dir(
        "proj", "b", "4.0.0", digest, "myskill", store_root=root / "variant-store"
    )


def _materialize(root: Path, bundle: Path, variant_dir: Path) -> object:
    return bind_skill_materialized(
        "myskill",
        bundle,
        root,
        config=_project_config(root),
        variant_dir=variant_dir,
        binding_repo=InMemorySkillBindingRepository(),
        binding_id="bid",
        bundle_id="b",
        bundle_version="4.0.0",
    )


class TestBundleHasPlaceholders:
    def test_detects_placeholder_md(self, tmp_path: Path) -> None:
        bundle = _bundle(tmp_path)
        assert bundle_has_placeholders(bundle) is True

    def test_placeholder_free_bundle(self, tmp_path: Path) -> None:
        bundle = _bundle(tmp_path, content="# plain skill\nno tokens here")
        assert bundle_has_placeholders(bundle) is False

    def test_story_id_token_is_not_a_placeholder(self, tmp_path: Path) -> None:
        # <STORY-ID>/<ROUND> are NOT {{...}} placeholders — they must not trigger
        # the materialized mode (FK-43 §43.4.2 token grammar).
        bundle = _bundle(tmp_path, content="story=<STORY-ID> round=<ROUND>")
        assert bundle_has_placeholders(bundle) is False


class TestMaterializeResolvesAllPlaceholders:
    def test_all_five_placeholders_resolved_at_both_bindpoints(
        self, tmp_path: Path
    ) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        _materialize(proj, bundle, _variant_dir(tmp_path))

        for harness_dir in (".claude", ".codex"):
            content = (
                proj / harness_dir / "skills" / "myskill" / "SKILL.md"
            ).read_text(encoding="utf-8")
            assert "{{" not in content  # no literal placeholder survives
            assert "owner=acme" in content
            assert "repo=app" in content
            assert "key=proj" in content
            assert "pre=PROJ" in content
            assert f"proof={_TOKEN}" in content
            # The non-placeholder spawn tokens are left untouched.
            assert "story=<STORY-ID>" in content
            assert "round=<ROUND>" in content

    def test_non_markdown_files_copied_verbatim(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        # A non-.md file with a {{...}}-looking token must be copied byte-for-byte
        # (substitution is .md-only, FK-43 §43.4.2).
        (bundle / "data.txt").write_text("{{not_a_placeholder}}", encoding="utf-8")
        _materialize(proj, bundle, _variant_dir(tmp_path))

        copied = (
            proj / ".claude" / "skills" / "myskill" / "data.txt"
        ).read_text(encoding="utf-8")
        assert copied == "{{not_a_placeholder}}"


class TestMaterializeFailClosed:
    def test_missing_token_raises_and_no_residual_link(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, None)  # manifest WITHOUT the token
        bundle = _bundle(proj.parent)

        with pytest.raises(UnknownPlaceholderError):
            _materialize(proj, bundle, _variant_dir(tmp_path))

        # Fail-closed: no half-materialized bind point survives.
        assert not (proj / ".claude" / "skills" / "myskill").exists()
        assert not (proj / ".codex" / "skills" / "myskill").exists()

    def test_no_manifest_at_all_raises(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        bundle = _bundle(proj.parent)
        with pytest.raises(UnknownPlaceholderError):
            _materialize(proj, bundle, _variant_dir(tmp_path))


class TestLinkOnlyInvariant:
    def test_bindpoint_is_link_and_targets_variant(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        variant_dir = _variant_dir(tmp_path)
        _materialize(proj, bundle, variant_dir)

        for harness_dir in (".claude", ".codex"):
            bindpoint = proj / harness_dir / "skills" / "myskill"
            assert is_directory_link(bindpoint)
            assert read_directory_link_target(bindpoint).resolve() == variant_dir.resolve()
            # No skill source copied into the project repo: the bind point is a link
            # that resolves into the variant store, not a real directory of files
            # embedded in the project tree (project_binding_is_link_only invariant).
            assert not (variant_dir / "SKILL.md").is_relative_to(proj)

        # The substituted copy lives ONLY in the variant store, never the repo root.
        assert variant_dir.is_dir()
        assert str(tmp_path / "variant-store") in str(variant_dir)


class TestIdempotencyAndDigest:
    def test_same_input_byte_identical_variant(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        variant_dir = _variant_dir(tmp_path)

        _materialize(proj, bundle, variant_dir)
        first = (variant_dir / "SKILL.md").read_bytes()
        # Re-materialize the SAME input -> byte-identical variant under same digest.
        _materialize(proj, bundle, variant_dir)
        second = (variant_dir / "SKILL.md").read_bytes()
        assert first == second

    def test_changed_token_yields_new_digest_dir(self, tmp_path: Path) -> None:
        before = _variant_dir(tmp_path, token="tokenA")
        after = _variant_dir(tmp_path, token="tokenB")
        assert before != after  # changed input -> NEW digest dir (immutable variants)

    def test_changed_config_value_yields_new_digest(self, tmp_path: Path) -> None:
        base = materialized_skill_variant_input_digest(
            project_key="proj",
            skill_proof_token=_TOKEN,
            gh_owner="acme",
            gh_repo="app",
            project_prefix="PROJ",
            bundle_id="b",
            bundle_version="4.0.0",
        )
        changed = materialized_skill_variant_input_digest(
            project_key="proj",
            skill_proof_token=_TOKEN,
            gh_owner="other-owner",
            gh_repo="app",
            project_prefix="PROJ",
            bundle_id="b",
            bundle_version="4.0.0",
        )
        assert base != changed

    def test_separator_prevents_boundary_spoof(self, tmp_path: Path) -> None:
        # ("ab","c") must differ from ("a","bc"): the \x00 join prevents a value
        # spoofing a component boundary.
        d1 = materialized_skill_variant_input_digest(
            project_key="ab",
            skill_proof_token="c",
            gh_owner="o",
            gh_repo="r",
            project_prefix="p",
            bundle_id="b",
            bundle_version="v",
        )
        d2 = materialized_skill_variant_input_digest(
            project_key="a",
            skill_proof_token="bc",
            gh_owner="o",
            gh_repo="r",
            project_prefix="p",
            bundle_id="b",
            bundle_version="v",
        )
        assert d1 != d2


class TestTransactionalRollback:
    def test_link_failure_rolls_back_variant_and_links(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Provoke a link failure on the SECOND harness so the FIRST link is created;
        # the self-atomic rollback must remove the first link AND the variant tree.
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        variant_dir = _variant_dir(tmp_path)

        import agentkit.skills.materialize as mat

        calls = {"n": 0}
        real_create = mat.create_directory_link

        def _flaky_create(link_path: Path, target: Path) -> object:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("provoked link failure")
            return real_create(link_path, target)

        monkeypatch.setattr(mat, "create_directory_link", _flaky_create)

        with pytest.raises(SkillBindingFailedError, match="provoked link failure"):
            _materialize(proj, bundle, variant_dir)

        # No residual: neither bind point nor the variant tree survives.
        assert not (proj / ".claude" / "skills" / "myskill").exists()
        assert not (proj / ".codex" / "skills" / "myskill").exists()
        assert not variant_dir.exists()

    def test_residual_link_surfaces_partial_state_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When the rollback CANNOT detach a created link, a SkillBindingPartialStateError
        # carries the residual (NOT a clean failure) — mirrors AG3-048 discipline.
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        variant_dir = _variant_dir(tmp_path)

        import agentkit.skills.materialize as mat

        calls = {"n": 0}
        real_create = mat.create_directory_link

        def _flaky_create(link_path: Path, target: Path) -> object:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("provoked link failure")
            return real_create(link_path, target)

        # Make the rollback's link removal a no-op so the first link "survives".
        monkeypatch.setattr(mat, "create_directory_link", _flaky_create)
        monkeypatch.setattr(mat, "remove_directory_link", lambda _p: None)

        with pytest.raises(SkillBindingPartialStateError) as exc:
            _materialize(proj, bundle, variant_dir)

        residual = exc.value.detail.get("residual_links")
        assert isinstance(residual, list) and residual

    def test_second_save_failure_rolls_back_row_links_and_variant(
        self, tmp_path: Path
    ) -> None:
        # ERROR 1 fix: if the SECOND repo save (VERIFIED row) fails, the rollback must
        # delete the BOUND row that was already persisted, remove both harness links, and
        # remove the variant tree — no orphan row, no residual bind point (AC8 / AG3-048
        # self-atomic discipline).
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_manifest(proj, _TOKEN)
        bundle = _bundle(proj.parent)
        variant_dir = _variant_dir(tmp_path)

        # A repo stub whose second call to save() raises.
        class _PartialRepo:
            def __init__(self) -> None:
                self._calls = 0
                self._store: dict[tuple[str, str], object] = {}

            def save(self, binding: object) -> None:  # type: ignore[override]
                self._calls += 1
                if self._calls == 2:
                    raise RuntimeError("provoked second-save failure")
                from agentkit.skills.binding import SkillBinding

                assert isinstance(binding, SkillBinding)
                self._store[(binding.project_key, binding.skill_name)] = binding

            def load(self, project_key: str, skill_name: str) -> object:
                return self._store.get((project_key, skill_name))

            def list_for_project(self, project_key: str) -> list[object]:
                return []

            def delete(self, project_key: str, skill_name: str) -> None:
                self._store.pop((project_key, skill_name), None)

        repo = _PartialRepo()
        from agentkit.skills.materialize import bind_skill_materialized

        with pytest.raises(RuntimeError, match="provoked second-save failure"):
            bind_skill_materialized(
                "myskill",
                bundle,
                proj,
                config=_project_config(proj),
                variant_dir=variant_dir,
                binding_repo=repo,  # type: ignore[arg-type]
                binding_id="bid",
                bundle_id="b",
                bundle_version="4.0.0",
            )

        # No orphan binding row — both keys should be absent after rollback.
        assert repo.load(proj.stem, "myskill") is None, "orphan binding row found"
        # No residual harness links at either bind point.
        assert not (proj / ".claude" / "skills" / "myskill").exists()
        assert not (proj / ".codex" / "skills" / "myskill").exists()
        # No residual variant tree.
        assert not variant_dir.exists()
