"""Installer integration checkpoints (FK-50 section 50.3).

Hosts the SonarQube CP 10d precondition checks (FK-50 CP 10d,
applicability-conditional) and the branch-plugin conformance self-test. The
CP10d config-drift-against-CP7 handling is out of scope (AG3-052 section 2.2;
owner Installer/AG3-039).

This package deliberately re-exports NOTHING. Every module below it is
classified ``core`` by
``concept/formal-spec/architecture-conformance/entities.md``, while the package
itself resolves to ``edge`` under longest-match-wins. A re-export surface here
therefore turned every consumer of a checkpoint into an edge module importing
core behaviour -- five distribution boundary crossings that existed only because
the facade existed, and that no caller needed: the sole importers were three
test modules (measured AG3-242, 2026-08-08). Importers name the checkpoint
module they use.
"""

from __future__ import annotations
