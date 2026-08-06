"""AG3-176 contract tests for immutable mandatory-VectorDB skill delivery."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest
from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient

from agentkit.backend.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.skills.bundle_store import SkillBundleStore
from agentkit.backend.skills.errors import SkillBindingFailedError
from agentkit.backend.skills.links import (
    create_directory_link,
    remove_directory_link,
)
from agentkit.backend.skills.repository import InMemorySkillBindingRepository
from agentkit.backend.skills.top import Skills
from agentkit.backend.vectordb.cli import main as concept_cli
from agentkit.backend.vectordb.engine import compose_runtime
from agentkit.backend.vectordb.mcp_server import (
    McpToolService,
    handle_tool_call,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BUNDLE = _REPO_ROOT / "src" / "agentkit" / "bundles" / "skill_bundles" / "create-userstory-core" / "4.2.0"


def _manifest_digest(manifest: dict[str, object]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_effectively_installed_pinned_bundle_is_complete_and_fail_closed(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=_BUNDLE.parents[1]),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", _BUNDLE, project)
    binding = skills.verify_pinned_binding(project, "create-userstory")
    installed = project / ".claude" / "skills" / "create-userstory"
    manifest = json.loads(
        (installed / "manifest.json").read_text(encoding="utf-8"),
    )
    skill = (installed / "SKILL.md").read_text(encoding="utf-8")

    assert binding.bundle_version == "4.2.0"
    assert manifest["bundle_version"] == "4.2.0"
    assert manifest["manifest_digest"] == _manifest_digest(manifest)
    assert len(skill) > 40_000
    assert "../4.0.0/SKILL.md" not in skill
    assert "CONFIGURED_CONCEPTS_DIR" in skill
    assert "VALIDATED_CONCEPT_REVISION" in skill
    assert 'source_type: "concept"' in skill
    assert "last_revision == VALIDATED_CONCEPT_REVISION" in skill
    assert "stale_chunk_count: 0" in skill
    assert "hard stop" in skill.lower()
    assert "grep" not in skill.lower()
    assert "glob" not in skill.lower()
    assert "IF_STORY_VECTORDB" not in skill
    assert "concept_search" in skill
    assert "optional concept_search" not in skill.lower()
    assert "{{AK3_INTERPRETER}} -m agentkit.backend.vectordb.wait_for_weaviate" in skill
    assert "{{AK3_WRAPPER}} concept" in skill
    assert "{{AK3_INTERPRETER}} tools/agentkit/projectedge.py create-story" in skill
    assert "{{AK3_WRAPPER}} export-story-md" in skill


def _write_concept_corpus(root: Path, *, suffix: str) -> Path:
    concepts = root / "architecture"
    concepts.mkdir()
    (concepts / "01_primary.md").write_text(
        dedent(
            f"""\
            ---
            concept_id: FK-01
            title: Primary
            module: primary
            status: active
            doc_kind: core
            authority_over:
              - scope: primary
            defers_to:
              - FK-02
            ---

            # Primary

            ## Rule

            FK-02 owns the companion rule. {suffix}
            """
        ),
        encoding="utf-8",
    )
    (concepts / "02_companion.md").write_text(
        dedent(
            """\
            ---
            concept_id: FK-02
            title: Companion
            module: companion
            status: active
            doc_kind: core
            authority_over:
              - scope: companion
            ---

            # Companion

            ## Rule

            Companion authority.
            """
        ),
        encoding="utf-8",
    )
    return concepts


def _validated_revision(
    concepts: Path,
    capsys: pytest.CaptureFixture[str],
) -> str:
    status = concept_cli(
        [
            "--concepts-dir",
            str(concepts),
            "validate",
            "--corpus",
            "--strict",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["status"] == "valid"
    revision = payload["corpus_revision"]
    assert isinstance(revision, str) and revision
    return revision


def _require_current_completion(
    revision: str,
    response: dict[str, object],
) -> None:
    if "error" in response:
        raise RuntimeError("story_list_sources tool error")
    sources = response["sources"]
    if not isinstance(sources, list):
        raise RuntimeError("sources has the wrong type")
    concepts = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("source_type") == "concept"
    ]
    if len(concepts) != 1:
        raise RuntimeError("concept completion is missing or ambiguous")
    completion = concepts[0]
    last_revision = completion.get("last_revision")
    stale_count = completion.get("stale_chunk_count")
    if not isinstance(last_revision, str) or not last_revision:
        raise RuntimeError("concept completion is missing")
    if type(stale_count) is not int or stale_count != 0:
        raise RuntimeError("concept completion reports stale chunks")
    if last_revision != revision:
        raise RuntimeError("concept completion revision mismatch")


def test_effective_pinned_skill_freshness_contract_uses_real_cli_and_mcp_boundaries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concepts = _write_concept_corpus(tmp_path, suffix="before")
    stories = tmp_path / "work-items"
    stories.mkdir()
    client = RecordingWeaviateClient()
    service = compose_runtime(
        {
            "PROJECT_ID": "AG3",
            "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.invalid:8080",
            "WEAVIATE_GRPC_ENDPOINT": "weaviate.invalid:50051",
        },
        concepts_dir=concepts,
        stories_dir=stories,
        client=client,
        cwd=str(tmp_path),
    )
    assert isinstance(service, McpToolService)
    before_revision = _validated_revision(concepts, capsys)

    missing = handle_tool_call(service, "story_list_sources", {})
    with pytest.raises(RuntimeError, match="completion is missing"):
        _require_current_completion(before_revision, missing)

    synced = handle_tool_call(
        service,
        "concept_sync",
        {"full_reindex": True},
    )
    assert synced["corpus_revision"] == before_revision
    current = handle_tool_call(service, "story_list_sources", {})
    _require_current_completion(before_revision, current)

    primary = concepts / "01_primary.md"
    primary.write_text(
        primary.read_text(encoding="utf-8").replace("before", "after"),
        encoding="utf-8",
    )
    changed_revision = _validated_revision(concepts, capsys)
    assert changed_revision != before_revision
    with pytest.raises(RuntimeError, match="revision mismatch"):
        _require_current_completion(changed_revision, current)

    def _outage(**_kwargs: object) -> object:
        raise VectorDbUnavailableError("external store unavailable")

    monkeypatch.setattr(client, "fetch_by_property", _outage)
    failed = handle_tool_call(service, "story_list_sources", {})
    assert failed["error"] == "vectordb_unavailable"
    with pytest.raises(RuntimeError, match="tool error"):
        _require_current_completion(changed_revision, failed)


def _write_bundle(
    root: Path,
    version: str,
    *,
    bundle_id: str = "create-userstory-core",
    skill_name: str = "create-userstory",
) -> Path:
    bundle = root / bundle_id / version
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(f"# {skill_name}\n", encoding="utf-8")
    manifest: dict[str, object] = {
        "bundle_id": bundle_id,
        "bundle_version": version,
        "profile": "CORE",
        "skill_name": skill_name,
        "variants": {"CORE": skill_name},
    }
    manifest["manifest_digest"] = _manifest_digest(manifest)
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def test_verify_uses_persisted_pin_and_requires_identical_harness_targets(
    tmp_path: Path,
) -> None:
    """A pin is honoured for the project's lifetime — and both harnesses must agree."""
    store_root = tmp_path / "store"
    pinned = _write_bundle(store_root, "4.2.0")
    newer = _write_bundle(store_root, "4.4.0")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", pinned, project)

    # Deliberately NOT the newest available version: an existing project stays
    # valid on the version it explicitly chose.
    binding = skills.verify_pinned_binding(project, "create-userstory")
    assert binding.bundle_version == "4.2.0"
    assert (project / ".claude" / "skills" / "create-userstory").resolve() == pinned.resolve()
    assert (project / ".codex" / "skills" / "create-userstory").resolve() == pinned.resolve()

    codex = project / ".codex" / "skills" / "create-userstory"
    remove_directory_link(codex)
    create_directory_link(codex, newer)
    with pytest.raises(SkillBindingFailedError, match="different bundle versions"):
        skills.verify_pinned_binding(project, "create-userstory")


