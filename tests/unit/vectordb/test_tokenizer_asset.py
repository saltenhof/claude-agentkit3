"""Tokenizer package asset (AG3-174 AC 1 / AC 10)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.tokenizer import (
    LICENSE,
    MODEL_ID,
    RUNTIME_LIBRARY,
    TOKENIZER_REVISION,
    TokenizerAssetError,
    clear_tokenizer_cache,
    count_tokens,
    load_manifest,
    load_tokenizer,
    verify_asset_digests,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_manifest_pins_identity() -> None:
    manifest = load_manifest()
    assert manifest.model_id == MODEL_ID
    assert manifest.tokenizer_revision == TOKENIZER_REVISION
    assert manifest.runtime_library == RUNTIME_LIBRARY
    assert manifest.license == LICENSE
    assert "tokenizer.json" in manifest.assets


def test_digest_verification_passes() -> None:
    clear_tokenizer_cache()
    manifest = verify_asset_digests()
    assert manifest.assets["tokenizer.json"]


def test_tokenizer_loads_offline() -> None:
    clear_tokenizer_cache()
    tok = load_tokenizer()
    encoded = tok.encode("hello vector database")
    assert len(encoded.ids) > 0
    assert count_tokens("hello vector database") == len(encoded.ids)


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "tok"
    root.mkdir()
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (root / "vocab.txt").write_text("a\n", encoding="utf-8")
    (root / "special_tokens_map.json").write_text("{}", encoding="utf-8")
    digests = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "special_tokens_map.json",
        )
    }
    digests["tokenizer.json"] = "0" * 64  # wrong
    (root / "DIGESTS.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "tokenizer_revision": TOKENIZER_REVISION,
                "runtime_library": RUNTIME_LIBRARY,
                "license": LICENSE,
                "assets": digests,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TokenizerAssetError, match="digest mismatch"):
        verify_asset_digests(root)


def test_missing_asset_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "tok"
    root.mkdir()
    (root / "DIGESTS.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "tokenizer_revision": TOKENIZER_REVISION,
                "runtime_library": RUNTIME_LIBRARY,
                "license": LICENSE,
                "assets": {"tokenizer.json": "abc"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TokenizerAssetError):
        verify_asset_digests(root)
