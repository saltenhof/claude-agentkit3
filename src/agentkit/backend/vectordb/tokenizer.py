"""Model-bound tokenizer asset loader (FK-13 §13.2, AG3-174).

Loads the versioned package asset for
``sentence-transformers/all-MiniLM-L6-v2`` with a bound SHA-256 digest check
before parsing. Fail-closed: missing or digest-mismatched assets raise; there
is no network fetch and no character-based fallback.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Final

from tokenizers import Tokenizer

MODEL_ID: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
TOKENIZER_REVISION: Final[str] = "e4ce9877abf3edfe10b0d82785e83bdcb973e22e"
RUNTIME_LIBRARY: Final[str] = "tokenizers==0.21.0"
LICENSE: Final[str] = "Apache-2.0"

#: Max chunk size in tokens (FK-13 §13.3.3: ~1000 tokens).
MAX_CHUNK_TOKENS: Final[int] = 1000

_ASSET_PACKAGE: Final[str] = "agentkit.backend.vectordb.assets.tokenizer"
_ASSET_DIR_NAME: Final[str] = "all-minilm-l6-v2"
_REQUIRED_ASSETS: Final[tuple[str, ...]] = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
)


class TokenizerAssetError(Exception):
    """Raised when the tokenizer package asset is missing or invalid."""


@dataclass(frozen=True)
class TokenizerManifest:
    """Pinned tokenizer identity and per-file digests."""

    model_id: str
    tokenizer_revision: str
    runtime_library: str
    license: str
    assets: dict[str, str]


def _asset_root() -> Path:
    """Resolve the on-disk package asset directory (fail-closed)."""
    try:
        base = resources.files(_ASSET_PACKAGE)
        root = Path(str(base.joinpath(_ASSET_DIR_NAME)))
    except (ModuleNotFoundError, FileNotFoundError, TypeError, AttributeError) as exc:
        raise TokenizerAssetError(
            f"Tokenizer package asset root missing for {_ASSET_PACKAGE}/"
            f"{_ASSET_DIR_NAME} (fail-closed, FK-13 §13.2)."
        ) from exc
    if not root.is_dir():
        # Fallback for editable installs where importlib resources may not map.
        fallback = Path(__file__).resolve().parent / "assets" / "tokenizer" / _ASSET_DIR_NAME
        if fallback.is_dir():
            return fallback
        raise TokenizerAssetError(
            f"Tokenizer asset directory not found at {root} or {fallback} "
            "(fail-closed, FK-13 §13.2)."
        )
    return root


def load_manifest(asset_root: Path | None = None) -> TokenizerManifest:
    """Load and validate the DIGESTS.json manifest (fail-closed)."""
    root = asset_root if asset_root is not None else _asset_root()
    digest_path = root / "DIGESTS.json"
    if not digest_path.is_file():
        raise TokenizerAssetError(
            f"Tokenizer DIGESTS.json missing at {digest_path} (fail-closed, FK-13 §13.2)."
        )
    try:
        raw = json.loads(digest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TokenizerAssetError(
            f"Tokenizer DIGESTS.json unreadable at {digest_path}: {exc} "
            "(fail-closed, FK-13 §13.2)."
        ) from exc
    if not isinstance(raw, dict):
        raise TokenizerAssetError("Tokenizer DIGESTS.json must be a JSON object.")
    assets = raw.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise TokenizerAssetError("Tokenizer DIGESTS.json missing non-empty 'assets' map.")
    digests: dict[str, str] = {}
    for name, digest in assets.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not digest:
            raise TokenizerAssetError(
                f"Tokenizer DIGESTS.json has invalid entry for {name!r}."
            )
        digests[name] = digest
    model_id = raw.get("model_id")
    revision = raw.get("tokenizer_revision")
    runtime = raw.get("runtime_library")
    license_name = raw.get("license")
    if not all(isinstance(v, str) and v for v in (model_id, revision, runtime, license_name)):
        raise TokenizerAssetError(
            "Tokenizer DIGESTS.json missing model_id/tokenizer_revision/"
            "runtime_library/license strings."
        )
    return TokenizerManifest(
        model_id=str(model_id),
        tokenizer_revision=str(revision),
        runtime_library=str(runtime),
        license=str(license_name),
        assets=digests,
    )


def verify_asset_digests(asset_root: Path | None = None) -> TokenizerManifest:
    """Verify every required asset against its bound SHA-256 digest.

    Digest check runs before any tokenizer parse. Fail-closed on mismatch,
    missing file, or unreadable content.
    """
    root = asset_root if asset_root is not None else _asset_root()
    manifest = load_manifest(root)
    if manifest.model_id != MODEL_ID:
        raise TokenizerAssetError(
            f"Tokenizer model_id mismatch: expected {MODEL_ID!r}, got {manifest.model_id!r}."
        )
    if manifest.tokenizer_revision != TOKENIZER_REVISION:
        raise TokenizerAssetError(
            f"Tokenizer revision mismatch: expected {TOKENIZER_REVISION!r}, "
            f"got {manifest.tokenizer_revision!r}."
        )
    if manifest.runtime_library != RUNTIME_LIBRARY:
        raise TokenizerAssetError(
            f"Tokenizer runtime_library mismatch: expected {RUNTIME_LIBRARY!r}, "
            f"got {manifest.runtime_library!r}."
        )
    for name in _REQUIRED_ASSETS:
        expected = manifest.assets.get(name)
        if expected is None:
            raise TokenizerAssetError(
                f"Tokenizer DIGESTS.json missing required asset {name!r}."
            )
        path = root / name
        if not path.is_file():
            raise TokenizerAssetError(
                f"Tokenizer asset missing: {path} (fail-closed, FK-13 §13.2)."
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise TokenizerAssetError(
                f"Tokenizer asset unreadable: {path}: {exc}"
            ) from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise TokenizerAssetError(
                f"Tokenizer asset digest mismatch for {name}: "
                f"expected {expected}, got {actual} (fail-closed, FK-13 §13.2)."
            )
    return manifest


@lru_cache(maxsize=1)
def load_tokenizer() -> Tokenizer:
    """Load the pinned tokenizer after digest verification (no network)."""
    root = _asset_root()
    verify_asset_digests(root)
    tokenizer_path = root / "tokenizer.json"
    try:
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
    except Exception as exc:  # noqa: BLE001 -- any parse fault is fail-closed
        raise TokenizerAssetError(
            f"Tokenizer asset is damaged or semantically incompatible at "
            f"{tokenizer_path}: {exc} (fail-closed, no network/cache fallback)."
        ) from exc
    # Disable padding/truncation so token counts reflect content length,
    # not the embedding max_length (128). Chunk boundary checks need the
    # true length under the bound vocabulary, not a truncated window.
    tokenizer.no_padding()
    tokenizer.no_truncation()
    return tokenizer


def count_tokens(text: str) -> int:
    """Return the token count for ``text`` using the bound model tokenizer."""
    if not isinstance(text, str):
        raise TokenizerAssetError(
            f"count_tokens requires str, got {type(text).__name__} (fail-closed)."
        )
    tokenizer = load_tokenizer()
    encoded = tokenizer.encode(text)
    return len(encoded.ids)


def clear_tokenizer_cache() -> None:
    """Drop the cached tokenizer (tests only)."""
    load_tokenizer.cache_clear()


__all__ = [
    "LICENSE",
    "MAX_CHUNK_TOKENS",
    "MODEL_ID",
    "RUNTIME_LIBRARY",
    "TOKENIZER_REVISION",
    "TokenizerAssetError",
    "TokenizerManifest",
    "clear_tokenizer_cache",
    "count_tokens",
    "load_manifest",
    "load_tokenizer",
    "verify_asset_digests",
]
