"""Contract test: Execution-Input wire shape vs. formal entities (AG3-100, FK-72 §72.14.3).

Pins the snapshot/next/reason wire payloads against the formal frontend-contracts
entities. The snapshot binds to the pre-existing
``frontend-contracts.entity.execution_input_snapshot``; the ``next`` answer binds to
the AG3-100-introduced ``frontend-contracts.entity.execution_input_next`` /
``execution_input_next_reason`` / ``execution_input_repo_slot``. Drift in either
direction (missing or extra attribute) fails this test, so the HTTP surface cannot
diverge from the SSOT contract. Wire field names are snake_case per the formal spec
(ARCH-55, no CamelCase prototype form).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from agentkit.execution_planning.scheduling import (
    ExecutionInputNext,
    ExecutionInputNextReason,
    ExecutionInputSnapshot,
    ExecutionInputStackCard,
    ExecutionInputStoryRef,
    RepoSlotInfo,
)

_ENTITIES = (
    Path(__file__).resolve().parents[3]
    / "concept"
    / "formal-spec"
    / "frontend-contracts"
    / "entities.md"
)
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(?P<body>.*?)\n```", re.DOTALL
)


def _entities_by_id() -> dict[str, dict[str, Any]]:
    text = _ENTITIES.read_text(encoding="utf-8")
    match = _FORMAL_BLOCK.search(text)
    assert match is not None, "no FORMAL-SPEC block in frontend-contracts/entities.md"
    spec = yaml.safe_load(match.group("body"))
    return {entity["id"]: entity for entity in spec["entities"]}


def _attr_names(entity: dict[str, Any]) -> set[str]:
    return {attr["name"] for attr in entity["attributes"]}


class TestSnapshotWireShape:
    def test_snapshot_entity_exists_with_snake_case_fields(self) -> None:
        """The snapshot entity carries exactly the four snake_case wire fields."""
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_snapshot"]
        assert _attr_names(entity) == {
            "project_key",
            "running",
            "eligible_ready",
            "total_ready",
            "global_slots_left",
        }

    def test_snapshot_model_matches_formal_attributes(self) -> None:
        """The ``ExecutionInputSnapshot`` model fields equal the formal attributes."""
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_snapshot"]
        assert set(ExecutionInputSnapshot.model_fields.keys()) == _attr_names(entity)


class TestStackCardWireShape:
    """Bind the stack card against ``frontend-contracts.entity.execution_input_stack``.

    The card MUST carry exactly the three formal refs ``story`` / ``predecessor`` /
    ``successor`` (nested story-summary-style refs), not the divergent flat prototype
    shape (``story_id`` / ``story_number`` / ``predecessor_story_id`` / ...). The
    formal entity is the authoritative wire contract.
    """

    def test_stack_entity_has_exactly_the_three_formal_refs(self) -> None:
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_stack"]
        assert _attr_names(entity) == {"story", "predecessor", "successor"}

    def test_stack_card_model_matches_formal_attributes(self) -> None:
        """``ExecutionInputStackCard`` fields equal the formal ``execution_input_stack``."""
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_stack"]
        assert set(ExecutionInputStackCard.model_fields.keys()) == _attr_names(entity)

    def test_stack_refs_target_story_summary(self) -> None:
        """The three refs all target ``story_summary`` per the formal spec."""
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_stack"]
        for attr in entity["attributes"]:
            assert attr["kind"] == "ref"
            assert attr["target"] == "frontend-contracts.entity.story_summary"
        # ``story`` is required, predecessor/successor optional (the formal entity).
        required = {attr["name"] for attr in entity["attributes"] if attr["required"]}
        assert required == {"story"}

    def test_story_ref_keys_on_the_story_summary_identity(self) -> None:
        """The nested ref is a story-summary-style ref keyed on the summary identity.

        ``story_summary`` keys on ``story_id`` (entities.md identity); the nested
        ref carries that identity plus the display/triage projections the
        deterministic selector owns (``title`` display, plus the backend triage
        fields ``story_number`` / ``repo`` -- the singular projection of the formal
        ``repos`` list, FK-72). No field that contradicts ``story_summary`` is
        invented: ``story_id`` and ``title`` are formal ``story_summary`` attributes.
        """
        summary = _entities_by_id()["frontend-contracts.entity.story_summary"]
        summary_attrs = _attr_names(summary)
        assert summary["identity"] == "story_id"
        ref_fields = set(ExecutionInputStoryRef.model_fields.keys())
        # Identity + formal display field are genuine story_summary attributes.
        assert {"story_id", "title"} <= ref_fields
        assert {"story_id", "title"} <= summary_attrs
        # ``story_number`` / ``repo`` are backend triage/display projections, never
        # invented formal contract keys: story_summary keys stories by ``story_id``,
        # not a numeric field, and exposes ``repos`` (list) not a singular ``repo``.
        assert "story_number" not in summary_attrs
        assert "repo" not in summary_attrs

    def test_stack_card_dump_is_nested_not_flat(self) -> None:
        """A serialized card nests ``story`` and omits the flat prototype keys."""
        card = ExecutionInputStackCard(
            story=ExecutionInputStoryRef(
                story_id="S1", story_number=1, title="one", repo="repo-a",
            ),
        )
        dumped = card.model_dump(mode="json")
        assert set(dumped.keys()) == {"story", "predecessor", "successor"}
        assert dumped["story"] == {
            "story_id": "S1",
            "story_number": 1,
            "title": "one",
            "repo": "repo-a",
        }
        assert dumped["predecessor"] is None
        assert dumped["successor"] is None
        # The divergent flat prototype keys must not leak onto the wire.
        for flat in ("story_id", "predecessor_story_id", "successor_story_id"):
            assert flat not in dumped


class TestNextWireShape:
    def test_next_entity_introduced_by_ag3_100(self) -> None:
        """AG3-100 introduces the formal ``execution_input_next`` reason family."""
        entities = _entities_by_id()
        assert "frontend-contracts.entity.execution_input_next" in entities
        assert "frontend-contracts.entity.execution_input_next_reason" in entities
        assert "frontend-contracts.entity.execution_input_repo_slot" in entities

    def test_next_model_matches_formal_attributes(self) -> None:
        entity = _entities_by_id()["frontend-contracts.entity.execution_input_next"]
        assert set(ExecutionInputNext.model_fields.keys()) == _attr_names(entity)

    def test_next_reason_model_matches_formal_attributes(self) -> None:
        entity = _entities_by_id()[
            "frontend-contracts.entity.execution_input_next_reason"
        ]
        assert set(ExecutionInputNextReason.model_fields.keys()) == _attr_names(entity)

    def test_repo_slot_model_matches_formal_attributes(self) -> None:
        entity = _entities_by_id()[
            "frontend-contracts.entity.execution_input_repo_slot"
        ]
        assert set(RepoSlotInfo.model_fields.keys()) == _attr_names(entity)


class TestWirePayloadSerialization:
    def test_snapshot_dump_is_snake_case(self) -> None:
        """A serialized snapshot uses exactly the snake_case wire keys."""
        snapshot = ExecutionInputSnapshot(
            project_key="tenant-a",
            running=(),
            eligible_ready=(
                ExecutionInputStackCard(
                    story=ExecutionInputStoryRef(
                        story_id="S1", story_number=1, title="one",
                    ),
                ),
            ),
            total_ready=1,
            global_slots_left=1,
        )
        dumped = snapshot.model_dump(mode="json")
        assert set(dumped.keys()) == {
            "project_key",
            "running",
            "eligible_ready",
            "total_ready",
            "global_slots_left",
        }
        # No CamelCase prototype form leaked onto the wire (ARCH-55).
        for camel in ("eligibleReady", "totalReady", "globalSlotsLeft"):
            assert camel not in dumped

    def test_next_reason_dump_is_snake_case(self) -> None:
        reason = ExecutionInputNextReason(
            repo_bucket="repo-a",
            on_critical_path=True,
            global_slots_left=2,
            repo_slots=(RepoSlotInfo(repo="repo-a", repo_slots_left=1),),
            active_tiebreaker="critical_path_desc_then_story_number_asc",
        )
        dumped = reason.model_dump(mode="json")
        assert set(dumped.keys()) == {
            "repo_bucket",
            "on_critical_path",
            "global_slots_left",
            "repo_slots",
            "active_tiebreaker",
        }
        assert dumped["repo_slots"][0] == {"repo": "repo-a", "repo_slots_left": 1}
