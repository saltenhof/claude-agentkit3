"""fc_patterns repository adapter (FK-41 §41.3.2, FK-69 §69.3, AG3-040 Sub-Block (b)).

The DB-owner-side adapter for ``fc_patterns``. Lives — like the other
FK-69 repos — on the accessor side. The schema owner is ``failure-corpus`` (FK-41
§41.3.2); the DB owner is ``telemetry-and-events``.

AG3-040 Sub-Block (b) provides ONLY a table + repository skeleton (minimal CRUD
round-trip: ``save``/``load``/``list_for_project``). The full PatternPromotion
logic (clustering, thresholds, recompute) stays Out of Scope (FK-41 §41.5,
follow-up story). There is therefore no functional producer yet and no
wiring into the ``ProjectionAccessor``; the adapter is independently
instantiable (analogous to ``StateBackendFCIncidentsRepository``).

``save`` is an upsert on ``pattern_id`` (a FailurePatternRecord is updated over the
course of promotion — unlike the append-only ``fc_incidents``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.failure_corpus.pattern import FailurePatternRecord


@runtime_checkable
class FcPatternRepository(Protocol):
    """Write/read adapter for ``fc_patterns`` (FK-41 §41.3.2, FK-69 §69.3).

    Schema owner: failure-corpus (FK-41 §41.3.2).
    DB owner: telemetry-and-events.
    """

    def save(self, pattern: FailurePatternRecord) -> None:
        """Persist (upsert on ``pattern_id``) a FailurePatternRecord."""
        ...

    def load(self, pattern_id: str) -> FailurePatternRecord | None:
        """Load a FailurePatternRecord by ``pattern_id`` or ``None``."""
        ...

    def list_for_project(self, project_key: str) -> list[FailurePatternRecord]:
        """List all FailurePatterns of a project (FK-41 §41.3.2: project-bound)."""
        ...


def _pattern_to_row(pattern: FailurePatternRecord) -> dict[str, Any]:
    """Serialize a ``FailurePatternRecord`` into an fc_patterns row."""
    return {
        "pattern_id": pattern.pattern_id,
        "project_key": pattern.project_key,
        "status": pattern.status.value,
        "category": pattern.category.value,
        "invariant": pattern.invariant,
        "incident_refs": json.dumps(list(pattern.incident_refs)),
        "promotion_rule": pattern.promotion_rule.value,
        "risk_level": pattern.risk_level.value,
        "incident_count": pattern.incident_count,
        "confirmed_at": (
            pattern.confirmed_at.isoformat() if pattern.confirmed_at else None
        ),
        "confirmed_by": pattern.confirmed_by,
        "owner": pattern.owner,
        "check_ref": pattern.check_ref,
        "retired_at": pattern.retired_at.isoformat() if pattern.retired_at else None,
    }


def _row_to_pattern(row: dict[str, Any]) -> FailurePatternRecord:
    """Deserialize an fc_patterns row into a ``FailurePatternRecord``."""
    from datetime import datetime

    from agentkit.backend.core_types import FailureCategory, PatternStatus
    from agentkit.backend.failure_corpus.pattern import (
        FailurePatternRecord as _FailurePattern,
    )
    from agentkit.backend.failure_corpus.pattern import (
        PatternRiskLevel,
        PromotionRule,
    )

    def _dt(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    return _FailurePattern(
        pattern_id=str(row["pattern_id"]),
        project_key=str(row["project_key"]),
        status=PatternStatus(str(row["status"])),
        category=FailureCategory(str(row["category"])),
        invariant=str(row["invariant"]),
        incident_refs=_decode_str_list(row["incident_refs"]),
        promotion_rule=PromotionRule(str(row["promotion_rule"])),
        risk_level=PatternRiskLevel(str(row["risk_level"])),
        incident_count=int(row["incident_count"]),
        confirmed_at=_dt(row.get("confirmed_at")),
        confirmed_by=(
            str(row["confirmed_by"]) if row.get("confirmed_by") is not None else None
        ),
        owner=str(row["owner"]) if row.get("owner") is not None else None,
        check_ref=str(row["check_ref"]) if row.get("check_ref") is not None else None,
        retired_at=_dt(row.get("retired_at")),
    )


def _decode_str_list(raw: object) -> list[str]:
    """Decode a JSON ``list[str]`` column (SQLite TEXT or Postgres JSON).

    FAIL-CLOSED (NO ERROR BYPASSING): a non-string element is corrupt
    persistence and is reported as an error (FK-41 §41.3.2 list[str]).
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        decoded: object = json.loads(raw) if raw else []
    elif isinstance(raw, list):
        decoded = raw
    else:
        raise TypeError(f"unexpected JSON-list column type: {type(raw)!r}")
    if not isinstance(decoded, list):
        raise ValueError(
            f"fc_patterns incident_refs must be a JSON array, got "
            f"{type(decoded).__name__}"
        )
    if not all(isinstance(x, str) for x in decoded):
        raise ValueError(
            "fc_patterns incident_refs must contain only strings (FK-41 §41.3.2), "
            f"got element types {[type(x).__name__ for x in decoded]}"
        )
    return list(decoded)


