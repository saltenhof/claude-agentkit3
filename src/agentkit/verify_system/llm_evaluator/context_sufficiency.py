"""Context sufficiency builder for Layer-2 review inputs (FK-37 §37.2)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.llm_evaluator.packing import BUNDLE_TOKEN_LIMIT

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

CONTEXT_SUFFICIENCY_FILE: str = "context_sufficiency.json"
CONTEXT_SUFFICIENCY_STAGE: str = "context_sufficiency"
CONTEXT_SUFFICIENCY_SCHEMA_VERSION: str = "1.0"

_MISSING_STATUSES: frozenset[str] = frozenset({"missing"})
_GAP_STATUSES: frozenset[str] = frozenset({"truncated", "summary_only"})
_SUMMARY_KEYS: tuple[str, ...] = ("concept_excerpt", "concept_summary", "summary")
_CONCEPT_PATHS_KEY: str = "concept_paths"
_EXTERNAL_SOURCES_KEY: str = "external_sources"


class SufficiencyLevel(StrEnum):
    """Layer-2 context sufficiency level."""

    SUFFICIENT = "sufficient"
    REVIEWABLE_WITH_GAPS = "reviewable_with_gaps"
    PARTIALLY_REVIEWABLE = "partially_reviewable"


class ContextFieldStatus(BaseModel):
    """Status of one semantic ContextBundle field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    chars: int = Field(ge=0)
    truncated: bool = False
    truncated_from: int | None = Field(default=None, ge=0)
    note: str | None = None


