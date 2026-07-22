"""AG3-176 AC7: create-userstory-core 5.0.0 — no Grep fallback, hard stops, bindable."""

from __future__ import annotations

import json
import re
from pathlib import Path

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
    VectorDbConfig,
)
from agentkit.backend.skills.bundle_store import SkillBundleStore
from agentkit.backend.skills.manifest_digest import compute_manifest_digest
from agentkit.backend.skills.placeholder import PlaceholderSubstitutor

_BUNDLE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "agentkit"
    / "bundles"
    / "skill_bundles"
    / "create-userstory-core"
    / "5.0.0"
)


def test_bundle_exists_with_manifest_digest() -> None:
    assert _BUNDLE.is_dir()
    manifest = json.loads((_BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_id"] == "create-userstory-core"
    assert manifest["bundle_version"] == "5.0.0"
    # Product algorithm — NOT SHA of SKILL.md (AG3-176 R2).
    assert manifest["manifest_digest"] == compute_manifest_digest(manifest)
    assert manifest["manifest_digest"] == (
        "d7f33274c41468febe6efa643bd70418fb8b4091e36cef40ffae3767980b0ca6"
    )


def test_store_selects_5_0_0_as_highest_semver() -> None:
    store = SkillBundleStore()
    bundle = store.get_bundle("create-userstory-core")
    assert bundle.bundle_version == "5.0.0"
    assert bundle.bundle_root == _BUNDLE
    payload = json.loads((_BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    assert bundle.manifest_digest == compute_manifest_digest(payload)


def test_skill_has_no_grep_fallback_for_concept_search() -> None:
    """Semantic NEGATIVE matrix (AG3-176 R9): no conditional / fallback / grep path."""
    text = (_BUNDLE / "SKILL.md").read_text(encoding="utf-8")
    assert "{{#IF_STORY_VECTORDB}}" not in text
    assert "{{^IF_STORY_VECTORDB}}" not in text
    assert "{{/IF_STORY_VECTORDB}}" not in text
    assert "{{concepts_dir}}" not in text
    assert "Structural Search (Fallback" not in text
    assert "Fallback — no VectorDB" not in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("grep ") or stripped.startswith("rg "):
            raise AssertionError(f"discovery grep/rg command still present: {line!r}")
        if re.match(r"^`+(grep|rg)\b", stripped):
            raise AssertionError(f"discovery grep/rg command still present: {line!r}")
    assert "HARD STOP" in text or "Hard Stop" in text or "hard stop" in text.lower()
    assert "concept_search" in text
    assert "concepts_dir" in text or "project config" in text.lower()


def test_hard_stop_conditions_documented() -> None:
    text = (_BUNDLE / "SKILL.md").read_text(encoding="utf-8")
    for needle in (
        "graph_unavailable",
        "graph_stale",
        "corpus_revision",
        "concept_search",
    ):
        assert needle in text


def test_immutable_4_0_0_still_present_for_pinning() -> None:
    """Alt-Projekte gepinnt: 4.0.0 remains immutable (FK-43)."""
    old = _BUNDLE.parent / "4.0.0"
    assert old.is_dir()
    old_manifest = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
    assert old_manifest["bundle_version"] == "4.0.0"
    assert old_manifest["manifest_digest"] == compute_manifest_digest(old_manifest)


def test_productive_materialize_substitution_5_0_0(tmp_path: Path) -> None:
    """Materialize-path substitution succeeds for every .md (AG3-176 R2/R3)."""
    del tmp_path  # project root not required for pure substitution
    config = ProjectConfig(
        project_key="demo",
        project_name="Demo",
        repositories=[RepositoryConfig(name="app", path=".")],
        concepts_dir="concepts",
        wiki_stories_dir="stories",
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False, vectordb=True),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
            vectordb=VectorDbConfig(
                host="weaviate.test.local", port=19903, grpc_port=50051
            ),
        ),
    )
    substitutor = PlaceholderSubstitutor()
    skill_md = (_BUNDLE / "SKILL.md").read_text(encoding="utf-8")
    # Real materialize seam: same substitutor used by bind_skill_materialized.
    rendered = substitutor.substitute(skill_md, config)
    assert "{{" not in rendered or "{{#" not in rendered
    # No unknown-token crash; known tokens resolved or absent.
    assert "{{concepts_dir}}" not in rendered
    assert "{{#IF_STORY_VECTORDB}}" not in rendered
    assert "concept_search" in rendered
    # Ensure every markdown file in the bundle materializes.
    for md in _BUNDLE.rglob("*.md"):
        body = md.read_text(encoding="utf-8")
        substitutor.substitute(body, config)
