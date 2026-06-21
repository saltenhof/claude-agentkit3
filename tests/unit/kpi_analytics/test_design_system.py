"""Unit tests for the DesignSystem token owner (AG3-092, FK-64).

AC1 — typed Pydantic token owner exists, no I/O, no HTTP.
AC2 — get_design_tokens delivers typed token set from owner.
AC7 — status family is complete (success/warning/danger/info + done/cancelled
       + backlog/approved/in_progress).
AC8 — chart.series.* token family present, covers SERIES_COLORS.
"""

from __future__ import annotations

import pytest

from agentkit.backend.kpi_analytics.catalog import KpiCatalog
from agentkit.backend.kpi_analytics.design_system import (
    ColorTokens,
    ControlTokens,
    DesignSystem,
    FontFamilyTokens,
    SemanticTextRoleTokens,
    SpacingFamily,
    TypographyLeadingTokens,
    TypographyScaleTokens,
    TypographyTokens,
    TypographyWeightTokens,
    build_css_variables,
    get_design_system,
)
from agentkit.backend.kpi_analytics.top import KpiAnalytics
from agentkit.backend.kpi_analytics.views import DesignTokens

# ---------------------------------------------------------------------------
# AC1 — token owner structure
# ---------------------------------------------------------------------------


def test_design_system_is_instantiable_without_io() -> None:
    """AC1: DesignSystem is a pure data model — no I/O, no HTTP."""
    ds = DesignSystem()
    assert ds is not None


def test_design_system_is_frozen() -> None:
    """AC1: token owner is immutable (Pydantic frozen model)."""
    from pydantic import ValidationError

    ds = DesignSystem()
    with pytest.raises((ValidationError, TypeError)):
        ds.colors = ds.colors  # type: ignore[misc]  # noqa: B010


def test_design_system_has_all_families() -> None:
    """AC1: all six token families are present."""
    ds = DesignSystem()
    assert ds.colors is not None
    assert ds.typography is not None
    assert ds.spacing is not None
    assert ds.control is not None
    assert ds.chart is not None


def test_design_system_color_family_has_all_sub_families() -> None:
    """AC1: color family contains neutral, accent, and status sub-families."""
    ds = DesignSystem()
    assert ds.colors.neutral is not None
    assert ds.colors.accent is not None
    assert ds.colors.status is not None


def test_design_system_typography_family_complete() -> None:
    """AC1: typography family has families, scale, weights, leading, roles."""
    ds = DesignSystem()
    typo = ds.typography
    assert typo.families is not None
    assert typo.scale is not None
    assert typo.weights is not None
    assert typo.leading is not None
    assert typo.roles is not None


def test_design_system_spacing_family_complete() -> None:
    """AC1: spacing family has spacing, border, radii."""
    ds = DesignSystem()
    sp = ds.spacing
    assert sp.spacing is not None
    assert sp.border is not None
    assert sp.radii is not None


def test_design_system_control_family_complete() -> None:
    """AC1: control family has height and padding tokens."""
    ds = DesignSystem()
    ct = ds.control
    assert ct.height_sm
    assert ct.height_md
    assert ct.padding_sm
    assert ct.padding_md


def test_get_design_system_returns_deterministic_result() -> None:
    """AC1: get_design_system() is deterministic — two calls return equal values."""
    ds1 = get_design_system()
    ds2 = get_design_system()
    assert ds1 == ds2


def test_design_system_no_http_endpoint_attribute() -> None:
    """AC1: DesignSystem has no HTTP-related method (FK-64 §64.2)."""
    ds = DesignSystem()
    # DesignSystem must not have router/endpoint methods
    for attr in ("handle_get", "handle_post", "router", "app", "serve"):
        assert not hasattr(ds, attr), f"DesignSystem must not expose {attr!r}"


# ---------------------------------------------------------------------------
# AC1 — token value spot-checks (verbatim from prototype CSS)
# ---------------------------------------------------------------------------


