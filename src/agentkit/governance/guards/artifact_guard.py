"""Artifact guard -- prevents sub-agents from tampering with QA directories."""

from __future__ import annotations

import os

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
        if context.get("qa_artifact_lock_active") is not True:
            return GuardVerdict.allow(self.name)
        if context.get("is_subagent") is not True:
            return GuardVerdict.allow(self.name)

        file_path = str(context.get("file_path", ""))
        story_id = str(context.get("active_story_id", ""))
        if story_id and self._is_protected_qa_path(file_path, story_id):
            return GuardVerdict.block(
                self.name,
                ViolationType.ARTIFACT_TAMPERING,
                "Sub-agent write to protected QA directory is forbidden",
                detail={"file_path": file_path, "story_id": story_id},
            )

        return GuardVerdict.allow(self.name)

    def _is_protected_qa_path(self, file_path: str, story_id: str) -> bool:
        normalized = os.path.normpath(file_path).replace("\\", "/")
        protected_prefix = f"_temp/qa/{story_id}/"
        return protected_prefix in f"{normalized}/"
