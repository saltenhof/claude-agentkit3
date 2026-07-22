"""Extra coverage for MCP contracts and dispatch edges."""

from __future__ import annotations

import pytest

from agentkit.backend.vectordb.mcp.contracts import (
    ToolArgumentError,
    optional_bool,
    require_bool,
    require_concept_status,
    require_limit,
    require_search_mode,
    require_str,
)
from agentkit.backend.vectordb.mcp_server import list_tools


def test_require_str_missing() -> None:
    with pytest.raises(ToolArgumentError):
        require_str({}, "query")


def test_require_bool_missing_without_default() -> None:
    with pytest.raises(ToolArgumentError):
        require_bool({}, "full_reindex")


def test_require_limit_bounds() -> None:
    assert require_limit({}) == 10
    assert require_limit({"limit": 5}) == 5
    with pytest.raises(ToolArgumentError):
        require_limit({"limit": 0})
    with pytest.raises(ToolArgumentError):
        require_limit({"limit": True})  # type: ignore[dict-item]


def test_search_mode_and_status_enums() -> None:
    assert require_search_mode({}) == "hybrid"
    with pytest.raises(ToolArgumentError):
        require_search_mode({"search_mode": "bogus"})
    assert require_concept_status({}) == "active"
    with pytest.raises(ToolArgumentError):
        require_concept_status({"concept_status": "gone"})


def test_optional_bool() -> None:
    assert optional_bool({}, "is_appendix") is None
    assert optional_bool({"is_appendix": True}, "is_appendix") is True
    with pytest.raises(ToolArgumentError):
        optional_bool({"is_appendix": 1}, "is_appendix")  # type: ignore[dict-item]


def test_list_tools_required_fields() -> None:
    tools = list_tools()
    assert {t["name"] for t in tools} == {
        "story_search",
        "story_list_sources",
        "story_sync",
        "concept_search",
        "concept_sync",
    }
