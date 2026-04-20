"""Unit tests for GitHub Projects operations."""

from __future__ import annotations

import pytest

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.projects import (
    ProjectItem,
    _update_project_field,
    add_issue_to_project,
    get_project_field_ids,
    get_project_field_options,
    list_project_items,
    set_field_date,
    set_field_number,
    set_field_single_select,
    set_field_text,
)


def test_list_project_items_parses_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: {
            "items": [
                {
                    "id": "PVTI_1",
                    "title": "Implement tenant scope",
                    "status": "In Progress",
                    "content": {"url": "https://example.test/issues/1"},
                },
                {
                    "id": "PVTI_2",
                    "title": "No content object",
                    "status": None,
                    "content": "not-a-dict",
                },
            ]
        },
    )

    items = list_project_items("acme", 3)

    assert items == [
        ProjectItem(
            item_id="PVTI_1",
            title="Implement tenant scope",
            status="In Progress",
            content_url="https://example.test/issues/1",
        ),
        ProjectItem(
            item_id="PVTI_2",
            title="No content object",
            status=None,
            content_url=None,
        ),
    ]


def test_list_project_items_rejects_unexpected_response_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: ["not", "a", "dict"],
    )

    with pytest.raises(IntegrationError, match="Unexpected response type"):
        list_project_items("acme", 3)


def test_add_issue_to_project_returns_item_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: {"id": "PVTI_123"},
    )

    assert (
        add_issue_to_project("acme", 3, "https://example.test/issues/1")
        == "PVTI_123"
    )


def test_add_issue_to_project_rejects_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: ["bad"],
    )

    with pytest.raises(IntegrationError, match="Unexpected response type"):
        add_issue_to_project("acme", 3, "https://example.test/issues/1")


def test_add_issue_to_project_requires_item_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: {},
    )

    with pytest.raises(IntegrationError, match="No item ID returned"):
        add_issue_to_project("acme", 3, "https://example.test/issues/1")


def test_update_project_field_builds_graphql_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str | None]] = []

    def fake_run_gh_graphql(
        query: str,
        *,
        owner: str | None = None,
    ) -> dict[str, object]:
        seen.append((query, owner))
        return {"data": {}}

    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_graphql",
        fake_run_gh_graphql,
    )

    _update_project_field(
        "PVT_1",
        "PVTI_1",
        "PVTF_1",
        '{text: "hello"}',
        owner="acme",
    )

    assert len(seen) == 1
    assert 'projectId: "PVT_1"' in seen[0][0]
    assert 'itemId: "PVTI_1"' in seen[0][0]
    assert 'fieldId: "PVTF_1"' in seen[0][0]
    assert '{text: "hello"}' in seen[0][0]
    assert seen[0][1] == "acme"


def test_set_field_helpers_forward_expected_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, str, str, str | None]] = []

    def fake_update(
        project_id: str,
        item_id: str,
        field_id: str,
        value_payload: str,
        *,
        owner: str | None = None,
    ) -> None:
        seen.append((project_id, item_id, field_id, value_payload, owner))

    monkeypatch.setattr(
        "agentkit.integrations.github.projects._update_project_field",
        fake_update,
    )

    set_field_single_select("PVT", "PVTI", "PVTF", "OPT", owner="acme")
    set_field_text("PVT", "PVTI", "PVTF", 'A "quote" and \\ slash', owner="acme")
    set_field_number("PVT", "PVTI", "PVTF", 3.5, owner="acme")
    set_field_date("PVT", "PVTI", "PVTF", "2026-04-20", owner="acme")

    assert seen == [
        ("PVT", "PVTI", "PVTF", '{singleSelectOptionId: "OPT"}', "acme"),
        ("PVT", "PVTI", "PVTF", '{text: "A \\"quote\\" and \\\\ slash"}', "acme"),
        ("PVT", "PVTI", "PVTF", "{number: 3.5}", "acme"),
        ("PVT", "PVTI", "PVTF", '{date: "2026-04-20"}', "acme"),
    ]


def test_get_project_field_ids_filters_empty_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: {
            "fields": [
                {"name": "Status", "id": "PVTF_1"},
                {"name": "", "id": "PVTF_2"},
                {"name": "Estimate", "id": ""},
            ]
        },
    )

    assert get_project_field_ids("acme", 3) == {"Status": "PVTF_1"}


def test_get_project_field_ids_rejects_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: ["bad"],
    )

    with pytest.raises(IntegrationError, match="Unexpected response type"):
        get_project_field_ids("acme", 3)


def test_get_project_field_options_returns_single_select_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: {
            "fields": [
                {
                    "name": "Status",
                    "options": [
                        {"name": "Todo", "id": "OPT_1"},
                        {"name": "Done", "id": "OPT_2"},
                    ],
                },
                {"name": "Estimate", "options": []},
            ]
        },
    )

    assert get_project_field_options("acme", 3) == {
        "Status": {"Todo": "OPT_1", "Done": "OPT_2"}
    }


def test_get_project_field_options_rejects_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.projects.run_gh_json",
        lambda *args, **kwargs: ["bad"],
    )

    with pytest.raises(IntegrationError, match="Unexpected response type"):
        get_project_field_options("acme", 3)
