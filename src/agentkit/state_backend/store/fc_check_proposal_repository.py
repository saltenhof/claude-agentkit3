"""fc_check_proposals repository adapter (FK-41 §41.3.3, FK-69 §69.3, AG3-040 (b)).

The DB-owner-side adapter for ``fc_check_proposals``. Lives — like the
other FK-69 repos — on the accessor side in ``state_backend/store``
(boundary ``state_backend_repository``). The schema owner is ``failure-corpus``
(FK-41 §41.3.3); the DB owner is ``telemetry-and-events``.

AG3-040 Sub-Block (b) provides ONLY a table + repository skeleton (minimal CRUD
round-trip: ``save``/``load``/``list_for_pattern``). The full CheckFactory logic
(derivation, effectiveness check) stays Out of Scope (FK-41 §41.6, follow-up
story). ``save`` is an upsert on ``check_id``.

``pattern_ref`` is an FK to ``fc_patterns(pattern_id)``: a proposal without an
existing pattern is rejected fail-closed on the DB side (FK-41 §41.3.3).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.state_backend.store.projection_repositories import (
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.failure_corpus.check_proposal import CheckProposalRecord


@runtime_checkable
class FcCheckProposalRepository(Protocol):
    """Write/read adapter for ``fc_check_proposals`` (FK-41 §41.3.3).

    Schema owner: failure-corpus (FK-41 §41.3.3).
    DB owner: telemetry-and-events.
    """

    def save(self, proposal: CheckProposalRecord) -> None:
        """Persist (upsert on ``check_id``) a CheckProposalRecord."""
        ...

    def load(self, check_id: str) -> CheckProposalRecord | None:
        """Load a CheckProposalRecord by ``check_id`` or ``None``."""
        ...

    def list_for_pattern(self, pattern_ref: str) -> list[CheckProposalRecord]:
        """List all CheckProposals for a ``pattern_ref`` (FK-41 §41.3.3)."""
        ...


def _proposal_to_row(proposal: CheckProposalRecord) -> dict[str, Any]:
    """Serialize a ``CheckProposalRecord`` into an fc_check_proposals row."""
    return {
        "check_id": proposal.check_id,
        "project_key": proposal.project_key,
        "status": proposal.status.value,
        "pattern_ref": proposal.pattern_ref,
        "invariant": proposal.invariant,
        "check_type": proposal.check_type.value,
        "pipeline_stage": proposal.pipeline_stage,
        "pipeline_layer": proposal.pipeline_layer,
        "owner": proposal.owner,
        "false_positive_risk": proposal.false_positive_risk.value,
        "positive_fixtures": json.dumps(list(proposal.positive_fixtures)),
        "negative_fixtures": json.dumps(list(proposal.negative_fixtures)),
        "created_at": proposal.created_at.isoformat(),
        "approved_at": (
            proposal.approved_at.isoformat() if proposal.approved_at else None
        ),
        "approved_by": proposal.approved_by,
        "rejected_reason": proposal.rejected_reason,
        "effectiveness_last_checked_at": (
            proposal.effectiveness_last_checked_at.isoformat()
            if proposal.effectiveness_last_checked_at
            else None
        ),
        "true_positives_90d": proposal.true_positives_90d,
        "false_positives_90d": proposal.false_positives_90d,
    }


def _row_to_proposal(row: dict[str, Any]) -> CheckProposalRecord:
    """Deserialize an fc_check_proposals row into a ``CheckProposalRecord``."""
    from datetime import datetime

    from agentkit.core_types import CheckStatus, CheckType
    from agentkit.failure_corpus.check_proposal import (
        CheckProposalRecord as _CheckProposal,
    )
    from agentkit.failure_corpus.check_proposal import (
        FalsePositiveRisk,
    )

    def _dt(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    created_at = _dt(row["created_at"])
    if created_at is None:  # pragma: no cover - NOT NULL column, defensive
        raise ValueError("fc_check_proposals.created_at must not be NULL")

    def _opt_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        return int(str(value))

    return _CheckProposal(
        check_id=str(row["check_id"]),
        project_key=str(row["project_key"]),
        status=CheckStatus(str(row["status"])),
        pattern_ref=str(row["pattern_ref"]),
        invariant=str(row["invariant"]),
        check_type=CheckType(str(row["check_type"])),
        pipeline_stage=str(row["pipeline_stage"]),
        pipeline_layer=int(row["pipeline_layer"]),
        owner=str(row["owner"]),
        false_positive_risk=FalsePositiveRisk(str(row["false_positive_risk"])),
        positive_fixtures=_decode_dict_list(row["positive_fixtures"]),
        negative_fixtures=_decode_dict_list(row["negative_fixtures"]),
        created_at=created_at,
        approved_at=_dt(row.get("approved_at")),
        approved_by=(
            str(row["approved_by"]) if row.get("approved_by") is not None else None
        ),
        rejected_reason=(
            str(row["rejected_reason"])
            if row.get("rejected_reason") is not None
            else None
        ),
        effectiveness_last_checked_at=_dt(row.get("effectiveness_last_checked_at")),
        true_positives_90d=_opt_int(row.get("true_positives_90d")),
        false_positives_90d=_opt_int(row.get("false_positives_90d")),
    )


def _decode_dict_list(raw: object) -> list[dict[str, Any]]:
    """Decode a JSON ``list[dict]`` column (SQLite TEXT or Postgres JSON).

    FAIL-CLOSED: a non-object element is corrupt persistence (FK-41
    §41.3.3 fixtures = ``{description, expected}``).
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
            f"fc_check_proposals fixtures must be a JSON array, got "
            f"{type(decoded).__name__}"
        )
    if not all(isinstance(x, dict) for x in decoded):
        raise ValueError(
            "fc_check_proposals fixtures must contain only objects (FK-41 §41.3.3)"
        )
    return [dict(x) for x in decoded]


