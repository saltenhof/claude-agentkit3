"""File-backed durable store for the §53.5 Story-Reset record (AG3-071).

The reset record is the human-readable, auditable proof of the administrative
intervention (§53.7.4: a small, durable proof — NOT a hidden shadow copy of the
runtime state). The authoritative idempotency / resume CLAIM lives in the existing
``ControlPlaneOperationRecord`` (real DB, ``operation_kind='story_reset'``); this
store is its audit twin, persisted as one JSON file per ``reset_id`` under the
reset audit root (mirroring the ``story_exit`` ``var/story_exit/...`` artifact
pattern). It introduces NO new operative state table and NO second claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentkit.story_reset.models import StoryResetRecord


class FileResetRecordStore:
    """JSON-file durable :class:`StoryResetRecord` store (one file per reset_id).

    Args:
        audit_root: Root directory for reset audit records (defaults to
            ``var/story_reset``, ephemeral-but-durable per CLAUDE.md ``var/``).
    """

    def __init__(self, audit_root: Path | str = Path("var/story_reset")) -> None:
        self._root = Path(audit_root)

    def _path(self, reset_id: str) -> Path:
        # reset_id is a service-minted ``story-reset-<hex>`` token (no path
        # separators); guard anyway against traversal in a fail-closed manner.
        safe = reset_id.replace("/", "_").replace("\\", "_")
        return self._root / safe / "story_reset_record.json"

    def load(self, reset_id: str) -> StoryResetRecord | None:
        """Load the reset record for ``reset_id`` (``None`` when absent)."""
        path = self._path(reset_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return StoryResetRecord.model_validate(data)

    def save(self, record: StoryResetRecord) -> None:
        """Persist (upsert) the reset record as pretty, stable JSON."""
        path = self._path(record.reset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )


__all__ = ["FileResetRecordStore"]
