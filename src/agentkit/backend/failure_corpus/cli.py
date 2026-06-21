"""Failure-corpus CLI adapter (FK-41 §41.9, AG3-078).

Thin boundary-layer over the ``FailureCorpus`` top-surface. Contains NO business
logic — delegates only. All six subcommands are registered in ``cli/main.py``.

Subcommands:
- ``add-incident``: Record a new incident candidate via ``record_incident``.
- ``suggest-patterns``: Cluster OBSERVED incidents into PatternCandidates.
- ``review-patterns``: Accept or reject a PatternCandidate (human gate).
- ``review-checks``: Approve, reject, or request revision of a CheckProposal.
- ``effectiveness-report``: Run the effectiveness job for all ACTIVE checks.
- ``list-checks``: List all check proposals for a project.

Sources:
- FK-41 §41.9 -- CLI-Boundary-Control
- FK-41 §41.5 -- PatternPromotion surface
- FK-41 §41.6 -- CheckFactory 6-step flow
- FK-41 §41.6.7 -- effectiveness tracking
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

# Shared argument help text (hoisted to avoid duplicated literals, Sonar S1192).
_HELP_PROJECT_KEY = "Project key"

# ---------------------------------------------------------------------------
# Parser registration (called from cli/main.py)
# ---------------------------------------------------------------------------


def register_subparsers(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register all ``failure-corpus`` sub-subcommands.

    Called from ``cli.main._setup_failure_corpus_subparsers`` to wire the six
    subcommands into the ``failure-corpus`` parser.

    Args:
        subparsers: The sub-subparsers action from the ``failure-corpus`` parser.
    """
    # add-incident
    add_p = subparsers.add_parser(
        "add-incident",
        help="Record a new incident candidate via FailureCorpus.record_incident",
    )
    add_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)
    add_p.add_argument("--story-id", required=True, help="Story ID")
    add_p.add_argument("--run-id", required=True, help="Run ID")
    add_p.add_argument(
        "--category",
        required=True,
        help="FailureCategory wire value (e.g. 'test_omission')",
    )
    add_p.add_argument(
        "--severity",
        required=True,
        help="IncidentSeverity wire value (e.g. 'high')",
    )
    add_p.add_argument(
        "--phase",
        required=True,
        help="Pipeline phase (e.g. 'implementation')",
    )
    add_p.add_argument(
        "--role",
        required=True,
        help="IncidentRole wire value (e.g. 'worker')",
    )
    add_p.add_argument("--model", required=True, help="Model identifier")
    add_p.add_argument("--symptom", required=True, help="Symptom free-text")
    add_p.add_argument(
        "--evidence",
        required=False,
        default="",
        help="Comma-separated evidence strings",
    )
    add_p.add_argument(
        "--merge-blocked",
        action="store_true",
        help="Flag: merge is blocked by this incident",
    )

    # suggest-patterns
    suggest_p = subparsers.add_parser(
        "suggest-patterns",
        help="Cluster OBSERVED incidents into PatternCandidates",
    )
    suggest_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)

    # review-patterns
    review_pat_p = subparsers.add_parser(
        "review-patterns",
        help="Accept or reject a PatternCandidate (human confirmation gate)",
    )
    review_pat_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)
    review_pat_p.add_argument("--pattern-id", required=True, help="Pattern identity (FP-NNNN)")
    review_pat_p.add_argument(
        "--decision",
        required=True,
        choices=["accepted", "rejected"],
        help="Human decision",
    )
    review_pat_p.add_argument(
        "--invariant",
        required=False,
        default=None,
        help="Invariant text (required for accepted decision)",
    )
    review_pat_p.add_argument(
        "--risk-level",
        required=False,
        default=None,
        help="Risk level wire value (medium/high/critical; required for accepted)",
    )
    review_pat_p.add_argument(
        "--promotion-rule",
        required=False,
        default=None,
        help=("Promotion rule wire value (repetition/high_severity/favorable_checkability; required for accepted decision)"),
    )
    review_pat_p.add_argument(
        "--category",
        required=False,
        default=None,
        help=("FailureCategory wire value (e.g. 'test_omission'; required for accepted decision)"),
    )

    # review-checks
    review_chk_p = subparsers.add_parser(
        "review-checks",
        help="Approve, reject, or request revision of a CheckProposal",
    )
    review_chk_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)
    review_chk_p.add_argument("--check-id", required=True, help="Check proposal identity (CHK-NNNN)")
    review_chk_p.add_argument(
        "--decision",
        required=True,
        choices=["approved", "rejected", "revise"],
        help="Human decision (3-valued: approved/rejected/revise)",
    )
    review_chk_p.add_argument(
        "--rejected-reason",
        required=False,
        default=None,
        help="Optional rejection reason (used for rejected and revise decisions)",
    )

    # effectiveness-report
    eff_p = subparsers.add_parser(
        "effectiveness-report",
        help="Run the effectiveness job for all ACTIVE checks (FK-41 §41.6.7)",
    )
    eff_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)
    eff_p.add_argument(
        "--window-days",
        type=int,
        default=90,
        help="Observation window in days (default 90)",
    )

    # list-checks
    list_chk_p = subparsers.add_parser(
        "list-checks",
        help="List all check proposals for a project",
    )
    list_chk_p.add_argument("--project-key", required=True, help=_HELP_PROJECT_KEY)
    list_chk_p.add_argument(
        "--pattern-id",
        required=False,
        default=None,
        help="Filter by pattern identity (FP-NNNN)",
    )


