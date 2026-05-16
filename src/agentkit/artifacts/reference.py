"""ArtifactReference — getypte Referenz auf ein Artefakt.

Quelle: FK-71 Glossar (Eintrag `ArtifactReference`),
bc-cut-decisions.md §BC 8.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agentkit.core_types import ArtifactClass


class ArtifactReference(BaseModel):
    """Eindeutige Referenz auf ein gespeichertes Artefakt.

    Alle Felder sind Pflicht und identifizieren das Artefakt kanonisch.
    Die Instanz ist immutabel (`frozen=True`).

    Attributes:
        artifact_class: Erzeugerklasse des referenzierten Artefakts.
        story_id: Story-Display-ID (z.B. ``AG3-042``).
        run_id: Run-Korrelations-ID.
        record_key: Kanonischer Pfad oder Record-Identifier im Storage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_class: ArtifactClass
    story_id: str
    run_id: str
    record_key: str
