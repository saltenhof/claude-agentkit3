"""Artifact guard -- prevents workers from tampering with QA artifacts.

QA artifacts (structural.json, semantic-review.json, decision.json, etc.)
must only be written by the QA system, not by workers.  This guard
blocks ``file_write`` and ``file_edit`` operations targeting those files.
"""

from __future__ import annotations

import os

from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.state_backend import PROTECTED_QA_ARTIFACTS


class ArtifactGuard:
    """Blocks worker writes to QA result files during execution.

    QA artifacts are produced exclusively by the QA layers.  If a
    worker attempts to create or modify one of these files, the
    operation is blocked.
    """

    PROTECTED_ARTIFACTS: tuple[str, ...] = PROTECTED_QA_ARTIFACTS
    """Filenames that must only be written by the QA system."""

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "artifact_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block writes to protected QA artifacts.

        Only inspects ``file_write`` and ``file_edit`` operations; all
        others are allowed unconditionally.

        Args:
            operation: The operation type being attempted.
            context: Must contain ``"file_path"`` for write/edit ops.

        Returns:
            ``ALLOW`` for non-protected files, ``BLOCK`` for QA artifacts.
        """
        if operation not in ("file_write", "file_edit"):
            return GuardVerdict.ALLOW(self.name)

        file_path = str(context.get("file_path", ""))
        basename = os.path.basename(file_path)

        if basename in self.PROTECTED_ARTIFACTS:
            return GuardVerdict.BLOCK(
                self.name,
                ViolationType.ARTIFACT_TAMPERING,
                f"Write to protected QA artifact {basename!r} is forbidden",
                detail={"file_path": file_path, "artifact": basename},
            )

        return GuardVerdict.ALLOW(self.name)
