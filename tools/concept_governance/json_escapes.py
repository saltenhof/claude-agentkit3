"""Repair of markdown escapes that leak into LLM JSON responses (W2/W3).

Two repairs, deliberately kept apart, because the leaked backslash means
something different on each side of a JSON pair:

* In a **value** it may be content. Our chunks are markdown and a model
  that quotes one back quotes its escapes with it, so the backslash has to
  SURVIVE — :func:`repair_markdown_escapes` therefore escapes it instead
  of dropping it, and the decoded value stays character-identical.
* In a **key** it can never be content. The response schemas are closed
  vocabularies of ``snake_case`` identifiers; a key with a backslash
  matches no field and is rejected as an unknown one. There the backslash
  is dropped — :func:`normalize_schema_keys`, which works on the PARSED
  document, so "key" is a structural fact and not a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any

BACKSLASH = "\\"

#: JSON's complete escape alphabet (RFC 8259 section 7).
_VALID_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')

#: Any backslash sequence, valid or not. ``re.S`` so a stray backslash before
#: a newline is matched too instead of being left behind.
_ANY_ESCAPE = re.compile(r"\\(?:u[0-9a-fA-F]{4}|.)", re.S)


def repair_markdown_escapes(text: str) -> str:
    """Escape backslashes that JSON does not recognise as escapes.

    Our concept prose is markdown, and markdown escapes the pipes and
    underscores inside tables (``\\|``, ``\\_``). Models quote those cells
    back verbatim, where the backslash is no longer an escape but a syntax
    error: ``Invalid JSON: invalid escape``. A single such cell used to end
    a whole governance run (AG3-179), and patching one character class at a
    time only moves the next failure one table over — ``\\_`` was fixed
    before, ``\\|`` came next.

    The stray backslash is DOUBLED, never dropped. Dropping it produces
    valid JSON that decodes to different text: the quoted cell
    ```LIGHT\\_INCUBATION` \\| `FULL\\_ATOM``` would come back as
    ```LIGHT_INCUBATION` | `FULL_ATOM```, and ``C:\\Program`` would come
    back as ``C:Program``. A quotation that no longer matches the chunk it
    claims to quote is a WRONG answer wearing the shape of a right one —
    worse than the rejected one it replaced, because the schema cannot see
    the difference. Doubling makes the same text parseable AND leaves the
    decoded value character-for-character identical to what the model sent.

    Valid escapes are matched FIRST and kept verbatim, so a legitimately
    escaped backslash (``\\\\``) is never doubled again and the character
    after it is never touched.

    This repairs FORM, never content: it is applied to an additional parse
    candidate, and the repaired text still has to satisfy the strict schema.
    A response that is wrong rather than merely mis-escaped stays rejected.

    Args:
        text: The raw response text.

    Returns:
        The text in which every backslash that JSON does not recognise is
        escaped as a literal backslash, so it survives decoding unchanged.
    """

    def repair(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if _VALID_ESCAPE.fullmatch(token) else BACKSLASH + token

    return _ANY_ESCAPE.sub(repair, text)


def normalize_schema_keys(candidate: str) -> str:
    """Drop backslashes from JSON object KEYS; values are never touched.

    A model that escapes markdown in its own output escapes the underscores
    of the schema's field names too (``"has\\_normative\\_statements"``).
    After :func:`repair_markdown_escapes` that parses, but the key now
    literally contains a backslash, matches no field of the closed response
    schema and is rejected as an unknown one — while the field it was meant
    to be is reported missing.

    Dropping it there cannot corrupt evidence: a key is a schema
    identifier, never a quotation, and this runs on the PARSED document, so
    what counts as a key is decided by the JSON structure and not by a
    regular expression guessing at positions.

    Args:
        candidate: A parse candidate. Text that is not JSON is returned
            unchanged — this is a repair, never a gate.

    Returns:
        The candidate, re-serialized only if a key actually changed.
    """
    try:
        document = json.loads(candidate)
    except ValueError:
        return candidate
    repaired, changed = _strip_key_escapes(document)
    return json.dumps(repaired) if changed else candidate


def _strip_key_escapes(value: Any) -> tuple[Any, bool]:  # noqa: ANN401 - a decoded JSON document is genuinely Any
    """Rewrite object keys without their backslashes; report whether any changed."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            clean = str(key).replace(BACKSLASH, "")
            repaired, item_changed = _strip_key_escapes(item)
            changed = changed or item_changed or clean != key
            result[clean] = repaired
        return result, changed
    if isinstance(value, list):
        pairs = [_strip_key_escapes(item) for item in value]
        return [item for item, _ in pairs], any(flag for _, flag in pairs)
    return value, False
