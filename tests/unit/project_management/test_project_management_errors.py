from __future__ import annotations

from agentkit.backend.exceptions import AgentKitError
from agentkit.backend.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
    ProjectNotFoundError,
    ProjectRepositoriesInvalidError,
    ProjectRepoStillInUseError,
    ProjectStoryIdPrefixConflictError,
)


def test_all_project_management_errors_have_one_static_agentkit_base_contract() -> None:
    error_types = (
        ProjectAlreadyArchivedError,
        ProjectImmutableFieldError,
        ProjectNotFoundError,
        ProjectRepositoriesInvalidError,
        ProjectRepoStillInUseError,
        ProjectStoryIdPrefixConflictError,
    )

    assert all(error_type.__bases__ == (AgentKitError,) for error_type in error_types)
