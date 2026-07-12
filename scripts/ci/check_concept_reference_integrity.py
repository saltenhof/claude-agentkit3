"""Check deterministic reference integrity across the concept corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))


def main() -> int:
    """Run the blocking concept-reference-integrity gate."""
    from concept_compiler import compile_formal_specs
    from concept_compiler.reference_integrity import (
        audit_reference_integrity,
        render_reference_integrity,
    )

    parser = argparse.ArgumentParser(description="Check concept reference integrity.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--concept-root", type=Path, default=Path("concept"))
    parser.add_argument("--formal-root", type=Path, default=Path("concept/formal-spec"))
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("concept/_meta/reference-integrity-baseline.yaml"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    concept_root = _resolve(repo_root, args.concept_root)
    formal_root = _resolve(repo_root, args.formal_root)
    baseline = _resolve(repo_root, args.baseline)
    compiled = compile_formal_specs(formal_root)
    result = audit_reference_integrity(repo_root, concept_root, compiled, baseline)
    print(render_reference_integrity(result))
    return 0 if result.ok else 1


def _resolve(repo_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