# ---------------------------------------------------------------------------
# Command handlers (thin delegation only — no business logic here)
# ---------------------------------------------------------------------------


def handle_add_incident(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus add-incident``.

    Delegates to ``FailureCorpus.record_incident`` via the composition root.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )
    from agentkit.backend.core_types import FailureCategory
    from agentkit.backend.failure_corpus.incident import IncidentCandidate
    from agentkit.backend.failure_corpus.types import IncidentRole, IncidentSeverity

    try:
        category = FailureCategory(args.category)
        severity = IncidentSeverity(args.severity)
        role = IncidentRole(args.role)
    except ValueError as exc:
        print(f"add-incident: invalid argument: {exc}", file=sys.stderr)
        return 1

    evidence = [e.strip() for e in args.evidence.split(",") if e.strip()]

    candidate = IncidentCandidate(
        project_key=args.project_key,
        story_id=args.story_id,
        run_id=args.run_id,
        category=category,
        severity=severity,
        phase=args.phase,
        role=role,
        model=args.model,
        symptom=args.symptom,
        evidence=evidence,
        merge_blocked=args.merge_blocked,
    )

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        incident_id = corpus.record_incident(candidate)
        print(f"Incident recorded: {incident_id}")
    except Exception as exc:
        print(f"add-incident failed: {exc}", file=sys.stderr)
        return 1

    return 0


