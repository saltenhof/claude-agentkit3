from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from agentkit.backend.pipeline_engine.compaction_resilience.artifacts import (
    GUARDRAIL_VERSION,
    RESUME_CAPSULE_MAX_CHARS,
    build_resume_capsule,
    sha256_file,
    write_compaction_artifacts,
)
from agentkit.backend.pipeline_engine.compaction_resilience.cleanup import run as cleanup_run
from agentkit.backend.pipeline_engine.compaction_resilience.epoch_writer import run as epoch_run
from agentkit.backend.pipeline_engine.compaction_resilience.manifest_writer import (
    run as manifest_run,
)
from agentkit.backend.pipeline_engine.compaction_resilience.models import (
    AgentManifest,
    SpawnSpec,
    parse_spawn_key,
)
from agentkit.backend.pipeline_engine.compaction_resilience.paths import (
    first_tool_path,
    manifest_path,
)
from agentkit.backend.pipeline_engine.compaction_resilience.recovery_injector import (
    run as recovery_run,
)
from agentkit.backend.prompt_runtime.composer import ComposeConfig
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class MemoryEpochRepository:
    epochs: dict[tuple[str, str], int] = field(default_factory=dict)

    def read_epoch(self, project_key: str, story_id: str) -> int:
        return self.epochs.get((project_key, story_id), 0)

    def increment_epoch(self, project_key: str, story_id: str) -> int:
        key = (project_key, story_id)
        self.epochs[key] = self.epochs.get(key, 0) + 1
        return self.epochs[key]


def _ctx(project_root: Path, *, title: str = "Build compaction support") -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-075",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title=title,
        project_root=project_root,
        worktree_path=project_root / "worktrees" / "AG3-075",
        worktree_map={"repo": project_root / "worktrees" / "AG3-075"},
        participating_repos=["repo"],
        labels=["pipeline-framework"],
        concept_paths=("concept/technical-design/36_compaction_resilience_prompt_persistence.md",),
    )


def _write_prompt(root: Path, content: str = "# full prompt secret body\n") -> Path:
    path = root / ".agentkit" / "prompts" / "run-1" / "inv-1" / "prompt.md"
    atomic_write_text(path, content, newline="")
    return path


def _write_manifest(root: Path, repo: MemoryEpochRepository, *, recovered_epoch: int = 0) -> AgentManifest:
    prompt = _write_prompt(root)
    artifacts = write_compaction_artifacts(
        _ctx(root),
        ComposeConfig(story_type=StoryType.IMPLEMENTATION),
        project_root=root,
        prompt_file=prompt,
        agent_type_base="worker-implementation",
    )
    repo.epochs[("test-project", "AG3-075")] = recovered_epoch
    manifest = AgentManifest(
        agent_id="agent-1",
        spawn_key=artifacts.spawn_key,
        story_id="AG3-075",
        project_key="test-project",
        prompt_file=prompt,
        prompt_hash=sha256_file(prompt),
        resume_capsule_file=artifacts.resume_capsule_path,
        resume_capsule_hash=sha256_file(artifacts.resume_capsule_path),
        guardrail_version=GUARDRAIL_VERSION,
        baseline_epoch=recovered_epoch,
        recovered_epoch=recovered_epoch,
        created_at="2026-06-09T00:00:00+00:00",
    )
    atomic_write_text(manifest_path(root, "agent-1"), manifest.model_dump_json(indent=2), newline="")
    return manifest


def test_spawn_key_parse_fail_open_without_story_segment() -> None:
    assert parse_spawn_key("qa-semantic--r2") is None
    parsed = parse_spawn_key("qa-semantic--story=AG3-075--r2")
    assert parsed is not None
    assert parsed.agent_type_base == "qa-semantic"
    assert parsed.story_id == "AG3-075"
    assert parsed.round == 2


def test_spawn_round_pattern_is_ascii_only() -> None:
    """_SPAWN_ROUND_PATTERN must match ASCII digits only (re.ASCII).

    Unicode decimal digits (e.g. Arabic-Indic ١ = '1') must NOT match
    so that round parsing is identical to the original [1-9][0-9]* behavior.
    """
    # ASCII round segments must still parse correctly.
    assert parse_spawn_key("worker--story=AG3-001--r1") is not None
    assert parse_spawn_key("worker--story=AG3-001--r99") is not None
    # Unicode digit in round segment must be rejected.
    # ١ is ARABIC-INDIC DIGIT ONE (decimal value 1, matched by \d without re.ASCII).
    unicode_round = "worker--story=AG3-001--r١"
    assert parse_spawn_key(unicode_round) is None


