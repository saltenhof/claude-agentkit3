"""Preflight turn orchestration for review evidence enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.prompt_runtime.resources import load_prompt_template
from agentkit.telemetry.events import Event, EventType
from agentkit.verify_system.evidence.request_resolver import (
    RequestResolver,
    parse_preflight_response,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.verify_system.evidence.assembler import EvidenceAssemblyResult
    from agentkit.verify_system.evidence.preflight_sender import PreflightReviewSender
    from agentkit.verify_system.evidence.repo_context import RepoContext
    from agentkit.verify_system.evidence.request_types import RequestResult, ReviewerRequest


PREFLIGHT_TEMPLATE_NAME = "review-preflight"
PREFLIGHT_TEMPLATE_VERSION = 1
PREFLIGHT_SENTINEL_PREFIX = "[PREFLIGHT:review-preflight-v1:"


@dataclass(frozen=True)
class PreflightTurnResult:
    """Result of a preflight turn plus the final review send."""

    raw_preflight_response: str
    requests: tuple[ReviewerRequest, ...]
    results: tuple[RequestResult, ...]
    extended_paths: tuple[Path, ...]
    review_response: str


class PreflightTurn:
    """Run preflight-send, request resolution and review-send deterministically."""

    def __init__(
        self,
        *,
        repos: Mapping[str, RepoContext],
        spawn_worktree_repo: str,
        story_dir: Path,
        sender: PreflightReviewSender,
        emitter: EventEmitter | None = None,
    ) -> None:
        """Create the turn with its file-capable transport and telemetry sink."""
        self._repos = dict(repos)
        self._spawn_worktree_repo = spawn_worktree_repo
        self._story_dir = story_dir
        self._sender = sender
        self._emitter = emitter

    def run(
        self,
        *,
        story_id: str,
        assembly: EvidenceAssemblyResult,
        review_prompt: str,
    ) -> PreflightTurnResult:
        """Execute the FK-47 preflight turn and then send the enriched review."""
        preflight_prompt = render_preflight_prompt(assembly.manifest.render_prompt_header(), story_id)
        original_paths = _path_tuple(assembly.merge_paths)
        self._emit(story_id, EventType.PREFLIGHT_REQUEST, {"merge_path_count": len(original_paths)})
        raw_response = self._sender.send(prompt=preflight_prompt, merge_paths=original_paths)
        requests = tuple(parse_preflight_response(raw_response))
        results: tuple[RequestResult, ...] = ()
        if requests:
            resolver = RequestResolver(
                self._repos,
                self._spawn_worktree_repo,
                story_dir=self._story_dir,
            )
            results = tuple(resolver.resolve_all(list(requests)))
        extended_paths = _extended_paths(original_paths, results)
        self._emit(
            story_id,
            EventType.PREFLIGHT_RESPONSE,
            {"request_count": len(requests), "result_count": len(results)},
        )
        self._emit(
            story_id,
            EventType.PREFLIGHT_COMPLIANT,
            {"resolved_count": sum(1 for result in results if result.status == "RESOLVED")},
        )
        review_response = self._sender.send(
            prompt=render_review_prompt(
                review_prompt,
                results,
                bundle_manifest_header=assembly.manifest.render_prompt_header(),
            ),
            merge_paths=extended_paths,
        )
        return PreflightTurnResult(
            raw_preflight_response=raw_response,
            requests=requests,
            results=results,
            extended_paths=extended_paths,
            review_response=review_response,
        )

    def _emit(self, story_id: str, event_type: EventType, payload: dict[str, object]) -> None:
        if self._emitter is None:
            return
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=event_type,
                source_component="verify_system.preflight_turn",
                phase="implementation",
                payload={"story_id": story_id, **payload},
            )
        )


def make_preflight_sentinel(story_id: str) -> str:
    """Return the canonical preflight sentinel for a story."""
    return f"{PREFLIGHT_SENTINEL_PREFIX}{story_id}]"


def render_preflight_prompt(bundle_manifest_header: str, story_id: str) -> str:
    """Render the registered review-preflight prompt template."""
    template = load_prompt_template(PREFLIGHT_TEMPLATE_NAME)
    return template.format(
        story_id=story_id,
        BUNDLE_MANIFEST_HEADER=bundle_manifest_header,
    )


def render_review_prompt(
    review_prompt: str,
    results: Sequence[RequestResult],
    *,
    bundle_manifest_header: str | None = None,
) -> str:
    """Append manifest authority and preflight outcomes to the review prompt."""
    prompt_parts = [
        part for part in (bundle_manifest_header, review_prompt) if part is not None
    ]
    if not results:
        return "\n\n".join(prompt_parts)
    lines = ["\n\n".join(prompt_parts), "", "## Preflight Request Results", ""]
    for result in results:
        target = result.request.target
        lines.append(f"- {result.request.type.value} {target}: {result.status}")
        if result.file_path is not None:
            lines.append(f"  file_path: {result.file_path}")
        if result.status != "RESOLVED" and result.content:
            lines.append(f"  detail: {result.content}")
    return "\n".join(lines)


def _path_tuple(paths: Sequence[str]) -> tuple[Path, ...]:
    return tuple(Path(path) for path in paths)


def _extended_paths(
    original_paths: Sequence[Path],
    results: Sequence[RequestResult],
) -> tuple[Path, ...]:
    ordered: dict[str, Path] = {path.as_posix(): path for path in original_paths}
    for result in results:
        if result.status == "RESOLVED" and result.file_path is not None:
            path = Path(result.file_path)
            ordered.setdefault(path.as_posix(), path)
    return tuple(ordered.values())


__all__ = [
    "PREFLIGHT_SENTINEL_PREFIX",
    "PREFLIGHT_TEMPLATE_NAME",
    "PREFLIGHT_TEMPLATE_VERSION",
    "PreflightTurn",
    "PreflightTurnResult",
    "make_preflight_sentinel",
    "render_preflight_prompt",
    "render_review_prompt",
]
