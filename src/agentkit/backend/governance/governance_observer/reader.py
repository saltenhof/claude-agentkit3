"""Production ExecutionEventReader backed by the state-backend store (FK-35 §35.3.5).

The :class:`StateBackendGovernanceEventReader` is the SOLE production implementation
of the :class:`~agentkit.backend.governance.governance_observer.score.ExecutionEventReader`
protocol.  It delegates to the state-backend facade for both
``governance_signal`` reads (rolling window) and ``governance_adjudication`` reads
(cooldown timestamp look-up).

Design decisions
----------------
* **No bridge to risk_window / RiskCategory** — the score source is exclusively
  ``execution_events / governance_signal / payload.risk_points`` (FK-35 §35.3.1a
  / §35.3.5).  Any FK-35↔FK-68 §68.8 overlap is a doc-only concern (AG3-103).
* **``read_last_adjudication_ts`` via DB-side MAX** — uses the dedicated
  ``load_last_adjudication_ts`` facade function which issues a single DB-side
  ``MAX(occurred_at)`` with exact JSON field matching (FK-35 §35.3.11).  This
  correctly handles any number of adjudications regardless of other-signal volume,
  unlike the previous bounded-scan (200-limit) + Python-max approach that could
  miss a same-signal adjudication when 200+ other-signal adjudications were newer.
* **Public run-scoped facade reader** — this reader calls the public
  ``agentkit.backend.state_backend.store.facade.load_execution_events`` (signal reads) and
  ``agentkit.backend.state_backend.store.facade.load_last_adjudication_ts`` (cooldown reads).
  Both are the same import surface the closure BC uses, so it is NOT
  import-restricted and GAC-1 stays green.  The private ``_backend_module``
  bypass is not used and must not be reintroduced.
* **``story_dir`` for SQLite** — ``story_dir`` is forwarded to both facade calls
  as the first positional argument so isolated test databases work correctly with
  the SQLite backend.
* **Fail-closed on SQLite + ``story_dir=None``** — if the active backend is SQLite
  and ``story_dir`` is ``None``, construction raises immediately (cannot default
  to ``cwd()`` — that would silently read the wrong database).  For Postgres
  ``story_dir`` is genuinely unused (the connection is derived from the env) and
  ``None`` is accepted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

#: Wire value for governance_signal (FK-91 Kap.35).
_GOVERNANCE_SIGNAL_WIRE: str = "governance_signal"


class StateBackendGovernanceEventReader:
    """Production :class:`ExecutionEventReader` over the canonical state backend.

    Implements both protocol methods required by the scoring and cooldown logic:

    * :meth:`read_governance_signals` — returns the ``window_size`` most-recent
      ``governance_signal`` payloads (FK-35 §35.3.5 rolling-window query).
    * :meth:`read_last_adjudication_ts` — returns the UNIX timestamp of the last
      ``governance_adjudication`` event for a given signal type (FK-35 §35.3.11
      cooldown) via a DB-side MAX query with exact JSON matching.

    Construction contract (FAIL-CLOSED)
    ------------------------------------
    When the active backend is SQLite, ``story_dir`` MUST be provided — passing
    ``None`` raises :class:`ValueError` at construction time.  For Postgres
    ``story_dir`` is unused (the connection is derived from the environment) and
    ``None`` is accepted.

    Args:
        story_dir: Story directory for the SQLite database.  Must not be ``None``
            when the active backend is SQLite.  Pass ``None`` for Postgres
            (production) where the backend derives the connection from the env.

    Raises:
        ValueError: When ``story_dir is None`` and the active backend is SQLite
            (FAIL-CLOSED — cannot default to ``cwd()`` for SQLite).
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        _assert_story_dir_valid_for_backend(story_dir)
        self._story_dir = story_dir

    def read_governance_signals(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return the ``limit`` most-recent ``governance_signal`` event payloads.

        Issues the FK-35 §35.3.5 rolling-window query via the state-backend facade
        (``ORDER BY occurred_at DESC LIMIT limit``).  Each returned dict contains at
        minimum ``risk_points`` (int), ``signal_type`` (str), and ``occurred_at``
        (float UNIX timestamp) so that ``_time_span_s`` works correctly.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            limit: Maximum events to return (rolling-window width).

        Returns:
            List of payload dicts ordered by ``occurred_at`` DESC.
        """
        records = self._load_signal_records(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            limit=limit,
        )
        return [_record_to_signal_payload(record) for record in records]

    def read_last_adjudication_ts(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        signal_type: str,
    ) -> float | None:
        """Return the UNIX timestamp of the last ``governance_adjudication`` event.

        Scoped to the EXACT ``(project_key, story_id, run_id, signal_type)`` tuple
        per FK-35 §35.3.11.  Issues a DB-side MAX(occurred_at) with exact JSON
        field matching via :func:`~agentkit.backend.state_backend.store.facade.load_last_adjudication_ts`
        — no bounded Python scan, no risk of missing an adjudication due to a
        200-row cap being exceeded.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            signal_type: Signal type wire value to filter on (exact match).

        Returns:
            UNIX timestamp of the last matching adjudication, or ``None``.
        """
        from agentkit.backend.state_backend.store.facade import load_last_adjudication_ts

        story_dir = self._resolved_story_dir()
        return load_last_adjudication_ts(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            payload_signal_type=signal_type,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolved_story_dir(self) -> Path:
        """Return the effective story_dir (never None — validated at construction).

        For Postgres ``self._story_dir`` may be ``None`` (the backend ignores it);
        we pass ``Path(".")`` as a dummy so the facade signature is satisfied —
        the Postgres driver discards the argument (see ``postgres_store._connect``
        which does ``del story_dir``).

        Returns:
            The story_dir Path, or a dummy cwd sentinel for Postgres.
        """
        if self._story_dir is not None:
            return self._story_dir
        # Postgres path — story_dir is unused; pass a harmless dummy
        from pathlib import Path

        return Path(".")

    def _load_signal_records(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        limit: int,
    ) -> list[ExecutionEventRecord]:
        """Load governance_signal records via the public state-backend facade.

        Uses ``load_execution_events`` — the same public surface the closure BC
        imports — with ``project_key``/``story_id``/``run_id``/``event_type``
        filters and a DB-side ``ORDER BY occurred_at DESC LIMIT limit``.
        Both SQLite and Postgres backends apply identical ordering semantics;
        no backend-private imports are used here.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            limit: Maximum rows (passed to the DB as LIMIT).

        Returns:
            List of :class:`~agentkit.backend.telemetry.contract.records.ExecutionEventRecord`.
        """
        from agentkit.backend.state_backend.store.facade import load_execution_events

        return load_execution_events(
            self._resolved_story_dir(),
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            event_type=_GOVERNANCE_SIGNAL_WIRE,
            limit=limit,
        )


def _assert_story_dir_valid_for_backend(story_dir: Path | None) -> None:
    """Fail-closed guard: raise when SQLite backend is active and story_dir is None.

    FIX C (AG3-085 round 3): ``story_dir=None`` is benign for Postgres (the
    connection is derived from the environment) but silently reads the wrong
    SQLite database when ``Path.cwd()`` is used as the fallback — a latent
    wrong-database read.  This guard enforces FAIL-CLOSED construction so the
    ambiguous implicit path cannot occur.

    Uses :func:`~agentkit.backend.state_backend.store.facade.active_backend_is_sqlite`
    (the sanctioned facade surface) rather than importing
    ``agentkit.backend.state_backend.config`` directly — preserving AC010/AC011 (GAC-1).

    Args:
        story_dir: The story directory passed to the reader constructor.

    Raises:
        ValueError: When ``story_dir is None`` and the active backend is SQLite.
    """
    if story_dir is not None:
        return
    from agentkit.backend.state_backend.store.facade import active_backend_is_sqlite

    if active_backend_is_sqlite():
        raise ValueError(
            "StateBackendGovernanceEventReader: story_dir must not be None when "
            "the active backend is SQLite.  Defaulting to cwd() would silently "
            "read the wrong database (FAIL-CLOSED — AG3-085 FIX C)."
        )


def _record_to_signal_payload(record: ExecutionEventRecord) -> dict[str, object]:
    """Build the signal-payload dict expected by the observer.

    Merges the stored payload fields with ``occurred_at`` as a UNIX
    float so that ``_time_span_s`` in ``observer.py`` works correctly.

    Args:
        record: An ``ExecutionEventRecord`` for a ``governance_signal`` event.

    Returns:
        Dict with ``risk_points``, ``signal_type``, ``occurred_at`` and any
        other fields carried in the stored payload.
    """
    merged: dict[str, object] = dict(record.payload)
    merged["occurred_at"] = record.occurred_at.timestamp()
    return merged
