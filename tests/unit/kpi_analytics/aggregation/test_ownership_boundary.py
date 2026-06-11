"""Ownership-boundary conformance for the RefreshWorker (FK-62 §62.6.1/§62.6.2, AC6).

The aggregation worker reads ONLY through the injected ``AnalyticsSourcePort``
(backed by ``ProjectionAccessor`` / ``Telemetry.read_projection`` at the
composition root) and writes ONLY through the ``FactStore``. So — analogous to the
AC8 boundary already pinned on ``fact_store/repository.py`` — the aggregation
modules must hold NO direct runtime DB connection and NO import of the
``state_backend.store`` write facade, ANYWHERE in the module (not just at module
level): all backend wiring goes through DI at the composition root.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_AGGREGATION_MODULES = (
    "agentkit.kpi_analytics.aggregation.worker",
    "agentkit.kpi_analytics.aggregation.dirty_sets",
    "agentkit.kpi_analytics.aggregation.source_port",
    "agentkit.kpi_analytics.aggregation.percentile",
    "agentkit.kpi_analytics.aggregation.models",
)

#: Forbidden import prefixes (FK-62 §62.6.1/§62.6.2): the runtime-schema drivers
#: and the state-backend write facade. The worker never holds its own DB handle.
_FORBIDDEN_PREFIXES = (
    "agentkit.state_backend.store",
    "agentkit.state_backend.sqlite_store",
    "agentkit.state_backend.postgres_store",
)


def _source_path(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Module {module_name!r} not found"
    assert spec.origin is not None, f"Module {module_name!r} has no origin"
    return Path(spec.origin)


def _imported_modules(source: str) -> list[str]:
    """Return every ``from X import ...`` / ``import X`` target, at ANY depth."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def test_aggregation_modules_do_not_import_runtime_or_store_facade() -> None:
    offenders: dict[str, list[str]] = {}
    for module_name in _AGGREGATION_MODULES:
        source = _source_path(module_name).read_text(encoding="utf-8")
        bad = [
            imported
            for imported in _imported_modules(source)
            if imported.startswith(_FORBIDDEN_PREFIXES)
        ]
        if bad:
            offenders[module_name] = bad
    assert not offenders, (
        "RefreshWorker ownership boundary violated (FK-62 §62.6.1/§62.6.2): "
        f"{offenders}"
    )


def test_worker_imports_only_factstore_protocol_for_writes() -> None:
    """The worker depends on the consumer-owned FactStore/Protocol, not a driver."""
    source = _source_path("agentkit.kpi_analytics.aggregation.worker").read_text(
        encoding="utf-8"
    )
    imports = _imported_modules(source)
    assert "agentkit.kpi_analytics.fact_store.store" in imports
    # And specifically NOT the concrete adapter module.
    assert "agentkit.state_backend.store.fact_repository" not in imports
