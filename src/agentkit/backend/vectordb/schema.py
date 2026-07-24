"""StoryContext collection schema (FK-13 §13.3.1 + §13.9.3).

One Weaviate collection holds both Story- and Concept-properties; ``project_id``
is the multi-tenant discriminator and ``source_type`` selects the projection
(FK-13 §13.9.2: "eine Collection, zwei Tools"). This module owns:

- the complete, FK-bound property set (contract source of truth);
- deterministic object identity (uuid5 from project_id + source_file + chunk_id);
- the property projection for a chunk (used by the ingest adapter).

The schema is declared once here; the Weaviate transport adapter consumes
``STORY_CONTEXT_PROPERTIES`` to create the collection idempotently. Production
property NAMES are English wire keys (ARCH-55).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Weaviate collection name (FK-13 §13.3.1).
STORY_CONTEXT_COLLECTION: Final[str] = "StoryContext"

#: Namespace for deterministic chunk UUIDs (project + source + chunk).
_CHUNK_UUID_NAMESPACE = uuid.UUID("7a1c0d2e-3b4f-5a6b-8c9d-0e1f2a3b4c5d")

#: Allowed source_type values (FK-13 §13.3.1 / §13.9.5).
SOURCE_TYPES: Final[tuple[str, ...]] = ("story", "research", "concept")

#: The COMPLETE StoryContext property set (FK-13 §13.3.1 + §13.9.3).
#: Each entry: (name, weaviate_data_type, vectorized). This is the contract
#: source of truth bound by ``tests/contract/.../test_storycontext_schema.py``.
STORY_CONTEXT_PROPERTIES: Final[tuple[tuple[str, str, bool], ...]] = (
    # --- FK-13 §13.3.1 (base) ---
    ("content", "TEXT", True),
    ("story_id", "TEXT", False),
    ("title", "TEXT", True),
    ("status", "TEXT", False),
    ("story_type", "TEXT", False),
    ("module", "TEXT", False),
    ("epic", "TEXT", False),
    ("source_type", "TEXT", False),
    ("source_file", "TEXT", False),
    ("section_heading", "TEXT", True),
    ("content_hash", "TEXT", False),
    ("project_id", "TEXT", False),
    # --- FK-13 §13.9.3 (concept extension) ---
    ("concept_id", "TEXT", False),
    ("is_appendix", "BOOL", False),
    ("parent_concept_id", "TEXT", False),
    ("defers_to", "TEXT[]", False),
    ("authority_over", "TEXT[]", False),
    ("section_number", "TEXT", False),
    ("normative_rules", "TEXT", False),
    ("concept_status", "TEXT", False),
)

#: Property names that MUST be present and correctly typed on every object.
REQUIRED_OBJECT_FIELDS: Final[tuple[str, ...]] = (
    "content",
    "source_type",
    "source_file",
    "project_id",
    "content_hash",
    "section_heading",
)


@dataclass(frozen=True)
class StoryContextObject:
    """One indexed object bound for the StoryContext collection.

    Attributes:
        uuid: Deterministic identity (uuid5 of project_id+source_file+chunk_id).
        properties: The full property mapping (all FK-13 fields, English keys).
    """

    uuid: str
    properties: dict[str, Any]


def deterministic_uuid(project_id: str, source_file: str, chunk_id: str) -> str:
    """Deterministic object identity (uuid5) for a chunk.

    Stable across re-syncs so an upsert replaces the same object (idempotent).
    """
    key = f"{project_id}|{source_file}|{chunk_id}"
    return str(uuid.uuid5(_CHUNK_UUID_NAMESPACE, key))


def validate_object(properties: Mapping[str, Any]) -> None:
    """Validate a StoryContext object's required fields (fail-closed, AC10).

    Raises:
        ValueError: When a required field is missing or wrongly typed.
    """
    for field_name in REQUIRED_OBJECT_FIELDS:
        if field_name not in properties:
            raise ValueError(
                f"StoryContext object missing required field {field_name!r} (AC10)"
            )
    source_type = properties["source_type"]
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            f"source_type {source_type!r} not in {SOURCE_TYPES} (AC10)"
        )
    if not isinstance(properties["content"], str) or not properties["content"]:
        raise ValueError("content must be a non-empty string (AC10)")
    if not isinstance(properties["project_id"], str) or not properties["project_id"]:
        raise ValueError("project_id must be a non-empty string (AC10)")
    if not isinstance(properties["content_hash"], str) or not properties["content_hash"]:
        raise ValueError("content_hash must be a non-empty string (AC10)")


def property_names() -> tuple[str, ...]:
    """Return the ordered property-name tuple (for contract binding)."""
    return tuple(name for name, _dt, _vec in STORY_CONTEXT_PROPERTIES)


def weaviate_property_specs() -> list[dict[str, object]]:
    """Project the schema into Weaviate v4 ``Property``-style dicts.

    The schema-owner (this module) declares the property set once; the thin
    transport adapter consumes this to create the collection idempotently. Kept
    as plain dicts (not Weaviate ``Property`` objects) so the schema-owner stays
    transport-version-agnostic.
    """
    specs: list[dict[str, object]] = []
    for name, data_type, vectorized in STORY_CONTEXT_PROPERTIES:
        specs.append(
            {
                "name": name,
                "data_type": data_type,
                "vectorize_property_name": False,
                "skip_vectorization": not vectorized,
            }
        )
    return specs


def ensure_story_context_collection(client: object) -> None:
    """Create the StoryContext collection idempotently (FK-13 §13.3.1, R02).

    Args:
        client: a Weaviate v4 client exposing ``collections`` (the adapter's
            real client). The schema-owner is :mod:`schema`; this function is the
            single place the collection shape is materialised.

    Raises:
        VectorDbWriteError: if the collection cannot be created/verified.
    """
    from agentkit.integration_clients.vectordb.errors import VectorDbWriteError

    try:
        collections = client.collections  # type: ignore[attr-defined]
        if collections.exists(STORY_CONTEXT_COLLECTION):
            return
        from weaviate.classes.config import (  # noqa: PLC0415 (optional dependency)
            Configure,
            DataType,
            Property,
            Tokenization,
        )

        _type_map = {"TEXT": DataType.TEXT, "BOOL": DataType.BOOL, "TEXT[]": DataType.TEXT_ARRAY}
        properties = [
            Property(
                name=str(spec["name"]),
                data_type=_type_map[str(spec["data_type"])],
                tokenization=Tokenization.FIELD,
                skip_vectorization=bool(spec["skip_vectorization"]),
            )
            for spec in weaviate_property_specs()
        ]
        collections.create(
            name=STORY_CONTEXT_COLLECTION,
            description="FK-13 StoryContext: story + research + concept chunks (project-scoped).",
            vector_config=Configure.Vectors.self_provided(),
            properties=properties,
        )
    except Exception as exc:  # noqa: BLE001 -- normalise to a typed write error
        raise VectorDbWriteError(
            f"could not ensure StoryContext collection: {exc} (fail-closed, FK-13 §13.2)"
        ) from exc


__all__ = [
    "REQUIRED_OBJECT_FIELDS",
    "SOURCE_TYPES",
    "STORY_CONTEXT_COLLECTION",
    "STORY_CONTEXT_PROPERTIES",
    "StoryContextObject",
    "deterministic_uuid",
    "ensure_story_context_collection",
    "property_names",
    "validate_object",
    "weaviate_property_specs",
]
