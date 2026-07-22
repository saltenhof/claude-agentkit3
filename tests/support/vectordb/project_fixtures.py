"""Shared fixtures for AG3-174 VectorDB tests (FK-13-conformant target corpus)."""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Minimal ProjectConfig that satisfies the authoritative loader.
_MINIMAL_PROJECT_YAML = dedent(
    """\
    project_key: {project_key}
    project_name: Test Project {project_key}
    repositories:
      - name: app
        path: .
    pipeline:
      config_version: '3.0'
      features:
        multi_llm: false
      sonarqube:
        available: false
        enabled: false
      ci:
        available: false
        enabled: false
      vectordb:
        host: weaviate.test.local
        port: 19903
        grpc_port: 50051
    concepts_dir: concepts
    wiki_stories_dir: stories
    """
)


def write_project_config(root: Path, *, project_key: str = "P1") -> Path:
    """Write a minimal fail-closed ProjectConfig under root."""
    cfg_dir = root / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "project.yaml"
    path.write_text(
        _MINIMAL_PROJECT_YAML.format(project_key=project_key),
        encoding="utf-8",
    )
    return path


def write_fk13_concept(
    concepts_dir: Path,
    *,
    concept_id: str = "FK-TEST",
    title: str | None = None,
    authority: list[str] | None = None,
    defers: list[dict[str, str]] | None = None,
    body: str | None = None,
    filename: str | None = None,
) -> Path:
    """Write one FK-13-conformant concept document (core, active)."""
    concepts_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"Title {concept_id}"
    authority = authority or ["vectordb-test"]
    defers = defers or []
    auth_yaml = "\n".join(f"  - scope: {s}" for s in authority) if authority else "  []"
    defer_yaml = (
        "\n".join(
            f"  - target: {d['target']}\n    scope: {d.get('scope', '')}\n"
            f"    reason: {d.get('reason', '')}"
            for d in defers
        )
        if defers
        else "  []"
    )
    section = body or f"## Purpose\n\nConcept body about {concept_id} retrieval.\n"
    name = filename or f"{concept_id.lower().replace('-', '_')}.md"
    path = concepts_dir / name
    path.write_text(
        f"""---
concept_id: {concept_id}
title: {title}
module: vectordb
status: active
doc_kind: core
authority_over:
{auth_yaml}
defers_to:
{defer_yaml}
---

# {title}

{section}
""",
        encoding="utf-8",
    )
    return path


def write_story_tree(root: Path, *, story_id: str = "S-001") -> None:
    """Write story.md + research + negative review under stories/."""
    story_dir = root / "stories" / story_id
    (story_dir / "research").mkdir(parents=True, exist_ok=True)
    (story_dir / "story.md").write_text(
        f"""---
story_id: {story_id}
title: Story One
status: Done
story_type: implementation
module: m
---

# Story One

## Problemstellung

Need semantic search.

## Loesungsansatz

Build the engine.
""",
        encoding="utf-8",
    )
    (story_dir / "research" / "notes.md").write_text(
        f"""---
story_id: {story_id}
title: Research Notes
---

# Research

## Findings

Useful research note about vectors.
""",
        encoding="utf-8",
    )
    (story_dir / "review-1.md").write_text(
        "# Review\n\nShould not be ingested.\n",
        encoding="utf-8",
    )


def make_fk13_project(tmp: Path, project_key: str = "P1") -> Path:
    """Create a complete FK-13 target project layout for tests."""
    root = tmp / project_key
    root.mkdir(parents=True, exist_ok=True)
    write_project_config(root, project_key=project_key)
    write_fk13_concept(root / "concepts", concept_id="FK-TEST")
    write_story_tree(root)
    return root
