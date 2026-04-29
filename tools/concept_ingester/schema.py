"""Weaviate collection schema for the concept corpus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from weaviate.classes.config import Configure, DataType, Property, Tokenization

if TYPE_CHECKING:
    from weaviate import WeaviateClient

COLLECTION_NAME = "Ak3ConceptChunk"


def ensure_collection(client: WeaviateClient, name: str = COLLECTION_NAME) -> None:
    """Create the collection if it does not exist yet."""
    if client.collections.exists(name):
        return
    client.collections.create(
        name=name,
        description=(
            "Chunks of the AgentKit 3 concept corpus. "
            "Layer is filterable but unfiltered queries rank across all layers."
        ),
        vector_config=Configure.Vectors.text2vec_transformers(
            pooling_strategy="masked_mean",
            vectorize_collection_name=False,
        ),
        properties=[
            Property(
                name="layer",
                data_type=DataType.TEXT,
                description="Concept layer: domain | formal | technical.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="doc_id",
                data_type=DataType.TEXT,
                description="Concept ID from frontmatter (DK-/FK-/formal.*) or rel_path.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="title",
                data_type=DataType.TEXT,
                description="Document title from frontmatter.",
            ),
            Property(
                name="module",
                data_type=DataType.TEXT,
                description="Module / context label from frontmatter.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="tags",
                data_type=DataType.TEXT_ARRAY,
                description="Frontmatter tag list.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="rel_path",
                data_type=DataType.TEXT,
                description="Path relative to concept/.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="section_anchor",
                data_type=DataType.TEXT,
                description="Stable anchor of the section within the document.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="heading",
                data_type=DataType.TEXT,
                description="Heading of the section ('(intro)' or '(document)' for special chunks).",
            ),
            Property(
                name="ordering",
                data_type=DataType.INT,
                description="Position of the chunk within its document.",
                skip_vectorization=True,
            ),
            Property(
                name="content",
                data_type=DataType.TEXT,
                description="Section body that gets vectorized.",
            ),
            Property(
                name="content_hash",
                data_type=DataType.TEXT,
                description="SHA-256 of content; used for delta detection.",
                tokenization=Tokenization.FIELD,
                skip_vectorization=True,
            ),
            Property(
                name="file_mtime",
                data_type=DataType.DATE,
                description="Last modification time of the source file (UTC).",
                skip_vectorization=True,
            ),
            Property(
                name="extra",
                data_type=DataType.OBJECT,
                description="Optional frontmatter attributes (doc_kind, status, version, ...).",
                skip_vectorization=True,
                nested_properties=[
                    Property(name="doc_kind", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="status", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="spec_kind", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="context", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="version", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="parent_concept_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="formal_scope", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                ],
            ),
        ],
    )


def drop_collection(client: WeaviateClient, name: str = COLLECTION_NAME) -> bool:
    """Delete the collection. Returns True if it existed."""
    if not client.collections.exists(name):
        return False
    client.collections.delete(name)
    return True
