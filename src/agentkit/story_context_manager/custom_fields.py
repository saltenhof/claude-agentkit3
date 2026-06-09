"""Story custom field definition and value records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class StoryCustomFieldType(StrEnum):
    """Supported story custom field data types."""

    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"
    JSON = "json"


class StoryCustomFieldValueStatus(StrEnum):
    """Custom field value lifecycle status."""

    PRESENT = "present"
    MISSING = "missing"
    INVALID = "invalid"
    CONFLICT = "conflict"


class StoryCustomFieldSource(StrEnum):
    """Producer/source of a custom field value."""

    PROVIDER = "provider"
    AGENTKIT = "agentkit"
    HUMAN = "human"


class ProviderSyncStatus(StrEnum):
    """Provider synchronization status for a custom field value."""

    IN_SYNC = "in_sync"
    PENDING = "pending"
    FAILED = "failed"
    NOT_WRITABLE = "not_writable"


@dataclass(frozen=True)
class StoryCustomFieldDefinition:
    """Story custom field definition owned by story_context_manager."""

    project_key: str
    field_key: str
    display_name: str
    field_type: StoryCustomFieldType
    provider: str
    provider_field_ref: str
    is_required: bool
    is_writable_by_agentkit: bool
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoryCustomFieldValue:
    """Story custom field value owned by story_context_manager."""

    project_key: str
    story_id: str
    field_key: str
    value: str
    value_status: StoryCustomFieldValueStatus
    source: StoryCustomFieldSource
    last_synced_at: datetime | None
    last_written_by: str | None
    provider_sync_status: ProviderSyncStatus
    conflict_detected: bool
    last_sync_attempt_at: datetime | None


__all__ = [
    "ProviderSyncStatus",
    "StoryCustomFieldDefinition",
    "StoryCustomFieldSource",
    "StoryCustomFieldType",
    "StoryCustomFieldValue",
    "StoryCustomFieldValueStatus",
]
