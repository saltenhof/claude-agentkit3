"""Project and project-token row mappers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import CorruptStateError

from ._common import dump_json

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.project_management.entities import Project



def project_to_row(project: Project) -> dict[str, Any]:
    """Convert a project entity to a DB-insertable row dict."""

    return {
        "key": project.key,
        "name": project.name,
        "story_id_prefix": project.story_id_prefix,
        "configuration_json": dump_json(project.configuration.model_dump(mode="json")),
        "archived_at": (
            project.archived_at.isoformat() if project.archived_at is not None else None
        ),
    }



def _backfill_legacy_project_configuration_payload(
    payload: dict[str, Any],
    *,
    project_key: str,
) -> dict[str, Any]:
    """Forward-compat: derive ``repositories`` for legacy/empty DB rows.

    The strict ``ProjectConfiguration`` schema requires ``repositories`` with
    at least one entry.  Two read-side cases must be handled here at the
    boundary so the schema can stay strict on writes:

    - ``repositories`` key absent      (legacy row pre-AG3-020)
    - ``repositories`` present but ``[]`` (legacy bootstrap fallback)

    Both trigger the same conservative fallback:

    - ``repo_url`` set and non-empty -> ``repositories = [repo_url]``
    - else                            -> ``repositories = [project_key]``
      (the project_key is guaranteed to exist; operator MUST replace it).

    A WARNING is logged for every legacy row encountered so the operator
    can correct the project record explicitly.

    Args:
        payload: Raw configuration dict as it came out of the JSON column.
        project_key: The project key this payload belongs to (for log context
            and last-resort fallback).

    Returns:
        A new dict with ``repositories`` populated, or the original dict
        unchanged when ``repositories`` was already present and non-empty.
    """

    existing = payload.get("repositories")
    if isinstance(existing, list) and existing:
        # Already populated, schema-acceptable — pass through unchanged.
        return payload
    repo_url = payload.get("repo_url", "")
    if isinstance(repo_url, str) and repo_url.strip():
        _log.warning(
            "Legacy project configuration for %r without usable 'repositories'; "
            "deriving [%r] from repo_url. Update the project record.",
            project_key,
            repo_url,
        )
        return {**payload, "repositories": [repo_url]}
    _log.warning(
        "Legacy project configuration for %r without usable 'repositories' and "
        "without a usable repo_url; falling back to [%r]. Operator MUST replace.",
        project_key,
        project_key,
    )
    return {**payload, "repositories": [project_key]}



def project_row_to_entity(row: dict[str, Any]) -> Project:
    """Convert a project DB row dict to a project entity."""

    from agentkit.backend.project_management.entities import (
        Project as _Project,
    )
    from agentkit.backend.project_management.entities import (
        ProjectConfiguration as _ProjectConfiguration,
    )

    configuration_raw = row.get("configuration_json", row.get("configuration"))
    configuration_payload = (
        json.loads(configuration_raw)
        if isinstance(configuration_raw, str)
        else configuration_raw
    )
    if not isinstance(configuration_payload, dict):
        raise CorruptStateError(
            f"project configuration for {row.get('key')!r} is not a dict; "
            f"got {type(configuration_payload).__name__}",
        )

    configuration_payload = _backfill_legacy_project_configuration_payload(
        configuration_payload,
        project_key=str(row["key"]),
    )

    archived_at_raw = row.get("archived_at")
    archived_at = (
        datetime.fromisoformat(archived_at_raw)
        if isinstance(archived_at_raw, str)
        else archived_at_raw
    )

    return _Project(
        key=str(row["key"]),
        name=str(row["name"]),
        story_id_prefix=str(row["story_id_prefix"]),
        configuration=_ProjectConfiguration.model_validate(configuration_payload),
        archived_at=archived_at,
    )



def project_api_token_to_row(token: ProjectApiToken) -> dict[str, Any]:
    """Convert a project API token to a DB row."""

    return {
        "token_id": token.token_id,
        "project_key": token.project_key,
        "label": token.label,
        "token_hash": token.token_hash,
        "created_at": token.created_at.isoformat(),
        "revoked_at": (
            token.revoked_at.isoformat() if token.revoked_at is not None else None
        ),
        "last_used_at": (
            token.last_used_at.isoformat() if token.last_used_at is not None else None
        ),
    }



def project_api_token_row_to_entity(row: dict[str, Any]) -> ProjectApiToken:
    """Convert a DB row to a project API token."""

    from agentkit.backend.auth.entities import ProjectApiToken as _ProjectApiToken

    def _datetime_from_row(key: str) -> datetime | None:
        value = row.get(key)
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    created_at = _datetime_from_row("created_at")
    if created_at is None:
        raise CorruptStateError("project_api_tokens.created_at is required")
    return _ProjectApiToken(
        token_id=str(row["token_id"]),
        project_key=str(row["project_key"]),
        label=str(row["label"]),
        token_hash=str(row["token_hash"]),
        created_at=created_at,
        revoked_at=_datetime_from_row("revoked_at"),
        last_used_at=_datetime_from_row("last_used_at"),
    )