def test_color_tokens_match_prototype_values() -> None:
    """AC1: spot-check color token values against prototype CSS."""
    ds = get_design_system()
    nc = ds.colors.neutral
    assert nc.bg == "#111214"
    assert nc.bg_deep == "#090a0b"
    assert nc.text == "#f0f0f0"
    assert nc.text_muted == "#9a9fa8"
    assert nc.border == "#34373d"


def test_typography_scale_tokens_no_px() -> None:
    """AC1/FK-64 §64.6.2: font-size scale uses em, never px."""
    ds = get_design_system()
    for fname, value in ds.typography.scale.model_dump().items():
        assert "px" not in str(value), (
            f"Typography scale token {fname!r} must not use px: {value!r}"
        )


def test_control_tokens_match_prototype_values() -> None:
    """AC1/AC5: control tokens match CSS prototype values."""
    ds = get_design_system()
    ct = ds.control
    assert ct.height_sm == "1.875rem"
    assert ct.height_md == "2.375rem"
    assert ct.padding_sm == "0.3125rem 0.625rem"
    assert ct.padding_md == "0.5rem 0.8125rem"


def test_spacing_tokens_match_prototype_values() -> None:
    """AC1: spacing tokens match CSS prototype values."""
    ds = get_design_system()
    sp = ds.spacing.spacing
    assert sp.space_1 == "0.25rem"
    assert sp.space_4 == "1rem"
    assert sp.space_8 == "2rem"


def test_radii_tokens_match_prototype_values() -> None:
    """AC1: radii tokens match CSS prototype values."""
    ds = get_design_system()
    r = ds.spacing.radii
    assert r.small == "0.25rem"
    assert r.medium == "0.5rem"
    assert r.pill == "100rem"


# ---------------------------------------------------------------------------
# AC2 — get_design_tokens on KpiAnalytics facade
# ---------------------------------------------------------------------------


def test_get_design_tokens_returns_typed_result() -> None:
    """AC2: get_design_tokens() no longer raises NotImplementedError."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    result = analytics.get_design_tokens()
    assert result is not None


def test_get_design_tokens_contains_all_families() -> None:
    """AC2: result contains all token families."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    result = analytics.get_design_tokens()
    assert result.colors
    assert result.typography
    assert result.spacing
    assert result.control
    assert result.chart


def test_get_design_tokens_is_deterministic() -> None:
    """AC2: successive calls return equal results."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    r1 = analytics.get_design_tokens()
    r2 = analytics.get_design_tokens()
    assert r1 == r2


# ---------------------------------------------------------------------------
# AC1/AC2 — DesignTokens is typed (ERROR 1 remediation)
# ---------------------------------------------------------------------------


def test_design_tokens_fields_are_typed_models() -> None:
    """AC1/AC2: DesignTokens fields are typed Pydantic family models, not dicts."""
    tokens = DesignTokens()
    assert isinstance(tokens.colors, ColorTokens), (
        "DesignTokens.colors must be ColorTokens, not dict"
    )
    assert isinstance(tokens.typography, TypographyTokens), (
        "DesignTokens.typography must be TypographyTokens, not dict"
    )
    assert isinstance(tokens.spacing, SpacingFamily), (
        "DesignTokens.spacing must be SpacingFamily, not dict"
    )
    assert isinstance(tokens.control, ControlTokens), (
        "DesignTokens.control must be ControlTokens, not dict"
    )


def test_get_design_tokens_returns_typed_family_models() -> None:
    """AC2: get_design_tokens returns typed family models on the DesignTokens view."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    result = analytics.get_design_tokens()
    # Each family must be a typed Pydantic model — not a plain dict
    assert isinstance(result.colors, ColorTokens)
    assert isinstance(result.typography, TypographyTokens)
    assert isinstance(result.spacing, SpacingFamily)
    assert isinstance(result.control, ControlTokens)


# ---------------------------------------------------------------------------
# AC4 — build_css_variables is exhaustive and owner-derived (ERROR 2)
# ---------------------------------------------------------------------------


