"""Contract: ChangeFrame carries the FK-23 §23.4.1 seven mandatory parts.

Pinned against the model itself (SSOT), not a duplicated literal copy: the
seven content parts MUST be required fields, ``created_at`` MUST be required
(§23.4.2), and the lifecycle fields MUST default to not-frozen (FK-25 §25.4.2 --
the frame is editable until gate-PASS, frozen only afterwards). The seven part
names are pinned against the model's ``SEVEN_PARTS`` SSOT.
"""

from __future__ import annotations

from agentkit.exploration.change_frame import SEVEN_PARTS, ChangeFrame


def test_seven_mandatory_parts_are_required_fields() -> None:
    fields = ChangeFrame.model_fields
    assert len(SEVEN_PARTS) == 7
    for name in SEVEN_PARTS:
        assert name in fields, f"missing mandatory part: {name}"
        assert fields[name].is_required(), f"{name} must be a required field"


def test_seven_parts_match_fk23_english_wire_keys() -> None:
    # FK-23 §23.4.1 English wire keys (ARCH-55). Pinned so a rename drifting
    # away from the concept's keys is caught.
    assert SEVEN_PARTS == (
        "goal_and_scope",
        "affected_building_blocks",
        "solution_direction",
        "contract_changes",
        "conformance_statement",
        "verification_sketch",
        "open_points",
    )


def test_identity_fields_are_required() -> None:
    fields = ChangeFrame.model_fields
    for name in ("story_id", "run_id", "created_at"):
        assert fields[name].is_required(), f"{name} must be required (§23.4.2)"


def test_lifecycle_fields_default_unfrozen() -> None:
    fields = ChangeFrame.model_fields
    assert fields["frozen"].default is False
    assert fields["frozen_at"].default is None


def test_no_gate_status_field_on_the_artifact() -> None:
    # FK-23 §23.5.0: gate_status lives on ExplorationPayload, not the artifact.
    assert "gate_status" not in ChangeFrame.model_fields
    assert "change_frame_ref" not in ChangeFrame.model_fields
