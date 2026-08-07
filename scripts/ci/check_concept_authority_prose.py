"""Run the non-blocking-nightly or pre-merge W2 concept check.

Exit codes
----------
``0``
    PASS -- the sweep completed and every finding is justified.
``1``
    ERROR -- the sweep completed and reported findings.
``3``
    NOT_DETERMINED -- the run was abandoned at its wall-clock deadline and
    reached no verdict. This is explicitly *not* a pass (``CLAUDE.md``
    section FAIL-CLOSED).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

# E402 below is structural, not a style waiver: these modules live under
# tools/ and only become importable once the sys.path bootstrap above has
# run, so the imports cannot move to the top of the file.
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

NOT_DETERMINED_EXIT_CODE = 3
DEADLINE_FINDING_CODE = "RUN_DEADLINE_EXCEEDED"

# Derived, not guessed (AG3-233). Every W2 nightly run that ever reached a
# verdict did so inside 25.9 minutes -- measured from the Jenkins console
# timestamps of builds 1200, 1201, 1204, 1205, 1219, 1237, 1240, 1246, 1247,
# 1249 and 1250: 0.25, 0.25, 13.60, 25.85, 0.20, 0.30, 1.85, 4.85, 8.10,
# 23.85 and 3.56 minutes. 1800 seconds therefore keeps every historically
# productive run intact (longest observed + ~16% headroom) while capping an
# advisory stage at roughly 1.7x the full pipeline instead of the 300-minute
# global rail. The per-call bounds below the script (180s per Hub send, 30s
# per acquire) bound a single call but never the run, which is why the bound
# has to live here.
DEFAULT_DEADLINE_SECONDS = 1800.0


class RunDeadline:
    """Wall-clock guard that turns a wedged run into a visible non-verdict.

    The guarded work reaches an external LLM service through blocking socket
    reads inside a ``ThreadPoolExecutor``. Those worker threads are not
    daemons and ``concurrent.futures`` joins them from an interpreter-shutdown
    hook, so a plain ``SystemExit`` on the main thread would block for exactly
    as long as the wedged call. The guard therefore prints the outcome itself
    and leaves through ``os._exit``.
    """

    def __init__(self, seconds: float, report: str) -> None:
        """Arm nothing yet; bind the bound and the text it will print."""
        self._seconds = seconds
        self._report = report
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._claimed = False
        self.expired = False

    def __enter__(self) -> RunDeadline:
        """Start the watchdog thread and return the armed guard."""
        threading.Thread(target=self._watch, name="run-deadline", daemon=True).start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Disarm the watchdog and take reporting ownership if it has not fired."""
        self._finished.set()
        self.expired = not self._claim()

    def _claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True

    def _watch(self) -> None:
        if self._finished.wait(self._seconds):
            return
        if not self._claim():
            return
        sys.stdout.write(self._report + "\n")
        sys.stdout.flush()
        # os._exit, not sys.exit: see the class docstring.
        os._exit(NOT_DETERMINED_EXIT_CODE)


def main() -> int:
    """Run W2 and return zero only when all findings are justified."""
    args = _build_parser().parse_args()
    repo_root = args.repo_root.resolve()
    concept_root = _resolve(repo_root, args.concept_root)
    baseline = _resolve(repo_root, args.baseline)
    with RunDeadline(args.deadline_seconds, _render_not_determined(args.deadline_seconds)) as deadline:
        result = _run(args, repo_root, concept_root, baseline)
    if deadline.expired:
        # The watchdog won the race by a hair and is terminating the process.
        return NOT_DETERMINED_EXIT_CODE
    print(render_result(result))
    return 0 if result.ok else 1


def _run(args: argparse.Namespace, repo_root: Path, concept_root: Path, baseline: Path) -> AuthorityRunResult:
    try:
        included = changed_concept_docs(repo_root, concept_root, args.base) if args.mode == "pre-merge" else None
    except GitScopeError as exc:
        return _startup_failure("GIT_SCOPE_FAILURE", str(exc))
    return _build_and_run(args, repo_root, concept_root, baseline, included)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check concept prose authority by deterministic policy.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--concept-root", type=Path, default=Path("concept"))
    parser.add_argument("--baseline", type=Path, default=Path("concept/_meta/authority-prose-baseline.yaml"))
    parser.add_argument("--mode", choices=("nightly", "pre-merge"), required=True)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--offline-evaluations", type=Path, help="Fixed JSON classifications for deterministic tests only.")
    parser.add_argument(
        "--deadline-seconds",
        type=_positive_seconds,
        default=DEFAULT_DEADLINE_SECONDS,
        help="Wall-clock bound; the run is abandoned as NOT_DETERMINED when it is reached.",
    )
    return parser


def _positive_seconds(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("--deadline-seconds must be positive")
    return value


def _render_not_determined(deadline_seconds: float) -> str:
    return "\n".join(
        [
            f"concept-authority-prose: NOT_DETERMINED (deadline_seconds={deadline_seconds:g})",
            f"[ERROR] {DEADLINE_FINDING_CODE} concept#(run) scope='' "
            f"assertion='deadline_seconds={deadline_seconds:g}' prompt={PROMPT_VERSION} model=unresolved: "
            "run abandoned at its wall-clock deadline; no verdict was reached and this is not a pass",
        ]
    )


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
