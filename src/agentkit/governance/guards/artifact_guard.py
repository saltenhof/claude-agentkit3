"""Artifact guard -- prevents sub-agents from tampering with QA directories.

Konsument der ``PROTECTED_QA_ARTIFACTS``-Liste aus
``agentkit.governance.guard_system.protected_paths`` (AG3-023 §AK10,
Story-Zeile 285): jeder geblockte Write wird zusaetzlich gegen die
kanonische Liste geprueft, damit der Guard nicht eine eigene Schatten-
Aufzaehlung der geschuetzten Filenamen pflegt.
"""

from __future__ import annotations

import os

from agentkit.governance.guard_system.protected_paths import PROTECTED_QA_ARTIFACTS
from agentkit.governance.protocols import GuardVerdict, ViolationType


class ArtifactGuard:
    """Blocks sub-agent writes into active story QA directories."""

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "artifact_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block sub-agent writes to the active story QA directory."""
        if operation not in ("file_write", "file_edit"):
            return GuardVerdict.allow(self.name)

        if str(context.get("operating_mode", "")) != "story_execution":
            return GuardVerdict.allow(self.name)
        if context.get("principal_kind") != "subagent":
            return GuardVerdict.allow(self.name)

        file_path = str(context.get("file_path", ""))
        story_id = str(context.get("active_story_id", ""))
        if story_id and self._is_protected_qa_path(file_path, story_id):
            if context.get("qa_artifact_lock_active") is True:
                return GuardVerdict.block(
                    self.name,
                    ViolationType.ARTIFACT_TAMPERING,
                    "Sub-agent write to protected QA artifact is forbidden",
                    detail={
                        "file_path": file_path,
                        "story_id": story_id,
                        "protected_filename": os.path.basename(file_path),
                    },
                )
            if context.get("qa_artifact_lock_known") is not True:
                return GuardVerdict.block(
                    self.name,
                    ViolationType.ARTIFACT_TAMPERING,
                    "Sub-agent write blocked because the QA artifact lock is missing",
                    detail={
                        "file_path": file_path,
                        "story_id": story_id,
                        "protected_filename": os.path.basename(file_path),
                    },
                )
            return GuardVerdict.allow(self.name)

        return GuardVerdict.allow(self.name)

    @staticmethod
    def _is_protected_qa_path(file_path: str, story_id: str) -> bool:
        """Protected = active-story QA-dir UND canonical QA-artifact filename.

        Konsumiert ``PROTECTED_QA_ARTIFACTS`` aus
        ``governance.guard_system.protected_paths`` (AG3-023 §AK10) als
        Single-Source-of-Truth fuer die geschuetzten Filenamen.
        """
        normalized = os.path.normpath(file_path).replace("\\", "/")
        protected_prefix = f"_temp/qa/{story_id}/"
        if protected_prefix not in f"{normalized}/":
            return False
        return os.path.basename(file_path) in PROTECTED_QA_ARTIFACTS
