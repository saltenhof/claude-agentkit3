"""Contract: AG3-055 exploration-worker drafting cannot drift.

Pins the two load-bearing contracts of the worker-driven drafting so a rename /
re-route is caught:

* the prompt SELECTION: an EXPLORATION ``execution_route`` MUST select the
  ``worker-exploration`` template (FK-23 §23.2.2 / FK-44), independent of the
  story type and the (initial) spawn reason -- the exploration worker reuses the
  WORKER spawn path with the exploration template (no parallel spawn path);
* the worker-output -> model CONTRACT: the recorded real worker payload MUST
  validate into a ``ChangeFrame`` carrying exactly the seven FK-23 §23.4.1 parts,
  and the drafting core MUST reject (not patch) a payload missing a part.
"""

from __future__ import annotations

import pytest
from tests.exploration_worker_result_fixture import (
    RECORDED_WORKER_CHANGE_FRAME_PAYLOAD,
    recorded_worker_payload,
)

from agentkit.backend.core_types import SpawnReason
from agentkit.backend.exploration.change_frame import SEVEN_PARTS, ChangeFrame
from agentkit.backend.prompt_runtime.selectors import select_template_name
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

_STORY_ID = "PROJ-128"
_RUN_ID = "77777777-7777-4777-8777-777777777777"


@pytest.mark.parametrize(
    "story_type",
    [StoryType.IMPLEMENTATION, StoryType.BUGFIX, StoryType.RESEARCH],
)
def test_exploration_route_selects_worker_exploration(
    story_type: StoryType,
) -> None:
    name = select_template_name(
        story_type,
        StoryMode.EXPLORATION,
        spawn_reason=SpawnReason.INITIAL,
    )
    assert name == "worker-exploration"


def test_recorded_worker_payload_validates_to_seven_part_change_frame() -> None:
    frame = ChangeFrame.from_payload(
        recorded_worker_payload(story_id=_STORY_ID, run_id=_RUN_ID)
    )
    dumped = frame.model_dump(mode="json")
    assert len(SEVEN_PARTS) == 7
    for part in SEVEN_PARTS:
        assert part in dumped, f"missing FK-23 part: {part}"


def test_recorded_payload_keys_cover_the_seven_parts() -> None:
    # The recorded fixture itself carries the seven FK-23 §23.4.1 wire keys, so a
    # drift in the worker contract surfaces here, not only at model validation.
    for part in SEVEN_PARTS:
        assert part in RECORDED_WORKER_CHANGE_FRAME_PAYLOAD


def test_missing_part_is_rejected_not_patched() -> None:
    bad = recorded_worker_payload(story_id=_STORY_ID, run_id=_RUN_ID)
    del bad["open_points"]
    with pytest.raises(ValueError):  # noqa: PT011  # pydantic ValidationError
        ChangeFrame.from_payload(bad)
