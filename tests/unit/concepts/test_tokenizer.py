"""Unit tests for the bound tokenizer asset loader (FK-13 §13.2, PO decision D5).

Covers the fail-closed contract: digest verified before parsing, no network
fetch, no char fallback, semantic-incompat rejection. Real asset, real digest
file, real tokenizers library.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.concepts import tokenizer as tok_mod
from agentkit.concepts.tokenizer import (
    PINNED_LIBRARY,
    PINNED_MODEL,
    PINNED_REVISION,
    TokenizerAssetError,
    chunk_token_count,
    load_bound_tokenizer,
)

ASSET_DIR = Path(tok_mod.__file__).resolve().parent.parent / "resources" / "tokenizer"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    load_bound_tokenizer.cache_clear()
    yield
    load_bound_tokenizer.cache_clear()


def test_bound_tokenizer_loads_and_counts_tokens() -> None:
    t = load_bound_tokenizer()
    assert t is not None
    assert chunk_token_count("chunk sizing under the bound model") > 0
    assert chunk_token_count("") == 0


def test_pinned_revision_and_library_and_model_recorded() -> None:
    # The exact pins from PO decision D5 must be recorded in code.
    assert PINNED_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
    assert PINNED_REVISION == "e4ce9877abf3edfe10b0d82785e83bdcb973e22e"
    assert PINNED_LIBRARY == "tokenizers==0.21.0"


def test_asset_files_present_on_disk() -> None:
    # Asset list per D5: tokenizer.json + vocab + digest file + license notice.
    assert (ASSET_DIR / "tokenizer.json").is_file()
    assert (ASSET_DIR / "vocab.txt").is_file()
    assert (ASSET_DIR / "tokenizer.json.sha256").is_file()
    assert (ASSET_DIR / "ASSET.md").is_file()
    assert (ASSET_DIR / "LICENSE.apache-2.0.txt").is_file()


def test_bound_digest_matches_actual_file(monkeypatch: pytest.MonkeyPatch) -> None:
    actual = tok_mod._sha256_of(ASSET_DIR / "tokenizer.json")
    bound = (ASSET_DIR / "tokenizer.json.sha256").read_text(encoding="utf-8").strip().lower()
    assert actual == bound


def test_missing_asset_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_is_file = Path.is_file

    def fake_isfile(self: Path) -> bool:
        if self == ASSET_DIR / "tokenizer.json":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_isfile)
    with pytest.raises(TokenizerAssetError, match="missing"):
        load_bound_tokenizer()


def test_divergent_digest_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tok_mod, "_sha256_of", lambda _path: "0" * 64)
    with pytest.raises(TokenizerAssetError, match="diverged"):
        load_bound_tokenizer()


def test_missing_digest_file_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_is_file = Path.is_file

    def fake_isfile(self: Path) -> bool:
        if self == ASSET_DIR / "tokenizer.json.sha256":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_isfile)
    with pytest.raises(TokenizerAssetError, match="digest file is missing"):
        load_bound_tokenizer()


def test_malformed_digest_file_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real _read_bound_digest must reject a non-hex digest file content.
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *a, **k: "not-a-hex-digest"
        if self == ASSET_DIR / "tokenizer.json.sha256"
        else Path.read_text(self, *a, **k, encoding="utf-8"),
    )
    with pytest.raises(TokenizerAssetError, match="valid SHA-256"):
        load_bound_tokenizer()


def test_semantically_incompatible_asset_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Digest OK, but the parsed model is not the MiniLM WordPiece model.
    class _FakeModel:
        pass

    class _FakeTokenizer:
        def __init__(self) -> None:
            self.model = _FakeModel()

    monkeypatch.setattr(
        "tokenizers.Tokenizer.from_file", lambda _path: _FakeTokenizer()
    )
    with pytest.raises(TokenizerAssetError, match="unexpected model kind"):
        load_bound_tokenizer()