def handle_suggest_patterns(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus suggest-patterns``.

    Delegates to ``FailureCorpus.suggest_patterns``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        candidates = corpus.suggest_patterns()
    except Exception as exc:
        print(f"suggest-patterns failed: {exc}", file=sys.stderr)
        return 1

    if not candidates:
        print("No pattern candidates found (no qualifying clusters).")
        return 0

    for cand in candidates:
        print(
            f"  {cand.pattern_id}: [{cand.category.value}] rule={cand.promotion_rule.value} incidents={len(cand.incident_refs)}"
        )
        print(f"    invariant_candidate: {cand.invariant_candidate}")
    return 0


def handle_review_patterns(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus review-patterns``.

    Delegates to ``FailureCorpus.confirm_pattern`` (human gate).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )
    from agentkit.backend.core_types import FailureCategory
    from agentkit.backend.failure_corpus.pattern import PatternRiskLevel, PromotionRule
    from agentkit.backend.failure_corpus.top import PatternDecision
    from agentkit.backend.failure_corpus.types import PatternId

    try:
        decision = PatternDecision(args.decision)
    except ValueError as exc:
        print(f"review-patterns: invalid decision: {exc}", file=sys.stderr)
        return 1

    risk_level = None
    if args.risk_level is not None:
        try:
            risk_level = PatternRiskLevel(args.risk_level)
        except ValueError as exc:
            print(f"review-patterns: invalid risk-level: {exc}", file=sys.stderr)
            return 1

    promotion_rule = None
    if args.promotion_rule is not None:
        try:
            promotion_rule = PromotionRule(args.promotion_rule)
        except ValueError as exc:
            print(f"review-patterns: invalid promotion-rule: {exc}", file=sys.stderr)
            return 1

    category = None
    if args.category is not None:
        try:
            category = FailureCategory(args.category)
        except ValueError as exc:
            print(f"review-patterns: invalid category: {exc}", file=sys.stderr)
            return 1

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        result = corpus.confirm_pattern(
            PatternId(args.pattern_id),
            decision,
            invariant=args.invariant,
            risk_level=risk_level,
            promotion_rule=promotion_rule,
            category=category,
        )
        print(f"Pattern {result.pattern_id}: decision={args.decision}")
    except Exception as exc:
        print(f"review-patterns failed: {exc}", file=sys.stderr)
        return 1

    return 0


def handle_review_checks(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus review-checks``.

    Delegates to ``FailureCorpus.approve_check`` (3-valued decision).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )
    from agentkit.backend.failure_corpus.top import CheckApprovalDecision
    from agentkit.backend.failure_corpus.types import CheckId

    try:
        decision = CheckApprovalDecision(args.decision)
    except ValueError as exc:
        print(f"review-checks: invalid decision: {exc}", file=sys.stderr)
        return 1

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        result = corpus.approve_check(
            CheckId(args.check_id),
            decision,
            rejected_reason=args.rejected_reason,
        )
        print(f"Check {result.check_id}: decision={args.decision}")
    except Exception as exc:
        print(f"review-checks failed: {exc}", file=sys.stderr)
        return 1

    return 0


def handle_effectiveness_report(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus effectiveness-report``.

    Delegates to ``FailureCorpus.report_effectiveness``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        report = corpus.report_effectiveness(window_days=args.window_days)
        print(
            f"Effectiveness report (window={report.window_days}d): "
            f"updated={report.updated_count} "
            f"deactivated={report.deactivated_count}"
        )
    except Exception as exc:
        print(f"effectiveness-report failed: {exc}", file=sys.stderr)
        return 1

    return 0


def handle_list_checks(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus list-checks``.

    Lists all check proposals for a project, optionally filtered by pattern.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_failure_corpus,
        build_projection_accessor,
    )

    try:
        accessor = build_projection_accessor()
        corpus = build_failure_corpus(accessor, project_key=args.project_key)
        results = corpus.list_checks(pattern_id=args.pattern_id)
    except Exception as exc:
        print(f"list-checks failed: {exc}", file=sys.stderr)
        return 1

    if not results:
        print("No check proposals found.")
        return 0

    for chk in results:
        print(f"  {chk.check_id}: [{chk.status.value}] type={chk.check_type.value} pattern={chk.pattern_ref}")
    return 0


# ---------------------------------------------------------------------------
# Top-level dispatcher (called from cli/main.py _dispatch_command)
# ---------------------------------------------------------------------------

_SUBCOMMAND_HANDLERS = {
    "add-incident": handle_add_incident,
    "suggest-patterns": handle_suggest_patterns,
    "review-patterns": handle_review_patterns,
    "review-checks": handle_review_checks,
    "effectiveness-report": handle_effectiveness_report,
    "list-checks": handle_list_checks,
}


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch a ``failure-corpus`` subcommand to the appropriate handler.

    Args:
        args: Parsed CLI arguments. Must have ``fc_command`` attribute.

    Returns:
        Exit code (0 success, 1 failure).
    """
    fc_command = getattr(args, "fc_command", None)
    if fc_command is None:
        print("failure-corpus: no subcommand given. Use --help.", file=sys.stderr)
        return 1

    handler = _SUBCOMMAND_HANDLERS.get(str(fc_command))
    if handler is None:
        print(f"failure-corpus: unknown subcommand {fc_command!r}", file=sys.stderr)
        return 1

    return handler(args)


__all__ = [
    "dispatch",
    "register_subparsers",
]