class StateBackendFcCheckProposalRepository:
    """Thin adapter for ``fc_check_proposals`` (SQLite + Postgres).

    Args:
        store_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    # -- Write --------------------------------------------------------------

    def save(self, proposal: CheckProposalRecord) -> None:
        """Persist (upsert on ``check_id``) a CheckProposalRecord."""
        row = _proposal_to_row(proposal)
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_UPSERT, row)
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                conn.execute(_SQLITE_UPSERT, row)

    # -- Read ---------------------------------------------------------------

    def load(self, check_id: str) -> CheckProposalRecord | None:
        """Load a CheckProposalRecord by ``check_id`` or ``None``."""
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(
                    "SELECT * FROM fc_check_proposals WHERE check_id = %s",
                    (check_id,),
                ).fetchone()
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                row = conn.execute(
                    "SELECT * FROM fc_check_proposals WHERE check_id = ?",
                    (check_id,),
                ).fetchone()
        return _row_to_proposal(dict(row)) if row is not None else None

    def list_for_pattern(self, pattern_ref: str) -> list[CheckProposalRecord]:
        """List all CheckProposals for a ``pattern_ref`` (FK-41 §41.3.3)."""
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM fc_check_proposals WHERE pattern_ref = %s "
                    "ORDER BY check_id",
                    (pattern_ref,),
                ).fetchall()
        else:
            with _sqlite_connect_qa(self._store_dir) as conn:
                rows = conn.execute(
                    "SELECT * FROM fc_check_proposals WHERE pattern_ref = ? "
                    "ORDER BY check_id",
                    (pattern_ref,),
                ).fetchall()
        return [_row_to_proposal(dict(r)) for r in rows]


_COLUMNS = (
    "check_id, project_key, status, pattern_ref, invariant, check_type, "
    "pipeline_stage, pipeline_layer, owner, false_positive_risk, "
    "positive_fixtures, negative_fixtures, created_at, approved_at, approved_by, "
    "rejected_reason, effectiveness_last_checked_at, true_positives_90d, "
    "false_positives_90d"
)

_UPDATE_SET = (
    "project_key=excluded.project_key, status=excluded.status, "
    "pattern_ref=excluded.pattern_ref, invariant=excluded.invariant, "
    "check_type=excluded.check_type, pipeline_stage=excluded.pipeline_stage, "
    "pipeline_layer=excluded.pipeline_layer, owner=excluded.owner, "
    "false_positive_risk=excluded.false_positive_risk, "
    "positive_fixtures=excluded.positive_fixtures, "
    "negative_fixtures=excluded.negative_fixtures, "
    "created_at=excluded.created_at, approved_at=excluded.approved_at, "
    "approved_by=excluded.approved_by, rejected_reason=excluded.rejected_reason, "
    "effectiveness_last_checked_at=excluded.effectiveness_last_checked_at, "
    "true_positives_90d=excluded.true_positives_90d, "
    "false_positives_90d=excluded.false_positives_90d"
)

_SQLITE_UPSERT = f"""
    INSERT INTO fc_check_proposals ({_COLUMNS})
    VALUES (
        :check_id, :project_key, :status, :pattern_ref, :invariant, :check_type,
        :pipeline_stage, :pipeline_layer, :owner, :false_positive_risk,
        :positive_fixtures, :negative_fixtures, :created_at, :approved_at,
        :approved_by, :rejected_reason, :effectiveness_last_checked_at,
        :true_positives_90d, :false_positives_90d
    )
    ON CONFLICT (check_id) DO UPDATE SET {_UPDATE_SET}
"""

_PG_UPSERT = f"""
    INSERT INTO fc_check_proposals ({_COLUMNS})
    VALUES (
        %(check_id)s, %(project_key)s, %(status)s, %(pattern_ref)s,
        %(invariant)s, %(check_type)s, %(pipeline_stage)s, %(pipeline_layer)s,
        %(owner)s, %(false_positive_risk)s, %(positive_fixtures)s,
        %(negative_fixtures)s, %(created_at)s, %(approved_at)s, %(approved_by)s,
        %(rejected_reason)s, %(effectiveness_last_checked_at)s,
        %(true_positives_90d)s, %(false_positives_90d)s
    )
    ON CONFLICT (check_id) DO UPDATE SET {_UPDATE_SET}
"""


__all__ = [
    "FcCheckProposalRepository",
    "StateBackendFcCheckProposalRepository",
]
