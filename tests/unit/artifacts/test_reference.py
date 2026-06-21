"""Unit-Tests fuer ArtifactReference (AG3-022 §2.1.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.backend.artifacts.reference import ArtifactReference
from agentkit.backend.core_types import ArtifactClass


class TestArtifactReference:
    """AK5: ArtifactReference ist frozen, alle Felder Pflicht."""

    def _make_reference(
        self,
        *,
        artifact_class: ArtifactClass = ArtifactClass.QA,
        story_id: str = "AG3-042",
        run_id: str = "run-001",
        record_key: str = "qa/layer1/result.json",
    ) -> ArtifactReference:
        return ArtifactReference(
            artifact_class=artifact_class,
            story_id=story_id,
            run_id=run_id,
            record_key=record_key,
        )

    def test_all_fields_present(self) -> None:
        ref = self._make_reference()
        assert ref.artifact_class == ArtifactClass.QA
        assert ref.story_id == "AG3-042"
        assert ref.run_id == "run-001"
        assert ref.record_key == "qa/layer1/result.json"

    def test_all_artifact_classes_accepted(self) -> None:
        for ac in ArtifactClass:
            ref = self._make_reference(artifact_class=ac)
            assert ref.artifact_class == ac

    def test_frozen(self) -> None:
        ref = self._make_reference()
        with pytest.raises(ValidationError):
            ref.story_id = "OTHER-1"  # type: ignore[misc]

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ArtifactReference.model_validate(
                {
                    "artifact_class": ArtifactClass.QA,
                    "story_id": "AG3-001",
                    "run_id": "r1",
                    "record_key": "k",
                    "extra_field": "x",
                }
            )

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArtifactReference.model_validate(
                {
                    "artifact_class": ArtifactClass.QA,
                    "story_id": "AG3-001",
                    "run_id": "r1",
                    # record_key missing
                }
            )
