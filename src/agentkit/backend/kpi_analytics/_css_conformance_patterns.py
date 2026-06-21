"""Compiled patterns and rule constants for the CSS conformance checker.

This private module holds the regular expressions, status-family whitelists,
rule-identifier strings, and token-var prefixes used by ``css_conformance``.
Splitting the pure data definitions out of the behaviour module keeps the
checker's module-level code small (Sonar ``PY_MODULE_TOP_LEVEL_MAX_LOC``) and
separates the *what* (token rules) from the *how* (the parser/state machine).

All names are re-exported by ``css_conformance`` and are private to the
``kpi_analytics`` BC; tests use only the checker's public API.
"""

from __future__ import annotations

import re

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
    "--chart-series-",
)

_ROOT_SELECTOR_PREFIX = ":root"

_OPEN_BRACE = "{"
_CLOSE_BRACE = "}"
