"""Strict YAML frontmatter parser for concept documents (FK-13 §13.9.6, AC10).

Fail-closed: every external input is validated strictly and rejected on any
deviation -- never repaired. There is NO library leniency here:

- invalid UTF-8 -> hard error (no ``errors="replace"``);
- duplicate mapping keys at any level -> hard error (no YAML-last-wins);
- unknown YAML tags -> hard error (safe loader);
- non-finite numbers (``.inf``/``.nan``) -> hard error;
- lone surrogates -> hard error;
- wrong container/scalar types and disallowed enums -> hard error (strict
  Pydantic model, no coercion, no ``.get(..., default)``);
- excessive nesting -> hard error (depth guard).

The resulting :class:`ConceptFrontmatter` is the typed, validated projection of
a concept document's frontmatter block.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Max frontmatter nesting depth (guard against YAML bombs / pathological input).
_MAX_YAML_DEPTH = 64


class FrontmatterError(ValueError):
    """Raised when a frontmatter block is missing, malformed or invalid."""

    def __init__(self, message: str, *, code: str = "E-SCHEMA-001") -> None:
        super().__init__(message)
        self.code = code


class _AuthorityScopeEntry(BaseModel):
    """A qualified ``authority_over`` entry (``{scope: ...}``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scope: str


class _DefersToEntry(BaseModel):
    """A qualified ``defers_to`` entry (``{target, scope, reason}``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target: str
    scope: str = ""
    reason: str = ""


class ConceptFrontmatter(BaseModel):
    """Typed, strictly-validated concept frontmatter (FK-13 §13.9.6).

    Required: ``concept_id``, ``title``, ``status``, ``doc_kind``. For
    ``doc_kind == appendix`` the ``parent_concept_id`` is mandatory (validated in
    the corpus validator as E-SCHEMA-004 since it needs the corpus context).
    """

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    concept_id: str
    title: str
    status: str
    doc_kind: str
    module: str = ""
    parent_concept_id: str = ""
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: str = ""
    tags: list[str] = Field(default_factory=list)
    authority_over: list[_AuthorityScopeEntry] = Field(default_factory=list)
    defers_to: list[_DefersToEntry] = Field(default_factory=list)
    section_number: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ConceptFrontmatter:
        """Validate a parsed mapping strictly; map enum/type errors to codes."""
        # Enum + type pre-checks: a non-string or disallowed value is a named
        # schema error (no coercion, AC10).
        for field_name, allowed in (("status", {"active", "draft", "archived"}), ("doc_kind", {"core", "appendix"})):
            value = data.get(field_name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise FrontmatterError(
                    f"{field_name} must be a string in {'|'.join(sorted(allowed))}, "
                    f"got {type(value).__name__} (no coercion, AC10)",
                    code="E-SCHEMA-003",
                )
            if value not in allowed:
                raise FrontmatterError(
                    f"{field_name} {value!r} is not in {'|'.join(sorted(allowed))}",
                    code="E-SCHEMA-003",
                )
        # List-type fields must be lists of strings (no coercion).
        for list_field in ("tags", "supersedes"):
            value = data.get(list_field)
            if value is None:
                continue
            if not isinstance(value, list):
                raise FrontmatterError(
                    f"{list_field} must be a list, got {type(value).__name__} (AC10)",
                    code="E-SCHEMA-002",
                )
            for item in value:
                if not isinstance(item, str):
                    raise FrontmatterError(
                        f"{list_field} entry must be a string, got {type(item).__name__} (AC10)",
                        code="E-SCHEMA-002",
                    )
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            # Surface the first error deterministically.
            raw_errors = exc.errors()
            first: dict[str, Any] = dict(raw_errors[0]) if raw_errors else {}
            loc = ".".join(str(p) for p in first.get("loc", ()))
            msg = first.get("msg", "validation error")
            code = "E-SCHEMA-002" if str(first.get("type", "")).startswith(("missing", "int_")) else "E-SCHEMA-001"
            raise FrontmatterError(f"frontmatter field {loc!r}: {msg}", code=code) from exc

    @property
    def authority_scopes(self) -> tuple[str, ...]:
        return tuple(e.scope for e in self.authority_over)

    @property
    def defers_to_targets(self) -> tuple[str, ...]:
        return tuple(e.target for e in self.defers_to)


# --------------------------------------------------------------------------- #
# Strict YAML loading
# --------------------------------------------------------------------------- #


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that REJECTS duplicate mapping keys (no YAML-last-wins)."""


def _no_duplicates_constructor(
    loader: yaml.Loader, node: yaml.MappingNode, deep: bool = False
) -> dict[str, Any]:
    """Reject duplicate keys in a mapping node at any nesting level."""
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
        if key in mapping:
            raise FrontmatterError(
                f"duplicate YAML key {key!r} in frontmatter (no last-wins, AC10)",
                code="E-SCHEMA-001",
            )
        _check_depth(value_node, depth=1)
        mapping[key] = loader.construct_object(value_node, deep=deep)  # type: ignore[no-untyped-call]
    return mapping


def _check_depth(node: yaml.Node, depth: int) -> None:
    if depth > _MAX_YAML_DEPTH:
        raise FrontmatterError(
            f"frontmatter nesting exceeds max depth {_MAX_YAML_DEPTH} (AC10)",
            code="E-SCHEMA-001",
        )
    if isinstance(node, yaml.MappingNode):
        for _, v in node.value:
            _check_depth(v, depth + 1)
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            _check_depth(v, depth + 1)


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates_constructor
)


