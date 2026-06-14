"""CSS conformance checker for the design-system token owner (FK-64 §64.17/§64.18).

This module provides two complementary checks:

1. **CSS↔Owner drift check** (``check_css_token_drift``): proves that the CSS
   custom properties in ``design-system.css`` exactly match the Python token
   owner values.  Owner = source of truth; CSS = checked expression.  The
   reference map is derived *exhaustively* from the owner via
   ``build_css_variables`` — there is no second hand-maintained list.  Every
   ``:root`` var not in the owner map AND not in the explicit non-token allowlist
   is flagged as an unowned token (fail-closed).

2. **Token-level conformance check** (``check_token_conformance``): enforces
   the 5 machine-checkable rules from FK-64 §64.17 / §64.18:
   - No ``font-size`` literals (any unit, not just px) outside the token
     definition (§64.17 / §64.6.2).
   - No new local font-size scales outside the token definition (§64.18 pt.4);
     also rejects ``font-size: var(--local-*)`` pointing to a non-token local.
   - No ad-hoc hex colors outside token definitions (§64.17).
   - Button/control heights/paddings only from control tokens, across ALL
     control selectors (§64.18 pt.2 / §64.17).
   - Status colors not semantically misused — a danger/error/cancelled selector
     must not reference a success/info token family, and vice versa
     (§64.18 pt.3 / §64.14).

Both checks are deterministic and fail-closed (violation → ``ConformanceError``).
Sonar S3776: cognitive complexity kept ≤ 15 per function via helper extraction.
Sonar S1192: repeated string literals extracted as module-level constants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Module-level constants (Sonar S1192: 3+ repeated string literals)
# ---------------------------------------------------------------------------

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# Matches "font-size: VALUE" and captures the value (greedy, stops at ; or }).
# The caller applies a whitelist: only var(...) is allowed; everything else
# (px, em, rem, %, unitless, keyword) is a violation (§64.17).
_FONT_SIZE_VALUE_RE = re.compile(r"\bfont-size\s*:\s*(?P<value>[^;{}]+)")

# Matches a control-size property declaration and captures the property name
# and the full value string.  Uses a negative lookbehind to avoid matching
# ``line-height`` as ``height``.  The caller applies the whitelist:
# only ``var(--control-*)`` tokens are allowed; anything else — literals
# (px/em/rem/%), non-control var() references, or keywords — is a violation.
_CONTROL_SIZE_PROP_RE = re.compile(
    r"(?<![a-z-])(?P<prop>min-height|height|padding)\s*:\s*(?P<value>[^;{}]+)"
)
_CSS_VAR_DECL_RE = re.compile(r"--(?P<name>[\w-]+)\s*:\s*(?P<value>[^;]+);")

# Matches EVERY ``:root { ... }`` block (a :root body has no nested ``}``).
# Used to collect token declarations across ALL :root blocks, not just the
# first, so a later overriding ``:root`` cannot slip a token past the drift
# and conformance checks (fail-closed multi-block parse).
_ROOT_BLOCK_RE = re.compile(r":root\s*\{([^}]+)\}", re.DOTALL)

# CSS var() reference pattern:
_VAR_USAGE_RE = re.compile(r"var\(--(?P<name>[\w-]+)\)")

# Local custom property declared with a raw font/size literal value (any unit).
# Used by the local-font-scale check; finditer catches every such declaration
# on a condensed line, not just the first.
_LOCAL_SIZE_DECL_RE = re.compile(r"--[\w-]+\s*:\s*[\d.]+(?:px|em|rem|%)")

# Known status-color CSS variable names (must not be reassigned with alien semantics):
_STATUS_CSS_NAMES = frozenset({
    "ak-success",
    "ak-warn",
    "ak-danger",
    "ak-info",
    "ak-done",
    "ak-status-backlog",
    "ak-status-approved",
    "ak-status-progress",
    "ak-status-done",
    "ak-status-cancelled",
})

# ALL status-family CSS var names monitored by the semantic-misuse check.
# Whitelist-by-construction: when a semantic-context selector references any
# var in this set, that var must be in the ALLOWED set for that context or it
# is a §64.18 pt.3 violation.
_ALL_STATUS_VARS: frozenset[str] = _STATUS_CSS_NAMES

# Selector keywords that identify each status-semantic context.
# Each keyword set is mutually exclusive (no keyword appears in two sets).
# FK-64 §64.14 separates severity badges from story-status badges:
#   - Severity family: danger/error, success, warning, info, done
#   - Story-status family: cancelled, backlog, approved, progress
# NOTE: "cancelled" is its OWN terminal story-status context (not folded into danger).
# "done" is a SEVERITY context; "status-done" is a story-status sub-token of done.
_DANGER_SELECTOR_KEYWORDS = frozenset({"danger", "error"})
_SUCCESS_SELECTOR_KEYWORDS = frozenset({"success"})
_WARNING_SELECTOR_KEYWORDS = frozenset({"warning", "warn"})
_INFO_SELECTOR_KEYWORDS = frozenset({"info"})
_DONE_SELECTOR_KEYWORDS = frozenset({"done"})
# Story-status-family contexts (cancelled/backlog/approved/progress — §64.14):
_CANCELLED_SELECTOR_KEYWORDS = frozenset({"cancelled"})
_STATUS_BACKLOG_SELECTOR_KEYWORDS = frozenset({"backlog"})
_STATUS_APPROVED_SELECTOR_KEYWORDS = frozenset({"approved"})
_STATUS_PROGRESS_SELECTOR_KEYWORDS = frozenset({"progress"})
# Story-status sub-tokens of done/cancelled (MAJOR 3, round-5): a selector such
# as ``.tone-status-done`` carries a story-status-done context and owns ONLY the
# ``--ak-status-done`` token — it must NOT collapse into the generic severity
# ``done`` context (which owns ``--ak-done``).  Same for ``status-cancelled``.
# These keywords are MORE SPECIFIC than ``done`` / ``cancelled`` and are matched
# first (longest/most-specific keyword wins — see ``_selector_semantic_context``).
_STATUS_DONE_SELECTOR_KEYWORDS = frozenset({"status-done"})
_STATUS_CANCELLED_SELECTOR_KEYWORDS = frozenset({"status-cancelled"})

# Strict 1:1 whitelist (FK-64 §64.14 / §64.17 ERROR 1, round-4):
# Each semantic context allows ONLY the single CSS token family it owns.
# No cross-axis allowances: severity contexts must not reference story-status
# tokens, and story-status contexts must not reference severity tokens.
# Adding a new status var to _ALL_STATUS_VARS automatically rejects it in
# every context that does not explicitly list it — whitelist-by-construction.
_ALLOWED_STATUS_MAP: dict[frozenset[str], frozenset[str]] = {
    _DANGER_SELECTOR_KEYWORDS:            frozenset({"ak-danger"}),
    _SUCCESS_SELECTOR_KEYWORDS:           frozenset({"ak-success"}),
    _WARNING_SELECTOR_KEYWORDS:           frozenset({"ak-warn"}),
    _INFO_SELECTOR_KEYWORDS:              frozenset({"ak-info"}),
    _DONE_SELECTOR_KEYWORDS:             frozenset({"ak-done"}),
    _CANCELLED_SELECTOR_KEYWORDS:        frozenset({"ak-status-cancelled"}),
    _STATUS_DONE_SELECTOR_KEYWORDS:      frozenset({"ak-status-done"}),
    _STATUS_CANCELLED_SELECTOR_KEYWORDS: frozenset({"ak-status-cancelled"}),
    _STATUS_BACKLOG_SELECTOR_KEYWORDS:   frozenset({"ak-status-backlog"}),
    _STATUS_APPROVED_SELECTOR_KEYWORDS:  frozenset({"ak-status-approved"}),
    _STATUS_PROGRESS_SELECTOR_KEYWORDS:  frozenset({"ak-status-progress"}),
}

# Control selectors: element selectors + .ak-* classes + control variant classes.
# Literal height/padding on any of these selectors is a §64.18 pt.2 violation.
_CONTROL_SELECTOR_RE = re.compile(
    r"(?:^|\b)(?:"
    r"button\b|input\b|select\b"           # element selectors
    r"|\.ak-button\b|\.ak-input\b"          # ak-component classes
    r"|\.ak-button--\w+|\.ak-input--\w+"    # variant classes
    r")"
)

# Prefix for control custom properties:
_CONTROL_PROP_PREFIX = "control-"

# Rule identifier strings (S1192: repeated across add() calls)
_RULE_FONT_SIZE = "§64.17/no-font-size-literal"
_RULE_LOCAL_SCALE = "§64.18-pt4/no-local-font-scale"
_RULE_ADHOC_HEX = "§64.17/no-adhoc-hex"
_RULE_CONTROL = "§64.18-pt2/control-token-required"
_RULE_STATUS_REINTERP = "§64.18-pt3/no-status-color-reinterpretation"
_RULE_DRIFT = "§64.17/css-owner-drift"
_RULE_UNOWNED = "§64.17/css-unowned-token"

# Token-var prefixes: any :root var with these prefixes that is not in the
# owner map is an unknown token (unowned).
_TOKEN_VAR_PREFIXES = (
    "--ak-",
    "--space-",
    "--text-",
    "--type-",
    "--control-",
    "--radius-",
    "--border-",
    "--weight-",
    "--font-",
    "--leading-",
    "--graph-edge-",
)


# ---------------------------------------------------------------------------
# Token-definition block state machine (ERROR 1, round-5 remediation)
# ---------------------------------------------------------------------------
#
# A "token-definition block" is a ``:root { ... }`` block: the ONE place where
# raw font/size literals and hex color values are allowed (they are token
# DEFINITIONS, not ad-hoc usage).  Every content check (font-size literal,
# local-font-scale, ad-hoc hex, status reuse, control sizes) must EXEMPT
# content that lies inside such a block — including the inline body of a
# one-line ``:root { ... }`` — but must NOT exempt content on lines that
# follow the block once it has closed.
#
# Two prior regressions came from ad-hoc tracking:
#   1. fail-open  — ``in_root`` left True after a one-line root, silencing
#      every subsequent line's checks.
#   2. false-positive — a one-line root reported ``(False, 0)``, so callers
#      did NOT exempt the line and falsely flagged its token definitions.
#
# This state machine fixes both by reporting, per line, BOTH facts the callers
# need: (a) whether THIS line's checkable content is exempt (inside a
# token-definition block), and (b) the brace-depth/in-block state to carry to
# the NEXT line.  Block nesting is tracked purely by ``{`` / ``}`` depth so it
# handles one-line, multi-line, and condensed layouts uniformly.  Parentheses
# (e.g. ``color-mix(in srgb, ...)``) do NOT change block depth — only braces.

_ROOT_SELECTOR_PREFIX = ":root"


@dataclass(frozen=True)
class _BlockState:
    """Immutable token-definition-block tracking state carried between lines.

    Attributes:
        in_token_block: True when the brace depth at the START of the next line
            is still inside an open ``:root`` token-definition block.
        block_depth: Net unmatched ``{`` count for the open token-definition
            block (0 when no such block is open).
    """

    in_token_block: bool = False
    block_depth: int = 0


_INITIAL_BLOCK_STATE = _BlockState()


def _advance_block_state(stripped: str, state: _BlockState) -> tuple[bool, _BlockState]:
    """Advance the token-definition-block state machine by one line.

    Args:
        stripped: The line with surrounding whitespace removed.
        state: The block state as it stood at the START of this line.

    Returns:
        A ``(content_exempt, next_state)`` pair where:
        - ``content_exempt`` is True when THIS line's checkable content lies
          inside a token-definition block and must therefore be skipped by the
          content checks.  This is True for: every line whose start is already
          inside an open block (including the closing-brace line), AND the line
          that OPENS a ``:root`` block (one-line or multi-line) — its inline
          token definitions are exempt.
        - ``next_state`` is the block state to pass to the NEXT line.  A
          one-line ``:root { ... }`` opens and closes on the same line, so its
          ``next_state`` is back outside (``in_token_block=False``); a
          violation on the following line is therefore NOT exempt.

    Determinism: nesting is counted only via ``{`` / ``}`` braces, so parentheses
    inside values (e.g. ``color-mix(in srgb, ...)``) never affect block depth.
    """
    if state.in_token_block:
        # Already inside the block at line start → this line's content is exempt.
        depth = state.block_depth + stripped.count("{") - stripped.count("}")
        if depth <= 0:
            # Block closes on this line; the closing-brace line is still exempt.
            return True, _INITIAL_BLOCK_STATE
        return True, _BlockState(in_token_block=True, block_depth=depth)

    if stripped.startswith(_ROOT_SELECTOR_PREFIX) and "{" in stripped:
        # This line OPENS a :root block → its inline content is exempt.
        depth = stripped.count("{") - stripped.count("}")
        if depth > 0:
            # Multi-line root: body continues on the following lines.
            return True, _BlockState(in_token_block=True, block_depth=depth)
        # One-line root: opens and closes here → next line is back outside.
        return True, _INITIAL_BLOCK_STATE

    # Outside any token-definition block: content is checkable, state unchanged.
    return False, _INITIAL_BLOCK_STATE


# ---------------------------------------------------------------------------
# Rule parser: full (selector-list, declaration-block) extraction.
# ---------------------------------------------------------------------------
#
# SELECTOR-LIST / MULTI-LINE class (ERROR 2, round 8): the selector-based checks
# (control sizes, status reuse) previously inspected only the single line that
# carried the ``{`` and only the first selector before it via a per-line regex.
# A multi-line and/or comma-separated selector list therefore evaded control and
# status classification, e.g.::
#
#     .ak-button,
#     .foo { padding: 1rem; }            # control selector hidden on prior line
#     .tone-danger,
#     .foo { color: var(--ak-success); } # status selector hidden on prior line
#
# This parser accumulates the FULL selector text (which may span multiple lines)
# up to the ``{``, splits it on commas into individual selectors, and pairs it
# with EVERY declaration line of the block.  Selector-based checks then evaluate
# the declaration block against ALL selectors in the list.  ``:root``
# token-definition blocks are skipped (their literals are definitions, not
# usage) — consistent with the content checks' ``_advance_block_state`` exemption.

_OPEN_BRACE = "{"
_CLOSE_BRACE = "}"


@dataclass(frozen=True)
class _CssRule:
    """A parsed CSS rule: its full selector list and declaration lines.

    Attributes:
        selectors: Every individual selector from the (possibly multi-line,
            comma-separated) selector list, each stripped of surrounding
            whitespace.  Empty entries are removed.
        declaration_lines: ``(line_index, stripped_text)`` pairs for every line
            that contributes declaration content to this rule's block, in source
            order.  ``line_index`` is 0-based (the caller adds 1 for display).
    """

    selectors: tuple[str, ...]
    declaration_lines: tuple[tuple[int, str], ...]


@dataclass
class _RuleParseState:
    """Mutable single-pass parser state for ``_iter_css_rules``."""

    block_state: _BlockState = _INITIAL_BLOCK_STATE
    pending_selector: str = ""
    in_rule: bool = False
    rule_selectors: tuple[str, ...] = ()
    declaration_lines: list[tuple[int, str]] = field(default_factory=list)
    depth: int = 0


def _split_selector_list(selector_text: str) -> tuple[str, ...]:
    """Split an accumulated selector list on commas into individual selectors."""
    return tuple(
        part.strip() for part in selector_text.split(",") if part.strip()
    )


def _open_rule(state: _RuleParseState, line: str, index: int) -> None:
    """Open a new rule body on the line that carries the first ``{``.

    The selector list is everything accumulated before the ``{`` (across prior
    lines plus this line's prefix); the post-``{`` remainder of this line becomes
    the rule's first declaration content.
    """
    before, _, after = line.partition(_OPEN_BRACE)
    full_selector = (state.pending_selector + " " + before).strip()
    state.pending_selector = ""
    state.in_rule = True
    state.rule_selectors = _split_selector_list(full_selector)
    state.declaration_lines = []
    state.depth = 1
    remainder = after.strip()
    if remainder:
        state.declaration_lines.append((index, remainder))
    state.depth += remainder.count(_OPEN_BRACE) - remainder.count(_CLOSE_BRACE)


def _continue_rule(state: _RuleParseState, stripped: str, index: int) -> _CssRule | None:
    """Add a body line to the open rule; finish and return it once braces close."""
    if stripped:
        state.declaration_lines.append((index, stripped))
    state.depth += stripped.count(_OPEN_BRACE) - stripped.count(_CLOSE_BRACE)
    if state.depth <= 0:
        rule = _CssRule(
            selectors=state.rule_selectors,
            declaration_lines=tuple(state.declaration_lines),
        )
        state.in_rule = False
        state.rule_selectors = ()
        state.declaration_lines = []
        return rule
    return None


def _iter_css_rules(lines: list[str]) -> list[_CssRule]:
    """Parse *lines* into rules of ``(full selector list, declaration block)``.

    ``:root`` token-definition blocks are skipped via the shared block-state
    machine.  Selector lists that span multiple lines and/or are comma-separated
    are accumulated and split, so every selector-based check can evaluate the
    declaration block against ALL selectors (fixing the multi-line/comma
    evasion).  Brace depth drives block boundaries, so one-line, multi-line and
    condensed layouts are handled uniformly (fail-closed).
    """
    rules: list[_CssRule] = []
    state = _RuleParseState()
    for index, line in enumerate(lines):
        stripped = line.strip()
        content_exempt, state.block_state = _advance_block_state(
            stripped, state.block_state
        )
        if content_exempt:
            continue  # inside a :root token-definition block — not a checked rule
        if state.in_rule:
            rule = _continue_rule(state, stripped, index)
            if rule is not None:
                rules.append(rule)
        elif _OPEN_BRACE in stripped:
            _open_rule(state, stripped, index)
            if state.depth <= 0:
                rules.append(
                    _CssRule(
                        selectors=state.rule_selectors,
                        declaration_lines=tuple(state.declaration_lines),
                    )
                )
                state.in_rule = False
        elif stripped:
            # Selector text continuing onto the next line (no ``{`` yet).
            state.pending_selector = (state.pending_selector + " " + stripped).strip()
    return rules


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformanceViolation:
    """A single FK-64 conformance violation.

    Attributes:
        rule: FK-64 rule identifier (e.g. ``"§64.17/no-font-size-literal"``).
        location: Human-readable location string (CSS file + line context).
        detail: What was found and why it violates the rule.
    """

    rule: str
    location: str
    detail: str


class ConformanceError(Exception):
    """Raised when one or more FK-64 conformance violations are detected.

    FAIL-CLOSED (FK-64 §64.18): a violation is an error, never a warning.
    """

    def __init__(self, violations: list[ConformanceViolation]) -> None:
        self.violations = violations
        lines = [f"  [{v.rule}] {v.location}: {v.detail}" for v in violations]
        super().__init__(
            f"{len(violations)} FK-64 conformance violation(s):\n" + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# CSS↔Owner drift check (AC4)
# ---------------------------------------------------------------------------


def _parse_css_root_vars(css_text: str) -> dict[str, list[str]]:
    """Extract ``--name: value`` declarations from ALL ``:root`` blocks.

    Returns a dict of ``--name`` → list of every stripped value (no trailing
    ``;``) declared for that var across EVERY ``:root`` block, in source order.

    Fail-closed multi-block parse (FK-64 §64.14/§64.17): an attacker can append
    a second ``:root { --ak-success: #deadbe; }`` after the legitimate CSS to
    override a token in the cascade.  Reading only the FIRST block (the previous
    ``re.search`` bug) let such an override pass both the drift and conformance
    checks.  Every ``:root`` block is now parsed and every value collected, so a
    duplicate/overriding declaration in a later block is visible to the caller
    and can be rejected.
    """
    result: dict[str, list[str]] = {}
    for root_match in _ROOT_BLOCK_RE.finditer(css_text):
        root_block = root_match.group(1)
        for m in _CSS_VAR_DECL_RE.finditer(root_block):
            name = "--" + m.group("name")
            value = m.group("value").strip()
            result.setdefault(name, []).append(value)
    return result


def check_css_token_drift(css_text: str) -> None:
    """Verify CSS custom properties exactly match the Python token owner (AC4).

    The reference map is built *exhaustively* from the owner via
    ``build_css_variables`` — there is no hand-maintained second list.

    Two directions are checked:
    (a) Every owner CSS var must appear in ``:root`` with the exact value.
    (b) Every ``:root`` var that matches a token-var prefix and is NOT in the
        owner map and NOT in the ``CSS_NON_TOKEN_ALLOWLIST`` is flagged as an
        unowned token (fail-closed — no silent surplus).

    Args:
        css_text: Full text of ``design-system.css``.

    Raises:
        ConformanceError: When any CSS token value drifts from the owner value
            or when an unowned token var is found.
    """
    from agentkit.kpi_analytics.design_system import (
        CSS_NON_TOKEN_ALLOWLIST,
        build_css_variables,
        get_design_system,
    )

    owner_map = build_css_variables(get_design_system())
    css_vars = _parse_css_root_vars(css_text)
    violations: list[ConformanceViolation] = []

    # (a) Owner → CSS: every owner var must appear in :root, and EVERY declared
    #     value across ALL :root blocks must equal the owner value.  A later
    #     :root block that re-declares the token with a different value is drift.
    for css_name, owner_value in owner_map.items():
        css_values = css_vars.get(css_name)
        if not css_values:
            violations.append(ConformanceViolation(
                rule=_RULE_DRIFT,
                location=f"design-system.css :root {css_name}",
                detail=f"token {css_name!r} exists in owner but is absent from CSS",
            ))
            continue
        for css_value in css_values:
            if css_value != owner_value:
                violations.append(ConformanceViolation(
                    rule=_RULE_DRIFT,
                    location=f"design-system.css :root {css_name}",
                    detail=f"value drift: CSS={css_value!r} vs owner={owner_value!r}",
                ))

    # (b) CSS → Owner: every token-prefixed :root var (in ANY :root block) must
    #     be owner-backed or allowlisted.
    for css_name in css_vars:
        if css_name in owner_map or css_name in CSS_NON_TOKEN_ALLOWLIST:
            continue
        if any(css_name.startswith(pfx) for pfx in _TOKEN_VAR_PREFIXES):
            violations.append(ConformanceViolation(
                rule=_RULE_UNOWNED,
                location=f"design-system.css :root {css_name}",
                detail=(
                    f"token-prefixed var {css_name!r} is not owner-backed "
                    "and not in the non-token allowlist"
                ),
            ))

    if violations:
        raise ConformanceError(violations)


# ---------------------------------------------------------------------------
# Token-level conformance checker (AC5 / AC6)
# ---------------------------------------------------------------------------


@dataclass
class _ConformanceContext:
    """Mutable accumulator for violations during a conformance scan."""

    violations: list[ConformanceViolation] = field(default_factory=list)

    def add(self, rule: str, location: str, detail: str) -> None:
        """Append a new violation."""
        self.violations.append(
            ConformanceViolation(rule=rule, location=location, detail=detail)
        )


def _is_font_size_value_literal(value: str) -> bool:
    """Return True when *value* is NOT an allowed ``var(--<token>)`` reference.

    FK-64 §64.17 (whitelist-by-construction): outside token-definition blocks a
    ``font-size`` value is conformant **only** if it starts with ``var(``.
    Every other form — px, em, rem, %, unitless numbers, keywords such as
    ``inherit``, ``normal``, ``larger``, ``smaller``, ``initial``, ``unset`` —
    is a violation.  Keyword exceptions were removed in remediation round 2
    because §64.17 forbids ANY non-token font-size outside the :root block.
    """
    return not value.strip().startswith("var(")


def _check_font_size_literals(
    lines: list[str], ctx: _ConformanceContext, filename: str
) -> None:
    """Rule §64.17 / §64.6.2: no ``font-size`` literal outside token definitions.

    Any ``font-size:`` whose value is NOT a ``var(...)`` token reference, ``inherit``,
    or ``normal`` is a violation — this covers px, em, rem, %, unitless, and keyword
    sizes.  Inside ``:root`` all font-size values are token definitions (allowed).
    """
    state = _INITIAL_BLOCK_STATE
    for i, line in enumerate(lines):
        stripped = line.strip()
        content_exempt, state = _advance_block_state(stripped, state)
        if content_exempt:
            continue  # token definition block — all font-size values allowed
        # finditer (not search): a single line may carry MULTIPLE font-size
        # declarations, e.g. ``.label { font-size: var(--text-sm); font-size: 12px; }``.
        # Every non-var value is a violation; checking only the first would let a
        # later bad declaration slip through (first-good-rest-bad must FAIL).
        for m in _FONT_SIZE_VALUE_RE.finditer(stripped):
            if _is_font_size_value_literal(m.group("value")):
                ctx.add(
                    _RULE_FONT_SIZE,
                    f"{filename}:{i + 1}",
                    f"font-size literal (non-var) outside token definition: {stripped!r}",
                )


def _get_owner_token_names() -> frozenset[str]:
    """Return the set of CSS var names exported by the token owner."""
    from agentkit.kpi_analytics.design_system import build_css_variables, get_design_system

    return frozenset(build_css_variables(get_design_system()))


def _check_local_font_scale(
    lines: list[str], ctx: _ConformanceContext, filename: str
) -> None:
    """Rule §64.18 pt.4: no new local font-size scales outside token block.

    Two sub-checks:
    1. A local custom property with a font/size literal value (any unit) outside
       ``:root`` is a violation (e.g. ``--local-font: 13px`` or ``1.2em``).
    2. A ``font-size: var(--X)`` reference where ``--X`` is NOT an owner token
       is a violation (local-var indirection must not bypass the rule).
    """
    owner_tokens = _get_owner_token_names()
    state = _INITIAL_BLOCK_STATE
    for i, line in enumerate(lines):
        stripped = line.strip()
        content_exempt, state = _advance_block_state(stripped, state)
        if content_exempt:
            continue
        # Sub-check 1: local custom property with size literal (any unit).
        # finditer (not search): a condensed line may declare several locals,
        # e.g. ``.w { --a: var(--ak-text); --b: 13px; --c: 14px; }`` — every
        # size-literal local is a violation, not only the first one found.
        for _ in _LOCAL_SIZE_DECL_RE.finditer(stripped):
            ctx.add(
                _RULE_LOCAL_SCALE,
                f"{filename}:{i + 1}",
                f"local font/size custom property outside token block: {stripped!r}",
            )
        # Sub-check 2: font-size: var(--non-token) indirection.
        # VAR SCOPE (ERROR 1, round 8): only the var(...) refs INSIDE a
        # ``font-size`` declaration's VALUE may be judged here.  The previous
        # code guarded with ``re.search`` for a font-size:var( anywhere on the
        # line but then scanned EVERY var() on the WHOLE line — so a sibling
        # declaration such as ``color: var(--shadow-md)`` on the same rule line
        # was wrongly attributed to the font-size rule (false positive on
        # legitimate CSS like ``.foo { color: var(--shadow-md); font-size:
        # var(--text-sm); }``).  We now iterate each font-size declaration and
        # scan vars ONLY within that declaration's matched value substring.
        for fs_m in _FONT_SIZE_VALUE_RE.finditer(stripped):
            font_size_value = fs_m.group("value")
            for var_m in _VAR_USAGE_RE.finditer(font_size_value):
                var_name = "--" + var_m.group("name")
                if var_name not in owner_tokens:
                    ctx.add(
                        _RULE_LOCAL_SCALE,
                        f"{filename}:{i + 1}",
                        (
                            f"font-size references non-token local var {var_name!r}: "
                            f"{stripped!r}"
                        ),
                    )


def _check_adhoc_hex(
    lines: list[str], ctx: _ConformanceContext, filename: str
) -> None:
    """Rule §64.17: no ad-hoc hex colors outside token definitions.

    Inside ``:root`` all hex values are token definitions (allowed).
    Outside ``:root``, hex values must not appear (use ``var(--ak-*)`` instead).
    """
    state = _INITIAL_BLOCK_STATE
    for i, line in enumerate(lines):
        stripped = line.strip()
        content_exempt, state = _advance_block_state(stripped, state)
        if content_exempt:
            continue  # token definitions — hex is allowed here
        if "/*" in stripped:
            continue  # comment line
        for hex_match in _HEX_COLOR_RE.finditer(stripped):
            hex_val = hex_match.group(0)
            ctx.add(
                _RULE_ADHOC_HEX,
                f"{filename}:{i + 1}",
                f"ad-hoc hex color {hex_val!r} outside token definition: {stripped!r}",
            )


def _is_control_selector(selector: str) -> bool:
    """Return True when *selector* belongs to a control-element/component."""
    return bool(_CONTROL_SELECTOR_RE.search(selector))


def _is_control_size_value_conformant(value: str) -> bool:
    """Return True only when *value* is exclusively ``var(--control-*)`` token refs.

    Whitelist-by-construction (§64.18 pt.2): on a control selector the
    height / min-height / padding value is conformant **only** if every
    space-separated token is either:
    - a ``var(--control-*)`` reference, or
    - a CSS delimiter that is not itself a var() reference (e.g. the short-
      hand separator between padding top/bottom and left/right — already
      covered because the full value string is checked for control-token refs).

    Anything else — a numeric literal (px/em/rem/%), a keyword, or a
    ``var(--non-control-*)`` reference — is a violation.
    """
    stripped = value.strip()
    if not stripped:
        return False
    # A shorthand value like "0.5rem 0.8rem" has multiple tokens separated by
    # spaces.  Collect all var() references and all non-var, non-empty tokens.
    var_names = [m.group("name") for m in _VAR_USAGE_RE.finditer(stripped)]
    # Remove all var(...) sub-expressions from the value to expose bare tokens.
    bare = _VAR_USAGE_RE.sub("", stripped).strip()
    # If there are bare non-whitespace tokens left, those are literals → violation.
    has_bare_tokens = bool(bare.replace(" ", "").replace("/", ""))
    if has_bare_tokens:
        return False
    # All remaining values are var() refs — every one must be a control token.
    return bool(var_names) and all(
        n.startswith(_CONTROL_PROP_PREFIX) for n in var_names
    )


def _check_control_size_line(
    stripped: str,
    current_selector: str,
    line_index: int,
    ctx: _ConformanceContext,
    filename: str,
) -> None:
    """Validate EVERY control-size declaration on a single control-selector line.

    ERROR 2 (round-5): the previous code used ``search`` and therefore only
    checked the FIRST ``height|min-height|padding`` declaration per line.  A
    condensed rule such as ``.ak-button { min-height: var(--control-height-md);
    padding: 1rem; }`` then PASSED because the bad ``padding: 1rem`` was never
    examined.  ``finditer`` validates each declaration independently so every
    violation on the line is reported.
    """
    for size_m in _CONTROL_SIZE_PROP_RE.finditer(stripped):
        if _is_control_size_value_conformant(size_m.group("value")):
            continue
        ctx.add(
            _RULE_CONTROL,
            f"{filename}:{line_index + 1}",
            (
                f"control selector {current_selector!r}: "
                f"{size_m.group('prop')} value must be exclusively "
                f"var(--control-*) token reference(s) — "
                f"use var(--control-*): {stripped!r}"
            ),
        )


def _rule_control_selector(rule: _CssRule) -> str | None:
    """Return a control selector from *rule*'s list, or ``None`` if none qualify.

    SELECTOR-LIST class (ERROR 2, round 8): the control-size rule applies if ANY
    selector in the (multi-line, comma-separated) list is a control selector.
    The returned selector is used only for the violation message.
    """
    for selector in rule.selectors:
        if _is_control_selector(selector):
            return selector
    return None


def _check_control_sizes(
    lines: list[str], ctx: _ConformanceContext, filename: str
) -> None:
    """Rule §64.18 pt.2: control heights and paddings must use control tokens.

    Whitelist-by-construction: on ALL control selectors (``button``, ``input``,
    ``select``, ``.ak-button``, ``.ak-input``, and their variant modifiers),
    the properties ``height``, ``min-height``, and ``padding`` are conformant
    **only** when every value token is a ``var(--control-*)`` reference.

    The check evaluates the FULL selector list of each rule (multi-line and
    comma-separated lists included): if ANY selector in the list is a control
    selector, the control-size rules apply to every declaration of the block.

    Violations include:
    - Numeric literals (px, em, rem, % — any unit).
    - Keywords (e.g. ``auto``, ``unset``).
    - ``var()`` references pointing to NON-control tokens (e.g. ``var(--space-4)``).

    Non-size properties on control selectors (``background``, ``color``,
    ``border``, etc.) are not checked by this rule.
    """
    for rule in _iter_css_rules(lines):
        control_selector = _rule_control_selector(rule)
        if control_selector is None:
            continue
        for line_index, declaration in rule.declaration_lines:
            _check_control_size_line(
                declaration, control_selector, line_index, ctx, filename
            )


# Flattened (keyword, owning-allowed-set) index, sorted by keyword length
# DESCENDING so the most-specific keyword is considered first when collapsing
# substring-superset overlaps (MAJOR 3, round-5 / ERROR round-6):
#   - "status-done"      (11) supersedes "done"      (4)  → story-status-done
#   - "status-cancelled" (16) supersedes "cancelled" (9)  → story-status-cancelled
#   - "warning"          (7)  supersedes "warn"      (4)  → single warning context
# Each entry maps the keyword to the ALLOWED token set of its semantic context.
# Building this once at import time keeps ``_selector_semantic_context`` small.
_SEMANTIC_KEYWORD_INDEX: tuple[tuple[str, frozenset[str]], ...] = tuple(
    sorted(
        (
            (keyword, allowed_set)
            for keyword_set, allowed_set in _ALLOWED_STATUS_MAP.items()
            for keyword in keyword_set
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


# Sentinel: selector carries two or more conflicting status semantics with
# DIFFERENT allowed-sets.  Fail-closed — the selector is treated as a
# status-reinterpretation violation regardless of which token it references.
_AMBIGUOUS_SEMANTIC_CONTEXT = "ambiguous"


def _keyword_match_spans(keyword: str, lowered: str) -> list[tuple[int, int]]:
    """Return all ``(start, end)`` spans where *keyword* occurs in *lowered*."""
    spans: list[tuple[int, int]] = []
    start = lowered.find(keyword)
    while start != -1:
        spans.append((start, start + len(keyword)))
        start = lowered.find(keyword, start + 1)
    return spans


def _is_superset_covered(
    inner: tuple[str, list[tuple[int, int]]],
    others: list[tuple[str, list[tuple[int, int]]]],
) -> bool:
    """True if every occurrence of *inner* sits inside a longer matched keyword.

    *inner* is ``(keyword, spans)``.  It is superseded (same semantic at higher
    specificity, NOT a conflict) when each of its spans is fully contained in a
    span of some other matched keyword that strictly contains *inner*'s keyword
    as a substring (e.g. every ``done`` lives inside a ``status-done``).
    """
    inner_keyword, inner_spans = inner
    for inner_start, inner_end in inner_spans:
        covered = any(
            inner_keyword in outer_keyword
            and len(outer_keyword) > len(inner_keyword)
            and outer_start <= inner_start
            and inner_end <= outer_end
            for outer_keyword, outer_spans in others
            for outer_start, outer_end in outer_spans
        )
        if not covered:
            return False
    return True


def _selector_semantic_context(selector: str) -> frozenset[str] | str | None:
    """Classify *selector* into its status-semantic context (FK-64 §64.14).

    Returns one of:
    - ``None`` — the selector carries no status semantic (not status-checked).
    - a ``frozenset`` — the single allowed token set for the one (post-collapse)
      semantic context the selector carries.
    - ``_AMBIGUOUS_SEMANTIC_CONTEXT`` — the selector carries TWO OR MORE
      conflicting semantics with different allowed-sets (fail-closed violation).

    Classification is strict 1:1 and fail-closed (§64.18).  ALL status-semantic
    keywords matching the selector are collected.  Substring-superset overlaps
    are then COLLAPSED positionally: a keyword whose every occurrence sits inside
    a longer matched keyword is the SAME semantic at higher specificity (e.g.
    ``status-done`` supersedes ``done``, ``warning`` supersedes ``warn``) and is
    dropped.  After collapsing, if more than one DISTINCT allowed-set remains the
    selector is ambiguous/conflicting (e.g. ``.tone-danger-success`` carries both
    danger and success) and is rejected — the checker never silently picks one.
    A selector with exactly one remaining allowed-set resolves to it; for
    example ``.tone-status-done`` resolves to ``{ak-status-done}`` (NOT the
    generic severity ``{ak-done}``).
    """
    lowered = selector.lower()
    matched: list[tuple[str, list[tuple[int, int]], frozenset[str]]] = [
        (keyword, spans, allowed_set)
        for keyword, allowed_set in _SEMANTIC_KEYWORD_INDEX
        if (spans := _keyword_match_spans(keyword, lowered))
    ]
    if not matched:
        return None

    spans_by_keyword = [(keyword, spans) for keyword, spans, _ in matched]
    remaining_allowed: set[frozenset[str]] = set()
    for keyword, spans, allowed_set in matched:
        others = [(k, s) for k, s in spans_by_keyword if k != keyword]
        if not _is_superset_covered((keyword, spans), others):
            remaining_allowed.add(allowed_set)

    if len(remaining_allowed) > 1:
        return _AMBIGUOUS_SEMANTIC_CONTEXT
    # Exactly one distinct allowed-set survives the collapse.
    return next(iter(remaining_allowed))


def _line_references_status_var(stripped: str) -> bool:
    """True if *stripped* uses any monitored ``var(--ak-status-family)`` token."""
    return any(
        var_m.group("name") in _ALL_STATUS_VARS
        for var_m in _VAR_USAGE_RE.finditer(stripped)
    )


def _rule_semantic_context(rule: _CssRule) -> frozenset[str] | str | None:
    """Classify a rule's FULL selector list into one status-semantic context.

    SELECTOR-LIST class (ERROR 2, round 8): the status check must consider every
    selector in the (multi-line, comma-separated) list, not just the one on the
    ``{``-line.  Each selector is classified via ``_selector_semantic_context``;
    the per-selector results are then combined:

    - ``None`` — no selector in the list carries a status semantic.
    - a ``frozenset`` — exactly one distinct allowed-set across the whole list.
    - ``_AMBIGUOUS_SEMANTIC_CONTEXT`` — any selector is itself ambiguous, OR the
      list mixes selectors with DIFFERENT allowed-sets (e.g. ``.tone-danger,
      .tone-success``).  Fail-closed, consistent with the round-6 single-selector
      ambiguity rule.
    """
    allowed_sets: set[frozenset[str]] = set()
    for selector in rule.selectors:
        ctx = _selector_semantic_context(selector)
        if ctx is None:
            continue
        if isinstance(ctx, str):  # a single selector already ambiguous
            return _AMBIGUOUS_SEMANTIC_CONTEXT
        allowed_sets.add(ctx)
    if not allowed_sets:
        return None
    if len(allowed_sets) > 1:
        return _AMBIGUOUS_SEMANTIC_CONTEXT
    return next(iter(allowed_sets))


def _check_status_redeclaration(
    declaration: str, line_index: int, ctx: _ConformanceContext, filename: str
) -> None:
    """Sub-check 1: a ``--ak-status-*`` var reassigned outside ``:root`` fails.

    ``_iter_css_rules`` already skips ``:root`` token-definition blocks, so any
    status-var declaration reaching this helper is outside the token block.
    """
    for name in _STATUS_CSS_NAMES:
        if f"--{name}:" in declaration or f"--{name} :" in declaration:
            ctx.add(
                _RULE_STATUS_REINTERP,
                f"{filename}:{line_index + 1}",
                f"status color --{name} reassigned outside token block: {declaration!r}",
            )


def _check_status_semantic_misuse(
    rule: _CssRule,
    semantic_ctx: frozenset[str] | str,
    ctx: _ConformanceContext,
    filename: str,
) -> None:
    """Sub-check 2: status tokens must match the rule's whitelisted family.

    Evaluates every declaration line of the rule against the (full-selector-list)
    semantic context.  An ambiguous context fails on any status token used; a
    concrete context fails on any status token outside its allowed set.
    """
    selector_label = ", ".join(rule.selectors)
    for line_index, declaration in rule.declaration_lines:
        if isinstance(semantic_ctx, str):
            # Conflicting multi-semantic selector list (e.g. ``.tone-danger,
            # .tone-success`` or ``.tone-danger-success``): fail-closed on any
            # status token — the checker never picks one semantic over another.
            if _line_references_status_var(declaration):
                ctx.add(
                    _RULE_STATUS_REINTERP,
                    f"{filename}:{line_index + 1}",
                    (
                        f"selector list {selector_label!r} carries conflicting status "
                        f"semantics (ambiguous per §64.14); status tokens may not be "
                        f"reinterpreted by a multi-semantic selector: {declaration!r}"
                    ),
                )
            continue
        for var_m in _VAR_USAGE_RE.finditer(declaration):
            var_name = var_m.group("name")
            if var_name in _ALL_STATUS_VARS and var_name not in semantic_ctx:
                ctx.add(
                    _RULE_STATUS_REINTERP,
                    f"{filename}:{line_index + 1}",
                    (
                        f"selector {selector_label!r} references status token "
                        f"--{var_name} which is not in the allowed set for its "
                        f"semantic context (semantic misuse per §64.14): {declaration!r}"
                    ),
                )


def _check_status_color_reuse(
    lines: list[str], ctx: _ConformanceContext, filename: str
) -> None:
    """Rule §64.18 pt.3: status colors must not be reinterpreted.

    Two sub-checks, both evaluated over the FULL multi-line / comma-separated
    selector list and declaration block of each rule (ERROR 2, round 8):
    1. **Redeclaration**: a ``--ak-status-*`` var reassigned outside ``:root``
       is a violation.
    2. **Semantic misuse**: a selector list carrying a danger/error/cancelled
       semantic must not reference a success/info token, and vice versa; a list
       mixing conflicting semantics is ambiguous and fails on any status token.
    """
    for rule in _iter_css_rules(lines):
        for line_index, declaration in rule.declaration_lines:
            _check_status_redeclaration(declaration, line_index, ctx, filename)
        semantic_ctx = _rule_semantic_context(rule)
        if semantic_ctx is None:
            continue
        _check_status_semantic_misuse(rule, semantic_ctx, ctx, filename)


def check_token_conformance(
    css_text: str,
    filename: str = "design-system.css",
) -> None:
    """Run all FK-64 §64.17/§64.18 conformance checks on CSS text (AC5/AC6).

    This is the machine check enforcing design-system discipline.  Any single
    violation causes a ``ConformanceError`` (FAIL-CLOSED, FK-64 §64.18).

    Rules checked:
    1. §64.17/no-font-size-literal   — no literal ``font-size`` (any unit) outside
       :root.
    2. §64.18-pt4/no-local-font-scale — no new local font/size custom properties
       outside the token block (px/em/rem/% units); also rejects
       ``font-size: var(--non-token)`` indirection.
    3. §64.17/no-adhoc-hex           — no ad-hoc hex colors outside :root.
    4. §64.18-pt2/control-token-required — heights/paddings use control tokens on
       ALL control selectors.
    5. §64.18-pt3/no-status-color-reinterpretation — status colors not remapped
       (redeclaration) and not semantically misused (wrong family in context).

    Args:
        css_text: Full CSS text to check.
        filename: Source label used in violation location strings.

    Raises:
        ConformanceError: When any rule is violated.
    """
    ctx = _ConformanceContext()
    lines = css_text.splitlines()

    _check_font_size_literals(lines, ctx, filename)
    _check_local_font_scale(lines, ctx, filename)
    _check_adhoc_hex(lines, ctx, filename)
    _check_control_sizes(lines, ctx, filename)
    _check_status_color_reuse(lines, ctx, filename)

    if ctx.violations:
        raise ConformanceError(ctx.violations)
