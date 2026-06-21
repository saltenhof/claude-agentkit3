"""Typed exceptions for the kpi_analytics bounded context."""

from __future__ import annotations


class AnalyticsNotConfiguredError(Exception):
    """Raised when a KpiAnalytics operation requires FactStore but none is configured.

    This exception signals that the analytics infrastructure (FactStore,
    RefreshWorker) is not yet available. Consumers must treat this as a
    hard configuration failure, not a data-not-found condition.
    """


class SchemaVersionError(Exception):
    """Raised fail-closed when ``sync_state.schema_version`` is missing or mismatched.

    FK-62 §62.4.3 / story AC10: the RefreshWorker reads the per-project
    ``schema_version`` cursor and compares it against ``EXPECTED_SCHEMA_VERSION``.
    A missing seed (seed owner AG3-038, story §2.2) or a divergent version is a
    hard precondition failure — the worker refuses to aggregate rather than
    computing against an unknown schema or seeding the version itself (no
    worker-side migration side effect).
    """

    def __init__(self, *, expected: int, found: int | None) -> None:
        self.expected = expected
        self.found = found
        detail = "missing seed" if found is None else f"found {found}"
        super().__init__(
            "sync_state.schema_version fail-closed: "
            f"expected {expected}, {detail} "
            "(seed owner is the schema/migration owner AG3-038, not the worker)"
        )
