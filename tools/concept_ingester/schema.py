"""Weaviate collection schema for the concept corpus.

Two collections:
- Ak3ConceptChunk: H2-section level chunks of every concept doc.
- Ak3GlossaryTerm: one entry per exported/internal glossary term.

Schema-projection version is materialised in every chunk; bumping it
forces a clean drop+rebuild via IngestStrategy.FULL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weaviate.classes.config import Configure, DataType, Property, Tokenization

if TYPE_CHECKING:
    from weaviate import WeaviateClient

CHUNK_COLLECTION_NAME = "Ak3ConceptChunk"
GLOSSARY_COLLECTION_NAME = "Ak3GlossaryTerm"

# Backwards-compatible alias used elsewhere in the package.
COLLECTION_NAME = CHUNK_COLLECTION_NAME

# Bump on every schema change; written into every chunk as
# `schema_projection_version` so drift is detectable at query time.
SCHEMA_PROJECTION_VERSION = "v2-2026-04-29"


def ensure_collection(client: WeaviateClient, name: str = CHUNK_COLLECTION_NAME) -> None:
    """Create the chunk collection if it does not exist yet."""
    if client.collections.exists(name):
        return
    client.collections.create(
        name=name,
        description=(
            "Chunks of the AgentKit 3 concept corpus. Layer is filterable; "
            "unfiltered queries rank across all layers. Frontmatter fields "
            "from the bounded-context refactor are top-level for filtering."
        ),
        vector_config=Configure.Vectors.text2vec_transformers(
            pooling_strategy="masked_mean",
            vectorize_collection_name=False,
        ),
        properties=_chunk_properties(),
    )


def ensure_glossary_collection(
    client: WeaviateClient,
    name: str = GLOSSARY_COLLECTION_NAME,
) -> None:
    """Create the glossary collection if it does not exist yet."""
    if client.collections.exists(name):
        return
    client.collections.create(
        name=name,
        description=(
            "Glossary terms exported by contract docs of a bounded context. "
            "term + definition is vectorised so semantic search lands directly "
            "on the canonical definition rather than on a body chunk."
        ),
        vector_config=Configure.Vectors.text2vec_transformers(
            pooling_strategy="masked_mean",
            vectorize_collection_name=False,
        ),
        properties=_glossary_properties(),
    )


def ensure_all_collections(client: WeaviateClient) -> None:
    """Create both collections if they do not exist yet."""
    ensure_collection(client, CHUNK_COLLECTION_NAME)
    ensure_glossary_collection(client, GLOSSARY_COLLECTION_NAME)


def drop_collection(client: WeaviateClient, name: str = CHUNK_COLLECTION_NAME) -> bool:
    """Delete the named collection. Returns True if it existed."""
    if not client.collections.exists(name):
        return False
    client.collections.delete(name)
    return True


def drop_all_collections(client: WeaviateClient) -> dict[str, bool]:
    """Delete both collections. Returns existence flags before drop."""
    existed = {
        CHUNK_COLLECTION_NAME: drop_collection(client, CHUNK_COLLECTION_NAME),
        GLOSSARY_COLLECTION_NAME: drop_collection(client, GLOSSARY_COLLECTION_NAME),
    }
    return existed


def _chunk_properties() -> list[Property]:
    return [
        # --- Identity / structural ---
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
            description="SHA-256 of content + structural frontmatter; used for delta detection.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="file_mtime",
            data_type=DataType.DATE,
            description="Last modification time of the source file (UTC).",
            skip_vectorization=True,
        ),
        # --- Bounded-context filters ---
        Property(
            name="domain",
            data_type=DataType.TEXT,
            description="Bounded-context id from frontmatter `domain`. Empty for cross-cutting docs.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="cross_cutting",
            data_type=DataType.BOOL,
            description="True for foundation/adapter/reference docs that have no BC owner.",
            skip_vectorization=True,
        ),
        Property(
            name="surface",
            data_type=DataType.TEXT,
            description=(
                "Computed at ingest from the domain-registry: 'contract' if listed under "
                "contract_docs, 'internal' if listed under member_docs, '' for cross-cutting."
            ),
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="domain_display_name",
            data_type=DataType.TEXT,
            description="Human-readable BC name; from domain-registry. Display only.",
            skip_vectorization=True,
        ),
        Property(
            name="contract_state",
            data_type=DataType.TEXT,
            description="active | compatible | deprecating | breaking. Empty if not declared.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="applies_policies",
            data_type=DataType.TEXT_ARRAY,
            description="Policy ids referenced by `applies_policies`. Filterable.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        # --- Reference graph (filterable IDs) ---
        Property(
            name="defers_to_ids",
            data_type=DataType.TEXT_ARRAY,
            description="Concept ids of `defers_to` targets, normalised across string/dict forms.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="defers_to_edges",
            data_type=DataType.TEXT_ARRAY,
            description=(
                "Composite '<target>|<scope>' edges for scope-precise filtering "
                "(e.g. 'FK-20|runtime-profile'). Empty scope yields '<target>|'."
            ),
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="formal_ref_ids",
            data_type=DataType.TEXT_ARRAY,
            description="Formal-spec ids referenced via `formal_refs`. Filterable.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="supersedes_ids",
            data_type=DataType.TEXT_ARRAY,
            description="Concept ids in `supersedes`.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="superseded_by_id",
            data_type=DataType.TEXT,
            description="Concept id in `superseded_by`, '' if none.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="authority_scopes",
            data_type=DataType.TEXT_ARRAY,
            description="Scopes from `authority_over`.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        # --- Glossary linkage ---
        Property(
            name="has_glossary",
            data_type=DataType.BOOL,
            description="True if the source doc carries a glossary block.",
            skip_vectorization=True,
        ),
        Property(
            name="exported_term_ids",
            data_type=DataType.TEXT_ARRAY,
            description="Term ids exported by the source doc's glossary.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        # --- Migration / drift tracking ---
        Property(
            name="schema_projection_version",
            data_type=DataType.TEXT,
            description="Version of the chunk schema this object was written against.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="domain_registry_hash",
            data_type=DataType.TEXT,
            description="SHA-256 over the domain-registry at ingest time. Drift indicator.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        # --- Non-query payload ---
        Property(
            name="metadata",
            data_type=DataType.OBJECT,
            description=(
                "Frontmatter fields not needed as filters: doc_kind, status, spec_kind, "
                "context, version, parent_concept_id, formal_scope, prose_anchor_policy, "
                "migration_ack, plus full defers_to and supersedes structure."
            ),
            skip_vectorization=True,
            nested_properties=[
                Property(name="doc_kind", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="status", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="spec_kind", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="context", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="version", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="parent_concept_id", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="formal_scope", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="prose_anchor_policy", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="migration_ack", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="defers_to_full", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="supersedes_full", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                Property(name="authority_over_full", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
            ],
        ),
    ]


def _glossary_properties() -> list[Property]:
    return [
        Property(
            name="term_id",
            data_type=DataType.TEXT,
            description="Stable id of the term within its source document (slugified).",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="term",
            data_type=DataType.TEXT,
            description="Original term as written in the glossary; vectorised together with definition.",
        ),
        Property(
            name="normalized_term",
            data_type=DataType.TEXT,
            description="Lower-cased term for exact lookup.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="definition",
            data_type=DataType.TEXT,
            description="Definition text; vectorised together with the term.",
        ),
        Property(
            name="term_kind",
            data_type=DataType.TEXT,
            description="exported | internal.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="domain",
            data_type=DataType.TEXT,
            description="Bounded-context id of the source doc.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="domain_display_name",
            data_type=DataType.TEXT,
            description="Human-readable BC name; display only.",
            skip_vectorization=True,
        ),
        Property(
            name="source_doc_id",
            data_type=DataType.TEXT,
            description="Concept id of the doc this term lives in (always a contract doc).",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="source_section_anchor",
            data_type=DataType.TEXT,
            description="Section anchor inside source_doc_id (Glossar block, if a section anchor exists).",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="see_also_terms",
            data_type=DataType.TEXT_ARRAY,
            description="Composite '<domain>|<term_id>' references from `see_also`.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="contract_state",
            data_type=DataType.TEXT,
            description="Inherited contract_state of the source doc.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="values",
            data_type=DataType.TEXT_ARRAY,
            description="Optional enum values from the glossary entry.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="reason",
            data_type=DataType.TEXT,
            description="For internal terms: reason why the term is not exported.",
            skip_vectorization=True,
        ),
        Property(
            name="content_hash",
            data_type=DataType.TEXT,
            description="SHA-256 of (term, definition, kind, source). Delta detection.",
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
            name="schema_projection_version",
            data_type=DataType.TEXT,
            description="Version of the glossary schema this object was written against.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
        Property(
            name="domain_registry_hash",
            data_type=DataType.TEXT,
            description="SHA-256 over the domain-registry at ingest time. Drift indicator.",
            tokenization=Tokenization.FIELD,
            skip_vectorization=True,
        ),
    ]
