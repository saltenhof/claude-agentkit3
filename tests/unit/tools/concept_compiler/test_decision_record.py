"""Unit tests for the pure W4 concept decision-record compliance core."""

from __future__ import annotations

from pathlib import Path

import pytest
from concept_compiler.decision_record import (
    evaluate_decision_record_compliance,
)
from concept_compiler.decision_record_diff import changed_body_lines
from concept_compiler.decision_record_models import (
    ChangedBodyLine,
    ConceptDiff,
    ConceptFileChange,
    DecisionRecordResult,
)
from concept_compiler.decision_record_records import validate_decision_record_file
from concept_compiler.decision_record_render import render_decision_record_result

DECISIONS_ROOT = "concept/_meta/decisions/"
VALID_RECORD = f"{DECISIONS_ROOT}2026-07-13-example-decision.md"


def _change(
    path: str = "concept/technical-design/example.md",
    *,
    added: tuple[str, ...] = ("The worker must stop.",),
    removed: tuple[str, ...] = (),
    kind: str = "M",
) -> ConceptFileChange:
    return ConceptFileChange(
        path=path,
        change_kind=kind,
        added_body_lines=tuple(ChangedBodyLine(line=index + 10, text=text) for index, text in enumerate(added)),
        removed_body_lines=tuple(ChangedBodyLine(line=index + 20, text=text) for index, text in enumerate(removed)),
    )


def _evaluate(
    *changes: ConceptFileChange,
    messages: tuple[str, ...] = (),
    records: frozenset[str] = frozenset(),
) -> DecisionRecordResult:
    return evaluate_decision_record_compliance(
        ConceptDiff(
            changed_files=changes,
            record_files=records,
            schema_conform_record_files=records,
        ),
        messages,
    )


def test_ac1_normative_change_without_record_is_error_and_byte_stable() -> None:
    result = _evaluate(_change())

    assert [finding.code for finding in result.findings] == ["MISSING_DECISION_RECORD"]
    assert result.findings[0].line == 10
    assert render_decision_record_result(result).encode() == (
        b"[ERROR] MISSING_DECISION_RECORD concept/technical-design/example.md:10 - "
        b"Normative or ambiguous concept change requires a decision record.\n"
        b"[ERROR] concept-decision-record: 1 error(s)"
    )


def test_ac2a_in_diff_decision_record_satisfies_normative_change() -> None:
    result = _evaluate(_change(), _change(VALID_RECORD, kind="A"), records=frozenset({VALID_RECORD}))

    assert result.ok


def test_well_named_record_with_invalid_frontmatter_does_not_satisfy() -> None:
    diff = ConceptDiff(
        changed_files=(_change(), _change(VALID_RECORD, kind="A")),
        record_files=frozenset({VALID_RECORD}),
    )

    result = evaluate_decision_record_compliance(diff, ())

    assert [finding.code for finding in result.findings] == ["MISSING_DECISION_RECORD"]


def test_ac2b_existing_record_trailer_satisfies_normative_change() -> None:
    result = _evaluate(
        _change(),
        messages=("Implement change\r\n\r\nConcept-Decision: 2026-07-13-example-decision.md\r\n",),
        records=frozenset({VALID_RECORD}),
    )

    assert result.ok


def test_ac2c_dead_record_trailer_is_error() -> None:
    result = _evaluate(_change(), messages=("Concept-Decision: 2026-07-13-missing\n",))

    assert [finding.code for finding in result.findings] == [
        "DEAD_DECISION_RECORD_REFERENCE",
        "MISSING_DECISION_RECORD",
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_change(f"{DECISIONS_ROOT}bad_name.md", kind="A"), ""),
        (_change(), "Concept-Decision: BAD-NAME\n"),
    ],
)
def test_ac2d_malformed_in_diff_or_referenced_record_name_is_error(
    change: ConceptFileChange, message: str
) -> None:
    changes = (_change(), change) if change.path.startswith(DECISIONS_ROOT) else (change,)
    result = _evaluate(*changes, messages=(message,) if message else ())

    assert "MALFORMED_DECISION_RECORD_NAME" in {finding.code for finding in result.findings}


def test_malformed_record_rename_is_not_masked_by_valid_in_diff_record() -> None:
    malformed_rename = ConceptFileChange(
        path="concept/technical-design/old-policy.md",
        post_path=f"{DECISIONS_ROOT}bad_name.md",
        change_kind="R",
        removed_body_lines=(ChangedBodyLine(line=10, text="The worker must stop."),),
    )
    result = _evaluate(
        malformed_rename,
        _change(VALID_RECORD, kind="A"),
        records=frozenset({VALID_RECORD}),
    )

    assert [finding.code for finding in result.findings] == ["MALFORMED_DECISION_RECORD_NAME"]


def test_ac3_punctuation_and_link_target_only_change_is_exempt() -> None:
    punctuation = _change(added=("---",), removed=("--",))
    link = _change(
        path="concept/domain-design/links.md",
        added=("See [the policy](#new-anchor).",),
        removed=("See [the policy](#old-anchor).",),
    )

    assert _evaluate(punctuation, link).ok


def test_semantic_symbol_change_is_ambiguous_not_pure_punctuation() -> None:
    result = _evaluate(_change(added=("| ❌ |",), removed=("| ✅ |",)))

    assert [finding.code for finding in result.findings] == ["MISSING_DECISION_RECORD"]


