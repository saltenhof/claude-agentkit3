"""Bundle manifest for deterministic review evidence assembly."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentkit.verify_system.evidence.authority import AuthorityClass, BundleEntry


def _iso_epoch(value: datetime | str | None) -> str:
    """Return an ISO-8601 UTC epoch string for a supplied or current instant."""
    if value is None:
        return datetime.now(UTC).isoformat()
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "evidence_epoch must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC).isoformat()


class BundleManifest(BaseModel):
    """Summary of the assembled review evidence bundle.

    Attributes:
        entries: Deterministically sorted bundle entries.
        total_size: Total UTF-8 byte size of included entry contents.
        truncated: Whether entries were excluded to enforce the size limit.
        warnings: Assembly warnings, including truncation and self-reference
            warnings.
        evidence_epoch: ISO-8601 assembly instant. It is injectable and is not
            part of ``manifest_hash``.
        manifest_hash: SHA-256 over sorted ``repo_id:path:size`` entry tuples.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[BundleEntry, ...]
    total_size: int = Field(ge=0)
    truncated: bool
    warnings: tuple[str, ...]
    evidence_epoch: str = Field(min_length=1)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("entries")
    @classmethod
    def _entries_must_be_unique(
        cls, value: tuple[BundleEntry, ...]
    ) -> tuple[BundleEntry, ...]:
        """Reject duplicate repo/path entries in the manifest."""
        seen: set[tuple[str, str]] = set()
        for entry in value:
            key = (entry.repo_id, entry.path.as_posix())
            if key in seen:
                msg = f"duplicate bundle entry: {entry.repo_id}:{entry.path.as_posix()}"
                raise ValueError(msg)
            seen.add(key)
        return value

    @classmethod
    def from_entries(
        cls,
        entries: list[BundleEntry],
        *,
        truncated: bool,
        warnings: list[str],
        evidence_epoch: datetime | str | None = None,
    ) -> BundleManifest:
        """Build a manifest and compute the deterministic manifest hash.

        Args:
            entries: Included bundle entries.
            truncated: Whether size-limit enforcement excluded entries.
            warnings: Assembly warnings to carry in-band.
            evidence_epoch: Optional injected assembly epoch.

        Returns:
            A frozen :class:`BundleManifest`.
        """
        sorted_entries = tuple(
            sorted(entries, key=lambda entry: (entry.repo_id, entry.path.as_posix()))
        )
        hash_input = "|".join(
            f"{entry.repo_id}:{entry.path.as_posix()}:{entry.size}"
            for entry in sorted_entries
        )
        manifest_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        return cls(
            entries=sorted_entries,
            total_size=sum(entry.size for entry in sorted_entries),
            truncated=truncated,
            warnings=tuple(warnings),
            evidence_epoch=_iso_epoch(evidence_epoch),
            manifest_hash=manifest_hash,
        )

    @property
    def file_paths(self) -> tuple[str, ...]:
        """Return deterministic repo-relative paths for review ``merge_paths``."""
        return tuple(entry.path.as_posix() for entry in self.entries)

    def render_prompt_header(self) -> str:
        """Render a deterministic header for review prompts.

        Returns:
            Structured Markdown that lists included files by authority class and
            records the evidence epoch and manifest hash.
        """
        labels: dict[AuthorityClass, str] = {
            AuthorityClass.PRIMARY_NORMATIVE: (
                "PRIMARY_NORMATIVE (authoritative sources, highest evidence strength)"
            ),
            AuthorityClass.PRIMARY_IMPLEMENTATION: (
                "PRIMARY_IMPLEMENTATION (changed files under review)"
            ),
            AuthorityClass.SECONDARY_CONTEXT: (
                "SECONDARY_CONTEXT (supporting context for verification)"
            ),
            AuthorityClass.WORKER_ASSERTION: (
                "WORKER_ASSERTION (worker-suggested context, lowest evidence strength)"
            ),
        }
        lines = ["## Bundle Content", ""]
        for authority in sorted(labels, key=lambda item: -item.value):
            entries = [
                entry for entry in self.entries if entry.authority == authority
            ]
            if not entries:
                continue
            lines.append(f"### {labels[authority]}")
            for entry in entries:
                scoped_path = f"{entry.repo_id}:{entry.path.as_posix()}"
                lines.append(f"- {scoped_path} ({entry.reason})")
            lines.append("")
        lines.append(f"Evidence-Epoch: {self.evidence_epoch}")
        lines.append(f"Manifest-Hash: {self.manifest_hash}")
        return "\n".join(lines)


__all__ = ["BundleManifest"]
