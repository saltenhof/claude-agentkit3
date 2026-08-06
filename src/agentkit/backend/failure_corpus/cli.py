"""Failure-corpus CLI adapter (FK-41 §41.9, AG3-078).

Thin boundary-layer over the ``FailureCorpus`` top-surface. Mutating commands
delegate to the authenticated active-writer contract; read-only commands use
the local read composition. All six subcommands are registered in
``cli/main.py``.

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

import getpass
import json
import ssl
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from agentkit.backend.failure_corpus.writer_client import FailureCorpusWriterClient

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
    _add_writer_arguments(add_p)

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
    _add_writer_arguments(review_pat_p)

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
    _add_writer_arguments(review_chk_p)

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
    _add_writer_arguments(eff_p)

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


def _add_writer_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared authenticated active-writer connection arguments."""

    parser.add_argument("--project-root", default=".", help="Project root")
    parser.add_argument("--base-url", required=False, help="Core Project-API base URL")
    parser.add_argument("--username", default="admin", help="Strategist username")
    parser.add_argument("--ca-file", default=None, help="Trusted control-plane CA certificate")
    parser.add_argument(
        "--op-id",
        default=None,
        help="Client-supplied idempotency key for replay after response loss",
    )


def _build_writer_client(args: argparse.Namespace) -> FailureCorpusWriterClient:
    """Authenticate the CLI and return its failure-corpus writer client."""

    from agentkit.backend.config.defaults import DEFAULT_CONTROL_PLANE_BASE_URL
    from agentkit.backend.failure_corpus.writer_client import FailureCorpusWriterClient
    from agentkit.harness_client.projectedge.client import HttpsJsonTransport
    from agentkit.harness_client.projectedge.runtime import read_bound_skill_bundle_version

    root = Path(str(getattr(args, "project_root", ".") or "."))
    ca_file = getattr(args, "ca_file", None)
    ssl_context = ssl.create_default_context(cafile=ca_file) if ca_file else None
    transport = HttpsJsonTransport(
        base_url=str(getattr(args, "base_url", "") or DEFAULT_CONTROL_PLANE_BASE_URL),
        ssl_context=ssl_context,
        skill_bundle_version=read_bound_skill_bundle_version(root),
    ).authenticate_strategist(
        username=str(getattr(args, "username", "admin")),
        password=getpass.getpass("Strategist password: "),
        project_key=str(args.project_key),
    )
    return FailureCorpusWriterClient(transport)


def _emit_writer_error(verb: str, exc: Exception) -> int:
    """Map authenticated HTTP and transport failures without a local fallback."""

    from urllib.error import URLError

    from agentkit.backend.exceptions import ControlPlaneApiError

    if isinstance(exc, ControlPlaneApiError):
        print(
            f"{verb} failed [{exc.error_code}] HTTP {exc.http_status}: {exc}",
            file=sys.stderr,
        )
    elif isinstance(exc, URLError):
        print(f"{verb} failed [BackendUnreachable]: {exc}", file=sys.stderr)
    elif isinstance(exc, json.JSONDecodeError):
        print(f"{verb} failed [TransportError]: {exc}", file=sys.stderr)
    elif isinstance(exc, ValueError):
        print(f"{verb} failed [InvalidRequest]: {exc}", file=sys.stderr)
    else:
        print(f"{verb} failed [TransportError]: {exc}", file=sys.stderr)
    return 1


def _operation_id(args: argparse.Namespace) -> str:
    """Resolve and expose the client-owned idempotency key before transport."""

    op_id = str(getattr(args, "op_id", None) or f"op-{uuid.uuid4().hex}")
    print(f"Operation ID: {op_id}")
    return op_id


# ---------------------------------------------------------------------------
# Command handlers (thin delegation only — no business logic here)
# ---------------------------------------------------------------------------


def handle_add_incident(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus add-incident``.

    Delegate the incident mutation to the authenticated active writer.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.failure_corpus.http_models import (
        FailureCorpusIncidentMutationRequest,
    )

    evidence = [e.strip() for e in args.evidence.split(",") if e.strip()]

    try:
        request = FailureCorpusIncidentMutationRequest(
            op_id=_operation_id(args),
            story_id=args.story_id,
            run_id=args.run_id,
            category=args.category,
            severity=args.severity,
            phase=args.phase,
            role=args.role,
            model=args.model,
            symptom=args.symptom,
            evidence=tuple(evidence),
            merge_blocked=args.merge_blocked,
        )
        client = _build_writer_client(args)
        result = client.add_incident(
            str(args.project_key),
            request,
        )
        print(f"Incident recorded: {result.incident_id}")
    except Exception as exc:
        return _emit_writer_error("add-incident", exc)

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

    Delegate the human-gated decision to the authenticated active writer.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.failure_corpus.http_models import FailureCorpusPatternReviewRequest

    try:
        request = FailureCorpusPatternReviewRequest(
            op_id=_operation_id(args),
            decision=args.decision,
            invariant=args.invariant,
            risk_level=args.risk_level,
            promotion_rule=args.promotion_rule,
            category=args.category,
        )
        client = _build_writer_client(args)
        result = client.review_pattern(
            str(args.project_key),
            str(args.pattern_id),
            request,
        )
        print(f"Pattern {result.pattern_id}: decision={args.decision}")
    except Exception as exc:
        return _emit_writer_error("review-patterns", exc)

    return 0


def handle_review_checks(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus review-checks``.

    Delegate the three-valued decision to the authenticated active writer.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.failure_corpus.http_models import FailureCorpusCheckReviewRequest

    try:
        request = FailureCorpusCheckReviewRequest(
            op_id=_operation_id(args),
            decision=args.decision,
            rejected_reason=args.rejected_reason,
        )
        client = _build_writer_client(args)
        result = client.review_check(
            str(args.project_key),
            str(args.check_id),
            request,
        )
        print(f"Check {result.check_id}: decision={args.decision}")
    except Exception as exc:
        return _emit_writer_error("review-checks", exc)

    return 0


def handle_effectiveness_report(args: argparse.Namespace) -> int:
    """Handle ``failure-corpus effectiveness-report``.

    Delegate the mutating effectiveness job to the authenticated active writer.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.backend.failure_corpus.http_models import FailureCorpusEffectivenessRequest

    try:
        request = FailureCorpusEffectivenessRequest(
            op_id=_operation_id(args),
            window_days=args.window_days,
        )
        client = _build_writer_client(args)
        report = client.report_effectiveness(
            str(args.project_key),
            request,
        )
        print(
            f"Effectiveness report (window={report.window_days}d): "
            f"updated={report.updated_count} "
            f"deactivated={report.deactivated_count}"
        )
    except Exception as exc:
        return _emit_writer_error("effectiveness-report", exc)

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