def test_ac3b_ambiguous_change_is_fail_closed() -> None:
    result = _evaluate(_change(added=("The retry window is five minutes.",)))

    assert [finding.code for finding in result.findings] == ["MISSING_DECISION_RECORD"]


def test_ac3c_ambiguous_change_with_format_only_reason_is_exempt() -> None:
    result = _evaluate(
        _change(added=("Corrected a spelling error.",)),
        messages=("Concept-Format-Only: spelling correction\n",),
    )

    assert result.ok


def test_ac3d_normative_change_with_format_only_reason_is_not_bypassed() -> None:
    result = _evaluate(_change(), messages=("Concept-Format-Only: wording only\n",))

    assert [finding.code for finding in result.findings] == ["MISSING_DECISION_RECORD"]


def test_empty_format_only_reason_is_error_and_does_not_downgrade() -> None:
    result = _evaluate(
        _change(added=("Corrected a spelling error.",)),
        messages=("Concept-Format-Only:   \n",),
    )

    assert [finding.code for finding in result.findings] == [
        "EMPTY_FORMAT_ONLY_REASON",
        "MISSING_DECISION_RECORD",
    ]


@pytest.mark.parametrize("value", ["2026-07-13-missing", "BAD-NAME"])
def test_dead_or_malformed_reference_is_error_even_for_exempt_change(value: str) -> None:
    result = _evaluate(
        _change(added=("---",), removed=("--",)),
        messages=(f"Concept-Decision: {value}\n",),
    )

    assert not result.ok
    assert result.findings[0].code in {
        "DEAD_DECISION_RECORD_REFERENCE",
        "MALFORMED_DECISION_RECORD_NAME",
    }


@pytest.mark.parametrize(
    "record_name",
    [
        "2026-07-02-k1-worktree-topologie.md",
        "2026-07-02-session-ownership-nachverankerung.md",
    ],
)
def test_ac4_existing_record_precedents_are_schema_conform(record_name: str) -> None:
    assert validate_decision_record_file(Path("concept/_meta/decisions") / record_name)


@pytest.mark.parametrize(
    "change",
    [
        _change("src/agentkit/example.py"),
        _change("tests/unit/test_example.py"),
        _change("stories/AG3-999/story.md"),
        _change(VALID_RECORD, kind="M"),
    ],
)
def test_ac5_out_of_scope_or_decisions_only_diff_has_no_findings(change: ConceptFileChange) -> None:
    assert _evaluate(change).ok


def test_adapter_line_split_excludes_frontmatter_and_fenced_code() -> None:
    old = "---\ntitle: Old\n---\nBefore\n```text\nThe worker must stop.\n```\n"
    new = "---\ntitle: New\n---\nAfter\n```text\nThe worker shall stop.\n```\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(4, "After")]
    assert [(line.line, line.text) for line in removed] == [(4, "Before")]


def test_adapter_line_split_fails_closed_on_unclosed_frontmatter() -> None:
    added, removed = changed_body_lines("", "---\nThe worker must stop.\n")

    assert [(line.line, line.text) for line in added] == [(2, "The worker must stop.")]
    assert removed == ()


def test_adapter_line_split_respects_opening_fence_length() -> None:
    old = "````text\n```\nold code\n````\nThe worker is optional.\n"
    new = "````text\n```\nnew code must stop\n````\nThe worker must stop.\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(5, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(5, "The worker is optional.")]


def test_adapter_line_split_detects_body_text_moved_into_fence() -> None:
    old = "The worker must stop.\n"
    new = "```text\nThe worker must stop.\n```\n"

    added, removed = changed_body_lines(old, new)

    assert added == ()
    assert [(line.line, line.text) for line in removed] == [(1, "The worker must stop.")]


def test_adapter_line_split_rejects_closing_fence_with_suffix() -> None:
    old = "```text\n```not-a-close\nold code\n```\nThe worker is optional.\n"
    new = "```text\n```not-a-close\nnew code must stop\n```\nThe worker must stop.\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(5, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(5, "The worker is optional.")]


def test_adapter_line_split_does_not_treat_four_space_indent_as_fence() -> None:
    old = "    ```\nThe worker is optional.\n    ```\n"
    new = "    ```\nThe worker must stop.\n    ```\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(2, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(2, "The worker is optional.")]


def test_adapter_line_split_does_not_accept_backtick_in_opener_info() -> None:
    old = "```bad`info\nThe worker is optional.\n```\n"
    new = "```bad`info\nThe worker must stop.\n```\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(2, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(2, "The worker is optional.")]


def test_adapter_line_split_treats_indented_pseudo_frontmatter_as_body() -> None:
    old = " ---\nThe worker is optional.\n---\n"
    new = " ---\nThe worker must stop.\n---\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(2, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(2, "The worker is optional.")]


def test_adapter_line_split_rejects_indented_frontmatter_close() -> None:
    old = "---\nThe worker is optional.\n ---\n"
    new = "---\nThe worker must stop.\n ---\n"

    added, removed = changed_body_lines(old, new)

    assert [(line.line, line.text) for line in added] == [(2, "The worker must stop.")]
    assert [(line.line, line.text) for line in removed] == [(2, "The worker is optional.")]
