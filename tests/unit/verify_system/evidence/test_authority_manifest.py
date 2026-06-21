"""Tests for evidence authority classes and bundle manifests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentkit.backend.verify_system.evidence import AuthorityClass, BundleEntry, BundleManifest


def _entry(path: str, authority: AuthorityClass, size: int = 3) -> BundleEntry:
    return BundleEntry(
        repo_id="app",
        path=Path(path),
        authority=authority,
        confidence=None,
        reason="test reason",
        size=size,
        content="x" * size,
    )


def test_authority_order_and_sort_key_prioritise_stronger_evidence() -> None:
    """Authority classes keep the FK-28 numeric order."""
    low = _entry("worker.md", AuthorityClass.WORKER_ASSERTION)
    high = _entry("story.md", AuthorityClass.PRIMARY_NORMATIVE)

    assert AuthorityClass.WORKER_ASSERTION < AuthorityClass.PRIMARY_NORMATIVE
    assert high.sort_key < low.sort_key


def test_manifest_hash_is_stable_for_same_entries_and_changes_with_entry_set() -> None:
    """Manifest hash is independent of input order and sensitive to entries."""
    epoch = "2026-06-08T12:00:00+00:00"
    first = BundleManifest.from_entries(
        [
            _entry("src/b.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=5),
            _entry("src/a.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=4),
        ],
        truncated=False,
        warnings=[],
        evidence_epoch=epoch,
    )
    second = BundleManifest.from_entries(
        [
            _entry("src/a.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=4),
            _entry("src/b.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=5),
        ],
        truncated=False,
        warnings=[],
        evidence_epoch=epoch,
    )
    changed = BundleManifest.from_entries(
        [_entry("src/a.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=4)],
        truncated=False,
        warnings=[],
        evidence_epoch=epoch,
    )

    assert first.manifest_hash == second.manifest_hash
    assert first.file_paths == ("src/a.py", "src/b.py")
    assert first.manifest_hash != changed.manifest_hash


def test_evidence_epoch_is_injectable_without_affecting_manifest_hash() -> None:
    """Different epochs leave the deterministic manifest hash unchanged."""
    entries = [_entry("src/a.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=4)]
    first = BundleManifest.from_entries(
        entries,
        truncated=False,
        warnings=[],
        evidence_epoch=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
    )
    second = BundleManifest.from_entries(
        entries,
        truncated=False,
        warnings=[],
        evidence_epoch="2026-06-08T13:00:00+00:00",
    )
    repeated = BundleManifest.from_entries(
        entries,
        truncated=False,
        warnings=[],
        evidence_epoch=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
    )

    assert first.manifest_hash == second.manifest_hash
    assert first.evidence_epoch != second.evidence_epoch
    assert first.model_dump_json() == repeated.model_dump_json()


def test_render_prompt_header_is_deterministic_and_structured() -> None:
    """The manifest owns the deterministic review prompt header text."""
    manifest = BundleManifest.from_entries(
        [
            _entry("src/app.py", AuthorityClass.PRIMARY_IMPLEMENTATION, size=4),
            _entry("story.md", AuthorityClass.PRIMARY_NORMATIVE, size=5),
        ],
        truncated=False,
        warnings=[],
        evidence_epoch="2026-06-08T12:00:00+00:00",
    )

    header = manifest.render_prompt_header()

    assert header == manifest.render_prompt_header()
    assert "PRIMARY_NORMATIVE" in header
    assert "app:story.md" in header
    assert manifest.manifest_hash in header
