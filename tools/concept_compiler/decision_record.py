"""Pure compliance core and stable rendering for the W4 concept gate."""

from __future__ import annotations

from .decision_record_heuristic import first_record_requiring_line
from .decision_record_models import (
    ConceptDiff,
    ConceptFileChange,
    DecisionRecordFinding,
    DecisionRecordResult,
)
from .decision_record_records import (
    DECISIONS_ROOT,
    decision_trailers,
    format_only_reasons,
    is_record_path_name_valid,
    record_path_for_trailer,
)


def evaluate_decision_record_compliance(
    diff: ConceptDiff, commit_messages: tuple[str, ...]
) -> DecisionRecordResult:
    """Evaluate injected concept changes without git or filesystem access."""
    scoped = tuple(change for change in diff.changed_files if _is_in_scope(change.path))
    if not scoped:
        return DecisionRecordResult(findings=())
    reasons = format_only_reasons(commit_messages)
    findings = _empty_reason_findings(scoped, reasons)
    satisfied, record_findings = _evaluate_records(diff, commit_messages)
    findings.extend(record_findings)
    required = tuple(
        (change, line)
        for change in scoped
        if (line := first_record_requiring_line(change, allow_ambiguous=any(reasons))) is not None
    )
    if not required:
        return DecisionRecordResult(findings=tuple(sorted(findings)))
    if not satisfied:
        findings.extend(
            DecisionRecordFinding(
                path=change.path,
                line=line.line,
                code="MISSING_DECISION_RECORD",
                message="Normative or ambiguous concept change requires a decision record.",
            )
            for change, line in required
        )
    return DecisionRecordResult(findings=tuple(sorted(findings)))


def _evaluate_records(
    diff: ConceptDiff, commit_messages: tuple[str, ...]
) -> tuple[bool, list[DecisionRecordFinding]]:
    findings: list[DecisionRecordFinding] = []
    in_diff = tuple(
        change.post_path or change.path
        for change in diff.changed_files
        if change.change_kind in {"A", "M", "R"}
        and (change.post_path or change.path).startswith(DECISIONS_ROOT)
    )
    valid_name_in_diff = {path for path in in_diff if is_record_path_name_valid(path)}
    valid_in_diff = {path for path in valid_name_in_diff if path in diff.schema_conform_record_files}
    findings.extend(_malformed_finding(path) for path in in_diff if path not in valid_name_in_diff)
    valid_references: set[str] = set()
    for value in decision_trailers(commit_messages):
        path = record_path_for_trailer(value)
        if not is_record_path_name_valid(path):
            findings.append(_malformed_finding(path))
        elif path not in diff.record_files:
            findings.append(
                DecisionRecordFinding(path, 1, "DEAD_DECISION_RECORD_REFERENCE", "Referenced decision record does not exist.")
            )
        elif path in diff.schema_conform_record_files:
            valid_references.add(path)
    return bool(valid_in_diff or valid_references), findings


def _malformed_finding(path: str) -> DecisionRecordFinding:
    return DecisionRecordFinding(path, 1, "MALFORMED_DECISION_RECORD_NAME", "Decision record name violates the required schema.")


def _empty_reason_findings(
    scoped: tuple[ConceptFileChange, ...], reasons: tuple[str, ...]
) -> list[DecisionRecordFinding]:
    if not any(reason == "" for reason in reasons):
        return []
    first = min(scoped, key=lambda change: change.path)
    line = first.body_lines[0].line if first.body_lines else 1
    return [
        DecisionRecordFinding(
            first.path, line, "EMPTY_FORMAT_ONLY_REASON", "Concept-Format-Only requires a non-empty reason."
        )
    ]


def _is_in_scope(path: str) -> bool:
    return path.startswith("concept/") and not path.startswith(DECISIONS_ROOT)
