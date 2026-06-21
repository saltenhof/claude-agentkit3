"""Contract test: project_summary wire shape (AG3-040 sub-block a).

Pins ``frontend-contracts.entity.project_summary`` exactly: the wire
payload produced by the project-management ``_project_payload`` adapter
and the :class:`ProjectSummary` model carry exactly ``project_key``,
``display_name`` and ``status`` — and no further fields.  Drift in
either direction (missing or extra field) fails this test.
"""

from __future__ import annotations

from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.http.routes import _project_payload
from agentkit.backend.project_management.views import ProjectSummary

_PROJECT_SUMMARY_FIELDS = frozenset({"project_key", "display_name", "status"})


def _project(*, archived: bool) -> Project:
    from datetime import UTC, datetime

    return Project(
        key="tenant-a",
        name="Tenant A",
        story_id_prefix="AG3",
        configuration=ProjectConfiguration(
            repo_url="",
            default_branch="main",
            default_worker_count=2,
            repositories=["repo-a"],
        ),
        archived_at=datetime.now(UTC) if archived else None,
    )


def test_project_summary_model_fields_are_exactly_the_contract() -> None:
    assert set(ProjectSummary.model_fields.keys()) == _PROJECT_SUMMARY_FIELDS


def test_project_payload_active_wire_shape() -> None:
    payload = _project_payload(_project(archived=False))
    assert payload == {
        "project_key": "tenant-a",
        "display_name": "Tenant A",
        "status": "active",
    }
    assert set(payload.keys()) == _PROJECT_SUMMARY_FIELDS


def test_project_payload_archived_status() -> None:
    payload = _project_payload(_project(archived=True))
    assert payload["status"] == "archived"
    assert set(payload.keys()) == _PROJECT_SUMMARY_FIELDS


def test_project_payload_has_no_leaked_entity_fields() -> None:
    payload = _project_payload(_project(archived=False))
    for leaked in ("key", "name", "story_id_prefix", "configuration",
                   "archived_at", "created_at"):
        assert leaked not in payload
