from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.concept_catalog.errors import ConceptRefNotFoundError
from agentkit.backend.concept_catalog.index import ConceptIndex

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


def _loaded_index(root: Path) -> ConceptIndex:
    index = ConceptIndex(root)
    index.load()
    return index


def test_load_parses_frontmatter(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        "technical-design/70-routing.md",
        """
concept_id: FK-70
title: Routing Contract
status: active
domain: governance
tags: [routing, concepts]
cross_cutting: false
defers_to:
  - DK-01
formal_refs:
  - formal.routing.entities
""",
        "Routing body.",
    )
    index = _loaded_index(tmp_path)

    ref = index.get("FK-70")

    assert ref is not None
    assert ref.concept_id == "FK-70"
    assert ref.layer == "technical"
    assert ref.title == "Routing Contract"
    assert ref.status == "active"
    assert ref.domain == "governance"
    assert ref.tags == ["routing", "concepts"]
    assert ref.cross_cutting is False
    assert ref.defers_to == ["DK-01"]
    assert ref.formal_refs == ["formal.routing.entities"]


def test_get_returns_none_for_missing_ref(tmp_path: Path) -> None:
    index = _loaded_index(tmp_path)

    assert index.get("FK-404") is None


def test_list_filters_by_layer_status_and_domain(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        "domain-design/01-domain.md",
        """
concept_id: DK-01
title: Domain
status: draft
domain: story-lifecycle
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "Domain body.",
    )
    _write_doc(
        tmp_path,
        "technical-design/70-routing.md",
        """
concept_id: FK-70
title: Routing
status: active
domain: governance
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "Routing body.",
    )
    index = _loaded_index(tmp_path)

    assert [ref.concept_id for ref in index.list(layer="domain")] == ["DK-01"]
    assert [ref.concept_id for ref in index.list(status="active")] == ["FK-70"]
    assert [ref.concept_id for ref in index.list(domain="story-lifecycle")] == ["DK-01"]


def test_backlinks_finds_incoming_refs(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        "domain-design/01-domain.md",
        """
concept_id: DK-01
title: Domain
status: active
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "Domain body.",
    )
    _write_doc(
        tmp_path,
        "technical-design/70-routing.md",
        """
concept_id: FK-70
title: Routing
status: active
tags: []
cross_cutting: false
defers_to:
  - target: DK-01
    scope: routing
    reason: example
formal_refs:
  - formal.routing.entities
""",
        "Routing body.",
    )
    _write_doc(
        tmp_path,
        "formal-spec/routing/entities.md",
        """
id: formal.routing.entities
title: Routing Entities
status: active
doc_kind: spec
context: routing
spec_kind: entity-set
version: 1
""",
        "Formal body.",
    )
    index = _loaded_index(tmp_path)

    assert index.backlinks("DK-01").incoming_defers_to == ["FK-70"]
    assert index.backlinks("formal.routing.entities").incoming_formal_refs == ["FK-70"]


def test_search_matches_title_and_body_deterministically(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        "technical-design/01-alpha.md",
        """
concept_id: FK-01
title: Alpha Routing
status: active
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "Body without the query.",
    )
    _write_doc(
        tmp_path,
        "technical-design/02-beta.md",
        """
concept_id: FK-02
title: Beta
status: active
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "Routing appears only in the body.",
    )
    index = _loaded_index(tmp_path)

    hits = index.search("routing")

    assert [hit.ref for hit in hits] == ["FK-01", "FK-02"]
    assert "routing" in hits[0].snippet


def test_content_returns_body_without_frontmatter(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        "domain-design/01-domain.md",
        """
concept_id: DK-01
title: Domain
status: active
tags: []
cross_cutting: false
defers_to: []
formal_refs: []
""",
        "# Heading\n\nBody text.",
    )
    index = _loaded_index(tmp_path)

    assert index.content("DK-01") == "# Heading\n\nBody text."
    with pytest.raises(ConceptRefNotFoundError):
        index.content("DK-404")
