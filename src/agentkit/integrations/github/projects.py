"""GitHub Projects v2 operations via gh CLI + GraphQL.

Provides operations for GitHub Projects v2: listing items, adding
issues, reading field metadata, and setting custom field values.
REST-style operations use ``gh project``, while field mutations
require GraphQL via ``gh api graphql``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.client import run_gh_graphql, run_gh_json


@dataclass(frozen=True)
class ProjectItem:
    """A project board item.

    Attributes:
        item_id: Node ID for GraphQL mutations.
        title: Display title of the item.
        status: Current status field value, or ``None`` if unset.
        content_url: URL of the linked issue/PR, or ``None``.
    """

    item_id: str
    title: str
    status: str | None
    content_url: str | None


def list_project_items(
    owner: str, project_number: int
) -> list[ProjectItem]:
    """List all items in a project.

    Args:
        owner: Project owner (user or org login).
        project_number: The project number (visible in the URL).

    Returns:
        List of project items.

    Raises:
        IntegrationError: If the command fails.
    """
    result = run_gh_json(
        "project", "item-list", str(project_number),
        "--owner", owner,
        "--format", "json",
        "--limit", "500",
    )
    if not isinstance(result, dict):
        raise IntegrationError(
            "Unexpected response type for project item-list",
            detail={"response": result},
        )
    items: list[ProjectItem] = []
    for raw_item in result.get("items", []):
        items.append(ProjectItem(
            item_id=raw_item.get("id", ""),
            title=raw_item.get("title", ""),
            status=raw_item.get("status", None),
            content_url=raw_item.get("content", {}).get("url") if isinstance(
                raw_item.get("content"), dict
            ) else None,
        ))
    return items


def add_issue_to_project(
    owner: str, project_number: int, issue_url: str
) -> str:
    """Add an issue to a project.

    Args:
        owner: Project owner (user or org login).
        project_number: The project number.
        issue_url: Full URL of the issue to add.

    Returns:
        The item ID (node ID) of the newly added project item.

    Raises:
        IntegrationError: If the command fails.
    """
    result = run_gh_json(
        "project", "item-add", str(project_number),
        "--owner", owner,
        "--url", issue_url,
        "--format", "json",
    )
    if not isinstance(result, dict):
        raise IntegrationError(
            "Unexpected response type for project item-add",
            detail={"response": result},
        )
    item_id: str = result.get("id", "")
    if not item_id:
        raise IntegrationError(
            "No item ID returned from project item-add",
            detail={"response": result},
        )
    return item_id


def _update_project_field(
    project_id: str,
    item_id: str,
    field_id: str,
    value_payload: str,
) -> None:
    """Run the updateProjectV2ItemFieldValue GraphQL mutation.

    Args:
        project_id: The project node ID (e.g. ``PVT_...``).
        item_id: The item node ID (e.g. ``PVTI_...``).
        field_id: The field node ID (e.g. ``PVTF_...`` or ``PVTSSF_...``).
        value_payload: The GraphQL ``value`` object as a JSON-like string
            fragment, e.g. ``'{singleSelectOptionId: "abc"}'``.

    Raises:
        IntegrationError: On GraphQL errors.
    """
    query = f"""
    mutation {{
      updateProjectV2ItemFieldValue(input: {{
        projectId: "{project_id}"
        itemId: "{item_id}"
        fieldId: "{field_id}"
        value: {value_payload}
      }}) {{
        projectV2Item {{
          id
        }}
      }}
    }}
    """
    run_gh_graphql(query)


def set_field_single_select(
    project_id: str, item_id: str, field_id: str, option_id: str
) -> None:
    """Set a single-select custom field (e.g. Status).

    Args:
        project_id: The project node ID.
        item_id: The item node ID.
        field_id: The field node ID.
        option_id: The option node ID to select.

    Raises:
        IntegrationError: On GraphQL errors.
    """
    _update_project_field(
        project_id, item_id, field_id,
        f'{{singleSelectOptionId: "{option_id}"}}',
    )


def set_field_text(
    project_id: str, item_id: str, field_id: str, value: str
) -> None:
    """Set a text custom field.

    Args:
        project_id: The project node ID.
        item_id: The item node ID.
        field_id: The field node ID.
        value: The text value to set.

    Raises:
        IntegrationError: On GraphQL errors.
    """
    # Escape double quotes in the value for GraphQL string literal
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    _update_project_field(
        project_id, item_id, field_id,
        f'{{text: "{escaped}"}}',
    )


def set_field_number(
    project_id: str, item_id: str, field_id: str, value: float
) -> None:
    """Set a number custom field.

    Args:
        project_id: The project node ID.
        item_id: The item node ID.
        field_id: The field node ID.
        value: The numeric value to set.

    Raises:
        IntegrationError: On GraphQL errors.
    """
    _update_project_field(
        project_id, item_id, field_id,
        f"{{number: {value}}}",
    )


def set_field_date(
    project_id: str, item_id: str, field_id: str, value: str
) -> None:
    """Set a date custom field (ISO 8601).

    Args:
        project_id: The project node ID.
        item_id: The item node ID.
        field_id: The field node ID.
        value: The date value in ISO 8601 format (e.g. ``"2024-01-15"``).

    Raises:
        IntegrationError: On GraphQL errors.
    """
    _update_project_field(
        project_id, item_id, field_id,
        f'{{date: "{value}"}}',
    )


def get_project_field_ids(
    owner: str, project_number: int
) -> dict[str, str]:
    """Get all field IDs for a project.

    Args:
        owner: Project owner (user or org login).
        project_number: The project number.

    Returns:
        Mapping of field name to field node ID.

    Raises:
        IntegrationError: If the command fails.
    """
    result = run_gh_json(
        "project", "field-list", str(project_number),
        "--owner", owner,
        "--format", "json",
    )
    if not isinstance(result, dict):
        raise IntegrationError(
            "Unexpected response type for project field-list",
            detail={"response": result},
        )
    fields: dict[str, str] = {}
    for field in result.get("fields", []):
        name: str = field.get("name", "")
        field_id: str = field.get("id", "")
        if name and field_id:
            fields[name] = field_id
    return fields


def get_project_field_options(
    owner: str, project_number: int
) -> dict[str, dict[str, str]]:
    """Get single-select field options for a project.

    Useful for finding option IDs (e.g. Status "Todo", "In Progress", "Done").

    Args:
        owner: Project owner (user or org login).
        project_number: The project number.

    Returns:
        Mapping of field name to a dict of option name -> option ID.
        Only fields with options (single-select) are included.

    Raises:
        IntegrationError: If the command fails.
    """
    result = run_gh_json(
        "project", "field-list", str(project_number),
        "--owner", owner,
        "--format", "json",
    )
    if not isinstance(result, dict):
        raise IntegrationError(
            "Unexpected response type for project field-list",
            detail={"response": result},
        )
    field_options: dict[str, dict[str, str]] = {}
    for field in result.get("fields", []):
        options: list[dict[str, Any]] = field.get("options", [])
        if options:
            name: str = field.get("name", "")
            field_options[name] = {
                opt["name"]: opt["id"] for opt in options
            }
    return field_options
