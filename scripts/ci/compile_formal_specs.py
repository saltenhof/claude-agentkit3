"""Compile and validate AK3 formal concept specifications."""

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

from concept_compiler import audit_formal_prose_links, compile_formal_specs
from concept_compiler.compiler import FormalCompilationError
from concept_compiler.drift import FormalDriftError
from concept_compiler.loader import FormalSpecError
from concept_compiler.scenario_runner import FormalScenarioError


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile AK3 formal concept specs.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("concept/formal-spec"),
        help="Root directory containing formal spec markdown files.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root used to resolve prose_refs.",
    )
    args = parser.parse_args()

    try:
        result = compile_formal_specs(args.root)
        drift_links = audit_formal_prose_links(result, args.repo_root)
    except (FormalCompilationError, FormalDriftError, FormalScenarioError, FormalSpecError) as exc:
        print(f"[formal-spec] FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        f"[formal-spec] OK: {len(result.documents)} documents, "
        f"{len(result.declared_ids)} ids, {len(result.references)} references, "
        f"{len(result.validated_scenarios)} scenarios, "
        f"{len(drift_links)} prose links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