def test_resume_capsule_is_structured_bounded_and_has_guardrails(tmp_path: Path) -> None:
    prompt = _write_prompt(tmp_path, "# full prompt\nDO-NOT-COPY-ME\n")
    capsule = build_resume_capsule(
        _ctx(tmp_path, title="x" * 10_000),
        prompt_file=prompt,
        spawn_key="worker-implementation--story=AG3-075--r1",
        guardrail_version=GUARDRAIL_VERSION,
    )
    assert len(capsule) <= RESUME_CAPSULE_MAX_CHARS
    assert f"Guardrail Invariants ({GUARDRAIL_VERSION})" in capsule
    assert "Zero Debt" in capsule
    assert "DO-NOT-COPY-ME" not in capsule
    assert "Volltext von CLAUDE.md" not in capsule


def test_write_compaction_artifacts_writes_spawn_spec_with_hashes(tmp_path: Path) -> None:
    prompt = _write_prompt(tmp_path)
    artifacts = write_compaction_artifacts(
        _ctx(tmp_path),
        ComposeConfig(story_type=StoryType.IMPLEMENTATION, round_nr=3),
        project_root=tmp_path,
        prompt_file=prompt,
        agent_type_base="worker-implementation",
    )
    assert artifacts.spawn_key == "worker-implementation--story=AG3-075--r3"
    spec = SpawnSpec.model_validate(json.loads(artifacts.spawn_spec_path.read_text(encoding="utf-8")))
    assert spec.project_key == "test-project"
    assert spec.prompt_hash == sha256_file(prompt)
    assert spec.resume_capsule_hash == sha256_file(artifacts.resume_capsule_path)


def test_manifest_writer_writes_manifest_with_project_key_and_epoch(tmp_path: Path) -> None:
    prompt = _write_prompt(tmp_path)
    artifacts = write_compaction_artifacts(
        _ctx(tmp_path),
        ComposeConfig(story_type=StoryType.IMPLEMENTATION),
        project_root=tmp_path,
        prompt_file=prompt,
        agent_type_base="worker-implementation",
    )
    repo = MemoryEpochRepository({("test-project", "AG3-075"): 4})

    written = manifest_run(
        {
            "agent_id": "agent-1",
            "agent_type": artifacts.spawn_key,
            "cwd": str(tmp_path),
        },
        repository=repo,
    )

    assert written is True
    manifest = AgentManifest.model_validate(json.loads(manifest_path(tmp_path, "agent-1").read_text(encoding="utf-8")))
    assert manifest.project_key == "test-project"
    assert manifest.baseline_epoch == 4
    assert manifest.recovered_epoch == 4


def test_manifest_writer_fail_open_for_unmanaged_or_drifted_spawn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert manifest_run({"agent_id": "agent-1", "agent_type": "worker--r1", "cwd": str(tmp_path)}) is False
    assert not manifest_path(tmp_path, "agent-1").exists()
    prompt = _write_prompt(tmp_path)
    artifacts = write_compaction_artifacts(
        _ctx(tmp_path),
        ComposeConfig(story_type=StoryType.IMPLEMENTATION),
        project_root=tmp_path,
        prompt_file=prompt,
        agent_type_base="worker-implementation",
    )
    atomic_write_text(artifacts.resume_capsule_path, "drifted", newline="")

    assert manifest_run({"agent_id": "agent-1", "agent_type": artifacts.spawn_key, "cwd": str(tmp_path)}) is False
    assert "warning" in capsys.readouterr().err


def test_manifest_writer_rejects_path_traversal_before_path_build(tmp_path: Path) -> None:
    assert manifest_run({"agent_id": "../bad", "agent_type": "worker--story=AG3-075--r1", "cwd": str(tmp_path)}) is False
    assert not (tmp_path / "_temp").exists()


