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

#: Term tokenisation for NARRATIVE text (BM25 must match single words).
TOKENIZATION_WORD: Final[str] = "WORD"

#: Whole-value tokenisation for identifiers/enums (exact filtering only).
TOKENIZATION_FIELD: Final[str] = "FIELD"


@dataclass(frozen=True)
class PropertySpec:
    """The COMPLETE Weaviate configuration of one StoryContext property.

    Every behavioural flag lives here (the schema is the SSOT): a narrative field
    must be tokenised into TERMS or the ``keyword`` search mode cannot match a
    single word inside it, while an identifier/enum field must stay whole-value so
    the hard project/source/status filters compare exactly.

    Attributes:
        name: Wire property name (English, ARCH-55).
        data_type: ``TEXT`` / ``BOOL`` / ``TEXT[]``.
        vectorized: Whether the value is part of the embedding (FK-13 §13.3.1
            "Vektorisiert"). ``False`` -> ``skip_vectorization``.
        tokenization: ``WORD`` for narrative text, ``FIELD`` for identifiers;
            ``""`` for non-text types (Weaviate rejects tokenisation there).
        searchable: BM25 inverted index (text types only).
        filterable: Filterable inverted index.
    """

    name: str
    data_type: str
    vectorized: bool
    tokenization: str
    searchable: bool
    filterable: bool = True

    @property
    def is_text(self) -> bool:
        """Whether the property is a text type (tokenisable + searchable)."""
        return self.data_type in ("TEXT", "TEXT[]")


def _narrative(name: str) -> PropertySpec:
    """A vectorised, word-tokenised, BM25-searchable narrative field."""
    return PropertySpec(name, "TEXT", True, TOKENIZATION_WORD, True)


def _identifier(name: str, data_type: str = "TEXT") -> PropertySpec:
    """A non-vectorised, whole-value field used for exact filtering."""
    return PropertySpec(
        name, data_type, False, TOKENIZATION_FIELD if data_type != "BOOL" else "", False
    )


def _rules(name: str) -> PropertySpec:
    """Rule text: not vectorised (§13.9.3) but word-tokenised for keyword reach."""
    return PropertySpec(name, "TEXT", False, TOKENIZATION_WORD, True)


#: The COMPLETE StoryContext property set (FK-13 §13.3.1 + §13.9.3) with its full
#: behavioural configuration. This is the contract source of truth bound by
#: ``tests/contract/.../test_storycontext_schema.py`` AND the reference the thin
#: adapter verifies an existing collection against (N12/N18).
STORY_CONTEXT_PROPERTIES: Final[tuple[PropertySpec, ...]] = (
    # --- FK-13 §13.3.1 (base) ---
    _narrative("content"),
    _identifier("story_id"),
    _narrative("title"),
    _identifier("status"),
    _identifier("story_type"),
    _identifier("module"),
    _identifier("epic"),
    _identifier("source_type"),
    _identifier("source_file"),
    _narrative("section_heading"),
    _identifier("content_hash"),
    _identifier("project_id"),
    # --- FK-13 §13.9.3 (concept extension) ---
    _identifier("concept_id"),
    _identifier("is_appendix", "BOOL"),
    _identifier("parent_concept_id"),
    _identifier("defers_to", "TEXT[]"),
    _identifier("authority_over", "TEXT[]"),
    _identifier("section_number"),
    _rules("normative_rules"),
    _identifier("concept_status"),
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
        # N19: module + epic are ADVERTISED by the story_search contract
        # (FK-13 §13.4.1 return table), so the profile must request and validate
        # them -- otherwise the envelope silently misses contract fields.
        ("module", False),
        ("epic", False),
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
        ("module", False),
        ("epic", False),
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
    return tuple(spec.name for spec in STORY_CONTEXT_PROPERTIES)


def property_spec(name: str) -> PropertySpec:
    """Return the full :class:`PropertySpec` of a schema property.

    Raises:
        ValueError: When the property is not part of the schema (fail-closed).
    """
    for spec in STORY_CONTEXT_PROPERTIES:
        if spec.name == name:
            return spec
    raise ValueError(f"{name!r} is not a StoryContext property (AC10)")


def weaviate_property_specs() -> list[dict[str, object]]:
    """Project the schema into transport-agnostic property dicts.

    The schema-owner (this module) declares the COMPLETE behaviour once; the thin
    transport adapter materialises it and verifies an existing collection against
    it (N12/N18). ``tokenization``/``searchable`` are only emitted for text types
    -- Weaviate rejects them on a boolean property.
    """
    specs: list[dict[str, object]] = []
    for spec in STORY_CONTEXT_PROPERTIES:
        entry: dict[str, object] = {
            "name": spec.name,
            "data_type": spec.data_type,
            "vectorize_property_name": False,
            "skip_vectorization": not spec.vectorized,
            "filterable": spec.filterable,
        }
        if spec.is_text:
            entry["tokenization"] = spec.tokenization
            entry["searchable"] = spec.searchable
        specs.append(entry)
    return specs


#: Vectorizer mandated by FK-13 §13.2: a SERVER-SIDE ``text2vec-transformers``
#: module with the all-MiniLM-L6-v2 sidecar (not client-supplied/precomputed
#: vectors). The three search modes (hybrid/near_text/bm25) are all server-side
#: and consistent with this configuration (N02 adjudication vs FK-13 §13.2/§13.3).
FK13_VECTORIZER: Final[str] = "text2vec_transformers"

#: The vectorizer MODEL settings FK-13 §13.2 requires, in the wire-key form the
#: client reports back (N30). ``vectorizeClassName`` must stay False (the
#: collection name is not part of any embedding) and the pooling strategy is
#: pinned, because a drifted model silently changes every vector.
FK13_VECTORIZER_MODEL: Final[dict[str, object]] = {
    "poolingStrategy": "masked_mean",
    "vectorizeClassName": False,
}


#: The properties the embedding is built FROM, in schema order (N35).
#:
#: The named-vector configuration carries a ``source_properties`` list that selects
#: which properties feed the embedding. It is as behaviour-defining as the pooling
#: strategy: a collection configured to vectorise only ``title`` produces embeddings
#: that no longer represent the chunk body, and semantic search then silently
#: answers from titles alone -- while pooling and ``vectorizeClassName`` still match.
#: The list is therefore derived from THIS SSOT (exactly the properties declared
#: ``vectorized``) and compared against the named-vector read-back.
FK13_VECTOR_SOURCE_PROPERTIES: Final[tuple[str, ...]] = tuple(
    spec.name for spec in STORY_CONTEXT_PROPERTIES if spec.vectorized
)


def property_data_type(name: str) -> str:
    """Return the declared Weaviate data type of a schema property.

    Raises:
        ValueError: When the property is not part of the schema (fail-closed).
    """
    return property_spec(name).data_type


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
    "FK13_VECTORIZER_MODEL",
    "FK13_VECTOR_SOURCE_PROPERTIES",
    "REQUIRED_OBJECT_FIELDS",
    "REQUIRED_SEARCH_PROPERTIES",
    "SOURCE_TYPES",
    "STORY_CONTEXT_COLLECTION",
    "STORY_CONTEXT_PROPERTIES",
    "TOKENIZATION_FIELD",
    "TOKENIZATION_WORD",
    "PropertySpec",
    "StoryContextObject",
    "deterministic_uuid",
    "property_data_type",
    "property_names",
    "property_spec",
    "search_property_spec",
    "validate_object",
    "weaviate_property_specs",
]
