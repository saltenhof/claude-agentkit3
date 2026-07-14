"""Markdown body extraction and deterministic line differencing."""

from __future__ import annotations

import difflib
import re

from .decision_record_models import ChangedBodyLine

_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<suffix>.*)$")


def changed_body_lines(
    old_text: str, new_text: str
) -> tuple[tuple[ChangedBodyLine, ...], tuple[ChangedBodyLine, ...]]:
    """Return added and removed body lines, excluding frontmatter and fences."""
    old_body = _body_lines(old_text.splitlines())
    new_body = _body_lines(new_text.splitlines())
    added: list[ChangedBodyLine] = []
    removed: list[ChangedBodyLine] = []
    matcher = difflib.SequenceMatcher(
        a=[text for _, text in old_body],
        b=[text for _, text in new_body],
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed.extend(
                ChangedBodyLine(line=old_body[index][0], text=old_body[index][1])
                for index in range(old_start, old_end)
            )
        if tag in {"replace", "insert"}:
            added.extend(
                ChangedBodyLine(line=new_body[index][0], text=new_body[index][1])
                for index in range(new_start, new_end)
            )
    return tuple(added), tuple(removed)


def _body_lines(lines: list[str]) -> list[tuple[int, str]]:
    frontmatter_end = _frontmatter_end(lines)
    in_fence = False
    fence_token = ""
    body: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        if index <= frontmatter_end:
            continue
        match = _FENCE_RE.match(line)
        if match:
            token = match.group("fence")
            if not in_fence:
                if token[0] == "`" and "`" in match.group("suffix"):
                    body.append((index, line))
                    continue
                in_fence, fence_token = True, token
            elif (
                token[0] == fence_token[0]
                and len(token) >= len(fence_token)
                and not match.group("suffix").strip()
            ):
                in_fence, fence_token = False, ""
            continue
        if not in_fence:
            body.append((index, line))
    return body


def _frontmatter_end(lines: list[str]) -> int:
    if not lines or lines[0] != "---":
        return 0
    for index, line in enumerate(lines[1:], start=2):
        if line == "---":
            return index
    return 1