def test_recovery_contract_first_tool_then_inject_and_update(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = MemoryEpochRepository()
    _write_manifest(tmp_path, repo, recovered_epoch=0)
    repo.epochs[("test-project", "AG3-075")] = 1

    assert recovery_run({"agent_id": "agent-1", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo) is None
    assert first_tool_path(tmp_path, "agent-1").exists()
    injected = recovery_run({"agent_id": "agent-1", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo)

    assert injected is not None
    assert "[COMPACTION RECOVERY" in injected
    assert "Original task restored" in injected
    manifest = AgentManifest.model_validate(json.loads(manifest_path(tmp_path, "agent-1").read_text(encoding="utf-8")))
    assert manifest.recovered_epoch == 1
    assert "additionalContext" in capsys.readouterr().out


def test_recovery_no_manifest_no_compaction_and_invalid_agent_id(tmp_path: Path) -> None:
    repo = MemoryEpochRepository()
    assert recovery_run({"agent_id": "../bad", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo) is None
    assert recovery_run({"agent_id": "agent-1", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo) is None
    _write_manifest(tmp_path, repo, recovered_epoch=2)
    atomic_write_text(first_tool_path(tmp_path, "agent-1"), "", newline="")
    repo.epochs[("test-project", "AG3-075")] = 2
    assert recovery_run({"agent_id": "agent-1", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo) is None


def test_recovery_mutating_tools_inject_with_warning_not_deny(tmp_path: Path) -> None:
    repo = MemoryEpochRepository()
    _write_manifest(tmp_path, repo, recovered_epoch=0)
    atomic_write_text(first_tool_path(tmp_path, "agent-1"), "", newline="")
    repo.epochs[("test-project", "AG3-075")] = 1

    injected = recovery_run({"agent_id": "agent-1", "tool_name": "Agent", "cwd": str(tmp_path)}, repository=repo)

    assert injected is not None
    assert "WARNING" in injected
    assert "[COMPACTION RECOVERY" in injected


def test_recovery_capsule_drift_warns_without_inject(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = MemoryEpochRepository()
    manifest = _write_manifest(tmp_path, repo, recovered_epoch=0)
    atomic_write_text(first_tool_path(tmp_path, "agent-1"), "", newline="")
    atomic_write_text(manifest.resume_capsule_file, "drifted", newline="")
    repo.epochs[("test-project", "AG3-075")] = 1

    assert recovery_run({"agent_id": "agent-1", "tool_name": "Read", "cwd": str(tmp_path)}, repository=repo) is None
    assert "hash mismatch" in capsys.readouterr().err


def test_epoch_writer_walkup_increments_and_isolates_stories(tmp_path: Path) -> None:
    repo = MemoryEpochRepository()
    worktree = tmp_path / "repo" / "worktrees" / "AG3-075"
    nested = worktree / "src" / "pkg"
    nested.mkdir(parents=True)
    atomic_write_text(
        worktree / ".agentkit-story.json",
        json.dumps(
            {
                "story_id": "AG3-075",
                "project_key": "test-project",
                "run_id": "AG3-075",
                "created_at": "2026-06-09T00:00:00+00:00",
            }
        ),
    )
    repo.epochs[("test-project", "AG3-076")] = 8

    assert epoch_run({"cwd": str(nested)}, repository=repo) == 1
    assert repo.read_epoch("test-project", "AG3-075") == 1
    assert repo.read_epoch("test-project", "AG3-076") == 8


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"story_id": "AG3-075", "run_id": "r"},
        "not-json",
    ],
)
def test_epoch_writer_fail_open_for_missing_or_invalid_marker(
    tmp_path: Path,
    payload: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = MemoryEpochRepository()
    if payload is not None:
        marker = tmp_path / ".agentkit-story.json"
        marker.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    assert epoch_run({"cwd": str(tmp_path)}, repository=repo) is None
    assert repo.epochs == {}
    assert "warning" in capsys.readouterr().err


def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    atomic_write_text(manifest_path(tmp_path, "agent-1"), "{}", newline="")
    atomic_write_text(first_tool_path(tmp_path, "agent-1"), "", newline="")
    assert cleanup_run({"agent_id": "agent-1", "cwd": str(tmp_path)}) == 2
    assert cleanup_run({"agent_id": "agent-1", "cwd": str(tmp_path)}) == 0


@pytest.mark.parametrize(
    "module_name",
    ["manifest_writer", "recovery_injector", "epoch_writer", "cleanup"],
)
def test_hook_modules_are_python_m_invocable(tmp_path: Path, module_name: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            f"agentkit.backend.pipeline_engine.compaction_resilience.{module_name}",
        ],
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
