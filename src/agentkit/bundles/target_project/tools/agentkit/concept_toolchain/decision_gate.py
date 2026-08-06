"""W4 decision-record gate (concept governance section 5 W4, FK-78 78.14).

Determines changed Markdown files below the concept roots as the union of
``git diff --name-only <base>`` (tracked changes against ``base``) and
``git ls-files --others --exclude-standard`` (untracked but unignored
working-tree files). A brand-new concept document is a change even before
it is staged, and no diff can report it. The obligation is satisfied when
(a) that change set adds or changes a schema-conform named record below
``<meta-root>/decisions/`` or (b) a ``Concept-Decision: <slug>`` trailer
references a schema-conform record. Dead or misnamed references are ERROR.

A trailer is resolved against the state its own provenance can vouch for.
A trailer read from a commit message is a claim made by a commit, so its
record must exist as a committed blob at ``HEAD``; a file lying in the
working tree proves nothing about a commit. A ``--trailer`` names work
that is being prepared and is therefore resolved against the working
tree, conjunctively: the record must be versionable content known to git
(tracked or untracked-unignored) and present on disk.

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
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "decision-gate"

NORMATIVE_MODAL_RE = re.compile(
    r"\b(muss(?:t|en)?|darf\s+nur|sind?\s+pflicht|"
    r"single\s+source\s+of\s+truth|verboten|fail[-\s]closed|"
    r"shall|must)\b",
    re.IGNORECASE,
)
_MARKDOWN_TARGET_RE = re.compile(r"(?<=\]\()[^)]+(?=\))")
_BARE_URL_RE = re.compile(r"https?://[^\s)>]+")


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
    """Run the W4 gate against ``base`` and the current working tree.

    "Working tree" is meant literally: untracked but unignored documents
    count as changes, so the gate sees the state the author has in front of
    them rather than the state that happens to be staged.
    """
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
    try:
        trailer_satisfied = _evaluate_trailers(project_root, config, messages, trailers, decisions_prefix, result)
    except _GitError as exc:
        result.complete = False
        result.incomplete_reason = f"decision-record resolution failed: {exc}"
        return result
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
    committed = tuple((value, _committed_record_unmet) for value in _trailer_values(messages, "Concept-Decision:"))
    prepared = tuple((value, _prepared_record_unmet) for value in cli_trailers)
    satisfied = False
    for value, unmet_condition in (*committed, *prepared):
        stem = value.removesuffix(".md")
        record_path = f"{decisions_prefix}{stem}.md"
        if not stem or grammar.fullmatch(stem) is None:
            message = f"Concept-Decision reference {value!r} violates the configured grammar"
            result.findings.append(error(f"{CHECK_ID}.record-name", record_path, "trailer", message))
            continue
        unmet = unmet_condition(project_root, record_path)
        if unmet is not None:
            message = f"Concept-Decision reference {value!r} {unmet}"
            result.findings.append(error(f"{CHECK_ID}.dead-reference", record_path, "trailer", message))
            continue
        satisfied = True
    return satisfied


def _committed_record_unmet(project_root: Path, record_path: str) -> str | None:
    """Return why a commit-borne trailer does not resolve at ``HEAD``."""
    try:
        _git(project_root, "cat-file", "-e", f"HEAD:{record_path}")
    except _GitError:
        return "does not resolve to a record committed at HEAD"
    return None


def _prepared_record_unmet(project_root: Path, record_path: str) -> str | None:
    """Return why a prepared trailer does not resolve in the working tree.

    Two conjunctive conditions, and the message names the one that failed.
    Git decides whether the record is versionable content at all -- an
    ignored file below ``decisions/`` is not, and a bare ``is_file()`` would
    have accepted it. The working tree decides whether it is there now.
    """
    listed = _git(
        project_root, "ls-files", "--full-name", "--cached", "--others", "--exclude-standard", "-z", "--", record_path
    )
    if not any(listed.split("\0")):
        return "does not name versionable repository content"
    if not (project_root / record_path).is_file():
        return "is known to git but absent from the working tree"
    return None


def _format_only_reasons(messages: Sequence[str]) -> tuple[str, ...]:
    return tuple(_trailer_values(messages, "Concept-Format-Only:"))


def _trailer_values(messages: Sequence[str], prefix: str) -> tuple[str, ...]:
    return tuple(line[len(prefix) :].strip() for message in messages for line in message.splitlines() if line.startswith(prefix))


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
        normalized = _remove_anchor_markup(line.text)
        normalized = _MARKDOWN_TARGET_RE.sub("<TARGET>", normalized)
        normalized = _BARE_URL_RE.sub("<URL>", normalized)
        if normalized != line.text:
            candidates.append((normalized, index))
    return candidates


def _remove_anchor_markup(text: str) -> str:
    """Remove supported anchor markup using bounded delimiter searches."""
    text = _remove_matching_spans(
        text,
        "{#",
        "}",
        lambda span: bool(span[2:-1]) and all(char.isalnum() or char in "_.:-" for char in span[2:-1]),
    )
    text = _remove_matching_spans(
        text,
        "<a",
        "</a>",
        lambda span: "id=" in span[: span.find(">")].lower(),
    )
    text = _remove_matching_spans(
        text,
        "<!--",
        "-->",
        lambda span: span[4:-3].strip().upper().startswith("PROSE-FORMAL:"),
    )
    return text


def _remove_matching_spans(
    text: str,
    opener: str,
    closer: str,
    accept: Callable[[str], bool],
) -> str:
    search_from = 0
    while (start := text.find(opener, search_from)) >= 0:
        end = text.find(closer, start + len(opener))
        if end < 0:
            break
        end += len(closer)
        span = text[start:end]
        if accept(span):
            text = text[:start] + text[end:]
            search_from = start
        else:
            search_from = end
    return text


def _changed_paths(project_root: Path, base: str) -> tuple[str, ...]:
    """Return every versionable path that differs from ``base`` right now.

    Two sources, unioned, because neither alone answers the question. ``git
    diff`` reports paths git already knows -- committed, staged and unstaged
    -- and cannot report a file git has never seen, which is exactly what a
    brand-new concept document is. ``git ls-files --others
    --exclude-standard`` supplies that remainder, and ``--exclude-standard``
    keeps generated artefacts out, so an ignored file is not smuggled in as
    a concept change.
    """
    tracked = _git(project_root, "diff", "--name-only", "-z", base)
    # ``--full-name`` keeps both halves in the same path base: ``git ls-files``
    # reports relative to the current directory, ``git diff`` relative to the
    # repository root.
    untracked = _git(project_root, "ls-files", "--full-name", "--others", "--exclude-standard", "-z")
    parts = (*tracked.split("\0"), *untracked.split("\0"))
    return tuple(sorted({part.replace("\\", "/") for part in parts if part}))


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