def test_build_css_variables_covers_graph_edge_tokens() -> None:
    """AC4/ERROR2: build_css_variables includes graph-edge tokens (not omitted)."""
    css_map = build_css_variables(get_design_system())
    assert "--graph-edge-width" in css_map, "--graph-edge-width must be in owner CSS map"
    assert "--graph-edge-width-strong" in css_map
    assert "--graph-edge-dash" in css_map


def test_build_css_variables_covers_font_family_tokens() -> None:
    """AC4/ERROR2: build_css_variables includes font-family tokens."""
    css_map = build_css_variables(get_design_system())
    assert "--font-body" in css_map
    assert "--font-display" in css_map


def test_build_css_variables_covers_leading_tokens() -> None:
    """AC4/ERROR2: build_css_variables includes line-height (leading) tokens."""
    css_map = build_css_variables(get_design_system())
    assert "--leading-tight" in css_map
    assert "--leading-title" in css_map
    assert "--leading-body" in css_map


def test_build_css_variables_covers_semantic_type_roles() -> None:
    """AC4/ERROR2: build_css_variables includes all semantic text-role tokens."""
    css_map = build_css_variables(get_design_system())
    for role_var in (
        "--type-label-size", "--type-label-weight",
        "--type-body-size", "--type-body-weight",
        "--type-ui-size", "--type-ui-weight",
        "--type-title-size", "--type-panel-title-size",
        "--type-page-title-size", "--type-kpi-size",
    ):
        assert role_var in css_map, f"Semantic text role {role_var!r} missing from owner CSS map"


def test_build_css_variables_covers_control_font_refs() -> None:
    """AC4/ERROR2: build_css_variables includes control-font-size/weight tokens."""
    css_map = build_css_variables(get_design_system())
    assert "--control-font-size" in css_map
    assert "--control-font-weight" in css_map


def test_build_css_variables_is_owner_derived_no_hand_list() -> None:
    """AC4/ERROR2: build_css_variables derives from the live owner, not a static copy."""
    ds = get_design_system()
    css_map = build_css_variables(ds)
    # Spot-check: value for --ak-success must match the owner's status.success field
    assert css_map["--ak-success"] == ds.colors.status.success
    # Spot-check: --text-xs must match the owner's typography scale
    assert css_map["--text-xs"] == ds.typography.scale.text_xs


