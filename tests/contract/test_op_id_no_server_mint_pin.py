"""Regression pin: no server-side ``op_id`` mint in the backend (AG3-140 AC1).

FK-91 §91.1a Rule 5: ``op_id`` is the CLIENT-supplied idempotency key. A
server-side mint (a wire-model ``op_id`` field with a ``default_factory``, or an
explicit server-side assignment on a mutating wire model) makes a client's retry
blind -- it can no longer reconcile an ambiguous mutation via
``GET /v1/project-edge/operations/{op_id}`` (Rule 17). AG3-140 removed every such
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
        f"Rule 5 requires a client-supplied op_id. Offending files: {offenders}"
    )


# ---------------------------------------------------------------------------
# ARCH-55 regression pin: no German in the AG3-140-touched source/tests.
# ARCH-55 is as binding as the Sonar rules -- source comments/identifiers/
# wire-keys must be English. This pin greps the AG3-140-touched .py files for a
# German blocklist so German cannot silently re-enter the AG3-140 diff.
# ---------------------------------------------------------------------------

#: Source patterns for the backend areas touched by AG3-140 and the later split
#: repairs. Each glob must match at least one file, so moved or deleted modules
#: fail closed instead of silently dropping out of ARCH-55 coverage.
_AG3_140_SOURCE_GLOBS: tuple[str, ...] = (
    "src/agentkit/backend/bootstrap/composition_*.py",
    "src/agentkit/backend/cli/*_commands.py",
    "src/agentkit/backend/cli/main.py",
    "src/agentkit/backend/cli/serve.py",
    "src/agentkit/backend/control_plane/runtime/*.py",
    "src/agentkit/backend/control_plane_http/*.py",
    "src/agentkit/backend/verify_system/**/*.py",
    "src/agentkit/backend/governance/hook_*.py",
    "src/agentkit/backend/state_backend/persistence_mappers/*.py",
    "src/agentkit/backend/state_backend/sqlite_store/*.py",
    "src/agentkit/backend/state_backend/postgres_store/*.py",
)

#: German words that must not appear in AG3-140 source comments/identifiers
#: (ARCH-55). Discrete words use word boundaries; participles match as substrings.
_GERMAN_BLOCKLIST = re.compile(
    r"\b(?:Regel|Befund|Fehlschlag|Abweichung|Minten|Sperre|Vertrag|Nachweis"
    r"|Anspruch|Wahrheit|Pflicht)\b|gemintet|beigestellt"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _guarded_ag3140_source_files(root: Path) -> tuple[Path, ...]:
    missing_patterns: list[str] = []
    files: dict[Path, None] = {}
    for pattern in _AG3_140_SOURCE_GLOBS:
        matches = sorted(path for path in root.glob(pattern) if path.suffix == ".py")
        if not matches:
            missing_patterns.append(pattern)
            continue
        for path in matches:
            if not path.exists():
                msg = f"guarded source path is missing: {path.relative_to(root)}"
                raise AssertionError(msg)
            files[path] = None
    if missing_patterns:
        raise AssertionError(
            "ARCH-55 source guard pattern(s) matched no files: "
            + ", ".join(missing_patterns)
        )
    return tuple(files)


def test_no_german_in_ag3140_touched_files() -> None:
    """ARCH-55: zero German blocklist words in the AG3-140-touched .py files."""
    root = _repo_root()
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for path in _guarded_ag3140_source_files(root):
        rel = str(path.relative_to(root))
        if path.resolve() == this_file:
            # This pin file legitimately DEFINES the German blocklist -- skip it.
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _GERMAN_BLOCKLIST.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:80]}")

    assert not offenders, (
        "German re-entered an AG3-140-touched file (ARCH-55, English-only source). "
        "Offenders:\n" + "\n".join(offenders)
    )