def test_bind_skill_rejects_a_pin_below_the_minimum_conform_bundle_version(
    tmp_path: Path,
) -> None:
    """`create-userstory-core` 4.1.0 still publishes naked PATH commands.

    Honouring that pin would let a supported project pass VERIFY while running
    the naked PATH-Python commands that the interpreter-isolation contract
    forbids — so this is one case where the lifetime-pin rule yields.
    """
    store_root = tmp_path / "store"
    abolished = _write_bundle(store_root, "4.1.0")
    _write_bundle(store_root, "4.2.0")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    with pytest.raises(
        SkillBindingFailedError,
        match="below the minimum conform version 4.2.0",
    ):
        skills.bind_skill("create-userstory", abolished, project)

    assert skills.resolve_binding(project, "create-userstory") is None
    assert not (project / ".claude" / "skills" / "create-userstory").exists()
    assert not (project / ".codex" / "skills" / "create-userstory").exists()


def test_bind_skill_materialized_rejects_bundle_below_floor_before_side_effects(
    tmp_path: Path,
) -> None:
    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        Features,
        JenkinsConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )

    store_root = tmp_path / "store"
    abolished = _write_bundle(
        store_root,
        "4.0.0",
        bundle_id="lookup-userstory-core",
        skill_name="lookup-userstory",
    )
    project = tmp_path / "project"
    project.mkdir()
    config = ProjectConfig(
        project_key="project",
        project_name="Project",
        repositories=[RepositoryConfig(name="project", path=project)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )
    repository = InMemorySkillBindingRepository()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=repository,
    )
    variant_dir = tmp_path / "variants" / "lookup-userstory"

    with pytest.raises(
        SkillBindingFailedError,
        match="below the minimum conform version 4.1.0",
    ):
        skills.bind_skill_materialized(
            "lookup-userstory",
            abolished,
            project,
            config=config,
            variant_dir=variant_dir,
            ak3_interpreter_command='"C:\\AgentKit\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit\\agentkit.exe"',
        )

    assert repository.load(project.stem, "lookup-userstory") is None
    assert not variant_dir.exists()
    assert not (project / ".claude" / "skills" / "lookup-userstory").exists()
    assert not (project / ".codex" / "skills" / "lookup-userstory").exists()


