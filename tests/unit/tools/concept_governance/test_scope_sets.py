"""AC1/AC3 deterministic closed-set and stable-partition proofs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import load_chunks
from concept_governance.scope_sets import build_scope_sets, partition_scope_sets
from concept_governance.vocabulary import load_scope_vocabulary
from tests.unit.tools.concept_governance.helpers import write_doc

if TYPE_CHECKING:
    from pathlib import Path


def test_scope_set_inversion_is_exact_closed_and_stable(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "lock-owner.md", "LOCK", "[{scope: lock.lifecycle}]")
    write_doc(
        concept,
        "lock-consumer.md",
        "LOCK-CONSUMER",
        defers_to="[{target: LOCK, scope: lock.lifecycle, reason: delegated}]",
    )
    write_doc(concept, "queue-owner.md", "QUEUE", "[{scope: queue.lifecycle}]")
    chunks = load_chunks(concept)
    vocabulary = load_scope_vocabulary(concept)

    first = build_scope_sets(chunks, vocabulary)
    second = build_scope_sets(load_chunks(concept), load_scope_vocabulary(concept))

    assert first == second
    by_scope = {item.scope: {chunk.doc for chunk in item.assertions} for item in first}
    assert by_scope == {
        "lock.lifecycle": {
            "domain-design/lock-consumer.md",
            "domain-design/lock-owner.md",
        },
        "queue.lifecycle": {"domain-design/queue-owner.md"},
    }
    assert partition_scope_sets(first, max_chunks=1) == partition_scope_sets(second, max_chunks=1)


def test_large_scope_set_is_partitioned_without_truncation(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    for index in range(5):
        write_doc(concept, f"owner-{index}.md", f"OWNER-{index}", "[{scope: lock.lifecycle}]")
    scope_sets = build_scope_sets(load_chunks(concept), load_scope_vocabulary(concept))

    partitions = partition_scope_sets(scope_sets, max_chunks=2, max_chars=100_000)

    assert [len(item.assertions) for item in partitions] == [2, 2, 1]
    all_ids = [chunk.chunk_id for partition in partitions for chunk in partition.assertions]
    assert all_ids == [chunk.chunk_id for chunk in scope_sets[0].assertions]
    assert [(item.index, item.count) for item in partitions] == [(1, 3), (2, 3), (3, 3)]