class StateBackendFcPatternRepository:
    """Thin adapter for ``fc_patterns`` (SQLite + Postgres).

    Args:
        store_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    # -- Write --------------------------------------------------------------

    def save(self, pattern: FailurePatternRecord) -> None:
        """Persist (upsert on ``pattern_id``) a FailurePatternRecord."""
        row = _pattern_to_row(pattern)
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_UPSERT, row)
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                conn.execute(_SQLITE_UPSERT, row)

    # -- Read ---------------------------------------------------------------

    def load(self, pattern_id: str) -> FailurePatternRecord | None:
        """Load a FailurePatternRecord by ``pattern_id`` or ``None``."""
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(
                    "SELECT * FROM fc_patterns WHERE pattern_id = %s",
                    (pattern_id,),
                ).fetchone()
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                row = conn.execute(
                    "SELECT * FROM fc_patterns WHERE pattern_id = ?",
                    (pattern_id,),
                ).fetchone()
        return _row_to_pattern(dict(row)) if row is not None else None

    def list_for_project(self, project_key: str) -> list[FailurePatternRecord]:
        """List all FailurePatterns of a project (FK-41 §41.3.2: project-bound)."""
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM fc_patterns WHERE project_key = %s "
                    "ORDER BY pattern_id",
                    (project_key,),
                ).fetchall()
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                rows = conn.execute(
                    "SELECT * FROM fc_patterns WHERE project_key = ? "
                    "ORDER BY pattern_id",
                    (project_key,),
                ).fetchall()
        return [_row_to_pattern(dict(r)) for r in rows]


_COLUMNS = (
    "pattern_id, project_key, status, category, invariant, incident_refs, "
    "promotion_rule, risk_level, incident_count, confirmed_at, confirmed_by, "
    "owner, check_ref, retired_at"
)

_UPDATE_SET = (
    "project_key=excluded.project_key, status=excluded.status, "
    "category=excluded.category, invariant=excluded.invariant, "
    "incident_refs=excluded.incident_refs, promotion_rule=excluded.promotion_rule, "
    "risk_level=excluded.risk_level, incident_count=excluded.incident_count, "
    "confirmed_at=excluded.confirmed_at, confirmed_by=excluded.confirmed_by, "
    "owner=excluded.owner, check_ref=excluded.check_ref, "
    "retired_at=excluded.retired_at"
)

_SQLITE_UPSERT = f"""
    INSERT INTO fc_patterns ({_COLUMNS})
    VALUES (
        :pattern_id, :project_key, :status, :category, :invariant,
        :incident_refs, :promotion_rule, :risk_level, :incident_count,
        :confirmed_at, :confirmed_by, :owner, :check_ref, :retired_at
    )
    ON CONFLICT (pattern_id) DO UPDATE SET {_UPDATE_SET}
"""

_PG_UPSERT = f"""
    INSERT INTO fc_patterns ({_COLUMNS})
    VALUES (
        %(pattern_id)s, %(project_key)s, %(status)s, %(category)s,
        %(invariant)s, %(incident_refs)s, %(promotion_rule)s, %(risk_level)s,
        %(incident_count)s, %(confirmed_at)s, %(confirmed_by)s, %(owner)s,
        %(check_ref)s, %(retired_at)s
    )
    ON CONFLICT (pattern_id) DO UPDATE SET {_UPDATE_SET}
"""


__all__ = [
    "FcPatternRepository",
    "StateBackendFcPatternRepository",
]
