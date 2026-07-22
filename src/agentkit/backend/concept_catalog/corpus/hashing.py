"""Deterministic content hashing for concept/story chunks (FK-13 §13.3.3)."""

from __future__ import annotations

import hashlib


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of UTF-8 ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of raw ``data``."""
    return hashlib.sha256(data).hexdigest()


def corpus_revision(file_hashes: list[str], *, parser_version: str) -> str:
    """Compute ``corpus_revision`` (FK-13 §13.9.8).

    ``SHA-256(sorted(all file hashes) + parser_version)`` with a ``sha256:``
    prefix.
    """
    payload = "\n".join(sorted(file_hashes)) + "\n" + parser_version
    return "sha256:" + sha256_text(payload)


__all__ = [
    "corpus_revision",
    "sha256_bytes",
    "sha256_text",
]
