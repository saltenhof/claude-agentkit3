from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes
from agentkit.backend.concept_catalog.index import ConceptIndex
from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes

if TYPE_CHECKING:
    from pathlib import Path


def _write_doc(
    root: Path,
    relative_path: str,
    frontmatter: str,
    body: str,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}", encoding="utf-8")


def _app(root: Path) -> ControlPlaneApplication:
    index = ConceptIndex(root)
    index.load()
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(concept_routes=ConceptCatalogRoutes(index))
    )


def _fixture_root(tmp_path: Path) -> Path:
    _write_doc(
        tmp_path,
        "domain-design/01-domain.md",
        """
concept_id: DK-01
title: Domain Concept
status: active
domain: story-lifecycle
tags: [domain]
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "# Domain Concept\n\nShared concept body.",
    )
    _write_doc(
        tmp_path,
        "technical-design/70-technical.md",
        """
concept_id: FK-70
title: Technical Catalog
status: active
domain: story-lifecycle
tags: [technical]
cross_cutting: false
defers_to:
  - target: DK-01
    scope: example
    reason: test
formal_refs: []
""",
        "# Technical Catalog\n\nSearchable catalog body.",
    )
    return tmp_path


def _json_body(response_body: bytes) -> dict[str, object]:
    body = json.loads(response_body.decode("utf-8"))
    assert isinstance(body, dict)
    return body


def test_get_concepts_lists_refs(tmp_path: Path) -> None:
    response = _app(_fixture_root(tmp_path)).handle_request(
        method="GET",
        path="/v1/concepts?layer=domain&status=active&domain=story-lifecycle",
        body=b"",
        request_headers={"X-Correlation-Id": "req-concepts"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    assert body["concepts"] == [
        {
            "concept_id": "DK-01",
            "path": str(tmp_path / "domain-design/01-domain.md"),
            "layer": "domain",
            "title": "Domain Concept",
            "status": "active",
            "domain": "story-lifecycle",
            "tags": ["domain"],
            "cross_cutting": False,
            "defers_to": [],
            "formal_refs": [],
        },
    ]
    assert ("X-Correlation-Id", "req-concepts") in response.headers


def test_get_concept_detail_returns_backlinks(tmp_path: Path) -> None:
    response = _app(_fixture_root(tmp_path)).handle_request(
        method="GET",
        path="/v1/concepts/DK-01",
        body=b"",
        request_headers={"X-Correlation-Id": "req-detail"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    backlinks = body["backlinks"]
    assert isinstance(backlinks, dict)
    assert backlinks["incoming_defers_to"] == ["FK-70"]


def test_get_concept_content_returns_markdown(tmp_path: Path) -> None:
    response = _app(_fixture_root(tmp_path)).handle_request(
        method="GET",
        path="/v1/concepts/FK-70/content",
        body=b"",
        request_headers={"X-Correlation-Id": "req-content"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.body.decode("utf-8") == "# Technical Catalog\n\nSearchable catalog body."
    assert ("Content-Type", "text/markdown; charset=utf-8") in response.headers


def test_get_concepts_search_returns_hits(tmp_path: Path) -> None:
    response = _app(_fixture_root(tmp_path)).handle_request(
        method="GET",
        path="/v1/concepts/search?q=searchable&limit=1",
        body=b"",
        request_headers={"X-Correlation-Id": "req-search"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    assert body["hits"] == [
        {
            "ref": "FK-70",
            "title": "Technical Catalog",
            "snippet": "technical catalog # technical catalog searchable catalog body.",
            "score": 1.025,
        },
    ]


def test_get_missing_concept_returns_404(tmp_path: Path) -> None:
    response = _app(_fixture_root(tmp_path)).handle_request(
        method="GET",
        path="/v1/concepts/DK-404",
        body=b"",
        request_headers={"X-Correlation-Id": "req-missing"},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
