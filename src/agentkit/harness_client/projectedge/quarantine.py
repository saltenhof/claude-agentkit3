"""Local-only worktree quarantine for a disowned Project Edge session.

Blood-type T with a thin R audit edge. The operation moves a whole local
worktree into a sibling quarantine store, falling back to copy-then-rename only
for cross-device moves. It never invokes Git, never uses a stash, and exposes no
backend/report/upload surface (FK-56 §56.13c/e; AG3-149).
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__all__ = ("QuarantineResult", "quarantine_worktree")


@dataclass(frozen=True)
class QuarantineResult:
    """Local audit result of one quarantined worktree."""

    event_id: str
    source_root: str
    quarantine_root: str
    reason: str
    occurred_at: str


def quarantine_worktree(
    *,
    source_root: Path,
    quarantine_store: Path,
    reason: str,
    now: datetime,
) -> QuarantineResult | None:
    """Atomically move/copy one local worktree into quarantine.

    Returns ``None`` when the source no longer exists (convergent replay).
    The audit is a local JSON file beside the quarantined directories; nothing
    from this module is serialised into a Project Edge request.
    """

    source = source_root.resolve()
    if not source.exists():
        return None
    if not source.is_dir():
        raise ValueError("quarantine source must be a directory")
    store = quarantine_store.resolve()
    if store == source or source in store.parents:
        raise ValueError("quarantine store must be outside the source worktree")

    event_id = f"quarantine-{uuid.uuid4().hex}"
    store.mkdir(parents=True, exist_ok=True)
    destination = store / f"{source.name}-{event_id}"
    try:
        os.replace(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        staging = store / f".{event_id}.copying"
        shutil.copytree(source, staging, copy_function=shutil.copy2)
        os.replace(staging, destination)
        shutil.rmtree(source)

    result = QuarantineResult(
        event_id=event_id,
        source_root=str(source),
        quarantine_root=str(destination),
        reason=reason,
        occurred_at=now.isoformat(),
    )
    audit_dir = store / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{event_id}.json"
    staging_audit = audit_dir / f".{event_id}.tmp"
    staging_audit.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(staging_audit, audit_path)
    return result
