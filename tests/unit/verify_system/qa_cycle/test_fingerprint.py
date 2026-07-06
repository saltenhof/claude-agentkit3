"""Unit tests for pushed-head QA-cycle fingerprinting (AG3-147 AC11)."""

from __future__ import annotations

import pytest

from agentkit.backend.verify_system.qa_cycle.fingerprint import (
    FingerprintComputationError,
    ReportedHeadEvidence,
    SyntheticFingerprintEvidenceSource,
    compute_evidence_fingerprint,
)

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA256_HEX_LEN = 64


def test_same_reported_heads_same_hash(tmp_path) -> None:
    heads = (ReportedHeadEvidence(repo_id="api", head_sha=_SHA_A),)

    first = compute_evidence_fingerprint(tmp_path, reported_heads=heads)
    second = compute_evidence_fingerprint(tmp_path, reported_heads=heads)

    assert first == second
    assert len(first) == _SHA256_HEX_LEN
    assert all(c in "0123456789abcdef" for c in first)


def test_changed_reported_head_changes_hash(tmp_path) -> None:
    before = compute_evidence_fingerprint(
        tmp_path, reported_heads=(ReportedHeadEvidence(repo_id="api", head_sha=_SHA_A),)
    )
    after = compute_evidence_fingerprint(
        tmp_path, reported_heads=(ReportedHeadEvidence(repo_id="api", head_sha=_SHA_B),)
    )

    assert before != after


def test_compare_paths_contribute_deterministically(tmp_path) -> None:
    without_compare = compute_evidence_fingerprint(
        tmp_path, reported_heads=(ReportedHeadEvidence(repo_id="api", head_sha=_SHA_A),)
    )
    with_compare = compute_evidence_fingerprint(
        tmp_path,
        reported_heads=(
            ReportedHeadEvidence(
                repo_id="api",
                head_sha=_SHA_A,
                compare_paths=("src/b.py", "src/a.py", "src/a.py"),
            ),
        ),
    )
    repeated = compute_evidence_fingerprint(
        tmp_path,
        reported_heads=(
            ReportedHeadEvidence(
                repo_id="api",
                head_sha=_SHA_A,
                compare_paths=("src/a.py", "src/b.py"),
            ),
        ),
    )

    assert with_compare != without_compare
    assert repeated == with_compare


def test_synthetic_source_is_deterministic_without_git(tmp_path) -> None:
    source = SyntheticFingerprintEvidenceSource()

    first = tuple(source.collect(tmp_path))
    second = tuple(source.collect(tmp_path))

    assert first == second
    assert first[0].repo_id == "unwired"
    assert len(first[0].head_sha) == 40


def test_missing_reported_heads_fails_closed(tmp_path) -> None:
    with pytest.raises(FingerprintComputationError, match="reported pushed heads"):
        compute_evidence_fingerprint(tmp_path, reported_heads=())


@pytest.mark.parametrize(
    ("repo_id", "head_sha"),
    [("", _SHA_A), ("api", ""), ("api", "not-a-sha")],
)
def test_invalid_reported_head_fails_closed(tmp_path, repo_id: str, head_sha: str) -> None:
    with pytest.raises(FingerprintComputationError, match="invalid reported pushed head"):
        compute_evidence_fingerprint(
            tmp_path,
            reported_heads=(ReportedHeadEvidence(repo_id=repo_id, head_sha=head_sha),),
        )
