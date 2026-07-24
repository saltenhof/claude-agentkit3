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


#: Per-source-type retrieval profile: which properties a HIT must carry.
#: Only fields the owning producer actually writes are listed -- FK-13 §13.9.3
#: keeps the concept properties unset for ``story``/``research`` objects, so
#: requiring them there would be wrong. ``True`` = additionally non-empty.
REQUIRED_SEARCH_PROPERTIES: Final[dict[str, tuple[tuple[str, bool], ...]]] = {
    "story": (
        ("content", True),
        ("story_id", False),
        ("title", True),
        ("status", False),
        ("story_type", False),
        ("source_type", True),
        ("source_file", True),
        ("section_heading", False),
        ("section_number", False),
        ("content_hash", True),
        ("project_id", True),
    ),
    "research": (
        ("content", True),
        ("story_id", False),
        ("title", True),
        ("status", False),
        ("story_type", False),
        ("source_type", True),
        ("source_file", True),
        ("section_heading", False),
        ("section_number", False),
        ("content_hash", True),
        ("project_id", True),
    ),
    "concept": (
        ("content", True),
        ("title", True),
        ("module", False),
        ("source_type", True),
        ("source_file", True),
        ("section_heading", False),
        ("section_number", False),
        ("content_hash", True),
        ("project_id", True),
        ("concept_id", True),
        ("is_appendix", False),
        ("parent_concept_id", False),
        ("defers_to", False),
        ("authority_over", False),
        ("normative_rules", False),
        ("concept_status", True),
    ),
}


@dataclass(frozen=True)
class StoryContextObject:
    """One indexed object bound for the StoryContext collection.

    Attributes:
        uuid: Deterministic identity (uuid5 of project_id+source_file+chunk_id).
        chunk_id: The chunk identity the uuid is derived FROM. Carried explicitly
            so a consumer can re-derive and VERIFY the object identity before any
            write (N13) instead of trusting an opaque uuid.
        properties: The full property mapping (all FK-13 fields, English keys).
    """

    uuid: str
    chunk_id: str
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


#: Vectorizer mandated by FK-13 §13.2: a SERVER-SIDE ``text2vec-transformers``
#: module with the all-MiniLM-L6-v2 sidecar (not client-supplied/precomputed
#: vectors). The three search modes (hybrid/near_text/bm25) are all server-side
#: and consistent with this configuration (N02 adjudication vs FK-13 §13.2/§13.3).
FK13_VECTORIZER: Final[str] = "text2vec_transformers"


def property_data_type(name: str) -> str:
    """Return the declared Weaviate data type of a schema property.

    Raises:
        ValueError: When the property is not part of the schema (fail-closed).
    """
    for prop_name, data_type, _vec in STORY_CONTEXT_PROPERTIES:
        if prop_name == name:
            return data_type
    raise ValueError(f"{name!r} is not a StoryContext property (AC10)")


def search_property_spec(source_type: str) -> tuple[tuple[str, str, bool], ...]:
    """Return the retrieval profile of a source_type as the transport spec.

    The tuples are ``(property_name, data_type, non_empty)``; the thin transport
    adapter validates every returned hit against them and raises on a missing or
    wrongly-typed field (N11 -- no ``setdefault`` repair default).

    Raises:
        ValueError: For an unknown source_type (fail-closed).
    """
    if source_type not in REQUIRED_SEARCH_PROPERTIES:
        raise ValueError(f"unknown source_type {source_type!r} (AC10)")
    return tuple(
        (name, property_data_type(name), non_empty)
        for name, non_empty in REQUIRED_SEARCH_PROPERTIES[source_type]
    )


__all__ = [
    "FK13_VECTORIZER",
    "REQUIRED_OBJECT_FIELDS",
    "REQUIRED_SEARCH_PROPERTIES",
    "SOURCE_TYPES",
    "STORY_CONTEXT_COLLECTION",
    "STORY_CONTEXT_PROPERTIES",
    "StoryContextObject",
    "deterministic_uuid",
    "property_data_type",
    "property_names",
    "search_property_spec",
    "validate_object",
    "weaviate_property_specs",
]
