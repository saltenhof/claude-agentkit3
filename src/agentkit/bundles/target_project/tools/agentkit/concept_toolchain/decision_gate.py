"""W4 decision-record gate (concept governance section 5 W4, FK-78 78.14).

Determines changed Markdown files below the concept roots via
``git diff --name-only <base>`` (base against the working tree). The
obligation is satisfied when (a) the same diff adds or changes a
schema-conform named record below ``<meta-root>/decisions/`` or (b) a
``Concept-Decision: <slug>`` trailer (commit message or ``--trailer``)
references an existing schema-conform record. Dead or misnamed references
are ERROR.

A non-empty ``Concept-Format-Only: <reason>`` trailer exempts only
non-normative diffs. Simplified fail-closed heuristic: whitespace-only,
pure-punctuation, and anchor-/link-target-only changes are ignorable; a
normative modal marker is always normative; every other substantial text
change stays ambiguous and requires a record unless a format-only reason
is present.
"""

from __future__ import annotations

import difflib
import re
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .docmodel import body_lines
from .findings import CheckResult, error

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "decision-gate"

NORMATIVE_MODAL_RE = re.compile(
    r"\b(muss(?:t|en)?|darf\s+nur|sind?\s+pflicht|"
    r"single\s+source\s+of\s+truth|verboten|fail[-\s]closed|"
    r"shall|must)\b",
    re.IGNORECASE,
)
_DECISION_TRAILER_RE = re.compile(r"^Concept-Decision:[ \t]*(.*?)[ \t]*\r?$", re.MULTILINE)
_FORMAT_ONLY_TRAILER_RE = re.compile(r"^Concept-Format-Only:[ \t]*(.*?)[ \t]*\r?$", re.MULTILINE)
_MARKDOWN_TARGET_RE = re.compile(r"(?<=\]\()[^)]+(?=\))")
_BARE_URL_RE = re.compile(r"https?://[^\s)>]+")
_ANCHOR_RE = re.compile(
    r"\{#[A-Za-z0-9_.:-]+\}|<a\s+[^>]*id=[\"'][^\"']+[\"'][^>]*>\s*</a>|<!--\s*PROSE-FORMAL:\s*[^>]+-->",
    re.IGNORECASE,
)


class _GitError(Exception):
    pass


@dataclass(frozen=True)
class _ChangedLine:
    line: int
    text: str


@dataclass(frozen=True)
class _FileChange:
    path: str
    added: tuple[_ChangedLine, ...]
    removed: tuple[_ChangedLine, ...]


def run_decision_gate(project_root: Path, config: GovernanceConfig, base: str, trailers: Sequence[str]) -> CheckResult:
    """Run the W4 gate against ``base`` and the current working tree."""
    result = CheckResult(check_id=CHECK_ID)
    try:
        _git(project_root, "rev-parse", "--verify", f"{base}^{{commit}}")
    except _GitError as exc:
        result.complete = False
        result.incomplete_reason = f"base revision {base!r} is not resolvable: {exc}"
        return result
    try:
        changed = _changed_paths(project_root, base)
        messages = _commit_messages(project_root, base)
    except _GitError as exc:
        result.complete = False
        result.incomplete_reason = f"git diff against {base!r} failed: {exc}"
        return result
    decisions_prefix = f"{config.concept_roots['meta']}/decisions/"
    roots = tuple(config.concept_roots.values())
    changed_markdown = [path for path in changed if path.endswith(".md") and path.startswith(tuple(f"{root}/" for root in roots))]
    concept_changes = [path for path in changed_markdown if not path.startswith(decisions_prefix)]
    record_in_diff = _evaluate_records_in_diff(changed_markdown, decisions_prefix, config, result)
    if not concept_changes:
        result.summary = "no concept documents changed"
        return result
    reasons = _format_only_reasons(messages)
    _report_empty_reasons(reasons, concept_changes, result)
    trailer_satisfied = _evaluate_trailers(project_root, config, messages, trailers, decisions_prefix, result)
    allow_ambiguous = any(reason.strip() for reason in reasons)
    requiring = _record_requiring_changes(project_root, base, concept_changes, allow_ambiguous)
    if requiring and not (record_in_diff or trailer_satisfied):
        result.findings.extend(
            error(
                f"{CHECK_ID}.missing-record",
                change.path,
                f"L{line.line}",
                "normative or ambiguous concept change requires a decision record",
            )
            for change, line in requiring
        )
    result.summary = f"{len(concept_changes)} changed concept document(s) evaluated"
    return result


def _evaluate_records_in_diff(
    changed_markdown: Sequence[str], decisions_prefix: str, config: GovernanceConfig, result: CheckResult
) -> bool:
    grammar = config.id_grammars["decision_record"]
    satisfied = False
    for path in changed_markdown:
        if not path.startswith(decisions_prefix):
            continue
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        if grammar.fullmatch(stem) is None:
            result.findings.append(
                error(f"{CHECK_ID}.record-name", path, "filename", "decision record name violates the configured grammar")
            )
        else:
            satisfied = True
    return satisfied


