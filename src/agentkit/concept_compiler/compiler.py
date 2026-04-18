"""Compilation and reference checks for formal concept specs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentkit.concept_compiler.loader import FormalSpecDocument, discover_formal_spec_files, load_formal_spec
from agentkit.exceptions import AgentKitError

REFERENCE_KEYS = frozenset(
    {
        "from",
        "to",
        "guard",
        "requires",
        "emits",
        "allowed_statuses",
        "phase",
        "status",
        "target_phase",
        "command",
    }
)


class FormalCompilationError(AgentKitError):
    """Raised when formal spec compilation fails."""


@dataclass(frozen=True)
class FormalReference:
    """Reference from one formal object to another."""

    source_doc_id: str
    field_path: str
    target_id: str


@dataclass(frozen=True)
class CompiledFormalSpec:
    """Compilation result for a formal spec tree."""

    documents: tuple[FormalSpecDocument, ...]
    declared_ids: frozenset[str]
    references: tuple[FormalReference, ...]


def compile_formal_specs(root: Path) -> CompiledFormalSpec:
    """Compile all formal spec documents under *root*."""
    paths = discover_formal_spec_files(root)
    documents = tuple(load_formal_spec(path) for path in paths)
    declared_ids = _collect_declared_ids(documents)
    references = _collect_references(documents)
    _validate_references(declared_ids, references)
    return CompiledFormalSpec(
        documents=documents,
        declared_ids=frozenset(declared_ids),
        references=references,
    )


def _collect_declared_ids(documents: tuple[FormalSpecDocument, ...]) -> set[str]:
    declared_ids: set[str] = set()
    for document in documents:
        for object_id in _walk_declared_ids(document.spec):
            if object_id in declared_ids:
                raise FormalCompilationError(
                    f"Duplicate formal object id detected: {object_id}",
                    detail={"duplicate_id": object_id, "document": document.doc_id},
                )
            declared_ids.add(object_id)
    return declared_ids


def _walk_declared_ids(node: Any) -> tuple[str, ...]:
    ids: list[str] = []
    if isinstance(node, dict):
        value = node.get("id")
        if isinstance(value, str) and value != "":
            ids.append(value)
        for child in node.values():
            ids.extend(_walk_declared_ids(child))
    elif isinstance(node, list):
        for child in node:
            ids.extend(_walk_declared_ids(child))
    return tuple(ids)


def _collect_references(documents: tuple[FormalSpecDocument, ...]) -> tuple[FormalReference, ...]:
    refs: list[FormalReference] = []
    for document in documents:
        refs.extend(_walk_references(document.doc_id, document.spec, "spec"))
    return tuple(refs)


def _walk_references(source_doc_id: str, node: Any, path: str) -> tuple[FormalReference, ...]:
    refs: list[FormalReference] = []
    if isinstance(node, dict):
        for key, value in node.items():
            field_path = f"{path}.{key}"
            if key in REFERENCE_KEYS:
                refs.extend(_references_for_value(source_doc_id, field_path, value))
            refs.extend(_walk_references(source_doc_id, value, field_path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            refs.extend(_walk_references(source_doc_id, value, f"{path}[{index}]"))
    return tuple(refs)


def _references_for_value(source_doc_id: str, field_path: str, value: Any) -> tuple[FormalReference, ...]:
    refs: list[FormalReference] = []
    if isinstance(value, str) and "." in value:
        refs.append(FormalReference(source_doc_id=source_doc_id, field_path=field_path, target_id=value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            refs.extend(_references_for_value(source_doc_id, f"{field_path}[{index}]", item))
    return tuple(refs)


def _validate_references(declared_ids: set[str], references: tuple[FormalReference, ...]) -> None:
    unresolved = [
        reference
        for reference in references
        if reference.target_id not in declared_ids
    ]
    if unresolved:
        formatted = ", ".join(
            f"{reference.target_id} ({reference.source_doc_id} @ {reference.field_path})"
            for reference in unresolved
        )
        raise FormalCompilationError(
            f"Unresolved formal references: {formatted}",
            detail={
                "unresolved": [
                    {
                        "source_doc_id": reference.source_doc_id,
                        "field_path": reference.field_path,
                        "target_id": reference.target_id,
                    }
                    for reference in unresolved
                ]
            },
        )
