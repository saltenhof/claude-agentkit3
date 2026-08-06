"""Run the non-blocking nightly or scope-filtered W3 concept sweep.

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
from concept_governance.scope_sets import DEFAULT_PARTITION_MAX_CHARS  # noqa: E402

NOT_DETERMINED_EXIT_CODE = 3
DEADLINE_FINDING_CODE = "RUN_DEADLINE_EXCEEDED"

# Derived, not guessed (AG3-233). W3 shares the corpus, the Hub and the
# per-call bounds of W2, and no nightly W3 run has ever swept: builds 1200
# through 1250 all end within 18 seconds on INCOMPLETE_SWEEP, so there is no
# measurement of a completed sweep to derive from. The bound is therefore
# taken from W2's evidence -- every W2 run that reached a verdict did so
# inside 25.9 minutes -- because both scripts talk to the same service over
# the same transport. Re-derive this value from W3's own first completed
# sweep once the sweep runs; until then it is the bound of the sibling stage,
# and that is stated rather than dressed up as a W3 measurement.
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
    """Run W3 and return zero only for a complete justified sweep."""
    args = _build_parser().parse_args()
    repo_root = args.repo_root.resolve()
    concept_root = _resolve(repo_root, args.concept_root)
    baseline = _resolve(repo_root, args.baseline)
    with RunDeadline(args.deadline_seconds, _render_not_determined(args.deadline_seconds)) as deadline:
        result = _run(args, concept_root, baseline)
    if deadline.expired:
        # The watchdog won the race by a hair and is terminating the process.
        return NOT_DETERMINED_EXIT_CODE
    print(render_scope_result(result))
    return 0 if result.ok else 1


def _run(args: argparse.Namespace, concept_root: Path, baseline: Path) -> ScopeConsistencyRunResult:
    try:
        evaluator = build_hub_scope_evaluator()
    except (OSError, ValueError) as exc:
        return _startup_failure(str(exc))
    return run_scope_consistency(
        concept_root,
        baseline,
        evaluator,
        tuple(args.scopes),
        limit=args.limit,
        partition_max_chars=args.partition_max_chars,
        partition_max_chunks=args.partition_max_chunks,
    )


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
    parser.add_argument("--partition-max-chars", type=int, default=DEFAULT_PARTITION_MAX_CHARS)
    parser.add_argument("--partition-max-chunks", type=int, default=20)
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
            f"concept-scope-consistency: NOT_DETERMINED (deadline_seconds={deadline_seconds:g})",
            f"[ERROR] {DEADLINE_FINDING_CODE} concept#(run) scope='' "
            f"assertion='deadline_seconds={deadline_seconds:g}' related=[] p4=pending "
            f"prompt={SCOPE_PROMPT_VERSION} model=unresolved: "
            "run abandoned at its wall-clock deadline; no verdict was reached and this is not a pass",
        ]
    )


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