def test_get_design_tokens_colors_have_status_family() -> None:
    """AC2/AC7: status family is present in the typed token result."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    result = analytics.get_design_tokens()
    # colors is now a typed ColorTokens model, not a plain dict
    assert result.colors.status is not None
    assert result.colors.status.success


# ---------------------------------------------------------------------------
# AC7 — status family completeness
# ---------------------------------------------------------------------------


def test_status_family_covers_severity_semantics() -> None:
    """AC7: severity tokens (success/warning/danger/info) are present."""
    st = get_design_system().colors.status
    assert st.success, "success missing"
    assert st.warning, "warning missing"
    assert st.danger, "danger missing"
    assert st.info, "info missing"


def test_status_family_covers_terminal_story_states() -> None:
    """AC7: terminal story states (done/cancelled) are present (§64.5.3)."""
    st = get_design_system().colors.status
    assert st.done, "done missing"
    assert st.cancelled, "cancelled missing"


def test_status_family_covers_workflow_states() -> None:
    """AC7: story-status workflow tokens (backlog/approved/in_progress) present (§64.14)."""
    st = get_design_system().colors.status
    assert st.status_backlog, "status_backlog missing"
    assert st.status_approved, "status_approved missing"
    assert st.status_in_progress, "status_in_progress missing"
    assert st.status_done, "status_done missing"
    assert st.status_cancelled, "status_cancelled missing"


def test_status_tokens_match_prototype_values() -> None:
    """AC7: status token values match the prototype CSS (no reinterpretation)."""
    st = get_design_system().colors.status
    assert st.success == "#74d17f"
    assert st.warning == "#ffb32c"
    assert st.danger == "#ff5b57"
    assert st.info == "#7ea7ff"
    assert st.done == "#82c4ff"
    assert st.cancelled == "#8b949e"
    assert st.status_backlog == "#a371f7"
    assert st.status_approved == "#2f81f7"
    assert st.status_in_progress == "#d29922"
    assert st.status_done == "#3fb950"
    assert st.status_cancelled == "#8b949e"


def test_status_mapping_covers_all_five_story_states() -> None:
    """AC7: Backlog/Approved/In Progress/Done/Cancelled all have tokens."""
    st = get_design_system().colors.status
    story_status_tokens = {
        "Backlog": st.status_backlog,
        "Approved": st.status_approved,
        "In Progress": st.status_in_progress,
        "Done": st.status_done,
        "Cancelled": st.status_cancelled,
    }
    for label, value in story_status_tokens.items():
        assert value, f"Story status {label!r} has no token value"


# ---------------------------------------------------------------------------
# AC8 — chart.series.* token family
# ---------------------------------------------------------------------------

# The 12 SERIES_COLORS from AnalyticsView.tsx:38-51 (verbatim)
_PROTOTYPE_SERIES_COLORS = [
    "#48e7ff",  # accent cyan
    "#ffb32c",  # warm yellow
    "#74d17f",  # success green
    "#b38cff",  # violet
    "#ff5b57",  # danger red
    "#7ea7ff",  # info blue
    "#ffd35e",  # accent warm strong
    "#82c4ff",  # done blue
    "#a371f7",  # backlog purple
    "#3fb950",  # status done
    "#d29922",  # progress amber
    "#9ff5ff",  # accent soft
]


def test_chart_series_family_exists() -> None:
    """AC8: chart.series token family is present."""
    ds = get_design_system()
    assert ds.chart is not None
    assert ds.chart.series is not None


def test_chart_series_covers_all_prototype_colors() -> None:
    """AC8: chart series tokens cover the 12 prototype SERIES_COLORS (AnalyticsView.tsx)."""
    series = get_design_system().chart.series
    series_values = list(series.model_dump().values())
    for expected_color in _PROTOTYPE_SERIES_COLORS:
        assert expected_color in series_values, (
            f"Prototype series color {expected_color!r} not found in chart.series tokens"
        )


def test_chart_series_in_get_design_tokens_output() -> None:
    """AC8: chart.series.* appears in the KpiAnalytics.get_design_tokens() output."""
    analytics = KpiAnalytics(catalog=KpiCatalog())
    result = analytics.get_design_tokens()
    # chart is now a typed ChartTokens model
    assert result.chart is not None, "chart family missing from get_design_tokens result"
    series = result.chart.series
    assert series is not None, "chart.series empty in get_design_tokens result"
    # At least one prototype series color is present
    series_values = list(series.model_dump().values())
    assert "#48e7ff" in series_values, "First prototype series color absent"


# ---------------------------------------------------------------------------
# ERROR 4 — owner-field-change affects CSS map (round-2 remediation)
# Proves semantic role refs + control font refs are derived from owner fields,
# not hardcoded — a field change on the owner propagates to build_css_variables.
# ---------------------------------------------------------------------------


def _make_ds_with_role(
    *,
    label_size: str = "text_xs",
    label_weight: str = "semibold",
    body_size: str = "text_sm",
    body_weight: str = "regular",
    ui_size: str = "text_sm",
    ui_weight: str = "medium",
    title_size: str = "text_md",
    title_weight: str = "semibold",
    panel_title_size: str = "text_lg",
    panel_title_weight: str = "semibold",
    page_title_size: str = "text_2xl",
    page_title_weight: str = "semibold",
    kpi_size: str = "text_2xl",
    kpi_weight: str = "black",
) -> DesignSystem:
    """Construct a DesignSystem with a custom SemanticTextRoleTokens."""
    roles = SemanticTextRoleTokens(
        label_size=label_size,
        label_weight=label_weight,
        body_size=body_size,
        body_weight=body_weight,
        ui_size=ui_size,
        ui_weight=ui_weight,
        title_size=title_size,
        title_weight=title_weight,
        panel_title_size=panel_title_size,
        panel_title_weight=panel_title_weight,
        page_title_size=page_title_size,
        page_title_weight=page_title_weight,
        kpi_size=kpi_size,
        kpi_weight=kpi_weight,
    )
    typo = TypographyTokens(
        families=FontFamilyTokens(),
        scale=TypographyScaleTokens(),
        weights=TypographyWeightTokens(),
        leading=TypographyLeadingTokens(),
        roles=roles,
    )
    return DesignSystem(typography=typo)


def test_semantic_role_field_change_propagates_to_css_map() -> None:
    """ERROR4/R2: changing SemanticTextRoleTokens.label_size changes --type-label-size.

    Proves build_css_variables is NOT hardcoded: modifying an owner field
    propagates directly to the exported CSS map.  A hardcoded implementation
    would return 'var(--text-xs)' even after the field is changed to 'text_lg'.
    """
    default_ds = get_design_system()
    default_map = build_css_variables(default_ds)
    assert default_map["--type-label-size"] == "var(--text-xs)"

    # Construct a DesignSystem with a modified label_size
    modified_ds = _make_ds_with_role(label_size="text_lg")
    modified_map = build_css_variables(modified_ds)

    # The CSS var must reflect the new owner field value
    assert modified_map["--type-label-size"] == "var(--text-lg)", (
        "build_css_variables is hardcoded: changing SemanticTextRoleTokens.label_size "
        "did not change --type-label-size in the CSS map"
    )
    # Other vars must be unaffected
    assert modified_map["--type-body-size"] == default_map["--type-body-size"]


def test_semantic_role_weight_field_change_propagates_to_css_map() -> None:
    """ERROR4/R2: changing SemanticTextRoleTokens.kpi_weight changes --type-kpi-weight.

    Verifies weight fields (not just size fields) are also derived from the owner.
    """
    default_ds = get_design_system()
    default_map = build_css_variables(default_ds)
    assert default_map["--type-kpi-weight"] == "var(--weight-black)"

    modified_ds = _make_ds_with_role(kpi_weight="bold")
    modified_map = build_css_variables(modified_ds)

    assert modified_map["--type-kpi-weight"] == "var(--weight-bold)", (
        "build_css_variables is hardcoded for kpi_weight; owner field change "
        "did not propagate to the CSS map"
    )


def test_control_font_role_change_propagates_to_css_map() -> None:
    """ERROR4/R2: changing ControlTokens.font_size changes --control-font-size.

    Constructs a DesignSystem where the control font_size references a different
    semantic role and asserts that --control-font-size reflects the change.
    The default is 'ui' (→ var(--type-ui-size)).  Changing to 'label' (a role
    whose size is text_xs) must yield var(--type-label-size).
    """
    default_ds = get_design_system()
    default_map = build_css_variables(default_ds)
    assert default_map["--control-font-size"] == "var(--type-ui-size)"

    # Build a custom ControlTokens pointing to the 'label' semantic role
    custom_control = ControlTokens(
        height_sm=default_ds.control.height_sm,
        height_md=default_ds.control.height_md,
        padding_sm=default_ds.control.padding_sm,
        padding_md=default_ds.control.padding_md,
        font_size="label",   # changed from "ui" → "label"
        font_weight="label",  # changed from "ui" → "label"
    )
    modified_ds = DesignSystem(control=custom_control)
    modified_map = build_css_variables(modified_ds)

    assert modified_map["--control-font-size"] == "var(--type-label-size)", (
        "build_css_variables --control-font-size is hardcoded; changing "
        "ControlTokens.font_size did not propagate to the CSS map"
    )
    assert modified_map["--control-font-weight"] == "var(--type-label-weight)", (
        "build_css_variables --control-font-weight is hardcoded; changing "
        "ControlTokens.font_weight did not propagate to the CSS map"
    )
