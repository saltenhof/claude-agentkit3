"""AG3-176 AC4/AC6: mandatory VectorDB flow + firing CP10b hooks."""

from __future__ import annotations

from pathlib import Path

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import cp05_pipeline_config
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import (
    cp10b_concept_validation_hook,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.flow import build_installer_flow
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.vectordb.git_hooks import (
    SECRET_DETECTION_MARKER,
    pre_commit_path,
)


def test_detach_removes_story_kb_keeps_foreign_mcp(tmp_path: Path) -> None:
    """R10: detach surgically strips story-knowledge-base from both harness files."""
    import json

    from agentkit.backend.installer.lifecycle.detach import detach_project
    from agentkit.backend.installer.mcp_registration.detach_story_kb import (
        detach_story_knowledge_base,
    )
    from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
        CodexMcpServerEntry,
        surgical_merge_mcp_server,
    )

    # Foreign + AK3 in .mcp.json
    mcp = {
        "mcpServers": {
            "foreign-server": {"command": "echo", "args": ["hi"]},
            "story-knowledge-base": {
                "type": "stdio",
                "command": "agentkit-mcp-story-kb",
                "args": [],
            },
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
    # Foreign Codex + AK3 story-kb
    base_toml = '[mcp_servers.foreign]\ncommand = "echo"\nargs = ["x"]\ncwd = "."\nrequired = true\n'
    entry = CodexMcpServerEntry(
        command="agentkit-mcp-story-kb",
        args=(),
        cwd=str(tmp_path),
        env={"PROJECT_ID": "p"},
    )
    merged, _ = surgical_merge_mcp_server(base_toml, "story-knowledge-base", entry)
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(merged, encoding="utf-8")

    result = detach_story_knowledge_base(tmp_path)
    assert result.mcp_json_changed
    assert result.codex_changed

    mcp_after = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "story-knowledge-base" not in mcp_after.get("mcpServers", {})
    assert mcp_after["mcpServers"]["foreign-server"] == mcp["mcpServers"]["foreign-server"]
    codex_after = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert "story-knowledge-base" not in codex_after
    assert "foreign" in codex_after
    assert 'command = "echo"' in codex_after

    # Full detach_project also runs the surgical path
    detach_project(tmp_path)
    if (tmp_path / ".mcp.json").is_file():
        final = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
        assert "story-knowledge-base" not in final.get("mcpServers", {})


def test_cp08_verify_fails_when_harness_link_missing(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """R8: VERIFY is FAILED when a harness skill link is absent."""
    from agentkit.backend.installer.bootstrap_checkpoints.cp07_to_09 import (
        cp08_skill_bindings,
    )

    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_vectordb=True,
    )
    ctx = build_checkpoint_context(config, ExecutionMode.VERIFY)
    result = cp08_skill_bindings(ctx)
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == "skill_binding_pin_mismatch"
    detail = (result.detail or "").lower()
    assert (
        "link missing" in detail
        or "verify failed" in detail
        or "no readable manifest" in detail
    )


def test_flow_has_no_vectordb_optional_branch() -> None:
    flow = build_installer_flow()
    names = set(flow.node_names)
    assert "branch_vectordb_enabled" not in names
    assert "branch_vectordb_enabled_stage2" not in names
    # CP10 -> CP10a direct edge
    targets = {e.target for e in flow.get_edges_from(nid.CP_10_MCP_REGISTRATION)}
    assert nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES in targets
    # CP11 -> CP10b direct
    targets11 = {e.target for e in flow.get_edges_from(nid.CP_11_GIT_HOOKS_AND_CLAUDE)}
    assert nid.CP_10B_CONCEPT_VALIDATION_HOOK in targets11


def test_cp10b_materializes_pre_commit_with_secret_and_concept(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=registration_repo,
        features_vectordb=True,
    )
    # Minimal project.yaml for bind_project / concepts_dir
    cfg_dir = tmp_path / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "project.yaml").write_text(
        "project_key: demo\n"
        "project_name: demo\n"
        "repositories:\n  - name: app\n    path: .\n"
        "pipeline:\n"
        "  config_version: '3.0'\n"
        "  features:\n    multi_llm: false\n"
        "  sonarqube: {available: false, enabled: false}\n"
        "  ci: {available: false, enabled: false}\n"
        "  vectordb: {host: weaviate.test.local, port: 19903, grpc_port: 50051}\n"
        "concepts_dir: concepts\n"
        "wiki_stories_dir: stories\n",
        encoding="utf-8",
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    cp05_pipeline_config(ctx)
    result = cp10b_concept_validation_hook(ctx)
    assert result.status in (CheckpointStatus.CREATED, CheckpointStatus.PASS)
    pre = pre_commit_path(tmp_path)
    assert pre.is_file()
    content = pre.read_text(encoding="utf-8")
    # R6: secret-detection preserved + argv-safe Python dispatch (not shell validate).
    assert SECRET_DETECTION_MARKER in content
    assert "agentkit.backend.governance.guard_system.secret_scan" in content
    assert "--staged" in content  # secret_scan --staged
    assert "hook_dispatch pre-commit" in content
    assert 'python -m agentkit.backend.vectordb.hook_dispatch' in content
    assert '--concepts-dir "concepts"' in content
    assert ">>> agentkit" in content or "agentkit pre-commit dispatch" in content
    # Dispatcher owns validate --staged (not interpolated shell case).
    from agentkit.backend.vectordb import hook_dispatch as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")
    assert "validate" in src and "--staged" in src
    assert "build" in src  # post-commit build-before-sync
    # Idempotent re-run
    result2 = cp10b_concept_validation_hook(ctx)
    assert result2.status is CheckpointStatus.PASS


