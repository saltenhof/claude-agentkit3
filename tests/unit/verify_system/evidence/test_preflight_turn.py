"""Tests for FK-47 preflight turn orchestration and sender port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.telemetry.contract.preflight_sentinel import PreflightSentinel
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.contract.results import ContractStatus
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import Event, EventType
from agentkit.verify_system.evidence import (
    AuthorityClass,
    BundleEntry,
    BundleManifest,
    EvidenceAssemblyResult,
    FailClosedPreflightReviewSender,
    PreflightReviewSenderError,
    PreflightTurn,
    RepoContext,
    make_preflight_sentinel,
    render_preflight_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass
class RecordingSender:
    """Deterministic file-capable sender for tests."""

    responses: list[str]
    prompts: list[str] = field(default_factory=list)
    merge_paths: list[tuple[Path, ...]] = field(default_factory=list)

    def send(self, *, prompt: str, merge_paths: Sequence[Path]) -> str:
        self.prompts.append(prompt)
        self.merge_paths.append(tuple(merge_paths))
        return self.responses.pop(0)


def _repo(tmp_path: Path) -> RepoContext:
    repo_path = tmp_path / "app"
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    (repo_path / "src" / "context.py").write_text("CONTEXT = 1\n", encoding="utf-8")
    return RepoContext(repo_id="app", repo_path=repo_path, affected=True)


def _assembly() -> EvidenceAssemblyResult:
    entry = BundleEntry(
        repo_id="app",
        path=Path("src/app.py"),
        authority=AuthorityClass.PRIMARY_IMPLEMENTATION,
        confidence=None,
        reason="Changed file",
        size=13,
        content="print('app')\n",
    )
    manifest = BundleManifest.from_entries(
        [entry],
        truncated=False,
        warnings=[],
        evidence_epoch="2026-06-08T12:00:00+00:00",
    )
    return EvidenceAssemblyResult(manifest=manifest, merge_paths=manifest.file_paths)


def _records(events: list[Event]) -> list[ExecutionEventRecord]:
    return [
        ExecutionEventRecord(
            project_key=event.project_key,
            story_id=event.story_id,
            run_id=event.run_id,
            event_id=event.event_id or f"event-{index}",
            event_type=event.event_type.value,
            occurred_at=datetime.now(UTC),
            source_component=event.source_component,
            severity=event.severity,
        )
        for index, event in enumerate(events)
    ]


def test_preflight_turn_with_valid_answer_extends_paths_and_balances_telemetry(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sender = RecordingSender([
        '{"requests":[{"type":"NEED_FILE","target":"src/context.py","reason":"needed"}]}',
        "review complete",
    ])
    emitter = MemoryEmitter()
    turn = PreflightTurn(
        repos={"app": repo},
        spawn_worktree_repo="app",
        story_dir=tmp_path / "stories" / "AG3-062",
        sender=sender,
        emitter=emitter,
    )

    assembly = _assembly()
    result = turn.run(story_id="AG3-062", assembly=assembly, review_prompt="review")

    assert result.extended_paths == (Path("src/app.py"), Path("src/context.py"))
    assert sender.merge_paths == [
        (Path("src/app.py"),),
        (Path("src/app.py"), Path("src/context.py")),
    ]
    assert "## Bundle Content" in sender.prompts[-1]
    assert "PRIMARY_IMPLEMENTATION" in sender.prompts[-1]
    assert f"Manifest-Hash: {assembly.manifest.manifest_hash}" in sender.prompts[-1]
    assert result.review_response == "review complete"
    assert [event.event_type for event in emitter.all_events] == [
        EventType.PREFLIGHT_REQUEST,
        EventType.PREFLIGHT_RESPONSE,
        EventType.PREFLIGHT_COMPLIANT,
    ]
    assert PreflightSentinel().check_balance(_records(emitter.all_events)).status is ContractStatus.PASS


def test_preflight_turn_invalid_answer_continues_with_original_bundle(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = _repo(tmp_path)
    sender = RecordingSender(["not-json", "review complete"])
    turn = PreflightTurn(
        repos={"app": repo},
        spawn_worktree_repo="app",
        story_dir=tmp_path / "stories" / "AG3-062",
        sender=sender,
    )

    result = turn.run(story_id="AG3-062", assembly=_assembly(), review_prompt="review")

    assert result.requests == ()
    assert result.results == ()
    assert result.extended_paths == (Path("src/app.py"),)
    assert sender.merge_paths[-1] == (Path("src/app.py"),)
    assert "could not be parsed" in caplog.text


def test_preflight_turn_all_unresolved_continues_with_original_bundle(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sender = RecordingSender([
        '{"requests":[{"type":"NEED_FILE","target":"missing.py","reason":"needed"}]}',
        "review complete",
    ])
    turn = PreflightTurn(
        repos={"app": repo},
        spawn_worktree_repo="app",
        story_dir=tmp_path / "stories" / "AG3-062",
        sender=sender,
    )

    result = turn.run(story_id="AG3-062", assembly=_assembly(), review_prompt="review")

    assert [request_result.status for request_result in result.results] == ["UNRESOLVED"]
    assert result.extended_paths == (Path("src/app.py"),)
    assert "UNRESOLVED" in sender.prompts[-1]


def test_fail_closed_preflight_sender_raises_without_productive_transport() -> None:
    with pytest.raises(PreflightReviewSenderError, match="No productive file-capable"):
        FailClosedPreflightReviewSender().send(prompt="prompt", merge_paths=[Path("src/app.py")])


def test_preflight_prompt_sentinel_uses_prefight_prefix_and_not_template_prefix() -> None:
    sentinel = make_preflight_sentinel("AG3-062")
    prompt = render_preflight_prompt("header", "AG3-062")

    assert sentinel == "[PREFLIGHT:review-preflight-v1:AG3-062]"
    assert sentinel in prompt
    assert "[TEMPLATE:" not in prompt
    assert "[SENTINEL:" not in prompt