def _reject_non_finite(value: Any) -> Any:
    """Reject float('inf')/float('nan') (YAML ``.inf``/``.nan`` literals)."""
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise FrontmatterError(
            "frontmatter contains a non-finite number (.inf/.nan), AC10",
            code="E-SCHEMA-001",
        )
    if isinstance(value, dict):
        for v in value.values():
            _reject_non_finite(v)
    elif isinstance(value, list):
        for v in value:
            _reject_non_finite(v)
    return value


def split_frontmatter(raw: str) -> tuple[str, str]:
    """Split a document into ``(frontmatter_text, body_text)``.

    Returns ``("", raw)`` when there is no frontmatter block.

    Raises:
        FrontmatterError: When the opening delimiter is present but not
            terminated, or the block is empty.
    """
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", raw
    # Find the closing '---' line (the first line after the opener that is
    # exactly '---', optionally with trailing whitespace).
    close_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            close_index = idx
            break
    if close_index == -1:
        raise FrontmatterError(
            "frontmatter block is opened but never terminated",
            code="E-SCHEMA-001",
        )
    frontmatter_text = "".join(lines[1:close_index])
    if not frontmatter_text.strip():
        raise FrontmatterError(
            "frontmatter block is empty",
            code="E-SCHEMA-001",
        )
    body = "".join(lines[close_index + 1:])
    return frontmatter_text, body.lstrip("\n")


def parse_frontmatter_block(text: str) -> dict[str, Any]:
    """Parse a frontmatter TEXT block strictly into a raw mapping.

    Fail-closed on every AC10 axis. Does NOT apply schema validation (use
    :meth:`ConceptFrontmatter.from_mapping` for that).
    """
    try:
        data = yaml.load(text, Loader=_StrictSafeLoader)
    except yaml.YAMLError as exc:
        raise FrontmatterError(
            f"frontmatter is not valid YAML: {exc}", code="E-SCHEMA-001"
        ) from exc
    if data is None:
        raise FrontmatterError("frontmatter block parsed to nothing", code="E-SCHEMA-001")
    if not isinstance(data, dict):
        raise FrontmatterError(
            f"frontmatter must be a YAML mapping, got {type(data).__name__}",
            code="E-SCHEMA-001",
        )
    _reject_non_finite(data)
    _reject_lone_surrogates(data)
    return data


def _reject_lone_surrogates(value: Any) -> Any:
    if isinstance(value, str):
        for idx, ch in enumerate(value):
            cp = ord(ch)
            if 0xD800 <= cp <= 0xDFFF:
                raise FrontmatterError(
                    f"frontmatter contains a lone surrogate at index {idx} (AC10)",
                    code="E-SCHEMA-001",
                )
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_lone_surrogates(k)
            _reject_lone_surrogates(v)
    elif isinstance(value, list):
        for v in value:
            _reject_lone_surrogates(v)
    return value


def read_text_strict(path: object) -> str:
    """Read a file as UTF-8 strictly (no ``errors='replace'``)."""
    from pathlib import Path  # noqa: PLC0415

    p = path if isinstance(path, Path) else Path(str(path))
    raw = p.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrontmatterError(
            f"file {p} is not valid UTF-8 (AC10): {exc}", code="E-SCHEMA-001"
        ) from exc


def parse_document_frontmatter(raw_text: str) -> ConceptFrontmatter | None:
    """Parse + validate the frontmatter of a document text.

    Returns ``None`` when the document has no frontmatter block. Raises
    :class:`FrontmatterError` on any strictness violation.
    """
    frontmatter_text, _body = split_frontmatter(raw_text)
    if not frontmatter_text:
        return None
    data = parse_frontmatter_block(frontmatter_text)
    return ConceptFrontmatter.from_mapping(data)


def iter_section_number(body: str) -> Iterator[tuple[str, int]]:
    """Yield ``(heading, level)`` for ``##``/``###`` headings in ``body``.

    Level: 2 for ``##``, 3 for ``###``. Used by the chunker to derive
    ``section_number``.
    """
    for match in re.finditer(r"^(#{2,3})\s+(.+?)\s*$", body, re.MULTILINE):
        hashes, heading = match.group(1), match.group(2)
        yield heading, len(hashes)


__all__ = [
    "ConceptFrontmatter",
    "FrontmatterError",
    "iter_section_number",
    "parse_document_frontmatter",
    "parse_frontmatter_block",
    "read_text_strict",
    "split_frontmatter",
]
