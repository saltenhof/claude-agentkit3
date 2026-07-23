"""Bound tokenizer asset loader (FK-13 §13.2, PO decision D5).

The FK-13 retrieval engine sizes chunks by tokens of the embedding model
``sentence-transformers/all-MiniLM-L6-v2``. The tokenizer is shipped as a
**versioned, immutable package asset** with a bound SHA-256 digest and a pinned
revision. Before the asset is parsed, its digest is verified against the bound
value. Any deviation -- missing asset, divergent digest, or a structurally /
semantically incompatible asset -- is a hard ERROR. There is **no** runtime
network fetch and **no** character-based fallback (DR 2026-07-21 Rand 3 /
FK-13 §13.2).

The asset is loaded once and cached for the lifetime of the process; discovery
is the deterministic W2 source and never reaches the network.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from tokenizers import Tokenizer

#: Directory holding the bound package asset (this file's sibling).
_ASSET_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "resources" / "tokenizer"

#: Primary asset (the fast tokenizer the loader parses).
_TOKENIZER_JSON: Final[Path] = _ASSET_DIR / "tokenizer.json"

#: Bound SHA-256 digest file shipped next to the asset.
_TOKENIZER_DIGEST: Final[Path] = _ASSET_DIR / "tokenizer.json.sha256"

#: Pinned HuggingFace revision the asset was fetched from (PO decision D5).
PINNED_REVISION: Final[str] = "e4ce9877abf3edfe10b0d82785e83bdcb973e22e"

#: Pinned model / tokenizer identifier (PO decision D5).
PINNED_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"

#: Runtime library pin (declared in ``pyproject.toml``).
PINNED_LIBRARY: Final[str] = "tokenizers==0.21.0"

#: Acceptable tokenizer model declared inside the asset (semantic check).
#: all-MiniLM-L6-v2 is a BERT WordPiece model; a structurally valid but
#: semantically different asset (e.g. a BPE/SentencePiece model) is rejected.
_REQUIRED_TOKENIZER_MODEL: Final[str] = "WordPiece"

#: Required trailing-vocabulary marker for the MiniLM WordPiece tokenizer.
_REQUIRED_UNK_TOKEN: Final[str] = "[UNK]"


class TokenizerAssetError(RuntimeError):
    """Raised when the bound tokenizer asset cannot be used fail-closed.

    Covers a missing asset / digest file, a divergent digest, and a structurally
    or semantically incompatible asset. The consuming flow MUST treat this as a
    hard blocker -- never fall back to a character-based or network substitute
    (FK-13 §13.2).
    """


def _read_bound_digest() -> str:
    """Return the bound SHA-256 digest from the shipped digest file."""
    if not _TOKENIZER_DIGEST.is_file():
        raise TokenizerAssetError(
            f"Bound digest file is missing: {_TOKENIZER_DIGEST} "
            "(FK-13 §13.2: tokenizer asset is mandatory, fail-closed)."
        )
    raw = _TOKENIZER_DIGEST.read_text(encoding="utf-8").strip()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw.lower()):
        raise TokenizerAssetError(
            f"Bound digest file {_TOKENIZER_DIGEST} does not contain a valid "
            f"SHA-256 hex digest (got {raw!r}); fail-closed (FK-13 §13.2)."
        )
    return raw.lower()


def _sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_semantics(tokenizer: Tokenizer) -> None:
    """Reject a structurally valid but semantically incompatible asset.

    A WordPiece BERT model is required (all-MiniLM-L6-v2). A different tokenizer
    kind (BPE, Unigram, ...) would silently change chunk boundaries even with a
    matching digest, so it is rejected explicitly.
    """
    model = tokenizer.model
    model_kind = type(model).__name__
    if model_kind != _REQUIRED_TOKENIZER_MODEL:
        raise TokenizerAssetError(
            f"Bound tokenizer asset has an unexpected model kind {model_kind!r}; "
            f"expected {_REQUIRED_TOKENIZER_MODEL!r} for {PINNED_MODEL} "
            "(FK-13 §13.2: no silent semantic fallback)."
        )
    # WordPiece vocab must carry the standard [UNK] special token.
    token_to_id = getattr(model, "token_to_id", None)
    unk_token = getattr(model, "unk_token", None)
    if not callable(token_to_id) or unk_token != _REQUIRED_UNK_TOKEN:
        raise TokenizerAssetError(
            f"Bound tokenizer asset is not the MiniLM WordPiece model "
            f"(unk_token={unk_token!r}); fail-closed (FK-13 §13.2)."
        )
    if token_to_id(_REQUIRED_UNK_TOKEN) is None:
        raise TokenizerAssetError(
            f"Bound tokenizer asset is missing the {_REQUIRED_UNK_TOKEN!r} "
            "special token; it is not the MiniLM WordPiece model "
            "(FK-13 §13.2: no silent semantic fallback)."
        )


@lru_cache(maxsize=1)
def load_bound_tokenizer() -> Tokenizer:
    """Load and return the bound tokenizer asset, fail-closed (FK-13 §13.2).

    Verifies the SHA-256 digest of ``tokenizer.json`` against the shipped
    digest **before** parsing, then confirms the asset is semantically the
    MiniLM WordPiece model. Cached per process.

    Returns:
        The loaded, verified :class:`tokenizers.Tokenizer`.

    Raises:
        TokenizerAssetError: If the asset or digest is missing/divergent, or the
            asset is semantically incompatible. No network / char fallback.
    """
    if not _TOKENIZER_JSON.is_file():
        raise TokenizerAssetError(
            f"Bound tokenizer asset is missing: {_TOKENIZER_JSON} "
            "(FK-13 §13.2: no runtime network fetch, no char fallback)."
        )
    actual = _sha256_of(_TOKENIZER_JSON)
    expected = _read_bound_digest()
    if actual != expected:
        raise TokenizerAssetError(
            f"Bound tokenizer asset digest diverged: expected {expected}, "
            f"got {actual} for {_TOKENIZER_JSON}; fail-closed (FK-13 §13.2). "
            "The package asset is immutable; re-pin the revision deliberately."
        )
    try:
        from tokenizers import Tokenizer  # noqa: PLC0415 (bound dependency)
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise TokenizerAssetError(
            f"{PINNED_LIBRARY} is not installed; the bound tokenizer is "
            "mandatory (FK-13 §13.2)."
        ) from exc
    try:
        tokenizer = Tokenizer.from_file(str(_TOKENIZER_JSON))
    except Exception as exc:  # noqa: BLE001 -- normalise to a typed asset error
        raise TokenizerAssetError(
            f"Bound tokenizer asset could not be parsed: {exc} "
            "(FK-13 §13.2: no char fallback)."
        ) from exc
    # Disable truncation: chunk-sizing needs the TRUE token count of a section
    # (so E-CHUNK-001 fires on oversized sections and the chunker can split).
    # The embedding model applies its own truncation at query time; counting here
    # must not silently cap long content.
    _verify_semantics(tokenizer)
    tokenizer.no_truncation()
    return tokenizer


def chunk_token_count(text: str) -> int:
    """Return the token count of ``text`` under the bound tokenizer.

    Convenience over :func:`load_bound_tokenizer` for chunk-sizing callers.
    """
    if not text:
        return 0
    return len(load_bound_tokenizer().encode(text).ids)


__all__ = [
    "PINNED_LIBRARY",
    "PINNED_MODEL",
    "PINNED_REVISION",
    "TokenizerAssetError",
    "chunk_token_count",
    "load_bound_tokenizer",
]
