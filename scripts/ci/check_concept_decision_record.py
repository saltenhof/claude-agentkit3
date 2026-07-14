"""Check concept changes for a required decision-record reference."""

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
    """Run the blocking concept decision-record gate."""
    from concept_compiler.decision_record import (
        evaluate_decision_record_compliance,
    )
    from concept_compiler.decision_record_git import (
        GitAdapterError,
        load_commit_messages,
        load_concept_diff,
    )
    from concept_compiler.decision_record_render import render_decision_record_result

    parser = argparse.ArgumentParser(description="Check concept decision-record compliance.")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    try:
        diff = load_concept_diff(args.repo_root.resolve(), args.base, args.head)
        messages = load_commit_messages(args.repo_root.resolve(), args.base, args.head)
    except GitAdapterError as exc:
        print(f"[ERROR] concept-decision-record adapter: {exc}")
        return 1
    result = evaluate_decision_record_compliance(diff, messages)
    print(render_decision_record_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
