"""Regression pin: no server-side ``op_id`` mint in the backend (AG3-140 AC1).

FK-91 §91.1a Regel 5: ``op_id`` is the CLIENT-supplied idempotency key. A
server-side mint (a wire-model ``op_id`` field with a ``default_factory``, or an
explicit server-side assignment on a mutating wire model) makes a client's retry
blind -- it can no longer reconcile an ambiguous mutation via
``GET /v1/project-edge/operations/{op_id}`` (Regel 17). AG3-140 removed every such
mint and made ``op_id`` a required ``Field(min_length=1)``.

This pin greps the entire ``src/agentkit/backend`` tree and fails closed if a
``default_factory`` ever reappears on an ``op_id`` field, so the contract cannot
silently regress. The legitimate CLIENT-side mints that remain (the guard-counter
hook and the failure-corpus story-creation adapter mint their own ``op_id`` AS A
CLIENT before the service call, never as a wire-model default) are matched
explicitly and are NOT server mints.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``op_id`` and ``default_factory`` on the same logical Field declaration. The
# removed anti-pattern was ``op_id: str = Field(default_factory=lambda: ...)`` /
# ``op_id: str = Field(default_factory=_mint_op_id)`` on a mutating wire model.
_OP_ID_DEFAULT_FACTORY = re.compile(
    r"op_id\s*:\s*[^\n]*default_factory", re.MULTILINE
)
# Defensive reverse: a ``default_factory=...`` whose target field is ``op_id``.
_DEFAULT_FACTORY_OP_ID = re.compile(
    r"default_factory[^\n]*\bop_id\b", re.MULTILINE
)


def _backend_root() -> Path:
    # tests/contract/<this file> -> repo root -> src/agentkit/backend
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "agentkit"
        / "backend"
    )


def test_no_default_factory_op_id_mint_in_backend() -> None:
    """AG3-140 AC1: zero ``default_factory`` op_id mints under src/agentkit/backend."""
    root = _backend_root()
    assert root.is_dir(), f"backend root not found: {root}"

    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _OP_ID_DEFAULT_FACTORY.search(text) or _DEFAULT_FACTORY_OP_ID.search(text):
            offenders.append(str(path.relative_to(root)))

    assert not offenders, (
        "server-side op_id mint (default_factory) reintroduced -- FK-91 §91.1a "
        f"Regel 5 requires a client-supplied op_id. Offending files: {offenders}"
    )
