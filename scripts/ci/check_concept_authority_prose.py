"""Run the non-blocking-nightly or pre-merge W2 concept check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from concept_governance import (  # noqa: E402
    GitScopeError,
    OfflineAuthorityProseEvaluator,
    build_hub_evaluator,
    changed_concept_docs,
    render_result,
    run_authority_check,
)
from concept_governance.models import (  # noqa: E402
    PROMPT_VERSION,
    AuthorityFinding,
    AuthorityRunResult,
)

if TYPE_CHECKING:
    from concept_governance.port import AuthorityProseEvaluator


def main() -> int:
    """Run W2 and return zero only when all findings are justified."""
    parser = argparse.ArgumentParser(description="Check concept prose authority by deterministic policy.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--concept-root", type=Path, default=Path("concept"))
    parser.add_argument("--baseline", type=Path, default=Path("concept/_meta/authority-prose-baseline.yaml"))
    parser.add_argument("--mode", choices=("nightly", "pre-merge"), required=True)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--offline-evaluations", type=Path, help="Fixed JSON classifications for deterministic tests only.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    concept_root = _resolve(repo_root, args.concept_root)
    baseline = _resolve(repo_root, args.baseline)
    try:
        included = changed_concept_docs(repo_root, concept_root, args.base) if args.mode == "pre-merge" else None
    except GitScopeError as exc:
        result = _startup_failure("GIT_SCOPE_FAILURE", str(exc))
    else:
        result = _build_and_run(args, repo_root, concept_root, baseline, included)
    print(render_result(result))
    return 0 if result.ok else 1


def _build_and_run(
    args: argparse.Namespace,
    repo_root: Path,
    concept_root: Path,
    baseline: Path,
    included: frozenset[str] | None,
) -> AuthorityRunResult:
    evaluator: AuthorityProseEvaluator
    try:
        if args.offline_evaluations is not None:
            evaluator = OfflineAuthorityProseEvaluator.from_path(_resolve(repo_root, args.offline_evaluations))
            parallelism = 1
        else:
            evaluator = build_hub_evaluator()
            parallelism = evaluator.parallelism
    except (OSError, ValueError) as exc:
        code = "EVALUATION_PARSE_FAILURE" if args.offline_evaluations is not None else "EVALUATION_TRANSPORT_FAILURE"
        return _startup_failure(code, str(exc))
    return run_authority_check(concept_root, baseline, evaluator, included, parallelism=parallelism)


def _resolve(repo_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _startup_failure(code: str, message: str) -> AuthorityRunResult:
    finding = AuthorityFinding(
        code=code, doc="concept", anchor="(run)", assertion=message,
        scope="", prompt_version=PROMPT_VERSION, model="unresolved", message=message,
    )
    return AuthorityRunResult(findings=(finding,))


if __name__ == "__main__":
    raise SystemExit(main())
