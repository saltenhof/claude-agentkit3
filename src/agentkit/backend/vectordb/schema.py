"""StoryContext Weaviate collection schema (FK-13 §13.3.1 + §13.9.3).

One collection for story, research and concept chunks. Idempotent ensure.
Production clients without provable introspection are rejected (R14).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

STORY_COLLECTION: Final[str] = "StoryContext"
SCHEMA_OWNER: Final[str] = "agentkit.backend.vectordb.schema.ensure_story_context_schema"
EXPECTED_VECTORIZER: Final[str] = "text2vec-transformers"


@dataclass(frozen=True)
class SchemaProperty:
    """One Weaviate property definition (transport-agnostic)."""

    name: str
    data_type: str  # text | text[] | bool | int | number
    vectorize: bool
    description: str
    tokenization: str | None = None  # field | word | None


#: Full FK-13 property inventory (contract-tested).
STORY_CONTEXT_PROPERTIES: Final[tuple[SchemaProperty, ...]] = (
    # §13.3.1
    SchemaProperty("content", "text", True, "Chunk text (searchable content)"),
    SchemaProperty("story_id", "text", False, "Story identifier", "field"),
    SchemaProperty("title", "text", True, "Story or document title"),
    SchemaProperty("status", "text", False, "Story status", "field"),
    SchemaProperty("story_type", "text", False, "Story type", "field"),
    SchemaProperty("module", "text", False, "Affected module", "field"),
    SchemaProperty("epic", "text", False, "Epic", "field"),
    SchemaProperty("source_type", "text", False, "story | concept | research", "field"),
    SchemaProperty("source_file", "text", False, "Source file path", "field"),
    SchemaProperty("section_heading", "text", True, "Section heading"),
    SchemaProperty("content_hash", "text", False, "SHA-256 of chunk text", "field"),
    SchemaProperty("project_id", "text", False, "Project discriminator", "field"),
    # §13.9.3 concept extensions
    SchemaProperty("concept_id", "text", False, "Canonical concept identifier", "field"),
    SchemaProperty("is_appendix", "bool", False, "Appendix vs core document"),
    SchemaProperty("parent_concept_id", "text", False, "Appendix parent concept", "field"),
    SchemaProperty("defers_to", "text[]", False, "Flat deferral target ids", "field"),
    SchemaProperty("authority_over", "text[]", False, "Authority scopes", "field"),
    SchemaProperty("section_number", "text", False, "Section number", "field"),
    SchemaProperty("normative_rules", "text", False, "Extracted normative rules", "field"),
    SchemaProperty("concept_status", "text", False, "active | draft | archived", "field"),
    # Operational fields for bounded-window / producer closure
    SchemaProperty("chunk_uuid", "text", False, "Deterministic chunk UUID string", "field"),
    SchemaProperty("producer_tool", "text", False, "Owning producer tool name", "field"),
    SchemaProperty("generation_id", "text", False, "Sync generation identifier", "field"),
    SchemaProperty("corpus_revision", "text", False, "Corpus revision at write time", "field"),
)


def property_names() -> tuple[str, ...]:
    """Return ordered property names for contract tests."""
    return tuple(p.name for p in STORY_CONTEXT_PROPERTIES)


class SchemaDriftError(Exception):
    """Raised when an existing StoryContext schema drifts from the contract (R14)."""


def ensure_story_context_schema(client: object) -> bool:
    """Idempotently create the ``StoryContext`` collection.

    When the collection already exists, its properties are verified against
    the FK-13 contract. Drift is a hard error (R14) — no silent accept.

    Returns:
        ``True`` if the collection was created, ``False`` if it already existed
        and matched the contract.
    """
    collections = getattr(client, "collections", None)
    if collections is None:
        raise TypeError("client must expose a collections API")
    exists = collections.exists
    if callable(exists) and bool(exists(STORY_COLLECTION)):
        _verify_existing_schema(client, STORY_COLLECTION)
        return False
    _create_collection(client, STORY_COLLECTION, STORY_CONTEXT_PROPERTIES)
    return True


def _verify_existing_schema(client: object, name: str) -> None:
    """Fail-closed full-form verification for an existing collection (R14)."""
    cfg = _load_collection_config(client, name)
    present_by_name = _index_properties(cfg, name)
    required = {p.name: p for p in STORY_CONTEXT_PROPERTIES}
    missing = set(required) - set(present_by_name)
    if missing:
        raise SchemaDriftError(
            f"StoryContext schema missing properties {sorted(missing)} "
            "(fail-closed, R14)."
        )
    for exp_name, exp in required.items():
        _assert_property_matches(exp_name, exp, present_by_name[exp_name])
    _assert_vectorizer(cfg)


def _load_collection_config(client: object, name: str) -> object:
    collections = client.collections  # type: ignore[attr-defined]
    get = getattr(collections, "get", None)
    if not callable(get):
        raise SchemaDriftError(
            f"production client cannot introspect collection {name} "
            "(no collections.get); fail-closed (R14)."
        )
    try:
        coll = get(name)
    except Exception as exc:  # noqa: BLE001
        raise SchemaDriftError(f"cannot load collection {name}: {exc}") from exc
    config = getattr(coll, "config", None)
    get_config = getattr(config, "get", None) if config is not None else None
    if not callable(get_config):
        raise SchemaDriftError(
            f"production client cannot read config for {name} "
            "(no config.get); fail-closed (R14)."
        )
    try:
        return get_config()
    except Exception as exc:  # noqa: BLE001
        raise SchemaDriftError(f"cannot read schema for {name}: {exc}") from exc


def _index_properties(cfg: object, name: str) -> dict[str, object]:
    props = getattr(cfg, "properties", None)
    if props is None:
        raise SchemaDriftError(
            f"schema for {name} has no properties list; fail-closed (R14)."
        )
    present_by_name: dict[str, object] = {}
    for p in props:
        pname = getattr(p, "name", None)
        if not isinstance(pname, str) or not pname:
            raise SchemaDriftError(
                f"schema property without name in {name}; fail-closed (R14)."
            )
        present_by_name[pname] = p
    return present_by_name


def _assert_property_matches(exp_name: str, exp: SchemaProperty, actual: object) -> None:
    actual_type = _normalize_data_type(
        getattr(actual, "data_type", None)
        or getattr(actual, "dataType", None)
        or getattr(actual, "dtype", None)
    )
    if not actual_type:
        raise SchemaDriftError(
            f"property {exp_name!r} data_type not introspectable; fail-closed (R14)."
        )
    if actual_type != exp.data_type:
        raise SchemaDriftError(
            f"property {exp_name!r} data_type drift: got {actual_type!r}, "
            f"expected {exp.data_type!r} (R14)."
        )
    # Vectorize / skip_vectorization is MANDATORY proof (R14) — absence is drift.
    actual_skip = getattr(actual, "skip_vectorization", None)
    if actual_skip is None:
        actual_skip = getattr(actual, "skipVectorization", None)
    if actual_skip is None:
        raise SchemaDriftError(
            f"property {exp_name!r} skip_vectorization not introspectable; "
            "fail-closed (R14)."
        )
    if type(actual_skip) is not bool:
        raise SchemaDriftError(
            f"property {exp_name!r} skip_vectorization must be bool, "
            f"got {type(actual_skip).__name__}={actual_skip!r} (R14)."
        )
    expected_skip = not exp.vectorize
    if bool(actual_skip) != expected_skip:
        raise SchemaDriftError(
            f"property {exp_name!r} vectorize drift: skip_vectorization="
            f"{actual_skip!r}, expected {expected_skip!r} (R14)."
        )
    # Tokenization mandatory when the contract specifies it (non-vectorized text).
    if exp.tokenization is not None:
        tok = getattr(actual, "tokenization", None)
        if tok is None:
            raise SchemaDriftError(
                f"property {exp_name!r} tokenization not introspectable; "
                "fail-closed (R14)."
            )
        tok_s = str(tok).lower().split(".")[-1]
        if tok_s != exp.tokenization:
            raise SchemaDriftError(
                f"property {exp_name!r} tokenization drift: got {tok_s!r}, "
                f"expected {exp.tokenization!r} (R14)."
            )


def _assert_vectorizer(cfg: object) -> None:
    """Require introspectable vectorizer/vector_config matching create (R14)."""
    vectorizer = (
        getattr(cfg, "vectorizer", None)
        or getattr(cfg, "vectorizer_config", None)
        or getattr(cfg, "vectorConfig", None)
        or getattr(cfg, "vector_config", None)
    )
    if vectorizer is None:
        raise SchemaDriftError(
            "vectorizer/vector_config not introspectable; fail-closed (R14)."
        )
    vec_name = _extract_vectorizer_name(vectorizer)
    if vec_name is None:
        raise SchemaDriftError(
            f"vectorizer name not extractable from {vectorizer!r}; fail-closed (R14)."
        )
    normalized = vec_name.lower().replace("_", "-")
    if EXPECTED_VECTORIZER not in normalized:
        raise SchemaDriftError(
            f"vectorizer drift: got {vec_name!r}, expected "
            f"{EXPECTED_VECTORIZER!r} (R14)."
        )


def _normalize_data_type(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        # Weaviate classic: ["text"] / ["text[]"] style.
        if len(raw) == 1:
            return _normalize_data_type(raw[0])
        return str(raw)
    text = str(raw)
    # Enum-like: DataType.TEXT / TEXT_ARRAY
    leaf = text.split(".")[-1].lower().replace("-", "_")
    mapping = {
        "text": "text",
        "text_array": "text[]",
        "text[]": "text[]",
        "bool": "bool",
        "boolean": "bool",
        "int": "int",
        "integer": "int",
        "number": "number",
        "number_array": "number[]",
    }
    return mapping.get(leaf, leaf)


def _extract_vectorizer_name(vectorizer: object) -> str | None:
    if isinstance(vectorizer, str):
        return vectorizer
    name = getattr(vectorizer, "vectorizer", None) or getattr(
        vectorizer, "name", None
    )
    if isinstance(name, str):
        return name
    # Weaviate v4 vector_config may be a map of named vectors.
    if isinstance(vectorizer, dict):
        for key in ("vectorizer", "name", "type"):
            val = vectorizer.get(key)
            if isinstance(val, str):
                return val
        # Nested: {"default": {"vectorizer": {"text2vec-transformers": ...}}}
        for val in vectorizer.values():
            nested = _extract_vectorizer_name(val)
            if nested is not None:
                return nested
    # Object with .vectorizer attribute already handled; try str last only for
    # enum-like values that contain the expected token.
    text = str(vectorizer)
    if EXPECTED_VECTORIZER in text.lower().replace("_", "-"):
        return EXPECTED_VECTORIZER
    return None


def _create_collection(
    client: object,
    name: str,
    properties: Sequence[SchemaProperty],
) -> None:
    """Create collection via weaviate-client when available, else duck-typed.

    No silent TypeError fallback that drops the canonical vectorizer (R14).
    Duck-typed test clients must accept ``vector_config`` or only expose
    ``properties`` without weaviate classes installed.
    """
    collections = client.collections  # type: ignore[attr-defined]
    prop_payload = [
        {
            "name": p.name,
            "data_type": p.data_type,
            "vectorize": p.vectorize,
            "tokenization": p.tokenization,
        }
        for p in properties
    ]
    try:
        from weaviate.classes.config import Configure, DataType, Property, Tokenization
    except ImportError:
        collections.create(
            name=name,
            properties=prop_payload,
            vector_config={"vectorizer": EXPECTED_VECTORIZER},
        )
        return

    type_map = {
        "text": DataType.TEXT,
        "text[]": DataType.TEXT_ARRAY,
        "bool": DataType.BOOL,
        "int": DataType.INT,
        "number": DataType.NUMBER,
    }
    props: list[Property] = []
    for prop in properties:
        kwargs: dict[str, object] = {
            "name": prop.name,
            "data_type": type_map[prop.data_type],
            "description": prop.description,
            "skip_vectorization": not prop.vectorize,
        }
        if prop.data_type in ("text", "text[]") and not prop.vectorize:
            kwargs["tokenization"] = Tokenization.FIELD
        props.append(Property(**kwargs))  # type: ignore[arg-type]
    collections.create(
        name=name,
        description="AgentKit StoryContext knowledge base (FK-13 §13.3 / §13.9).",
        vector_config=Configure.Vectors.text2vec_transformers(
            pooling_strategy="masked_mean",
            vectorize_collection_name=False,
        ),
        properties=props,
    )


__all__ = [
    "EXPECTED_VECTORIZER",
    "SCHEMA_OWNER",
    "STORY_COLLECTION",
    "STORY_CONTEXT_PROPERTIES",
    "SchemaDriftError",
    "SchemaProperty",
    "ensure_story_context_schema",
    "property_names",
]
