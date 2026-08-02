"""The pooling strategy is DERIVED from the pinned embedding model (FK-13 §13.2).

Regression for the 2026-08-02 finding: ``poolingStrategy`` sat in the schema as a
free-standing constant with no owner in FK-13. A wrong pooling strategy raises
NOTHING — it aggregates every embedding with the wrong operation and shows up
only as worse retrieval — so nothing would ever have reported the drift.
"""

from __future__ import annotations

import pytest

from agentkit.backend.vectordb.schema import (
    FK13_EMBEDDING_MODEL,
    FK13_MODEL_POOLING_STRATEGY,
    FK13_VECTORIZER_MODEL,
    pooling_strategy_for,
)


def test_wire_pooling_strategy_is_derived_from_the_pinned_model() -> None:
    """The wire value is never written by hand; it follows the model pin."""
    assert FK13_VECTORIZER_MODEL["poolingStrategy"] == pooling_strategy_for(
        FK13_EMBEDDING_MODEL
    )


def test_vectorize_class_name_stays_false() -> None:
    """The collection name is not part of any embedding (FK-13 §13.2)."""
    assert FK13_VECTORIZER_MODEL["vectorizeClassName"] is False


@pytest.mark.parametrize(
    ("model", "strategy"),
    [
        ("sentence-transformers/all-MiniLM-L6-v2", "masked_mean"),
        ("BAAI/bge-m3", "cls"),
    ],
)
def test_each_known_model_maps_to_its_trained_strategy(model: str, strategy: str) -> None:
    """bge-m3 is a CLS-pooling model; MiniLM is a mean-pooling model.

    Pinning ``masked_mean`` for bge-m3 (the state before this change, once the
    infrastructure had moved) computes every embedding with the wrong
    aggregation — silently.
    """
    assert pooling_strategy_for(model) == strategy


def test_unknown_model_fails_closed_instead_of_guessing() -> None:
    """A guessed strategy would degrade retrieval without raising anything."""
    with pytest.raises(KeyError, match="no pooling strategy declared"):
        pooling_strategy_for("some/unlisted-model")


def test_pinned_model_is_declared_in_the_derivation_table() -> None:
    """The pin and the table cannot drift apart: the pin must be a table key."""
    assert FK13_EMBEDDING_MODEL in FK13_MODEL_POOLING_STRATEGY
