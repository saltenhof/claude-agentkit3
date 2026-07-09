"""Story metadata facade operations and static BC-store compatibility exports."""

from __future__ import annotations

from agentkit.backend.state_backend.execution_planning_store import (
    delete_story_dependency as delete_story_dependency,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_parallelization_config as load_parallelization_config,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_story_dependencies as load_story_dependencies,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_story_dependency_rows_for_story as load_story_dependency_rows_for_story,
)
from agentkit.backend.state_backend.execution_planning_store import (
    save_parallelization_config as save_parallelization_config,
)
from agentkit.backend.state_backend.execution_planning_store import (
    save_story_dependency as save_story_dependency,
)
from agentkit.backend.state_backend.project_store import (
    load_project as load_project,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_token as load_project_api_token,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_token_by_hash as load_project_api_token_by_hash,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_tokens_for_project as load_project_api_tokens_for_project,
)
from agentkit.backend.state_backend.project_store import (
    load_project_by_story_id_prefix as load_project_by_story_id_prefix,
)
from agentkit.backend.state_backend.project_store import (
    load_projects as load_projects,
)
from agentkit.backend.state_backend.project_store import (
    save_project as save_project,
)
from agentkit.backend.state_backend.project_store import (
    save_project_api_token as save_project_api_token,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    delete_story_are_link as delete_story_are_link,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    load_story_are_links as load_story_are_links,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    save_story_are_link as save_story_are_link,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    update_story_are_link_kind as update_story_are_link_kind,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context as load_story_context,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context_by_story_number_global as load_story_context_by_story_number_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context_by_uuid_global as load_story_context_by_uuid_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context_global as load_story_context_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_contexts_global as load_story_contexts_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    read_story_context_record as read_story_context_record,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_story_context as save_story_context,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_story_context_global as save_story_context_global,
)

__all__ = [
    "save_story_context", "save_story_context_global", "load_story_context",
    "load_story_context_global", "load_story_context_by_story_number_global",
    "load_story_context_by_uuid_global", "load_story_contexts_global",
    "read_story_context_record", "save_project", "load_project", "load_projects",
    "load_project_by_story_id_prefix", "save_project_api_token",
    "load_project_api_token", "load_project_api_token_by_hash",
    "load_project_api_tokens_for_project", "save_story_dependency",
    "load_story_dependencies", "load_story_dependency_rows_for_story",
    "delete_story_dependency", "load_parallelization_config",
    "save_parallelization_config", "save_story_are_link", "load_story_are_links",
    "update_story_are_link_kind", "delete_story_are_link",
]
