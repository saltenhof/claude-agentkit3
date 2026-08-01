"""Provision the declared corpus and bookkeeping collections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.vectordb.completion_ledger import (
    RECEIPT_COLLECTION,
    RECEIPT_PROPERTIES,
    RUN_RECEIPT_COLLECTION,
    RUN_RECEIPT_PROPERTIES,
)
from agentkit.backend.vectordb.schema import STORY_CONTEXT_COLLECTION
from agentkit.backend.vectordb.source_generation import CLAIM_COLLECTION, CLAIM_PROPERTIES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.vectordb.client_port import CorpusClientPort


def ensure_corpus_collections(client: CorpusClientPort) -> None:
    """Create OR verify the three corpus collections against the schema SSOT.

    Shared by EVERY write path into ``StoryContext`` (N38): the MCP runtime and the
    story-export/split/repair sync owner bootstrap the same schema, so a collection
    can never be created without the ownership-ordering property the destructive
    delete conditions on.

    The auxiliary receipt/claim collections are ensured too and NOT suppressed -- a
    failure must surface fail-closed (N08), since completion/claim persistence is
    required for the freshness and D3 contracts.
    """
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        FK13_VECTORIZER,
        FK13_VECTORIZER_MODEL,
        weaviate_property_specs,
    )

    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=FK13_VECTORIZER,
        vectorizer_model=FK13_VECTORIZER_MODEL,
        vector_source_properties=FK13_VECTOR_SOURCE_PROPERTIES,
    )
    client.ensure_collection(
        collection=RECEIPT_COLLECTION,
        property_specs=_receipt_property_specs(),
        vectorizer="self_provided",
    )
    client.ensure_collection(
        collection=RUN_RECEIPT_COLLECTION,
        property_specs=_aux_property_specs(RUN_RECEIPT_PROPERTIES),
        vectorizer="self_provided",
    )
    client.ensure_collection(
        collection=CLAIM_COLLECTION,
        property_specs=_aux_property_specs(CLAIM_PROPERTIES),
        vectorizer="self_provided",
    )


def _aux_property_specs(names: Sequence[str]) -> list[dict[str, object]]:
    """Property specs of an auxiliary bookkeeping collection.

    Auxiliary records are pure state (receipts, claims, sequence tokens): every
    field is an exact-match identifier, so nothing is vectorised, nothing is
    BM25-searchable and everything stays whole-value tokenised.
    """
    return [
        {
            "name": name,
            "data_type": "TEXT",
            "skip_vectorization": True,
            "vectorize_property_name": False,
            "filterable": True,
            "tokenization": "FIELD",
            "searchable": False,
        }
        for name in names
    ]


def _receipt_property_specs() -> list[dict[str, object]]:
    """Property specs of the auxiliary receipt collection."""
    return _aux_property_specs(RECEIPT_PROPERTIES)


__all__ = ["ensure_corpus_collections"]
