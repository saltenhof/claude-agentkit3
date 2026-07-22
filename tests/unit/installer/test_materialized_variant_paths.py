"""Unit tests for the materialized-skill-variant store paths (AG3-111, FK-43 §43.4.1.1).

The variant store is SEPARATE from the ``SkillBundleStore`` root and digest-keyed over
the full materialization-relevant input (FIX Q1).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.installer.paths import (
    MATERIALIZED_SKILL_VARIANT_STORE_ENV,
    default_materialized_skill_variant_store_root,
    materialized_skill_variant_dir,
    materialized_skill_variant_input_digest,
    materialized_skill_variant_store_root,
)

if TYPE_CHECKING:
    import pytest


def _digest(**overrides: str) -> str:
    base = {
        "project_key": "proj",
        "skill_proof_token": "tok",
        "gh_owner": "acme",
        "gh_repo": "app",
        "project_prefix": "PROJ",
        "bundle_id": "b",
        "bundle_version": "4.0.0",
    }
    base.update(overrides)
    return materialized_skill_variant_input_digest(**base)  # type: ignore[arg-type]


class TestStoreRoot:
    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MATERIALIZED_SKILL_VARIANT_STORE_ENV, r"X:\custom-variants")
        assert default_materialized_skill_variant_store_root() == Path(r"X:\custom-variants")

    def test_explicit_root_wins(self) -> None:
        explicit = Path("/explicit/root")
        assert materialized_skill_variant_store_root(explicit) == explicit

    def test_default_is_install_state_area_not_repo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(MATERIALIZED_SKILL_VARIANT_STORE_ENV, raising=False)
        root = default_materialized_skill_variant_store_root()
        # The default lives in the AK3 install/state area, never under a repo path.
        assert "materialized-skill-variants" in str(root)
        assert "AgentKit" in str(root) or "/var/lib/agentkit/" in str(root).replace("\\", "/")


class TestDigest:
    def test_deterministic_for_same_input(self) -> None:
        assert _digest() == _digest()

    def test_changes_with_each_component(self) -> None:
        base = _digest()
        for field, value in (
            ("project_key", "other"),
            ("skill_proof_token", "other"),
            ("gh_owner", "other"),
            ("gh_repo", "other"),
            ("project_prefix", "OTHER"),
            ("bundle_id", "other"),
            ("bundle_version", "9.9.9"),
        ):
            assert _digest(**{field: value}) != base, field

    def test_separator_prevents_boundary_collision(self) -> None:
        # ("ab","c") must not collide with ("a","bc").
        d1 = _digest(project_key="ab", skill_proof_token="c")
        d2 = _digest(project_key="a", skill_proof_token="bc")
        assert d1 != d2


class TestVariantDirLayout:
    def test_layout_is_project_bundle_digest_skill(self) -> None:
        digest = _digest()
        vd = materialized_skill_variant_dir(
            "proj", "b", "4.0.0", digest, "myskill", store_root=Path("/store")
        )
        assert vd == Path("/store") / "proj" / "b@4.0.0" / digest / "myskill"

    def test_changed_input_yields_new_digest_dir(self) -> None:
        store = Path("/store")
        before = materialized_skill_variant_dir(
            "proj", "b", "4.0.0", _digest(skill_proof_token="A"), "s", store_root=store
        )
        after = materialized_skill_variant_dir(
            "proj", "b", "4.0.0", _digest(skill_proof_token="B"), "s", store_root=store
        )
        assert before != after


class TestReadSkillBundleManifest:
    """``_read_skill_bundle_manifest`` sources bundle_id/version for the variant dir."""

    def test_reads_present_manifest(self, tmp_path: Path) -> None:
        import json

        from agentkit.backend.installer.runner import _read_skill_bundle_manifest

        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "manifest.json").write_text(
            json.dumps({"bundle_id": "execute-userstory-core", "bundle_version": "5.1.0"}),
            encoding="utf-8",
        )
        info = _read_skill_bundle_manifest(bundle)
        assert info["bundle_id"] == "execute-userstory-core"
        assert info["bundle_version"] == "5.1.0"

    def test_missing_manifest_returns_empty(self, tmp_path: Path) -> None:
        from agentkit.backend.installer.runner import _read_skill_bundle_manifest

        bundle = tmp_path / "bundle"
        bundle.mkdir()
        assert _read_skill_bundle_manifest(bundle) == {}

    def test_non_object_manifest_returns_empty(self, tmp_path: Path) -> None:
        from agentkit.backend.installer.runner import _read_skill_bundle_manifest

        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert _read_skill_bundle_manifest(bundle) == {}


class TestVariantDirForUsesManifestKeys:
    """``_materialized_variant_dir_for`` folds the manifest bundle_id/version."""

    def test_uses_manifest_bundle_keys_in_path(self, tmp_path: Path) -> None:
        import json

        from agentkit.backend.config.models import (
            SUPPORTED_CONFIG_VERSION,
            Features,
            JenkinsConfig,
            PipelineConfig,
            ProjectConfig,
            RepositoryConfig,
            SonarQubeConfig,
        )
        from agentkit.backend.core_types.plane_artifact_names import (
            AGENT_SPAWN_SKILL_PROOF_KEY,
            INSTALLED_MANIFEST_FILENAME,
        )
        from agentkit.backend.installer.runner import (
            InstallConfig,
            _materialized_variant_dir_for,
        )

        root = tmp_path / "proj"
        root.mkdir()
        (root / INSTALLED_MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    AGENT_SPAWN_SKILL_PROOF_KEY: "tok123",
                    "authorized_prompt_paths": [],
                    "template_manifest_hash": "h",
                }
            ),
            encoding="utf-8",
        )
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "manifest.json").write_text(
            json.dumps({"bundle_id": "execute-userstory-core", "bundle_version": "4.0.0"}),
            encoding="utf-8",
        )
        project_config = ProjectConfig(
            project_key="proj",
            project_name="Proj",
            repositories=[RepositoryConfig(name="app", path=root)],
            github_owner="acme",
            pipeline=PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=False),
                sonarqube=SonarQubeConfig(available=False, enabled=False),
                ci=JenkinsConfig(available=False, enabled=False),
                vectordb={  # type: ignore[arg-type]
                    "host": "weaviate.test.local",
                    "port": 19903,
                    "grpc_port": 50051,
                },
            ),
        )
        install_config = InstallConfig(
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
            project_key="proj", project_name="Proj", project_root=root
        )
        vd = _materialized_variant_dir_for(
            install_config, project_config, root, "execute-userstory", bundle
        )
        assert "execute-userstory-core@4.0.0" in str(vd)
        assert str(vd).endswith("execute-userstory")
