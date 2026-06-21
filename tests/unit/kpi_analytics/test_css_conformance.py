"""Unit tests for the CSS conformance checker (AG3-092, FK-64 §64.17/§64.18).

AC4 — CSS↔Owner drift check: owner is source, CSS is checked expression.
      Negative: injected value drift detected; unowned :root token var detected.
AC5 — Conformance check fails on each injected violation (general rules, not
      just narrow tautologies):
        - font-size literal (px, em, AND rem — not just px)
        - local px-var consumed via var() (non-token local indirection)
        - non-.ak-* control selector (e.g. ``button.primary { height: 3rem }``)
        - status semantic misuse (danger selector using success token)
        - unowned :root token var
AC6 — Conformance check PASS on conformant CSS / real prototype.
"""

from __future__ import annotations

import pathlib

import pytest

from agentkit.backend.kpi_analytics.css_conformance import (
    ConformanceError,
    check_css_token_drift,
    check_token_conformance,
)
from agentkit.backend.kpi_analytics.design_system import (
    CSS_NON_TOKEN_ALLOWLIST,
    build_css_variables,
    get_design_system,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CSS_DIR = pathlib.Path(__file__).parents[3] / "frontend" / "prototype" / "src"
_DESIGN_SYSTEM_CSS = _CSS_DIR / "design-system.css"


def _load_prototype_css() -> str:
    return _DESIGN_SYSTEM_CSS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC4 — CSS↔Owner drift check (positive + negative)
# ---------------------------------------------------------------------------


def test_css_owner_drift_check_pass_on_prototype() -> None:
    """AC4 positive: prototype design-system.css matches the Python owner."""
    check_css_token_drift(_load_prototype_css())  # must not raise


def test_css_owner_drift_check_detects_value_drift() -> None:
    """AC4 negative: injected CSS value drift is detected as ConformanceError."""
    # Replace the known bg-deep value with an alien color
    css = _load_prototype_css().replace(
        "--ak-bg-deep: #090a0b;", "--ak-bg-deep: #deadbe;"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_css_token_drift(css)
    violations = exc_info.value.violations
    assert any("ak-bg-deep" in v.location or "ak-bg-deep" in v.detail for v in violations)
    assert any("css-owner-drift" in v.rule for v in violations)


def test_css_owner_drift_check_detects_missing_token() -> None:
    """AC4 negative: a token absent from CSS is detected as a drift violation."""
    # Remove the --ak-success token entirely
    css = _load_prototype_css().replace("--ak-success: #74d17f;", "")
    with pytest.raises(ConformanceError) as exc_info:
        check_css_token_drift(css)
    violations = exc_info.value.violations
    assert any("ak-success" in v.detail for v in violations)


def test_css_owner_drift_check_detects_unowned_token_var() -> None:
    """AC4 negative: an unowned token-prefixed :root var is flagged (no silent surplus).

    ERROR 2 remediation: the drift check now fail-closes on any :root var whose
    name starts with a token-family prefix but is NOT in the owner map and NOT
    in the non-token allowlist.
    """
    # Inject an unowned token-prefixed var into :root
    css = _load_prototype_css().replace(
        "--ak-bg: #111214;",
        "--ak-bg: #111214;\n  --ak-unknown-rogue-token: #badc0d;",
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_css_token_drift(css)
    violations = exc_info.value.violations
    assert any("ak-unknown-rogue-token" in v.detail for v in violations)
    assert any("unowned" in v.rule for v in violations)


def test_css_owner_drift_check_allowlist_vars_do_not_raise() -> None:
    """AC4 positive: non-token allowlist vars (overlay/shadow/rail) do not cause errors."""
    # The prototype CSS contains --overlay-*, --rail-width, --shadow-* which are
    # in CSS_NON_TOKEN_ALLOWLIST and must not be flagged.
    css = _load_prototype_css()
    # Verify the allowlist is non-empty and the prototype passes
    assert len(CSS_NON_TOKEN_ALLOWLIST) > 0
    check_css_token_drift(css)  # must not raise


def test_drift_check_owner_map_is_exhaustive() -> None:
    """AC4/ERROR2: build_css_variables covers all token-family prefixed vars in prototype CSS."""
    # Every :root var with a token-family prefix must be owner-backed or allowlisted.
    # If this test passes, there is no "silent surplus" in the prototype.
    owner_map = build_css_variables(get_design_system())
    css = _load_prototype_css()
    # Parse :root vars inline to verify exhaustiveness
    import re
    root_match = re.search(r":root\s*\{([^}]+)\}", css, re.DOTALL)
    assert root_match, ":root block not found in prototype CSS"
    token_prefixes = (
        "--ak-", "--space-", "--text-", "--type-", "--control-",
        "--radius-", "--border-", "--weight-", "--font-", "--leading-",
        "--graph-edge-", "--chart-series-",
    )
    for m in re.finditer(r"--(?P<name>[\w-]+)\s*:", root_match.group(1)):
        var_name = "--" + m.group("name")
        if any(var_name.startswith(pfx) for pfx in token_prefixes):
            assert (
                var_name in owner_map or var_name in CSS_NON_TOKEN_ALLOWLIST
            ), f":root token var {var_name!r} is not owner-backed and not allowlisted"


# ---------------------------------------------------------------------------
# AC5 — Conformance negative tests (five injected violations, one each)
# ---------------------------------------------------------------------------


def test_conformance_fails_on_font_size_px_literal() -> None:
    """AC5/ERROR3: font-size px literal outside token definition → §64.17 violation.

    ERROR 3 remediation: the check enforces ANY non-var font-size, not just px.
    """
    injected = (
        _load_prototype_css()
        + "\n.my-view-label { font-size: 13px; color: var(--ak-text); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected.css")
    violations = exc_info.value.violations
    assert any("no-font-size-literal" in v.rule for v in violations)


def test_conformance_fails_on_font_size_em_literal() -> None:
    """AC5/ERROR3: font-size em literal outside token definition → §64.17 violation.

    The general rule forbids ALL non-var font-size literals — not just px.
    """
    injected = (
        _load_prototype_css()
        + "\n.my-component { font-size: 1.125em; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-em.css")
    violations = exc_info.value.violations
    assert any("no-font-size-literal" in v.rule for v in violations)


def test_conformance_fails_on_font_size_rem_literal() -> None:
    """AC5/ERROR3: font-size rem literal outside token definition → §64.17 violation.

    The general rule forbids ALL non-var font-size literals — not just px.
    """
    injected = (
        _load_prototype_css()
        + "\n.my-component { font-size: 1rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-rem.css")
    violations = exc_info.value.violations
    assert any("no-font-size-literal" in v.rule for v in violations)


def test_conformance_fails_on_local_font_size_scale() -> None:
    """AC5: new local font-size scale outside token block → §64.18 pt.4 violation."""
    injected = (
        _load_prototype_css()
        + "\n.my-widget { --my-font-sm: 0.8em; color: var(--ak-text); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected.css")
    violations = exc_info.value.violations
    assert any("no-local-font-scale" in v.rule for v in violations)


def test_conformance_fails_on_local_px_var_via_font_size_var() -> None:
    """AC5/ERROR4: font-size via a non-token local var is a §64.18 pt.4 violation.

    ERROR 4 remediation: ``--local-font-size: 13px`` outside :root AND its
    consumption via ``font-size: var(--local-font-size)`` are both violations.
    """
    injected = (
        _load_prototype_css()
        + "\n.my-widget {\n"
        "  --local-font-size: 13px;\n"
        "  font-size: var(--local-font-size);\n"
        "}\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-local-px-var.css")
    violations = exc_info.value.violations
    # Either the local var declaration OR the non-token var() reference triggers it
    assert any("no-local-font-scale" in v.rule for v in violations)


def test_conformance_fails_on_adhoc_hex_outside_token_definition() -> None:
    """AC5: ad-hoc hex color outside :root → §64.17 violation."""
    injected = (
        _load_prototype_css()
        + "\n.my-panel-badge { color: #c0ffee; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected.css")
    violations = exc_info.value.violations
    assert any("no-adhoc-hex" in v.rule for v in violations)


def test_conformance_fails_on_button_literal_height() -> None:
    """AC5: button height with literal rem value → §64.18 pt.2 violation."""
    injected = (
        _load_prototype_css()
        + "\n.ak-button--xl { min-height: 3rem; padding: 0.75rem 1rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected.css")
    violations = exc_info.value.violations
    assert any("control-token-required" in v.rule for v in violations)


def test_conformance_fails_on_non_ak_control_selector_literal_height() -> None:
    """AC5/ERROR5: literal height on a non-.ak-* control selector → §64.18 pt.2 violation.

    ERROR 5 remediation: the rule applies to ALL control selectors, not just
    .ak-button / .ak-input.  ``button.primary { height: 3rem }`` must also fail.
    """
    injected = (
        _load_prototype_css()
        + "\nbutton.primary { height: 3rem; padding: 1rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-non-ak.css")
    violations = exc_info.value.violations
    assert any("control-token-required" in v.rule for v in violations)


def test_conformance_fails_on_bare_input_selector_literal_height() -> None:
    """AC5/ERROR5: literal height on bare ``input`` element selector → §64.18 pt.2."""
    injected = (
        _load_prototype_css()
        + "\ninput { height: 2rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-input.css")
    violations = exc_info.value.violations
    assert any("control-token-required" in v.rule for v in violations)


def test_conformance_fails_on_status_color_reinterpretation() -> None:
    """AC5: status color reassigned outside :root → §64.18 pt.3 violation."""
    injected = (
        _load_prototype_css()
        + "\n.my-theme { --ak-success: #aabbcc; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected.css")
    violations = exc_info.value.violations
    assert any("no-status-color-reinterpretation" in v.rule for v in violations)


def test_conformance_fails_on_status_semantic_misuse_danger_uses_success() -> None:
    """AC5/ERROR6: danger selector referencing a success token → §64.18 pt.3 violation.

    ERROR 6 remediation: semantic misuse (not just redeclaration) is now detected.
    A selector with "danger" context must not use a success-family token.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-danger { color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-semantic-misuse.css")
    violations = exc_info.value.violations
    assert any("no-status-color-reinterpretation" in v.rule for v in violations), (
        "Expected semantic misuse violation for danger selector using success token"
    )


def test_conformance_fails_on_status_semantic_misuse_cancelled_uses_success() -> None:
    """AC5/ERROR6: cancelled selector referencing a success token → §64.18 pt.3 violation."""
    injected = (
        _load_prototype_css()
        + "\n.tone-cancelled-override { color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="injected-cancelled-misuse.css")
    violations = exc_info.value.violations
    assert any("no-status-color-reinterpretation" in v.rule for v in violations)


def test_conformance_pass_danger_selector_uses_danger_token() -> None:
    """AC5/ERROR6 positive: danger selector using danger token is conformant."""
    # .tone-danger in the prototype CSS uses var(--ak-danger) — must pass
    css = _load_prototype_css()
    # This must not raise for the conformant prototype CSS
    check_token_conformance(css)  # no raise


# ---------------------------------------------------------------------------
# AC6 — Conformance PASS on conformant CSS
# ---------------------------------------------------------------------------


def test_conformance_pass_on_prototype_css() -> None:
    """AC6: prototype design-system.css passes all conformance rules."""
    check_token_conformance(_load_prototype_css())  # must not raise


def test_conformance_pass_on_minimal_conformant_css() -> None:
    """AC6: a minimal, conformant CSS snippet passes all rules."""
    # A simple conformant snippet: uses tokens for colors and sizes, no bare hex
    conformant = """\
:root {
  --ak-bg: #111214;
  --ak-text: #f0f0f0;
  --ak-success: #74d17f;
  --control-height-md: 2.375rem;
}

.my-panel {
  color: var(--ak-text);
  background: var(--ak-bg);
}
"""
    check_token_conformance(conformant, filename="conformant.css")  # must not raise


def test_conformance_error_contains_all_violations() -> None:
    """AC5/AC6: ConformanceError lists all found violations in the exception."""
    # Inject two different violations
    injected = (
        _load_prototype_css()
        + "\n.bad1 { font-size: 12px; }\n"
        + ".bad2 { color: #cafebabe; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="multi.css")
    violations = exc_info.value.violations
    rules = {v.rule for v in violations}
    assert "§64.17/no-font-size-literal" in rules
    assert "§64.17/no-adhoc-hex" in rules


# ---------------------------------------------------------------------------
# ERROR 1 — font-size whitelist-by-construction (round-2 remediation)
# The rule allows ONLY var(...); every other form is a violation.
# At least 3 distinct non-var forms must each independently fail.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_font_size_inherit_keyword() -> None:
    """ERROR1/R2: font-size: inherit keyword outside :root → §64.17 violation.

    The whitelist (only var(...) allowed) rejects keywords such as 'inherit'
    that were previously exempt.  FK-64 §64.17 forbids ANY non-token font-size
    outside the token-definition block.
    """
    injected = _load_prototype_css() + "\n.my-label { font-size: inherit; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="inherit.css")
    assert any("no-font-size-literal" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_font_size_normal_keyword() -> None:
    """ERROR1/R2: font-size: normal keyword outside :root → §64.17 violation.

    'normal' is a CSS keyword; the whitelist rejects it just like any literal.
    """
    injected = _load_prototype_css() + "\n.widget { font-size: normal; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="normal.css")
    assert any("no-font-size-literal" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_font_size_unitless_number() -> None:
    """ERROR1/R2: font-size: 1.2 (unitless) outside :root → §64.17 violation.

    A bare numeric value without a unit is not a var() reference and is
    therefore rejected by the whitelist.
    """
    injected = _load_prototype_css() + "\n.kpi { font-size: 1.2; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="unitless.css")
    assert any("no-font-size-literal" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_font_size_larger_keyword() -> None:
    """ERROR1/R2: font-size: larger keyword outside :root → §64.17 violation.

    'larger' is a relative keyword, still not a var() reference.
    """
    injected = _load_prototype_css() + "\n.zoom { font-size: larger; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="larger.css")
    assert any("no-font-size-literal" in v.rule for v in exc_info.value.violations)


def test_conformance_passes_font_size_var_reference() -> None:
    """ERROR1/R2 positive: font-size: var(--text-sm) outside :root → conformant."""
    conformant = (
        ":root {\n  --text-sm: 0.875em;\n}\n"
        ".label { font-size: var(--text-sm); }\n"
    )
    check_token_conformance(conformant, filename="conformant-varref.css")  # must not raise


# ---------------------------------------------------------------------------
# ERROR 2 — control size whitelist-by-construction (round-2 remediation)
# Only var(--control-*) is allowed; 3+ distinct violation forms must each fail.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_control_height_non_control_var() -> None:
    """ERROR2/R2: height: var(--space-4) on control selector → §64.18 pt.2 violation.

    Whitelist-by-construction: even a valid var() reference is a violation if
    it does not point to a --control-* token.  Round 1 only caught literals.
    """
    injected = (
        _load_prototype_css()
        + "\n.ak-button--xl { height: var(--space-4); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="non-control-var.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_control_height_em_literal() -> None:
    """ERROR2/R2: height: 2em on button selector → §64.18 pt.2 violation.

    'em' units were not caught by the old literal regex (only px/rem matched).
    """
    injected = (
        _load_prototype_css()
        + "\n.ak-button--xl { height: 2em; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="em-literal.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_control_padding_px_literal() -> None:
    """ERROR2/R2: padding: 8px on control selector → §64.18 pt.2 violation."""
    injected = (
        _load_prototype_css()
        + "\n.ak-input { padding: 8px; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="padding-px.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_control_minheight_non_control_var_select() -> None:
    """ERROR2/R2: min-height: var(--leading-tight) on select → §64.18 pt.2 violation.

    A non-control var() reference on the native 'select' element selector
    proves the whitelist applies to ALL control selectors and ALL units.
    """
    injected = (
        _load_prototype_css()
        + "\nselect { min-height: var(--leading-tight); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="select-bad-var.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_conformance_passes_control_height_control_var() -> None:
    """ERROR2/R2 positive: height: var(--control-height-md) → conformant."""
    conformant = (
        ":root {\n  --control-height-md: 2.375rem;\n}\n"
        ".ak-button { min-height: var(--control-height-md); padding: var(--control-padding-md); }\n"
        ".ak-button:hover { background: var(--ak-surface-3); }\n"
    )
    check_token_conformance(conformant, filename="control-ok.css")  # must not raise


# ---------------------------------------------------------------------------
# ERROR 3 — status semantic whitelist-by-construction (round-2 remediation)
# At least 3 distinct cross-family misuses must each independently fail.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_danger_selector_uses_warn_token() -> None:
    """ERROR3/R2: danger selector referencing a warning token → §64.18 pt.3.

    '.tone-danger { color: var(--ak-warn) }' crosses the danger→warning boundary.
    The whitelist only allows {ak-danger, ak-status-cancelled} for danger context.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-danger-alt { color: var(--ak-warn); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="danger-warn.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_conformance_fails_on_success_selector_uses_info_token() -> None:
    """ERROR3/R2: success selector referencing an info token → §64.18 pt.3.

    '.tone-success { color: var(--ak-info) }' crosses the success→info boundary.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-success-alt { color: var(--ak-info); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="success-info.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_conformance_fails_on_info_selector_uses_warn_token() -> None:
    """ERROR3/R2: info selector referencing a warning token → §64.18 pt.3.

    '.tone-info { color: var(--ak-warn) }' crosses the info→warning boundary.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-info-badge { color: var(--ak-warn); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="info-warn.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_conformance_fails_on_error_selector_uses_success_token() -> None:
    """ERROR3/R2: error selector (danger family) referencing success token → §64.18 pt.3."""
    injected = (
        _load_prototype_css()
        + "\n.state-error { color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="error-success.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_conformance_passes_prototype_status_selectors() -> None:
    """ERROR3/R2 positive: all prototype status selectors pass the whitelist check."""
    # The prototype CSS has .tone-danger, .tone-success, .tone-warning, .tone-info,
    # .tone-done, .tone-cancelled — each using only their own family's tokens.
    check_token_conformance(_load_prototype_css())  # must not raise


# ---------------------------------------------------------------------------
# ERROR 4 (R3) — story-status semantic whitelist (round-3 remediation)
# FK-64 §64.14: story-status selectors must only reference their own family token.
# Negative tests: each cross-family misuse must fail independently.
# Positive test: real prototype story-status selectors must still pass.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_status_backlog_selector_uses_danger_token() -> None:
    """R3/story-status: backlog selector using --ak-danger → §64.18 pt.3 violation.

    .tone-status-backlog has story-status-backlog context; only --ak-status-backlog
    is allowed.  Referencing a severity-family token (--ak-danger) is a misuse.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-status-backlog { color: var(--ak-danger); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="backlog-danger.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: backlog selector must not use --ak-danger"


def test_conformance_fails_on_status_approved_selector_uses_success_token() -> None:
    """R3/story-status: approved selector using --ak-success → §64.18 pt.3 violation.

    .tone-status-approved context only permits --ak-status-approved.  Using a
    severity-family token (--ak-success) is a semantic cross-family misuse.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-status-approved { color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="approved-success.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: approved selector must not use --ak-success"


def test_conformance_fails_on_status_progress_selector_uses_info_token() -> None:
    """R3/story-status: progress selector using --ak-info → §64.18 pt.3 violation.

    .tone-status-progress context only permits --ak-status-progress.  Using a
    severity-family token (--ak-info) is a semantic cross-family misuse.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-status-progress { color: var(--ak-info); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="progress-info.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: progress selector must not use --ak-info"


def test_conformance_fails_on_status_backlog_selector_uses_approved_token() -> None:
    """R3/story-status: backlog selector using the approved token → §64.18 pt.3 violation.

    Cross-misuse within story-status family: --ak-status-approved is not allowed
    in a backlog-context selector.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-status-backlog { color: var(--ak-status-approved); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="backlog-uses-approved.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: backlog selector must not use --ak-status-approved"


def test_conformance_passes_prototype_story_status_selectors() -> None:
    """R3/story-status positive: real prototype story-status selectors still pass.

    .tone-status-backlog, .tone-status-approved, .tone-status-progress each use
    only their own matching token — no false-positive on the genuine prototype CSS.
    """
    check_token_conformance(_load_prototype_css())  # must not raise


# ---------------------------------------------------------------------------
# ERROR 1 (R4) — strict 1:1 whitelist: cross-axis severity↔story-status
# FK-64 §64.14: severity and story-status are SEPARATE families.
# Each .tone-* selector must reference ONLY its own single family token.
# Negative tests: the three required cross-axis cases MUST each FAIL.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_warning_selector_uses_status_progress_token() -> None:
    """R4/strict-1:1: warning selector using story-status token → §64.18 pt.3.

    .tone-warning carries a severity-warning context (allowed: {ak-warn} only).
    --ak-status-progress is a story-status token; cross-axis use is a violation.
    FK-64 §64.14: severity and story-status are SEPARATE badge families.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-warning { color: var(--ak-status-progress); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="warning-uses-status-progress.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: .tone-warning must not reference --ak-status-progress"


def test_conformance_fails_on_success_selector_uses_status_done_token() -> None:
    """R4/strict-1:1: success selector using story-status-done token → §64.18 pt.3.

    .tone-success carries a severity-success context (allowed: {ak-success} only).
    --ak-status-done is a story-status token; cross-axis use is a violation.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-success { color: var(--ak-status-done); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="success-uses-status-done.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: .tone-success must not reference --ak-status-done"


def test_conformance_fails_on_cancelled_selector_uses_danger_token() -> None:
    """R4/strict-1:1: cancelled selector using severity-danger token → §64.18 pt.3.

    .tone-cancelled carries the story-status-cancelled context (allowed: {ak-status-cancelled}).
    --ak-danger is a severity token; referencing it from a cancelled context is cross-axis misuse.
    FK-64 §64.14: cancelled is a terminal story-status, not a severity alias.
    """
    injected = (
        _load_prototype_css()
        + "\n.tone-cancelled { color: var(--ak-danger); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(injected, filename="cancelled-uses-danger.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected violation: .tone-cancelled must not reference --ak-danger"


def test_conformance_passes_prototype_all_tone_selectors_strict_1to1() -> None:
    """R4/strict-1:1 positive: every .tone-* selector in the real prototype passes.

    Verifies that the strict 1:1 map does not produce false-positives on the
    genuine design-system.css: .tone-success→--ak-success, .tone-warning→--ak-warn,
    .tone-danger→--ak-danger, .tone-info→--ak-info, .tone-done→--ak-done,
    .tone-cancelled→--ak-status-cancelled, .tone-status-*→their own tokens.
    """
    check_token_conformance(_load_prototype_css())  # must not raise


# ---------------------------------------------------------------------------
# ERROR 2 (R4) — one-line :root { ... } must not silence subsequent violations
# A one-liner opens AND closes on the same line → in_root stays False afterward.
# All three rule families must still fire on lines that follow a one-liner :root.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_violations_after_one_line_root_block() -> None:
    """R4/brace-depth: font-size, hex, and status misuse after one-liner :root → all detected.

    Prior bug: a one-line ':root { --ak-bg: #111214; }' left in_root=True for
    every subsequent line, silently skipping font-size, hex, and status checks.
    This regression test proves that all three violations are detected even when
    the :root block is written as a single line.
    """
    one_liner_css = (
        ":root { --ak-bg: #111214; }\n"
        ".bad { font-size: 12px; color: #c0ffee; }\n"
        ".tone-danger { color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(one_liner_css, filename="one-liner-root.css")
    rules_found = {v.rule for v in exc_info.value.violations}
    assert "§64.17/no-font-size-literal" in rules_found, (
        "font-size literal after one-liner :root was not detected"
    )
    assert "§64.17/no-adhoc-hex" in rules_found, (
        "ad-hoc hex after one-liner :root was not detected"
    )
    assert "§64.18-pt3/no-status-color-reinterpretation" in rules_found, (
        "status misuse after one-liner :root was not detected"
    )


# ---------------------------------------------------------------------------
# ERROR 1 (R5) — token-definition block state machine: one-line :root must NOT
# be flagged (no false positive), while violations AFTER the block ARE caught.
# The previous fix regressed twice (fail-open, then false-positive); these
# tests pin down BOTH halves of the contract for one-line and multi-line roots.
# ---------------------------------------------------------------------------


def test_conformance_passes_on_one_line_root_token_definitions() -> None:
    """R5: a standalone one-line ``:root { ... }`` with font/hex token defs PASSES.

    The inline body of a one-line root holds token DEFINITIONS — the only place
    where ``em`` font sizes and hex colors are allowed.  The state machine must
    exempt this line's content (no false positive).  This is the concrete case
    that the round-4 fix wrongly flagged.
    """
    one_line_root = ":root { --text-sm: 0.875em; --ak-bg: #111214; }\n"
    check_token_conformance(one_line_root, filename="one-line-root-defs.css")  # no raise


def test_conformance_one_line_root_then_violation_detects_all_three() -> None:
    """R5: one-line root + ``.bad`` line + danger misuse → all three violations.

    Proves the state machine is NOT fail-open: a one-line root must not silence
    the following lines.  Mirrors the reported ERROR 1 acceptance case exactly.
    """
    css = (
        ":root { --ak-bg:#111214; }\n"
        ".bad { font-size:12px; color:#c0ffee; }\n"
        ".tone-danger { color: var(--ak-success) }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="one-line-then-bad.css")
    rules = {v.rule for v in exc_info.value.violations}
    assert "§64.17/no-font-size-literal" in rules
    assert "§64.17/no-adhoc-hex" in rules
    assert "§64.18-pt3/no-status-color-reinterpretation" in rules


def test_conformance_passes_on_multi_line_root_token_definitions() -> None:
    """R5: a multi-line ``:root { ... }`` with font/hex token defs PASSES.

    Body lines (font/size literals and hex values) are token definitions and
    must be exempt until the closing-brace line.
    """
    multi_line_root = (
        ":root {\n"
        "  --text-sm: 0.875em;\n"
        "  --ak-bg: #111214;\n"
        "  --shadow: 0 0 0 color-mix(in srgb, var(--ak-accent), transparent 28%);\n"
        "}\n"
    )
    check_token_conformance(multi_line_root, filename="multi-line-root-defs.css")  # no raise


def test_conformance_multi_line_root_then_violation_is_detected() -> None:
    """R5: a violation AFTER a multi-line root is caught (state machine closes block)."""
    css = (
        ":root {\n"
        "  --text-sm: 0.875em;\n"
        "  --ak-bg: #111214;\n"
        "}\n"
        ".bad { font-size: 12px; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="multi-line-then-bad.css")
    assert any("no-font-size-literal" in v.rule for v in exc_info.value.violations)


def test_conformance_passes_on_normal_one_line_rule_with_token_refs() -> None:
    """R5: a normal one-line (non-root) rule using only token refs PASSES.

    Ensures the state machine does not over-exempt: this line is outside any
    token block but contains no violations, so it must simply pass.
    """
    css = (
        ":root {\n  --ak-text: #f0f0f0;\n  --ak-bg: #111214;\n}\n"
        ".panel { color: var(--ak-text); background: var(--ak-bg); }\n"
    )
    check_token_conformance(css, filename="normal-one-line-rule.css")  # no raise


# ---------------------------------------------------------------------------
# ERROR 2 (R5) — control-size finditer: EVERY declaration on the line checked.
# A condensed good-then-bad control rule must FAIL on the later bad property.
# ---------------------------------------------------------------------------


def test_conformance_fails_on_condensed_control_good_then_bad() -> None:
    """R5/finditer: condensed control rule where a LATER property is bad → FAILS.

    ``.ak-button { min-height: var(--control-height-md); padding: 1rem; }`` —
    the first property is conformant but ``padding: 1rem`` is a literal.  The
    old ``search`` only checked the first match and wrongly PASSED; ``finditer``
    must report the ``padding`` violation.
    """
    css = (
        ":root {\n  --control-height-md: 2.375rem;\n}\n"
        ".ak-button { min-height: var(--control-height-md); padding: 1rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="condensed-good-then-bad.css")
    violations = exc_info.value.violations
    assert any("control-token-required" in v.rule for v in violations)
    assert any("padding" in v.detail for v in violations), (
        "the later bad 'padding' declaration must be the reported violation"
    )


def test_conformance_passes_on_condensed_control_all_good() -> None:
    """R5/finditer positive: condensed control rule, all properties conformant → PASSES."""
    css = (
        ":root {\n"
        "  --control-height-md: 2.375rem;\n"
        "  --control-padding-md: 0.5rem 0.8125rem;\n"
        "}\n"
        ".ak-button { min-height: var(--control-height-md); "
        "padding: var(--control-padding-md); }\n"
    )
    check_token_conformance(css, filename="condensed-all-good.css")  # no raise


def test_conformance_passes_on_real_ak_button_block() -> None:
    """R5/finditer positive: the real prototype ``.ak-button`` block PASSES.

    The genuine ``.ak-button`` uses ``min-height: var(--control-height-md)`` and
    ``padding: var(--control-padding-md)`` across multiple lines — no false
    positive from the finditer-per-declaration validation.
    """
    check_token_conformance(_load_prototype_css())  # no raise


# ---------------------------------------------------------------------------
# MAJOR 3 (R5) — status-done / status-cancelled context must NOT collapse into
# the generic done/cancelled context.  Classification is most-specific-wins.
# ---------------------------------------------------------------------------


def test_conformance_passes_status_done_selector_uses_status_done_token() -> None:
    """R5/MAJOR3: ``.tone-status-done`` using ``--ak-status-done`` PASSES.

    Story-status-done context owns ONLY ``--ak-status-done``.  Before the fix
    this wrongly FAILED because ``status-done`` collapsed into the generic
    severity ``done`` context (which owns ``--ak-done``).
    """
    css = (
        ":root {\n  --ak-status-done: #3fb950;\n}\n"
        ".tone-status-done { color: var(--ak-status-done) }\n"
    )
    check_token_conformance(css, filename="status-done-ok.css")  # no raise


def test_conformance_fails_status_done_selector_uses_generic_done_token() -> None:
    """R5/MAJOR3: ``.tone-status-done`` using ``--ak-done`` → §64.18 pt.3 violation.

    Before the fix this wrongly PASSED because ``status-done`` collapsed into the
    generic ``done`` context (allowed ``--ak-done``).  With the dedicated
    story-status-done context, ``--ak-done`` is now cross-axis misuse.
    """
    css = (
        ":root {\n  --ak-done: #82c4ff;\n  --ak-status-done: #3fb950;\n}\n"
        ".tone-status-done { color: var(--ak-done) }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="status-done-uses-done.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_conformance_passes_generic_done_selector_uses_done_token() -> None:
    """R5/MAJOR3: ``.tone-done`` using ``--ak-done`` still PASSES (no regression).

    The generic severity ``done`` context (the real ``.tone-done`` selector)
    must keep owning ``--ak-done`` after adding the more-specific status-done.
    """
    css = (
        ":root {\n  --ak-done: #82c4ff;\n}\n"
        ".tone-done { color: var(--ak-done) }\n"
    )
    check_token_conformance(css, filename="done-ok.css")  # no raise


def test_conformance_passes_status_cancelled_selector_uses_status_cancelled() -> None:
    """R5/MAJOR3: ``.tone-status-cancelled`` using ``--ak-status-cancelled`` PASSES."""
    css = (
        ":root {\n  --ak-status-cancelled: #8b949e;\n}\n"
        ".tone-status-cancelled { color: var(--ak-status-cancelled) }\n"
    )
    check_token_conformance(css, filename="status-cancelled-ok.css")  # no raise


def test_conformance_passes_real_tone_cancelled_selector() -> None:
    """R5/MAJOR3: the real ``.tone-cancelled`` (→ ``--ak-status-cancelled``) PASSES.

    The generic terminal ``cancelled`` context owns ``--ak-status-cancelled``
    (the real CSS), and must NOT be shadowed by the more-specific
    ``status-cancelled`` keyword for a selector that lacks the ``status-`` prefix.
    """
    css = (
        ":root {\n  --ak-status-cancelled: #8b949e;\n}\n"
        ".tone-cancelled { color: var(--ak-status-cancelled) }\n"
    )
    check_token_conformance(css, filename="cancelled-ok.css")  # no raise


# ---------------------------------------------------------------------------
# ERROR (R6) — ambiguous multi-semantic selector must FAIL (fail-closed).
# A selector carrying two CONFLICTING status semantics (different allowed-sets)
# must be rejected regardless of which token it references; the checker must
# never silently pick one semantic.  Substring-superset overlaps (status-done
# ⊃ done, warning ⊃ warn) are NOT conflicts and must keep classifying to one.
# ---------------------------------------------------------------------------


def test_conformance_fails_ambiguous_danger_success_selector() -> None:
    """R6: ``.tone-danger-success`` carries danger AND success → §64.18 violation.

    Before the R6 fix this wrongly PASSED: the longest-match-wins logic returned
    the first context and validated only against it, so referencing the matched
    family (success) slipped through.  Now the conflicting semantics make the
    selector ambiguous and any status token it references is a violation.
    """
    css = (
        ":root {\n  --ak-danger: #ff5b57;\n  --ak-success: #74d17f;\n}\n"
        ".tone-danger-success { color: var(--ak-success) }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="ambiguous-danger-success.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected ambiguity violation for .tone-danger-success referencing --ak-success"


def test_conformance_fails_ambiguous_status_done_success_selector() -> None:
    """R6: ``.tone-status-done-success`` carries status-done AND success → fail.

    ``done`` collapses into ``status-done`` (same semantic, higher specificity),
    but ``status-done`` and ``success`` are two DISTINCT allowed-sets → ambiguous.
    Referencing ``--ak-status-done`` (the matched token) must still FAIL.
    """
    css = (
        ":root {\n  --ak-status-done: #3fb950;\n  --ak-success: #74d17f;\n}\n"
        ".tone-status-done-success { color: var(--ak-status-done) }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="ambiguous-status-done-success.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "Expected ambiguity violation for .tone-status-done-success"


def test_conformance_passes_warning_selector_uses_warn_token() -> None:
    """R6: ``.tone-warning`` (warn ⊂ warning, same semantic) PASSES, single ctx.

    The superset-collapse must not turn a genuine single-semantic selector into
    an ambiguous one: ``warn`` is subsumed by ``warning`` (both own ``ak-warn``).
    """
    css = (
        ":root {\n  --ak-warn: #ffb32c;\n}\n"
        ".tone-warning { color: var(--ak-warn) }\n"
    )
    check_token_conformance(css, filename="warning-ok.css")  # no raise


# ---------------------------------------------------------------------------
# ROUND 7 — comprehensive multi-occurrence / multi-block sweep.
# Every per-line check must catch a SECOND (not just the first) occurrence, and
# the drift check must read EVERY ``:root`` block, not just the first.  These
# pin the first-good-rest-bad contract for each finditer/multi-block site so the
# search/first-match class of bug cannot reappear.
# ---------------------------------------------------------------------------


def test_drift_check_detects_overriding_second_root_block() -> None:
    """R7/multi-block: a SECOND ``:root`` overriding a token value → drift FAILS.

    Appending ``:root { --ak-success: #deadbe; }`` after the legitimate CSS
    overrides ``--ak-success`` in the cascade.  The previous ``re.search`` read
    only the FIRST ``:root`` block, so this slipped past the drift check.  The
    multi-block parse now compares every declared value to the owner value.
    """
    css = _load_prototype_css() + "\n:root { --ak-success: #deadbe; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_css_token_drift(css)
    violations = exc_info.value.violations
    assert any("ak-success" in v.location for v in violations)
    assert any("css-owner-drift" in v.rule for v in violations)
    assert any("#deadbe" in v.detail for v in violations)


def test_drift_check_detects_unowned_token_in_second_root_block() -> None:
    """R7/multi-block: an unowned token var in a SECOND ``:root`` → drift FAILS.

    A later ``:root`` block introducing a token-prefixed var that the owner does
    not back must be flagged just like one in the first block (no silent surplus
    hidden in a trailing block).
    """
    css = _load_prototype_css() + "\n:root { --ak-rogue-second-block: #badc0d; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_css_token_drift(css)
    violations = exc_info.value.violations
    assert any("ak-rogue-second-block" in v.detail for v in violations)
    assert any("unowned" in v.rule for v in violations)


def test_drift_check_allows_identical_redeclaration_in_second_root_block() -> None:
    """R7/multi-block: a SECOND ``:root`` re-declaring a token with the SAME value passes.

    An identical re-declaration changes nothing in the cascade and must not be a
    false positive — only a DIFFERING value (or an unowned var) is drift.
    """
    css = _load_prototype_css() + "\n:root { --ak-success: #74d17f; }\n"
    check_css_token_drift(css)  # must not raise


def test_conformance_fails_on_second_font_size_on_same_line() -> None:
    """R7/finditer: ``font-size: var(...); font-size: 12px;`` on one line → FAILS.

    The first declaration is conformant (var ref) and the second is a literal.
    ``search`` only examined the first match and wrongly PASSED; ``finditer``
    must catch the later literal (first-good-rest-bad must FAIL).
    """
    css = (
        ":root {\n  --text-sm: 0.875em;\n}\n"
        ".label { font-size: var(--text-sm); font-size: 12px; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="second-font-size.css")
    assert any(
        "no-font-size-literal" in v.rule for v in exc_info.value.violations
    ), "the second (literal) font-size declaration must be flagged"


def test_conformance_fails_on_second_local_size_decl_on_same_line() -> None:
    """R7/finditer: first local var is a token ref, the SECOND is a size literal → FAILS.

    ``.w { --a: var(--ak-text); --b: 13px; }`` — only the second local declares a
    raw size literal.  The previous ``re.search`` checked just the first match
    and could miss the later literal; ``finditer`` validates every declaration.
    """
    css = (
        ":root {\n  --ak-text: #f0f0f0;\n}\n"
        ".w { --a: var(--ak-text); --b: 13px; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="second-local-size.css")
    assert any(
        "no-local-font-scale" in v.rule for v in exc_info.value.violations
    ), "the second (literal) local custom property must be flagged"


def test_conformance_fails_on_second_hex_on_same_line() -> None:
    """R7/finditer: first color is a token ref, the SECOND value is a raw hex → FAILS.

    ``.b { color: var(--ak-text); border-color: #c0ffee; }`` — the ad-hoc hex
    check already uses finditer; this pins that a first-good-rest-bad single line
    still fails (regression guard for the hex check).
    """
    css = (
        ":root {\n  --ak-text: #f0f0f0;\n}\n"
        ".b { color: var(--ak-text); border-color: #c0ffee; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="second-hex.css")
    assert any("no-adhoc-hex" in v.rule for v in exc_info.value.violations)


def test_conformance_fails_on_second_control_prop_on_same_line() -> None:
    """R7/finditer: control rule first prop good, SECOND prop a literal → FAILS.

    ``.ak-button { min-height: var(--control-height-md); padding: 1rem; }`` — the
    control-size check already uses finditer; this guards that a condensed
    good-then-bad control line still reports the later violation.
    """
    css = (
        ":root {\n  --control-height-md: 2.375rem;\n}\n"
        ".ak-button { min-height: var(--control-height-md); padding: 1rem; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="second-control-prop.css")
    violations = exc_info.value.violations
    assert any("control-token-required" in v.rule for v in violations)
    assert any("padding" in v.detail for v in violations)


def test_conformance_fails_on_status_misuse_with_second_var_on_line() -> None:
    """R7/finditer: status selector, first token allowed, SECOND token alien → FAILS.

    ``.tone-danger { color: var(--ak-danger); border-color: var(--ak-success); }``
    — the danger context allows only ``--ak-danger``; the SECOND var (success)
    is cross-family misuse.  The status check already uses finditer over var
    usages; this guards the first-good-rest-bad single-line contract.
    """
    css = (
        ":root {\n  --ak-danger: #ff5b57;\n  --ak-success: #74d17f;\n}\n"
        ".tone-danger { color: var(--ak-danger); border-color: var(--ak-success); }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="status-second-var.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    ), "the second (alien-family) status token must be flagged"


def test_conformance_pass_on_prototype_after_round7_sweep() -> None:
    """R7 positive: the real prototype CSS still passes BOTH checks (no false positive).

    The prototype legitimately repeats patterns (multiple font-size: var refs,
    multiple control props, multiple status selectors); the multi-occurrence
    sweep must not introduce a false positive on the genuine design system.
    """
    css = _load_prototype_css()
    check_css_token_drift(css)  # must not raise
    check_token_conformance(css)  # must not raise


# ---------------------------------------------------------------------------
# ROUND 8 — two NEW classes:
#   (A) var-scope: a value-level check must only judge vars belonging to the
#       declaration the rule targets (font-size value), never sibling
#       declarations on the same line (no false positive on legitimate CSS).
#   (B) selector-list/multi-line: control/status checks must evaluate the FULL
#       comma-separated and/or multi-line selector list, not just the {-line
#       (no fail-open on a violation hidden behind a multi-line selector list).
# ---------------------------------------------------------------------------

_ROUND8_ROOT = (
    ":root {\n"
    "  --text-sm: 0.875em;\n"
    "  --ak-text: #f0f0f0;\n"
    "  --ak-success: #74d17f;\n"
    "  --ak-danger: #ff5b57;\n"
    "  --control-height-md: 2.375rem;\n"
    "  --control-padding-md: 0.5rem 0.8125rem;\n"
    "  --shadow-md: 0 0.625rem 1.625rem rgba(0,0,0,0.3);\n"
    "}\n"
)


def test_r8_color_var_plus_font_size_var_on_one_line_is_no_false_positive() -> None:
    """R8/var-scope: ``color: var(--shadow-md); font-size: var(--text-sm);`` PASSES.

    The font-size local-var indirection check must scan vars ONLY inside the
    font-size declaration's value.  Previously it scanned every var() on the
    line, so the sibling ``color: var(--shadow-md)`` (a non-owner allowlist var)
    was wrongly attributed to the font-size rule — a false positive that would
    block legitimate CSS.
    """
    css = _ROUND8_ROOT + ".foo { color: var(--shadow-md); font-size: var(--text-sm); }\n"
    check_token_conformance(css, filename="r8-color-and-fontsize.css")  # must not raise


def test_r8_box_shadow_var_plus_control_var_is_no_false_positive() -> None:
    """R8/var-scope: box-shadow var alongside valid control vars PASSES.

    A non-control declaration (``box-shadow: var(--shadow-md)``) on a control
    selector must not be judged by the control-size rule; only height/min-height/
    padding values are control-checked, each scoped to its own value.
    """
    css = (
        _ROUND8_ROOT
        + ".ak-button { box-shadow: var(--shadow-md); "
        "min-height: var(--control-height-md); padding: var(--control-padding-md); }\n"
    )
    check_token_conformance(css, filename="r8-boxshadow-and-control.css")  # no raise


def test_r8_font_size_non_token_local_var_still_fails() -> None:
    """R8/var-scope: a non-token var USED AS the font-size value still FAILS.

    Scoping to the font-size value must not become fail-open: a genuine
    non-owner local var as the font-size value is still a §64.18 pt.4 violation.
    """
    css = _ROUND8_ROOT + ".w { color: var(--ak-text); font-size: var(--my-local); }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-fontsize-nontoken-local.css")
    assert any("no-local-font-scale" in v.rule for v in exc_info.value.violations)


def test_r8_multiline_control_selector_list_violation_fails() -> None:
    """R8/selector-list: ``.ak-button,\\n.foo { padding: 1rem; }`` FAILS.

    The control selector ``.ak-button`` is on the line BEFORE the ``{``.  The
    old single-line selector match missed it (fail-open).  The full selector
    list is now parsed, so the literal padding is flagged.
    """
    css = _ROUND8_ROOT + ".ak-button,\n.foo { padding: 1rem; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-multiline-control.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_r8_multiline_status_selector_list_violation_fails() -> None:
    """R8/selector-list: ``.tone-danger,\\n.foo { color: var(--ak-success); }`` FAILS.

    The status selector ``.tone-danger`` is on the line BEFORE the ``{``; the
    danger context must reject the success token even though the selector spans
    multiple lines.
    """
    css = _ROUND8_ROOT + ".tone-danger,\n.foo { color: var(--ak-success); }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-multiline-status.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_r8_comma_control_mixed_with_neutral_violation_fails() -> None:
    """R8/selector-list: ``.foo, .ak-button { padding: 1rem; }`` FAILS.

    A comma list that mixes a neutral selector with a control selector must
    still apply the control rule (ANY control selector in the list arms it).
    """
    css = _ROUND8_ROOT + ".foo, .ak-button { padding: 1rem; }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-comma-control-neutral.css")
    assert any("control-token-required" in v.rule for v in exc_info.value.violations)


def test_r8_comma_status_mixed_with_neutral_violation_fails() -> None:
    """R8/selector-list: ``.neutral, .tone-danger { color: var(--ak-success); }`` FAILS."""
    css = _ROUND8_ROOT + ".neutral, .tone-danger { color: var(--ak-success); }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-comma-status-neutral.css")
    assert any(
        "no-status-color-reinterpretation" in v.rule for v in exc_info.value.violations
    )


def test_r8_multiline_conflicting_status_list_is_ambiguous_and_fails() -> None:
    """R8/selector-list: ``.tone-danger,\\n.tone-success { color: var(--ak-success); }`` FAILS.

    A comma list mixing two DIFFERENT status semantics is ambiguous → fail-closed
    on any status token (consistent with round-6 single-selector ambiguity).
    """
    css = _ROUND8_ROOT + ".tone-danger,\n.tone-success { color: var(--ak-success); }\n"
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-conflicting-status-list.css")
    violations = exc_info.value.violations
    assert any("no-status-color-reinterpretation" in v.rule for v in violations)
    assert any("conflicting status" in v.detail for v in violations)


def test_r8_multiline_control_list_all_good_passes() -> None:
    """R8/selector-list positive: a multi-line control list with valid tokens PASSES."""
    css = (
        _ROUND8_ROOT
        + ".ak-button,\n.ak-input { min-height: var(--control-height-md); "
        "padding: var(--control-padding-md); }\n"
    )
    check_token_conformance(css, filename="r8-multiline-control-good.css")  # no raise


def test_r8_first_good_second_bad_font_size_control_hex_all_fail() -> None:
    """R8: multiple decls on one line, first good / second bad, each family FAILS."""
    css = (
        _ROUND8_ROOT
        + ".l { font-size: var(--text-sm); font-size: 12px; }\n"
        + ".ak-button { min-height: var(--control-height-md); padding: 1rem; }\n"
        + ".b { color: var(--ak-text); border-color: #c0ffee; }\n"
    )
    with pytest.raises(ConformanceError) as exc_info:
        check_token_conformance(css, filename="r8-first-good-second-bad.css")
    rules = {v.rule for v in exc_info.value.violations}
    assert "§64.17/no-font-size-literal" in rules
    assert "§64.18-pt2/control-token-required" in rules
    assert "§64.17/no-adhoc-hex" in rules


def test_r8_prototype_still_passes_both_checks() -> None:
    """R8 positive: the real prototype CSS still passes BOTH checks (no false positive)."""
    css = _load_prototype_css()
    check_css_token_drift(css)  # must not raise
    check_token_conformance(css)  # must not raise
