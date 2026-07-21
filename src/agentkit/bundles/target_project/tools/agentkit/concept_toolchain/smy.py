"""Parser for the SMY subset (Structured Metadata YAML, FK-78 section 78.14).

Supported: block mappings, block sequences, plain/single-/double-quoted
scalars, folded ``>`` scalars (including ``>-``), comments, and simple
one-line flow lists (``[a, b]``).

Not supported and rejected fail-closed with a line number: anchors (``&``),
aliases (``*``), tags (``!``/``!!``), multi-document markers (``---``)
inside the body, literal ``|`` scalars, flow mappings, and nested flow
styles.

The only type conversions are unquoted ``true``/``false`` to ``bool`` and
pure integers to ``int``. Empty values become ``None``.
"""

from __future__ import annotations

import re

_INT_RE = re.compile(r"^-?\d+$")
_KEY_LINE_RE = re.compile(r"^(?P<key>[^\s#&*!\[\{'\"|>-][^:#]*?):(?: (?P<rest>.*))?$")
_TRAILING_COMMENT_RE = re.compile(r"\s#.*$")


class SmyError(Exception):
    """Raised when input is outside the SMY subset or malformed."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


class _Cursor:
    """Line-based view over the raw input with indentation metadata."""

    def __init__(self, text: str) -> None:
        self.indents: list[int] = []
        self.contents: list[str] = []
        for number, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.lstrip(" ")
            indent = len(raw) - len(stripped)
            if stripped.startswith("\t") or "\t" in raw[:indent]:
                raise SmyError(number, "tab indentation is not supported")
            self.indents.append(indent)
            self.contents.append(stripped.rstrip())

    def next_content(self, index: int) -> int | None:
        """Return the next structural line index at or after *index*."""
        for position in range(index, len(self.contents)):
            content = self.contents[position]
            if content and not content.startswith("#"):
                return position
        return None


def parse_smy(text: str) -> dict[str, object]:
    """Parse *text* as an SMY block mapping.

    Args:
        text: The SMY document body (frontmatter payload or spec zone).

    Returns:
        The parsed top-level mapping.

    Raises:
        SmyError: If the input is malformed or uses unsupported YAML.
    """
    cursor = _Cursor(text)
    first = cursor.next_content(0)
    if first is None:
        return {}
    _reject_structural_markers(cursor.contents[first], first + 1)
    if cursor.contents[first].startswith("- ") or cursor.contents[first] == "-":
        raise SmyError(first + 1, "top-level value must be a block mapping")
    value, stop = _parse_mapping(cursor, first, cursor.indents[first])
    trailing = cursor.next_content(stop)
    if trailing is not None:
        raise SmyError(trailing + 1, "unexpected content after top-level mapping")
    return value


def _parse_block(cursor: _Cursor, index: int, indent: int) -> tuple[object, int]:
    content = cursor.contents[index]
    if content.startswith("- ") or content == "-":
        return _parse_sequence(cursor, index, indent)
    return _parse_mapping(cursor, index, indent)


def _parse_mapping(cursor: _Cursor, index: int, indent: int) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {}
    position = index
    while True:
        current = cursor.next_content(position)
        if current is None or cursor.indents[current] < indent:
            return result, position if current is None else current
        if cursor.indents[current] > indent:
            raise SmyError(current + 1, "unexpected indentation inside mapping")
        content = cursor.contents[current]
        _reject_structural_markers(content, current + 1)
        if content.startswith("- ") or content == "-":
            raise SmyError(current + 1, "sequence item is not allowed directly inside a mapping")
        key, rest = _split_key(content, current + 1)
        if key in result:
            raise SmyError(current + 1, f"duplicate mapping key {key!r}")
        value, position = _parse_value(cursor, current, indent, rest)
        result[key] = value


def _split_key(content: str, line: int) -> tuple[str, str]:
    match = _KEY_LINE_RE.match(content)
    if match is None:
        raise SmyError(line, "expected a 'key: value' mapping entry")
    key = match.group("key").strip()
    rest = (match.group("rest") or "").strip()
    if rest.startswith("#"):
        rest = ""
    return key, rest


def _parse_value(cursor: _Cursor, index: int, indent: int, rest: str) -> tuple[object, int]:
    if rest == "":
        return _parse_nested_value(cursor, index, indent)
    if rest in (">", ">-"):
        return _parse_folded(cursor, index, indent, chomp=(rest == ">-"))
    return _parse_scalar_value(cursor, index, indent, rest)


def _parse_nested_value(cursor: _Cursor, index: int, indent: int) -> tuple[object, int]:
    following = cursor.next_content(index + 1)
    if following is None or cursor.indents[following] < indent:
        return None, index + 1
    child_content = cursor.contents[following]
    child_is_item = child_content.startswith("- ") or child_content == "-"
    if cursor.indents[following] == indent:
        if child_is_item:
            return _parse_sequence(cursor, following, indent)
        return None, index + 1
    return _parse_block(cursor, following, cursor.indents[following])


def _parse_sequence(cursor: _Cursor, index: int, indent: int) -> tuple[list[object], int]:
    items: list[object] = []
    position = index
    while True:
        current = cursor.next_content(position)
        if current is None or cursor.indents[current] < indent:
            return items, position if current is None else current
        if cursor.indents[current] > indent:
            raise SmyError(current + 1, "unexpected indentation inside sequence")
        content = cursor.contents[current]
        _reject_structural_markers(content, current + 1)
        if not (content.startswith("- ") or content == "-"):
            return items, current
        item, position = _parse_sequence_item(cursor, current, indent, content)
        items.append(item)


def _parse_sequence_item(cursor: _Cursor, index: int, indent: int, content: str) -> tuple[object, int]:
    body = content[2:].strip() if content != "-" else ""
    if body == "":
        following = cursor.next_content(index + 1)
        if following is None or cursor.indents[following] <= indent:
            return None, index + 1
        return _parse_block(cursor, following, cursor.indents[following])
    if body.startswith("- ") or body == "-":
        raise SmyError(index + 1, "nested inline sequence items are not supported")
    if _KEY_LINE_RE.match(body) is not None:
        item_column = cursor.indents[index] + (len(content) - len(content[2:].lstrip()))
        cursor.indents[index] = item_column
        cursor.contents[index] = body
        return _parse_mapping(cursor, index, item_column)
    if body in (">", ">-"):
        return _parse_folded(cursor, index, indent, chomp=(body == ">-"))
    return _parse_scalar_value(cursor, index, indent, body)


def _parse_folded(cursor: _Cursor, index: int, indent: int, *, chomp: bool) -> tuple[str, int]:
    paragraphs: list[list[str]] = [[]]
    position = index + 1
    while position < len(cursor.contents):
        content = cursor.contents[position]
        if content == "":
            if paragraphs[-1]:
                paragraphs.append([])
            position += 1
            continue
        if cursor.indents[position] <= indent:
            break
        paragraphs[-1].append(content)
        position += 1
    text = "\n".join(" ".join(parts) for parts in paragraphs if parts)
    if not chomp and text:
        text += "\n"
    return text, position


_UNSUPPORTED_HEADS = {
    "&": "anchors are not supported",
    "*": "aliases are not supported",
    "!": "tags are not supported",
    "{": "flow mappings are not supported",
    "|": "literal block scalars are not supported",
    ">": "folded scalar markers must not carry inline content",
}


def _parse_scalar_value(cursor: _Cursor, index: int, indent: int, rest: str) -> tuple[object, int]:
    line = index + 1
    head = rest[0]
    if head in _UNSUPPORTED_HEADS:
        raise SmyError(line, _UNSUPPORTED_HEADS[head])
    if head == "[":
        return _parse_flow_value(cursor, index, indent, rest)
    if head in ("'", '"'):
        value, consumed = _read_quoted_body(rest, head, line)
        _require_only_comment(rest[consumed:], line)
        return value, index + 1
    return _parse_plain_value(cursor, index, indent, rest)


def _parse_plain_value(cursor: _Cursor, index: int, indent: int, rest: str) -> tuple[object, int]:
    parts = [_strip_trailing_comment(rest)]
    position = index + 1
    while position < len(cursor.contents):
        content = cursor.contents[position]
        if content == "" or content.startswith("#") or cursor.indents[position] <= indent:
            break
        if content.startswith("- ") or content == "-" or _KEY_LINE_RE.match(content) is not None:
            raise SmyError(position + 1, "structural entry inside a plain scalar continuation")
        parts.append(_strip_trailing_comment(content))
        position += 1
    if len(parts) == 1:
        return _convert_plain(parts[0]), position
    return " ".join(parts), position


def _parse_flow_value(cursor: _Cursor, index: int, indent: int, rest: str) -> tuple[object, int]:
    line = index + 1
    buffer = rest
    position = index + 1
    while True:
        scanned = _scan_flow_list(buffer, line)
        if scanned is not None:
            tokens, consumed = scanned
            _require_only_comment(buffer[consumed:], line)
            return _flow_tokens_to_items(tokens, line), position
        if position >= len(cursor.contents):
            raise SmyError(line, "flow list must be closed before the end of the document")
        content = cursor.contents[position]
        if content == "" or cursor.indents[position] <= indent:
            raise SmyError(line, "flow list must be closed before the block ends")
        buffer += " " + content
        position += 1


def _flow_tokens_to_items(tokens: list[str], line: int) -> list[object]:
    items: list[object] = []
    for token in tokens:
        item = token.strip()
        if item == "":
            raise SmyError(line, "empty flow list item")
        if item[0] in ("'", '"'):
            value, used = _read_quoted_body(item, item[0], line)
            _require_only_comment(item[used:], line)
            items.append(value)
        else:
            items.append(_convert_plain(item))
    return items


def _strip_trailing_comment(value: str) -> str:
    return _TRAILING_COMMENT_RE.sub("", value).strip()


def _convert_plain(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if _INT_RE.match(value):
        return int(value)
    return value


def _require_only_comment(remainder: str, line: int) -> None:
    stripped = remainder.strip()
    if stripped and not stripped.startswith("#"):
        raise SmyError(line, "unexpected content after scalar")


def _read_quoted_body(rest: str, quote: str, line: int) -> tuple[str, int]:
    characters: list[str] = []
    position = 1
    while position < len(rest):
        char = rest[position]
        if quote == "'" and char == "'":
            if position + 1 < len(rest) and rest[position + 1] == "'":
                characters.append("'")
                position += 2
                continue
            return "".join(characters), position + 1
        if quote == '"' and char == "\\" and position + 1 < len(rest):
            characters.append(_double_quote_escape(rest[position + 1]))
            position += 2
            continue
        if quote == '"' and char == '"':
            return "".join(characters), position + 1
        characters.append(char)
        position += 1
    raise SmyError(line, "unterminated quoted scalar")


def _double_quote_escape(char: str) -> str:
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    return escapes.get(char, "\\" + char)


def _scan_flow_list(rest: str, line: int) -> tuple[list[str], int] | None:
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    position = 1
    while position < len(rest):
        char = rest[position]
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif char in ("[", "{"):
            raise SmyError(line, "nested flow styles are not supported")
        elif char == "]":
            joined = "".join(current)
            if joined.strip() or tokens:
                tokens.append(joined)
            return tokens, position + 1
        elif char == ",":
            tokens.append("".join(current))
            current = []
        else:
            current.append(char)
        position += 1
    return None


def _reject_structural_markers(content: str, line: int) -> None:
    if content == "---" or content.startswith("--- "):
        raise SmyError(line, "multi-document markers are not supported")
    if content == "...":
        raise SmyError(line, "document end markers are not supported")
