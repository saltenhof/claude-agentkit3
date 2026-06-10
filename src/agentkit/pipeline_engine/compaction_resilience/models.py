"""Typed models for FK-36 compaction-resilience runtime artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
_SPAWN_ROUND_PATTERN = re.compile(r"^r(?P<round>[1-9]\d*)$")


class SpawnKey(BaseModel):
    """Parsed compound subagent type key from FK-36 §36.6.1."""

    agent_type_base: str
    story_id: str
    round: int

    model_config = ConfigDict(frozen=True)

    @property
    def value(self) -> str:
        """Return the stable wire-format spawn key."""
        return build_spawn_key(
            agent_type_base=self.agent_type_base,
            story_id=self.story_id,
            round_nr=self.round,
        )


class SpawnSpec(BaseModel):
    """Compose-time spawn metadata consumed by ``manifest_writer``."""

    story_id: str
    project_key: str
    spawn_key: str
    agent_type_base: str
    round: int
    prompt_file: Path
    prompt_hash: str
    resume_capsule_file: Path
    resume_capsule_hash: str
    guardrail_version: str
    created_at: str

    model_config = ConfigDict(frozen=True)

    @field_validator("prompt_hash", "resume_capsule_hash")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("hash fields must be lowercase SHA256 hex digests")
        return value


class AgentManifest(BaseModel):
    """Per-agent runtime manifest written at ``SubagentStart``."""

    agent_id: str
    spawn_key: str
    story_id: str
    project_key: str
    prompt_file: Path
    prompt_hash: str
    resume_capsule_file: Path
    resume_capsule_hash: str
    guardrail_version: str
    baseline_epoch: int = Field(ge=0)
    recovered_epoch: int = Field(ge=0)
    created_at: str

    model_config = ConfigDict(frozen=True)


class StoryMarker(BaseModel):
    """Worktree-local marker used by ``epoch_writer`` for story scoping."""

    story_id: str
    project_key: str
    run_id: str
    created_at: str

    model_config = ConfigDict(frozen=True)


def build_spawn_key(
    *,
    agent_type_base: str,
    story_id: str,
    round_nr: int,
) -> str:
    """Build the stable FK-36 compound spawn key."""
    if round_nr < 1:
        raise ValueError("round_nr must be >= 1")
    return f"{agent_type_base}--story={story_id}--r{round_nr}"


def parse_spawn_key(value: str) -> SpawnKey | None:
    """Parse ``{base}--story={id}--r{round}``, fail-open on unmanaged keys."""
    segments = value.split("--")
    story_segments = [segment for segment in segments if segment.startswith("story=")]
    if not story_segments:
        return None
    if len(segments) < 3:
        return None
    story_id = story_segments[0].removeprefix("story=")
    round_segment = segments[-1]
    match = _SPAWN_ROUND_PATTERN.fullmatch(round_segment)
    if not story_id or match is None:
        return None
    story_index = segments.index(story_segments[0])
    agent_type_base = "--".join(segments[:story_index])
    if not agent_type_base:
        return None
    return SpawnKey(
        agent_type_base=agent_type_base,
        story_id=story_id,
        round=int(match.group("round")),
    )


def valid_agent_id(value: str) -> bool:
    """Return whether an agent id is path-safe per FK-36 §36.10."""
    return _AGENT_ID_PATTERN.fullmatch(value) is not None


def coerce_json_object(value: Any) -> dict[str, Any]:
    """Return a JSON object dict or an empty dict for non-object hook input."""
    return value if isinstance(value, dict) else {}


__all__ = [
    "AgentManifest",
    "SpawnKey",
    "SpawnSpec",
    "StoryMarker",
    "build_spawn_key",
    "coerce_json_object",
    "parse_spawn_key",
    "valid_agent_id",
]