def test_resolve_binding_rejects_persisted_bundle_below_floor(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    repository = InMemorySkillBindingRepository()
    repository.save(
        SkillBinding(
            binding_id="binding-id",
            project_key=project.stem,
            skill_name="lookup-userstory",
            bundle_id="lookup-userstory-core",
            bundle_version="4.0.0",
            content_digest="0" * 64,
            target_path=project / ".claude" / "skills" / "lookup-userstory",
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=datetime.now(tz=UTC),
        )
    )
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=tmp_path / "store"),
        binding_repo=repository,
    )

    with pytest.raises(
        SkillBindingFailedError,
        match="below the minimum conform version 4.1.0",
    ):
        skills.resolve_binding(project, "lookup-userstory")


def test_verify_rejects_execute_userstory_400_below_its_conform_floor(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    abolished = _write_bundle(
        store_root,
        "4.0.0",
        bundle_id="execute-userstory-core",
        skill_name="execute-userstory",
    )
    _write_bundle(
        store_root,
        "4.1.0",
        bundle_id="execute-userstory-core",
        skill_name="execute-userstory",
    )
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    with pytest.raises(
        SkillBindingFailedError,
        match="below the minimum conform version 4.1.0",
    ):
        skills.bind_skill("execute-userstory", abolished, project)


def test_installer_resolution_never_selects_a_bundle_below_the_floor(
    tmp_path: Path,
) -> None:
    from agentkit.backend.exceptions import InstallationError
    from agentkit.backend.installer.runner import (
        MANDATORY_SKILLS,
        InstallConfig,
        _resolve_mandatory_skill_bundles,
    )

    store_root = tmp_path / "store"
    _write_bundle(store_root, "4.1.0")
    store = SkillBundleStore(store_root=store_root)
    skills = Skills(
        bundle_store=store,
        binding_repo=InMemorySkillBindingRepository(),
    )
    project = tmp_path / "project"
    project.mkdir()
    config = InstallConfig(
        project_key="project",
        project_name="Project",
        project_root=project,
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids={name: "create-userstory-core" for name in MANDATORY_SKILLS},
    )

    with pytest.raises(
        InstallationError,
        match="below the minimum conform version 4.2.0",
    ) as captured:
        _resolve_mandatory_skill_bundles(config, project)

    assert captured.value.detail["cause"] == "BundleVersionNonConform"


def _relink_project_skill(project: Path, target: Path, *, both: bool) -> None:
    harnesses = (".claude", ".codex") if both else (".codex",)
    for harness in harnesses:
        link = project / harness / "skills" / "create-userstory"
        remove_directory_link(link)
        create_directory_link(link, target)


def test_verify_rejects_both_links_to_same_outside_store_self_declared_version(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    canonical = _write_bundle(store_root, "4.2.0")
    outside = _write_bundle(tmp_path / "foreign-store", "4.2.0")
    (outside / "SKILL.md").write_text("# foreign content\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", canonical, project)
    _relink_project_skill(project, outside, both=True)

    with pytest.raises(SkillBindingFailedError, match="outside its canonical pin"):
        skills.verify_pinned_binding(project, "create-userstory")


def test_verify_rejects_changed_skill_even_with_recomputed_manifest_digest(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    canonical = _write_bundle(store_root, "4.2.0")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", canonical, project)
    (canonical / "SKILL.md").write_text("# changed after pin\n", encoding="utf-8")
    manifest_path = canonical / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["self_recomputed"] = True
    manifest["manifest_digest"] = _manifest_digest(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillBindingFailedError, match="content diverges"):
        skills.verify_pinned_binding(project, "create-userstory")


def test_verify_rejects_only_one_same_version_foreign_harness_link(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    canonical = _write_bundle(store_root, "4.2.0")
    outside = _write_bundle(tmp_path / "foreign-store", "4.2.0")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", canonical, project)
    _relink_project_skill(project, outside, both=False)

    with pytest.raises(SkillBindingFailedError, match="different bundle versions"):
        skills.verify_pinned_binding(project, "create-userstory")


def test_verify_rejects_store_version_symlink_escape(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    canonical = _write_bundle(store_root, "4.2.0")
    project = tmp_path / "project"
    project.mkdir()
    skills = Skills(
        bundle_store=SkillBundleStore(store_root=store_root),
        binding_repo=InMemorySkillBindingRepository(),
    )
    skills.bind_skill("create-userstory", canonical, project)
    escaped = tmp_path / "escaped-version"
    canonical.rename(escaped)
    create_directory_link(canonical, escaped)

    with pytest.raises(
        SkillBindingFailedError,
        match="persisted pin is not canonically resolvable",
    ):
        skills.verify_pinned_binding(project, "create-userstory")
