"""Canonical skill-bundle manifest digest (FK-43 §43.5.2, AG3-176 R2).

Single algorithm used by product binding verification and contract tests:
SHA-256 over UTF-8 canonical JSON of the manifest object with the
``manifest_digest`` field excluded, keys sorted.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def compute_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return the FK-43 canonical digest for a parsed manifest mapping."""
    payload = {k: v for k, v in manifest.items() if k != "manifest_digest"}
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["compute_manifest_digest"]
