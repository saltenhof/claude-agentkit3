"""AgentKit --- Deterministic orchestration engine for AI-driven story execution."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, distribution


def _enforce_installed_runtime_isolation() -> None:
    """Reject an installed AgentKit distribution outside a virtual environment.

    A source tree must remain importable by the in-tree PEP-517 backend before
    installation metadata exists. Once the distribution is installed, this
    package boundary covers wheels and source installs alike.
    """
    if sys.prefix != sys.base_prefix:
        return
    try:
        distribution("agentkit")
    except PackageNotFoundError:
        return
    from agentkit.backend.installer.interpreter import resolve_ak3_interpreter

    resolve_ak3_interpreter()


_enforce_installed_runtime_isolation()

__version__ = "0.1.0"
