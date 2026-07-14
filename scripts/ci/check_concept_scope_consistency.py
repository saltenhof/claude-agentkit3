"""Run the non-blocking nightly or scope-filtered W3 concept sweep."""

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

from concept_governance import (  # noqa: E402
    ScopeConsistencyFinding,
    ScopeConsistencyRunResult,
    build_hub_scope_evaluator,
    render_scope_result,
    run_scope_consistency,
)
from concept_governance.scope_models import SCOPE_PROMPT_VERSION  # noqa: E402


def main() -> int:
    """Run W3 and return zero only for a complete justified sweep."""
    parser = _build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    concept_root = _resolve(repo_root, args.concept_root)
    baseline = _resolve(repo_root, args.baseline)
    try:
        evaluator = build_hub_scope_evaluator()
    except (OSError, ValueError) as exc:
        result = _startup_failure(str(exc))
    else:
        result = run_scope_consistency(
            concept_root,
            baseline,
            evaluator,
            tuple(args.scopes),
            limit=args.limit,
            partition_max_chars=args.partition_max_chars,
            partition_max_chunks=args.partition_max_chunks,
        )
    print(render_scope_result(result))
    return 0 if result.ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sweep closed authority scope sets for contradictions.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--concept-root", type=Path, default=Path("concept"))
    parser.add_argument("--baseline", type=Path, default=Path("concept/_meta/authority-prose-baseline.yaml"))
    parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        default=[],
        help="Live authority_over scope; repeat for multiple touched scopes.",
    )
    parser.add_argument("--limit", type=int, help="Deterministically select only the first N scope sets (smoke runs only).")
    parser.add_argument("--partition-max-chars", type=int, default=48_000)
    parser.add_argument("--partition-max-chunks", type=int, default=20)
    return parser


def _resolve(repo_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _startup_failure(message: str) -> ScopeConsistencyRunResult:
    finding = ScopeConsistencyFinding(
        code="HUB_UNREACHABLE", doc="concept", anchor="(run)", assertion=message,
        related_loci=(), scope="", prompt_version=SCOPE_PROMPT_VERSION,
        model="unresolved", message=message, formalization_check=None,
    )
    incomplete = finding.model_copy(
        update={"code": "INCOMPLETE_SWEEP", "assertion": "completed=0", "message": "completed=0"}
    )
    return ScopeConsistencyRunResult(
        findings=(finding, incomplete), scope_sets=0, partitions=0, completed_partitions=0
    )


if __name__ == "__main__":
    raise SystemExit(main())
