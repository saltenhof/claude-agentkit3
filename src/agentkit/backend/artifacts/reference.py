"""ArtifactReference — typed reference to an artifact.

Source: FK-71 glossary (entry `ArtifactReference`),
bc-cut-decisions.md §BC 8.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agentkit.backend.core_types import ArtifactClass


class ArtifactReference(BaseModel):
    """Unique reference to a stored artifact.

    All fields are mandatory and identify the artifact canonically.
    The instance is immutable (`frozen=True`).

    Attributes:
        artifact_class: Producer class of the referenced artifact.
        story_id: Story display ID (e.g. ``AG3-042``).
        run_id: Run correlation ID.
        record_key: Canonical path or record identifier in storage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_class: ArtifactClass
    story_id: str
    run_id: str
    record_key: str
