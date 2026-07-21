"""Shared fixtures for the deployable concept-toolchain engine tests.

The bundled package lives below ``src/agentkit/bundles/target_project`` and
is imported exactly as it runs in a target project: with
``tools/agentkit`` on ``sys.path`` and ``concept_toolchain`` as the
top-level package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "src" / "agentkit" / "bundles" / "target_project" / "tools" / "agentkit"
CHECK_SCRIPT = TOOLS_DIR / "concept_toolchain" / "check.py"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

GOVERNANCE_CONFIG: dict[str, object] = {
    "schema_version": "1.0.0",
    "concept_roots": {
        "domain": "concept/domain-design",
        "technical": "concept/technical-design",
        "formal": "concept/formal-spec",
        "meta": "concept/_meta",
        "guardrails": "guardrails",
    },
    "incubator_root": "concept-incubator",
    "lock_backend": "filesystem",
    "id_grammars": {
        "domain_doc": "^DK-\\d{2}$",
        "technical_doc": "^FK-\\d{2}$",
        "formal_object": "^formal\\.[a-z0-9-]+\\.[a-z0-9-]+$",
        "decision_record": "^\\d{4}-\\d{2}-\\d{2}-[a-z0-9-]+$",
        "scope": "^[a-z0-9]+([.-][a-z0-9]+)*$",
        "source": "^SRC-[0-9a-f]{8}-\\d{4,}$",
    },
    "frontmatter_contract": {
        "required_fields": [
            "concept_id",
            "title",
            "module",
            "status",
            "doc_kind",
            "parent_concept_id",
            "authority_over",
            "defers_to",
            "supersedes",
            "superseded_by",
            "tags",
        ],
        "classification": "formal_refs_xor_prose_only",
        "detail_requires_parent": True,
        "full_supersession_reciprocity": True,
    },
    "vcs_policy": {
        "mode": "class_based",
        "sensitive_disposition": "local",
        "unclassified_class": "sensitive",
    },
    "data_class_default": "sensitive",
}


def write_governance_config(project_root: Path, config: Mapping[str, object] | None = None) -> None:
    """Write the governance configuration into a test project root."""
    meta = project_root / "concept" / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    payload = dict(GOVERNANCE_CONFIG) if config is None else dict(config)
    (meta / "concept-governance.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def concept_doc(
    concept_id: str,
    *,
    title: str = "Sample document",
    doc_kind: str = "core",
    parent: str = "",
    scopes: tuple[str, ...] | None = None,
    defers: str = "defers_to: []",
    supersedes: str = "supersedes: []",
    superseded_by: str = "",
    classification: str = "formal_scope: prose-only",
    drop_fields: tuple[str, ...] = (),
    body: str = "Body text.\n",
) -> str:
    """Render one contract-conform concept document."""
    scope_lines = "\n".join(
        f"  - scope: {scope}" for scope in (scopes if scopes is not None else (f"scope-{concept_id.lower()}",))
    )
    lines = [
        f"concept_id: {concept_id}",
        f"title: {title}",
        "module: sample",
        "status: active",
        f"doc_kind: {doc_kind}",
        f"parent_concept_id: {parent}".rstrip(),
        "authority_over:",
        scope_lines,
        defers,
        supersedes,
        f"superseded_by: {superseded_by}".rstrip(),
        "tags: [sample]",
        classification,
    ]
    kept = [line for line in lines if line.split(":")[0].strip() not in drop_fields]
    frontmatter = "\n".join(line for line in kept if line != "")
    return f"---\n{frontmatter}\n---\n\n# {title}\n\n{body}"


def write_doc(project_root: Path, relative: str, text: str) -> Path:
    """Write one document below the project root."""
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def formal_spec(
    context: str,
    spec_kind: str,
    zone_body: str,
    *,
    prose_ref: str = "concept/technical-design/20_formal_host.md",
) -> str:
    """Render one formal spec file with a FORMAL-SPEC zone."""
    object_id = f"formal.{context}.{spec_kind}"
    return (
        "---\n"
        f"id: {object_id}\n"
        f"title: {context} {spec_kind}\n"
        "status: active\n"
        "doc_kind: spec\n"
        f"context: {context}\n"
        f"spec_kind: {spec_kind}\n"
        "version: 1\n"
        "prose_refs:\n"
        f"  - {prose_ref}\n"
        "---\n"
        "\n"
        f"# {context} {spec_kind}\n"
        "\n"
        "<!-- FORMAL-SPEC:BEGIN -->\n"
        "```yaml\n"
        f"object: {object_id}\n"
        "schema_version: 1\n"
        f"kind: {spec_kind}\n"
        f"context: {context}\n"
        f"{zone_body}"
        "```\n"
        "<!-- FORMAL-SPEC:END -->\n"
    )


def write_formal_context(
    project_root: Path,
    *,
    terminal: bool = True,
    guard: str = "sample.invariant.single",
    scenario_end: str = "sample.status.done",
) -> None:
    """Write a complete, by-default green formal context named ``sample``."""
    root = "concept/formal-spec/sample"
    terminal_flag = "    terminal: true\n" if terminal else ""
    write_doc(
        project_root,
        f"{root}/state-machine.md",
        formal_spec(
            "sample",
            "state-machine",
            "states:\n"
            "  - id: sample.status.open\n"
            "    initial: true\n"
            "  - id: sample.status.done\n"
            f"{terminal_flag}"
            "transitions:\n"
            "  - id: sample.transition.open_to_done\n"
            "    from: sample.status.open\n"
            "    to: sample.status.done\n"
            f"    guard: {guard}\n",
        ),
    )
    write_doc(
        project_root,
        f"{root}/commands.md",
        formal_spec(
            "sample",
            "command-set",
            "commands:\n"
            "  - id: sample.command.finish\n"
            "    signature: cli finish\n"
            "    allowed_statuses:\n"
            "      - sample.status.open\n"
            "    requires:\n"
            "      - sample.invariant.single\n"
            "    emits:\n"
            "      - sample.event.finished\n",
        ),
    )
    write_doc(
        project_root,
        f"{root}/events.md",
        formal_spec(
            "sample",
            "event-set",
            "events:\n  - id: sample.event.finished\n    producer: sample\n    role: lifecycle\n",
        ),
    )
    write_doc(
        project_root,
        f"{root}/invariants.md",
        formal_spec(
            "sample",
            "invariant-set",
            "invariants:\n  - id: sample.invariant.single\n    scope: process\n    rule: exactly one finish per run\n",
        ),
    )
    write_doc(
        project_root,
        f"{root}/scenarios.md",
        formal_spec(
            "sample",
            "scenario-set",
            "scenarios:\n"
            "  - id: sample.scenario.happy\n"
            "    start:\n"
            "      status: sample.status.open\n"
            "    trace:\n"
            "      - command: sample.command.finish\n"
            "    expected_end:\n"
            f"      status: {scenario_end}\n",
        ),
    )
    write_doc(
        project_root,
        f"{root}/entities.md",
        formal_spec(
            "sample",
            "entity-set",
            "entities:\n  - id: sample.entity.thing\n    identity_key: thing_id\n",
        ),
    )
    formal_refs = "\n".join(
        f"  - formal.sample.{kind}"
        for kind in ("state-machine", "command-set", "event-set", "invariant-set", "scenario-set", "entity-set")
    )
    write_doc(
        project_root,
        "concept/technical-design/20_formal_host.md",
        concept_doc("FK-20", title="Formal host", classification=f"formal_refs:\n{formal_refs}"),
    )


@pytest.fixture
def green_corpus(tmp_path: Path) -> Path:
    """A minimal corpus that passes frontmatter, references, formal, projection."""
    write_governance_config(tmp_path)
    (tmp_path / "concept" / "_meta" / "projection-manifest.json").write_text(
        json.dumps({"schema_version": "1.0.0", "entries": []}, indent=2), encoding="utf-8"
    )
    (tmp_path / "guardrails").mkdir(exist_ok=True)
    write_doc(tmp_path, "concept/domain-design/01-sample.md", concept_doc("DK-01", body="See FK-10.\n"))
    write_doc(
        tmp_path,
        "concept/technical-design/10_sample.md",
        concept_doc("FK-10", body="Refer to DK-01 and `concept/domain-design/01-sample.md`.\n"),
    )
    write_formal_context(tmp_path)
    return tmp_path