class ContextSufficiencyArtifact(BaseModel):
    """Persistable context-sufficiency artifact payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = CONTEXT_SUFFICIENCY_SCHEMA_VERSION
    story_id: str
    stage: str = CONTEXT_SUFFICIENCY_STAGE
    bundles: dict[str, ContextFieldStatus]
    sufficiency: SufficiencyLevel
    gaps: list[str]


@dataclass(frozen=True)
class ContextSufficiencyResult:
    """Builder result with enriched input and artifact payload."""

    enriched_input: Layer2ReviewInput
    arch_references: str
    evidence_manifest: BundleManifest | dict[str, object] | str | None
    sufficiency: SufficiencyLevel
    artifact: ContextSufficiencyArtifact

    @property
    def gaps(self) -> tuple[str, ...]:
        """Return sufficiency gaps."""
        return tuple(self.artifact.gaps)


class ContextSufficiencyBuilder:
    """Load, enrich, and classify the six FK-37 context fields."""

    def __init__(
        self,
        *,
        story_id: str,
        story_dir: Path,
        context_json: dict[str, object] | None = None,
        worktree_root: Path | None = None,
    ) -> None:
        """Initialize the builder."""
        self._story_id = story_id
        self._story_dir = story_dir
        self._context_json = dict(context_json or {})
        self._worktree_root = worktree_root or _infer_worktree_root(story_dir)

    @classmethod
    def from_story_dir(
        cls,
        *,
        story_id: str,
        story_dir: Path,
        worktree_root: Path | None = None,
    ) -> ContextSufficiencyBuilder:
        """Create a builder by loading ``context.json`` if present."""
        return cls(
            story_id=story_id,
            story_dir=story_dir,
            context_json=_load_context_json(story_dir),
            worktree_root=worktree_root,
        )

    def build(
        self,
        review_input: Layer2ReviewInput,
        *,
        caller_diff_summary: str | None = None,
        caller_evidence_manifest: BundleManifest | dict[str, object] | str | None = None,
    ) -> ContextSufficiencyResult:
        """Build enriched Layer-2 context and classify sufficiency."""
        story_spec = review_input.story_spec or self._load_story_spec()
        handover = review_input.handover or self._load_handover()
        concept_excerpt = review_input.concept_excerpt or self._load_concept_excerpt()
        arch_references = self._load_arch_references()
        diff_summary = caller_diff_summary
        evidence_manifest = caller_evidence_manifest

        field_values: dict[str, object | None] = {
            "story_spec": story_spec,
            "diff_summary": diff_summary,
            "concept_excerpt": concept_excerpt,
            "handover": handover,
            "arch_references": arch_references,
            "evidence_manifest": evidence_manifest,
        }
        bundles = {
            field_name: _status_for(field_name, value)
            for field_name, value in field_values.items()
        }
        gaps = _gaps_for(bundles)
        sufficiency = _classify(bundles)
        enriched = Layer2ReviewInput(
            story_spec=story_spec,
            diff_summary=diff_summary or review_input.diff_summary,
            concept_excerpt=concept_excerpt,
            handover=handover,
        )
        artifact = ContextSufficiencyArtifact(
            story_id=self._story_id,
            bundles=bundles,
            sufficiency=sufficiency,
            gaps=gaps,
        )
        return ContextSufficiencyResult(
            enriched_input=enriched,
            arch_references=arch_references,
            evidence_manifest=evidence_manifest,
            sufficiency=sufficiency,
            artifact=artifact,
        )

    def caller_diff_summary(self) -> str | None:
        """Return caller-supplied ``diff_summary`` from ``context.json``."""
        value = self._context_json.get("diff_summary")
        return value if isinstance(value, str) and value.strip() else None

    def caller_evidence_manifest(
        self,
    ) -> BundleManifest | dict[str, object] | str | None:
        """Return caller-supplied ``evidence_manifest`` from ``context.json``."""
        value = self._context_json.get("evidence_manifest")
        return _parse_evidence_manifest(value)

    def _load_story_spec(self) -> str:
        path = self._story_dir / "story.md"
        return _read_text(path)

    def _load_handover(self) -> str:
        path = self._story_dir / "handover.json"
        if not path.is_file():
            return ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Fail-OPEN per FK-33 §33.7.4 (sufficiency is a non-blocking pre-step):
            # a broken handover.json degrades the field to "missing" (a Warning),
            # never a hard crash. But the root-cause is PRESERVED in the log rather
            # than erased silently (FAIL-CLOSED evidence discipline, AG3-067 def-6).
            logger.warning(
                "context-sufficiency: handover.json at %s is unreadable/invalid "
                "(%s: %s); field degraded to 'missing'",
                path,
                type(exc).__name__,
                exc,
            )
            return ""
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def _load_concept_excerpt(self) -> str:
        loaded = self._load_concept_paths()
        if loaded:
            return loaded
        for key in _SUMMARY_KEYS:
            value = self._context_json.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _load_arch_references(self) -> str:
        parts: list[str] = []
        loaded = self._load_concept_paths()
        if loaded:
            parts.append(loaded)
        external_sources = self._context_json.get(_EXTERNAL_SOURCES_KEY)
        if isinstance(external_sources, list):
            rendered = [
                json.dumps(source, sort_keys=True, ensure_ascii=False)
                if isinstance(source, dict)
                else str(source)
                for source in external_sources
            ]
            if rendered:
                parts.append("## External Sources\n" + "\n".join(rendered))
        return "\n\n".join(parts)

    def _load_concept_paths(self) -> str:
        paths = self._context_json.get(_CONCEPT_PATHS_KEY)
        if not isinstance(paths, list):
            return ""
        sections: list[str] = []
        for raw_path in paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            path = self._resolve_concept_path(raw_path)
            if path is None:
                continue
            content = _read_text(path)
            if content:
                sections.append(f"## {path.as_posix()}\n{content}")
        return "\n\n".join(sections)

    def _resolve_concept_path(self, raw_path: str) -> Path | None:
        candidate = (self._worktree_root / raw_path).resolve()
        if candidate.is_file():
            return candidate
        concept_root = self._worktree_root / "concept"
        for base in (concept_root, concept_root / "domain-design", concept_root / "technical-design"):
            fallback = (base / raw_path).resolve()
            if fallback.is_file():
                return fallback
        return None


def _status_for(field_name: str, value: object | None) -> ContextFieldStatus:
    rendered = _render_field(value)
    if not rendered.strip():
        return ContextFieldStatus(status="missing", chars=0)
    if field_name == "diff_summary" and len(rendered) > BUNDLE_TOKEN_LIMIT:
        return ContextFieldStatus(
            status="truncated",
            chars=BUNDLE_TOKEN_LIMIT,
            truncated=True,
            truncated_from=len(rendered),
        )
    if field_name == "concept_excerpt" and _looks_summary_only(rendered):
        return ContextFieldStatus(
            status="summary_only",
            chars=len(rendered),
            note="Only summary text available; primary concept source was not loaded.",
        )
    return ContextFieldStatus(status="present", chars=len(rendered))


def _render_field(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BundleManifest):
        return value.model_dump_json()
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _looks_summary_only(value: str) -> bool:
    return bool(value.strip()) and "\n#" not in value and len(value) < 1_500


def _gaps_for(bundles: dict[str, ContextFieldStatus]) -> list[str]:
    gaps: list[str] = []
    for field_name, status in bundles.items():
        if status.status in _MISSING_STATUSES:
            gaps.append(f"{field_name}: missing")
        elif status.status in _GAP_STATUSES:
            gaps.append(f"{field_name}: {status.status}")
    return gaps


def _classify(bundles: dict[str, ContextFieldStatus]) -> SufficiencyLevel:
    if any(status.status in _MISSING_STATUSES for status in bundles.values()):
        return SufficiencyLevel.PARTIALLY_REVIEWABLE
    if any(status.status in _GAP_STATUSES for status in bundles.values()):
        return SufficiencyLevel.REVIEWABLE_WITH_GAPS
    return SufficiencyLevel.SUFFICIENT


def _load_context_json(story_dir: Path) -> dict[str, object]:
    path = story_dir / "context.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Fail-OPEN (FK-33 §33.7.4): a broken context.json degrades the
        # caller-side reference paths to "missing" (Warning), not a crash. The
        # root cause is logged, never erased silently (AG3-067 def-6).
        logger.warning(
            "context-sufficiency: context.json at %s is unreadable/invalid "
            "(%s: %s); caller-side fields degraded to 'missing'",
            path,
            type(exc).__name__,
            exc,
        )
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "context-sufficiency: context.json at %s is not a JSON object "
            "(got %s); caller-side fields degraded to 'missing'",
            path,
            type(payload).__name__,
        )
        return {}
    return payload


def _parse_evidence_manifest(value: object) -> BundleManifest | dict[str, object] | str | None:
    if value is None:
        return None
    if isinstance(value, BundleManifest):
        return value
    if isinstance(value, dict):
        try:
            return BundleManifest.model_validate(value)
        except ValueError:
            return dict(value)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        # Fail-OPEN (FK-33 §33.7.4): an unreadable concept/story source degrades
        # the field to "missing" (Warning), not a crash. The root cause is logged
        # rather than erased silently (AG3-067 def-6).
        logger.warning(
            "context-sufficiency: source file %s is unreadable (%s: %s); "
            "field degraded to 'missing'",
            path,
            type(exc).__name__,
            exc,
        )
        return ""


def _infer_worktree_root(story_dir: Path) -> Path:
    if story_dir.parent.name == "stories":
        return story_dir.parent.parent
    return story_dir


__all__ = [
    "CONTEXT_SUFFICIENCY_FILE",
    "CONTEXT_SUFFICIENCY_SCHEMA_VERSION",
    "CONTEXT_SUFFICIENCY_STAGE",
    "ContextFieldStatus",
    "ContextSufficiencyArtifact",
    "ContextSufficiencyBuilder",
    "ContextSufficiencyResult",
    "SufficiencyLevel",
]
