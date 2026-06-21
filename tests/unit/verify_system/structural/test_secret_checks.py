"""Secret filename and content structural check tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.pipeline_engine.phase_executor.models import PhaseSnapshot, PhaseStatus
from agentkit.backend.state_backend.store import save_phase_snapshot, save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.structural.checker import FULL_STAGE_REGISTRY, StructuralChecker
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "TEST-087"
_AWS_PREFIX = "AK" "IA"
_GITHUB_PREFIX = "gh" "p_"
_OPENAI_PREFIX = "sk" "-"


class _EvidencePort:
    def __init__(self, evidence: ChangeEvidence) -> None:
        self._evidence = evidence

    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return self._evidence


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        change_impact=ChangeImpact.LOCAL,
    )


def _seed(story_dir: Path, ctx: StoryContext) -> None:
    from datetime import UTC, datetime

    save_story_context(story_dir, ctx)
    save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id=ctx.story_id,
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),
            artifacts=[],
            evidence={},
        ),
    )


def _evidence(
    *,
    secret_files: tuple[str, ...] = (),
    secret_content_hits: tuple[str, ...] = (),
) -> ChangeEvidence:
    return ChangeEvidence(
        available=True,
        current_branch=f"story/{_STORY_ID}",
        commit_messages=(f"feat: {_STORY_ID} implement",),
        pushed=True,
        secret_files=secret_files,
        secret_content_hits=secret_content_hits,
        changed_files=("src/app.py",),
        actual_impact=ChangeImpact.LOCAL,
    )


def _run(story_dir: Path, evidence: ChangeEvidence) -> set[str]:
    result = StructuralChecker(
        registry=FULL_STAGE_REGISTRY,
        change_evidence_port=_EvidencePort(evidence),
    ).evaluate(_ctx(), story_dir)
    return {finding.check for finding in result.findings}


def test_security_secrets_blocks_new_file_name_patterns(tmp_path: Path) -> None:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    ctx = _ctx()
    _seed(story_dir, ctx)
    checks = _run(
        story_dir,
        _evidence(
            secret_files=(
                "config/credentials.json",
                "config/serviceaccount.json",
                "env/API_TOKEN.txt",
                "release/app.keystore",
                "release/app.jks",
            )
        ),
    )
    assert "security.secrets" in checks


def test_security_secrets_content_blocks_secret_prefixes(tmp_path: Path) -> None:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    ctx = _ctx()
    _seed(story_dir, ctx)
    checks = _run(
        story_dir,
        _evidence(
            secret_content_hits=(
                f"src/app.py:{_AWS_PREFIX}",
                f"src/app.py:{_GITHUB_PREFIX}",
                f"src/app.py:{_OPENAI_PREFIX}",
            )
        ),
    )
    assert "security.secrets_content" in checks


def test_security_stages_clean_on_clean_secret_evidence(tmp_path: Path) -> None:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    ctx = _ctx()
    _seed(story_dir, ctx)
    checks = _run(story_dir, _evidence())
    assert "security.secrets" not in checks
    assert "security.secrets_content" not in checks


def test_security_secrets_content_fail_closed_without_evidence(tmp_path: Path) -> None:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    checks = _run(story_dir, ChangeEvidence(available=False))
    assert "security.secrets_content" in checks
