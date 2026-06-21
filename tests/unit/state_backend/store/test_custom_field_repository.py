"""Story custom field repository tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store.custom_field_repository import (
    StoryCustomFieldRepository,
    StoryCustomFieldWriteRejectedError,
)
from agentkit.backend.story_context_manager.custom_fields import (
    ProviderSyncStatus,
    StoryCustomFieldDefinition,
    StoryCustomFieldSource,
    StoryCustomFieldType,
    StoryCustomFieldValue,
    StoryCustomFieldValueStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


def _definition(*, writable: bool = True) -> StoryCustomFieldDefinition:
    return StoryCustomFieldDefinition(
        project_key="proj",
        field_key="risk",
        display_name="Risk",
        field_type=StoryCustomFieldType.ENUM,
        provider="github",
        provider_field_ref="PVTF_x",
        is_required=True,
        is_writable_by_agentkit=writable,
        allowed_values=("low", "high"),
    )


def _value(
    *,
    conflict: bool = False,
    owner: str | None = "agentkit",
) -> StoryCustomFieldValue:
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    return StoryCustomFieldValue(
        project_key="proj",
        story_id="AG3-087",
        field_key="risk",
        value="high",
        value_status=StoryCustomFieldValueStatus.PRESENT,
        source=StoryCustomFieldSource.AGENTKIT,
        last_synced_at=now,
        last_written_by=owner,
        provider_sync_status=ProviderSyncStatus.PENDING,
        conflict_detected=conflict,
        last_sync_attempt_at=now,
    )


def test_custom_field_definition_and_value_roundtrip(tmp_path: Path) -> None:
    repo = StoryCustomFieldRepository(tmp_path)
    definition = _definition()
    value = _value()

    repo.save_definition(definition)
    repo.save_value(value)

    assert repo.get_definition("proj", "risk") == definition
    assert repo.get_value("proj", "AG3-087", "risk") == value


def test_agentkit_single_writer_bar_blocks_non_writable(tmp_path: Path) -> None:
    repo = StoryCustomFieldRepository(tmp_path)
    repo.save_definition(_definition(writable=False))

    with pytest.raises(StoryCustomFieldWriteRejectedError):
        repo.write_agentkit_value(_value())


def test_agentkit_single_writer_bar_blocks_conflict(tmp_path: Path) -> None:
    repo = StoryCustomFieldRepository(tmp_path)
    repo.save_definition(_definition())
    repo.save_value(_value(conflict=True))

    with pytest.raises(StoryCustomFieldWriteRejectedError):
        repo.write_agentkit_value(_value())


def test_agentkit_single_writer_bar_blocks_foreign_owner(tmp_path: Path) -> None:
    repo = StoryCustomFieldRepository(tmp_path)
    repo.save_definition(_definition())
    repo.save_value(_value(owner="github"))

    with pytest.raises(StoryCustomFieldWriteRejectedError):
        repo.write_agentkit_value(_value())
