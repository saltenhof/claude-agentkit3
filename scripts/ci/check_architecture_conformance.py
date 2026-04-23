"""Check formal architecture-conformance contracts against Python source."""

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
    from concept_compiler import (
        audit_architecture_conformance,
        compile_formal_specs,
        raise_on_architecture_violations,
    )
    from concept_compiler.architecture_conformance import ArchitectureConformanceError
    from concept_compiler.compiler import FormalCompilationError
    from concept_compiler.drift import FormalDriftError
    from concept_compiler.loader import FormalSpecError
    from concept_compiler.scenario_runner import FormalScenarioError

    parser = argparse.ArgumentParser(
        description="Check AK3 architecture-conformance contracts."
    )
    parser.add_argument(
        "--formal-root",
        type=Path,
        default=Path("concept/formal-spec"),
        help="Root directory containing formal spec markdown files.",
    )
    parser.add_argument(
        "--code-root",
        type=Path,
        default=Path("src"),
        help="Python source root to scan.",
    )
    args = parser.parse_args()

    try:
        compiled = compile_formal_specs(args.formal_root)
        violations = audit_architecture_conformance(compiled, args.code_root)
        raise_on_architecture_violations(violations)
    except (
        ArchitectureConformanceError,
        FormalCompilationError,
        FormalDriftError,
        FormalScenarioError,
        FormalSpecError,
    ) as exc:
        print(f"[architecture-conformance] FAILED: {exc}", file=sys.stderr)
        return 1

    print("[architecture-conformance] OK: no architecture contract violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
