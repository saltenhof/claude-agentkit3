"""Artifact guard -- prevents sub-agents from tampering with QA directories.

Consumer of the ``PROTECTED_QA_ARTIFACTS`` list from
``agentkit.backend.governance.guard_system.protected_paths`` (AG3-023 §AK10, story line
285): every blocked write is additionally checked against the canonical list so
the guard does not maintain its own shadow enumeration of the protected
filenames.

The guard protects two co-located but functionally distinct artifact sets
under ``_temp/qa/{story_id}/`` (FK-23 §23.4.3 / FK-31 §31.3):

1. the QA-layer artifacts (``PROTECTED_QA_ARTIFACTS``) -- write-protected while
   the QA-artifact lock is ``ACTIVE`` (``qa_artifact_lock_active``);
2. the exploration change-frame artifact (``PROTECTED_CHANGE_FRAME``) --
   write-protected once the change-frame is **frozen**
   (``change_frame_frozen``). The freeze trigger (setting ``frozen=true`` and
   feeding the ``change_frame_frozen`` signal into the guard context) is owned
   by AG3-047; the **protection mechanics** live here (AG3-045 AC8): a frozen
   change-frame is truly write-protected, a still-editable one (before freeze,
   FK-25 §25.4.2) is not.
"""

from __future__ import annotations

import os

from agentkit.backend.governance.guard_system.protected_paths import (
    PROTECTED_CHANGE_FRAME,
    PROTECTED_QA_ARTIFACTS,
)
from agentkit.backend.governance.protocols import GuardVerdict, ViolationType


class ArtifactGuard:
    """Blocks sub-agent writes into active story QA directories."""

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "artifact_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block sub-agent writes to protected artifacts of the active story.

        Two co-located protected sets under ``_temp/qa/{story_id}/`` are
        enforced: the QA-layer artifacts (gated on the QA-artifact lock) and
        the exploration change-frame (gated on its freeze, FK-23 §23.4.3).
        """
        if operation not in ("file_write", "file_edit"):
            return GuardVerdict.allow(self.name)
        if str(context.get("operating_mode", "")) != "story_execution":
            return GuardVerdict.allow(self.name)
        if context.get("principal_kind") != "subagent":
            return GuardVerdict.allow(self.name)

        file_path = str(context.get("file_path", ""))
        story_id = str(context.get("active_story_id", ""))
        if not story_id or not self._is_active_story_qa_dir(file_path, story_id):
            return GuardVerdict.allow(self.name)

        filename = os.path.basename(file_path)
        if filename in PROTECTED_QA_ARTIFACTS:
            return self._evaluate_qa_artifact(file_path, story_id, context)
        if filename == PROTECTED_CHANGE_FRAME:
            return self._evaluate_change_frame_artifact(file_path, story_id, context)
        return GuardVerdict.allow(self.name)

    def _evaluate_qa_artifact(
        self, file_path: str, story_id: str, context: dict[str, object]
    ) -> GuardVerdict:
        """Block a QA-layer artifact write while the QA-artifact lock applies."""
        if context.get("qa_artifact_lock_active") is True:
            return self._block(
                file_path,
                story_id,
                "Sub-agent write to protected QA artifact is forbidden",
            )
        if context.get("qa_artifact_lock_known") is not True:
            return self._block(
                file_path,
                story_id,
                "Sub-agent write blocked because the QA artifact lock is missing",
            )
        return GuardVerdict.allow(self.name)

    def _evaluate_change_frame_artifact(
        self, file_path: str, story_id: str, context: dict[str, object]
    ) -> GuardVerdict:
        """Block an exploration change-frame write fail-closed on the freeze state.

        The freeze state is fed into the guard context by AG3-047's freeze
        trigger via two signals (mirroring the QA-artifact lock):

        * ``change_frame_frozen`` -- ``True`` when the change-frame is frozen;
        * ``change_frame_freeze_known`` -- ``True`` when the freeze state could
          be determined at all.

        A frozen change-frame is forbidden (AG3-045 AC8). An explicitly known
        not-frozen change-frame is still editable (FK-25 §25.4.2) and allowed.
        But an UNKNOWN / missing / unreadable freeze state is NOT treated as
        "not frozen" -- it is blocked fail-closed (FAIL-CLOSED, ARCH-48 default
        deny; AG3-045 deep-review #5): a sub-agent must never slip a write past
        the guard merely because the freeze signal was absent.
        """
        if context.get("change_frame_frozen") is True:
            return self._block(
                file_path,
                story_id,
                "Sub-agent write to a frozen exploration change-frame is forbidden",
            )
        if context.get("change_frame_freeze_known") is not True:
            return self._block(
                file_path,
                story_id,
                "Sub-agent write blocked because the exploration change-frame "
                "freeze state is unknown (fail-closed)",
            )
        return GuardVerdict.allow(self.name)

    def _block(self, file_path: str, story_id: str, message: str) -> GuardVerdict:
        """Build a uniform ARTIFACT_TAMPERING block verdict."""
        return GuardVerdict.block(
            self.name,
            ViolationType.ARTIFACT_TAMPERING,
            message,
            detail={
                "file_path": file_path,
                "story_id": story_id,
                "protected_filename": os.path.basename(file_path),
            },
        )

    @staticmethod
    def _is_active_story_qa_dir(file_path: str, story_id: str) -> bool:
        """Whether ``file_path`` lives in the active story's ``_temp/qa`` dir."""
        normalized = os.path.normpath(file_path).replace("\\", "/")
        protected_prefix = f"_temp/qa/{story_id}/"
        return protected_prefix in f"{normalized}/"
