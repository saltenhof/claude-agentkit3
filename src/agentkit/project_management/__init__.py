"""Public surface for the project_management bounded context."""

from __future__ import annotations

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
    ProjectNotFoundError,
    ProjectStoryIdPrefixConflictError,
)
from agentkit.project_management.lifecycle import (
    archive_project,
    create_project,
    update_configuration,
)
from agentkit.project_management.repository import ProjectRepository
from agentkit.project_management.service import (
    ProjectDetailService,
    compute_story_counters,
    derive_mode_lock,
)
from agentkit.project_management.views import (
    ProjectDetailView,
    ProjectModeLock,
    ProjectSummary,
    StoryCounters,
)

__all__ = [
    "Project",
    "ProjectAlreadyArchivedError",
    "ProjectConfiguration",
    "ProjectDetailService",
    "ProjectDetailView",
    "ProjectImmutableFieldError",
    "ProjectModeLock",
    "ProjectNotFoundError",
    "ProjectRepository",
    "ProjectStoryIdPrefixConflictError",
    "ProjectSummary",
    "StoryCounters",
    "archive_project",
    "compute_story_counters",
    "create_project",
    "derive_mode_lock",
    "update_configuration",
]
