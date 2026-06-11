"""Installer BootstrapCheckpoints (FK-50 §50.3).

The concrete first-registration checkpoint handlers (CP 1..CP 12 incl. reserved
CP 3/CP 4 and sub-checkpoints CP 10a/10b/10c/10d) plus the orchestrator that
wires them into the :class:`CheckpointEngine`. This layer sits ABOVE
``checkpoint_engine`` (architecture-conformance intra-BC layer order) and may
call other BCs' top surfaces (agent-skills, governance, prompt-runtime, ...).
"""

from __future__ import annotations

from agentkit.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
    build_checkpoint_engine,
    run_checkpoint_install,
)
from agentkit.installer.bootstrap_checkpoints.registry import (
    build_branch_predicate_registry,
    build_handler_registry,
)

__all__ = [
    "build_branch_predicate_registry",
    "build_checkpoint_context",
    "build_checkpoint_engine",
    "build_handler_registry",
    "run_checkpoint_install",
]