def _evaluate_trailers(
    project_root: Path,
    config: GovernanceConfig,
    messages: Sequence[str],
    cli_trailers: Sequence[str],
    decisions_prefix: str,
    result: CheckResult,
) -> bool:
    grammar = config.id_grammars["decision_record"]
    values = [match.group(1) for message in messages for match in _DECISION_TRAILER_RE.finditer(message)]
    values.extend(cli_trailers)
    satisfied = False
    for value in values:
        stem = value.removesuffix(".md")
        record_path = f"{decisions_prefix}{stem}.md"
        if not stem or grammar.fullmatch(stem) is None:
            message = f"Concept-Decision reference {value!r} violates the configured grammar"
            result.findings.append(error(f"{CHECK_ID}.record-name", record_path, "trailer", message))
            continue
        if not (project_root / record_path).is_file():
            message = f"Concept-Decision reference {value!r} does not resolve to an existing record"
            result.findings.append(error(f"{CHECK_ID}.dead-reference", record_path, "trailer", message))
            continue
        satisfied = True
    return satisfied


def _format_only_reasons(messages: Sequence[str]) -> tuple[str, ...]:
    return tuple(match.group(1) for message in messages for match in _FORMAT_ONLY_TRAILER_RE.finditer(message))


def _report_empty_reasons(reasons: Sequence[str], concept_changes: Sequence[str], result: CheckResult) -> None:
    if any(reason.strip() == "" for reason in reasons):
        result.findings.append(
            error(f"{CHECK_ID}.format-only", min(concept_changes), "trailer", "Concept-Format-Only requires a non-empty reason")
        )


def _record_requiring_changes(
    project_root: Path, base: str, concept_changes: Sequence[str], allow_ambiguous: bool
) -> list[tuple[_FileChange, _ChangedLine]]:
    requiring: list[tuple[_FileChange, _ChangedLine]] = []
    for path in sorted(concept_changes):
        change = _load_file_change(project_root, base, path)
        line = _first_record_requiring_line(change, allow_ambiguous=allow_ambiguous)
        if line is not None:
            requiring.append((change, line))
    return requiring


def _load_file_change(project_root: Path, base: str, path: str) -> _FileChange:
    try:
        old_text = _git(project_root, "show", f"{base}:{path}")
    except _GitError:
        old_text = ""
    target = project_root / path
    new_text = target.read_text(encoding="utf-8") if target.is_file() else ""
    old_body = body_lines(old_text)
    new_body = body_lines(new_text)
    matcher = difflib.SequenceMatcher(a=[text for _, text in old_body], b=[text for _, text in new_body], autojunk=False)
    added: list[_ChangedLine] = []
    removed: list[_ChangedLine] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(_ChangedLine(line=old_body[i][0], text=old_body[i][1]) for i in range(old_start, old_end))
        if tag in ("replace", "insert"):
            added.extend(_ChangedLine(line=new_body[i][0], text=new_body[i][1]) for i in range(new_start, new_end))
    return _FileChange(path=path, added=tuple(added), removed=tuple(removed))


def _first_record_requiring_line(change: _FileChange, *, allow_ambiguous: bool) -> _ChangedLine | None:
    link_only = _link_only_line_ids(change)
    normative: list[_ChangedLine] = []
    ambiguous: list[_ChangedLine] = []
    for side, lines in (("added", change.added), ("removed", change.removed)):
        for index, line in enumerate(lines):
            if (side, index) in link_only or not line.text.strip() or _is_pure_punctuation(line.text):
                continue
            if NORMATIVE_MODAL_RE.search(line.text):
                normative.append(line)
            else:
                ambiguous.append(line)
    if normative:
        return min(normative, key=lambda item: item.line)
    if ambiguous and not allow_ambiguous:
        return min(ambiguous, key=lambda item: item.line)
    return None


def _is_pure_punctuation(text: str) -> bool:
    characters = [character for character in text if not character.isspace()]
    return all(unicodedata.category(character).startswith("P") for character in characters)


def _link_only_line_ids(change: _FileChange) -> frozenset[tuple[str, int]]:
    added = _normalized_candidates(change.added)
    removed = _normalized_candidates(change.removed)
    shared = Counter(key for key, _ in added) & Counter(key for key, _ in removed)
    matched: set[tuple[str, int]] = set()
    for key, count in shared.items():
        matched.update(("added", index) for _, index in [pair for pair in added if pair[0] == key][:count])
        matched.update(("removed", index) for _, index in [pair for pair in removed if pair[0] == key][:count])
    return frozenset(matched)


def _normalized_candidates(lines: tuple[_ChangedLine, ...]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        normalized = _ANCHOR_RE.sub("", line.text)
        normalized = _MARKDOWN_TARGET_RE.sub("<TARGET>", normalized)
        normalized = _BARE_URL_RE.sub("<URL>", normalized)
        if normalized != line.text:
            candidates.append((normalized, index))
    return candidates


def _changed_paths(project_root: Path, base: str) -> tuple[str, ...]:
    output = _git(project_root, "diff", "--name-only", "-z", base)
    return tuple(part.replace("\\", "/") for part in output.split("\0") if part)


def _commit_messages(project_root: Path, base: str) -> tuple[str, ...]:
    output = _git(project_root, "log", "--format=%B%x00", f"{base}..HEAD")
    return tuple(message for message in output.split("\0") if message.strip())


def _git(project_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise _GitError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout
