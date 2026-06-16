"""Design-System token owner for the kpi-and-dashboard BC (FK-64 §64.2).

The ``DesignSystem`` component holds **only** token definitions and component
guidelines (token scales, typography, spacing, colors, component rules).  It
is a pure UI-layer definition without runtime logic, I/O, or HTTP endpoints —
boundary-control lives in ``control_plane`` (FK-64 §64.2).

Token families follow FK-64 §§64.5–64.8, §64.14–§64.15, §64.17:
  - Color / neutral colors    (§64.5.1)
  - Accent colors             (§64.5.2)
  - Status / semantic colors  (§64.5.3 + §64.14)
  - Typography scale + roles  (§64.6)
  - Spacing, border, radii    (§64.7)
  - Control tokens            (§64.8)
  - Chart series colors       (§64.15 / §64.17)

ARCH-55: all identifiers, field names and token keys are English.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Repeat-key constants (Sonar S1192: >=3 occurrences -> module constant)
# ---------------------------------------------------------------------------

_CSS_VAR_EMPTY = ""  # no literal repetition risk here; present for clarity

# Shared ``rem`` literal used as default by three otherwise-independent token
# families (spacing, border, radii) that coincide at this value.
_HALF_REM = "0.5rem"


# ---------------------------------------------------------------------------
# Color families (FK-64 §64.5)
# ---------------------------------------------------------------------------


class NeutralColorTokens(BaseModel):
    """Neutral surface, background, border, and text token values (§64.5.1).

    All values are verbatim from ``frontend/prototype/src/design-system.css``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Backgrounds
    bg: str = "#111214"
    bg_deep: str = "#090a0b"
    bg_canvas: str = "#0c0d0f"
    bg_canvas_top: str = "#101114"
    bg_raised: str = "#18191c"
    bg_raised_top: str = "#202126"
    bg_raised_alt: str = "#1a1c20"
    bg_raised_warm: str = "#1e2024"
    bg_rail_bottom: str = "#141518"
    bg_metrics_top: str = "#111316"
    bg_sheet_group: str = "#191b1f"
    bg_epic_from: str = "#24262b"
    bg_tab_top: str = "#25282e"
    bg_tab_mid: str = "#1b1e23"
    bg_tab_bottom: str = "#121418"
    bg_topbar_top: str = "#2b2d31"
    bg_topbar_bottom: str = "#23252a"
    # Warm metric tile (KPI accent surface)
    metric_warm_top: str = "#421a36"
    metric_warm_bottom: str = "#1b0e1a"
    metric_warm_border: str = "#623052"
    # Surfaces
    surface: str = "#1e2023"
    surface_2: str = "#26282c"
    surface_3: str = "#303237"
    surface_table_head: str = "#202226"
    surface_tab_active_top: str = "#1c3844"
    surface_tab_active_bottom: str = "#122830"
    # Borders
    border: str = "#34373d"
    border_strong: str = "#464a52"
    border_header: str = "#2e3339"
    border_tab: str = "#3a4049"
    border_tab_hover: str = "#4a535f"
    border_tab_shell: str = "#353a41"
    border_hairline: str = "0.0625rem"
    line_graph: str = "#65717d"
    # Text
    text: str = "#f0f0f0"
    text_grid: str = "#d8dde3"
    text_inverse: str = "#ffffff"
    text_on_warm: str = "#130f08"
    text_soft: str = "#d3d5d8"
    text_muted: str = "#9a9fa8"
    text_faint: str = "#6f747c"
    text_tab_muted: str = "#878c96"


class AccentColorTokens(BaseModel):
    """Accent / highlight color tokens (FK-64 §64.5.2).

    Teal (cyan) = primary CTA; warm yellow = warnings / attention.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    accent: str = "#0797b8"
    accent_strong: str = "#0cb2d8"
    accent_text: str = "#48e7ff"
    accent_text_soft: str = "#9ff5ff"
    accent_button: str = "#067f9d"
    accent_button_hover: str = "#0995b8"
    accent_warm: str = "#ffb32c"
    accent_warm_strong: str = "#ffd35e"
    violet: str = "#b38cff"


class StatusColorTokens(BaseModel):
    """Semantic / status color tokens (FK-64 §64.5.3 + §64.14).

    Covers:
    - Severity semantics: success / warning / danger / info
    - Terminal story states: done / cancelled
    - Story-status workflow: backlog / approved / in_progress / done / cancelled

    Colors must NOT be reinterpreted across contexts (FK-64 §64.14, §64.18 pt.3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Severity (gate / QA)
    success: str = "#74d17f"
    warning: str = "#ffb32c"
    danger: str = "#ff5b57"
    info: str = "#7ea7ff"
    # Terminal story states (§64.5.3)
    done: str = "#82c4ff"
    cancelled: str = "#8b949e"
    # Story-status workflow tokens (§64.14)
    status_backlog: str = "#a371f7"
    status_approved: str = "#2f81f7"
    status_in_progress: str = "#d29922"
    status_done: str = "#3fb950"
    status_cancelled: str = "#8b949e"


class ColorTokens(BaseModel):
    """Full color token family grouping all three sub-families.

    Args:
        neutral: Neutral / structural color tokens (§64.5.1).
        accent: Accent highlight tokens (§64.5.2).
        status: Semantic status tokens (§64.5.3 + §64.14).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    neutral: NeutralColorTokens = NeutralColorTokens()
    accent: AccentColorTokens = AccentColorTokens()
    status: StatusColorTokens = StatusColorTokens()


# ---------------------------------------------------------------------------
# Typography family (FK-64 §64.6)
# ---------------------------------------------------------------------------


class TypographyScaleTokens(BaseModel):
    """Font-size scale tokens (FK-64 §64.6.2).

    All values are relative (``em``).  Pixel sizes for font are forbidden
    (§64.6.2); the ``px`` unit must not appear in these token values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_xxs: str = "0.625em"
    text_2xs: str = "0.6875em"
    text_xs: str = "0.75em"
    text_sm: str = "0.875em"
    text_md: str = "0.9375em"
    text_base: str = "1em"
    text_lg: str = "1.125em"
    text_xl: str = "1.375em"
    text_2xl: str = "1.625em"
    text_3xl: str = "2em"
    # Semantic display size for KPI headline values (§64.6.2 — relative em).
    text_kpi_display: str = "1.75em"


class TypographyWeightTokens(BaseModel):
    """Font-weight tokens (FK-64 §64.6).

    Values mirror the prototype ``--weight-*`` custom properties.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    regular: int = 400
    medium: int = 500
    semibold: int = 600
    bold: int = 700
    black: int = 800


class TypographyLeadingTokens(BaseModel):
    """Line-height (leading) tokens (FK-64 §64.6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tight: float = 1.25
    title: float = 1.35
    body: float = 1.5


class SemanticTextRoleTokens(BaseModel):
    """Semantic text-role tokens (FK-64 §64.6.3).

    Each role is expressed via references to the scale tokens (prototype uses
    CSS ``var()`` references; here we store the *resolved* scale token key so
    the type is self-contained).

    Roles: micro / sub_label / label / body / ui / title / panel_title /
    page_title / kpi / kpi_display.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    micro_size: str = "text_xxs"
    sub_label_size: str = "text_2xs"
    label_size: str = "text_xs"
    label_weight: str = "semibold"
    body_size: str = "text_sm"
    body_weight: str = "regular"
    ui_size: str = "text_sm"
    ui_weight: str = "medium"
    title_size: str = "text_md"
    title_weight: str = "semibold"
    panel_title_size: str = "text_lg"
    panel_title_weight: str = "semibold"
    page_title_size: str = "text_2xl"
    page_title_weight: str = "semibold"
    kpi_size: str = "text_2xl"
    kpi_weight: str = "black"
    kpi_display_size: str = "text_kpi_display"


class FontFamilyTokens(BaseModel):
    """Font-family tokens (FK-64 §64.6.1).

    ``body`` = Open Sans (UI / body text).
    ``display`` = League Spartan (titles / KPI labels).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str = (
        '"Open Sans", "Aptos", "Segoe UI", ui-sans-serif, system-ui, sans-serif'
    )
    display: str = '"League Spartan", "Open Sans", sans-serif'


class TypographyTokens(BaseModel):
    """Full typography token family (FK-64 §64.6).

    Args:
        families: Font-family definitions (§64.6.1).
        scale: Relative size scale tokens (§64.6.2).
        weights: Font-weight tokens.
        leading: Line-height tokens.
        roles: Semantic text-role assignments (§64.6.3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    families: FontFamilyTokens = FontFamilyTokens()
    scale: TypographyScaleTokens = TypographyScaleTokens()
    weights: TypographyWeightTokens = TypographyWeightTokens()
    leading: TypographyLeadingTokens = TypographyLeadingTokens()
    roles: SemanticTextRoleTokens = SemanticTextRoleTokens()


# ---------------------------------------------------------------------------
# Spacing, border, radii (FK-64 §64.7)
# ---------------------------------------------------------------------------


class SpacingTokens(BaseModel):
    """Spacing scale tokens (FK-64 §64.7.1).

    4pt-based ``rem`` scale; gaps, paddings, and margins must use these.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    space_1: str = "0.25rem"
    space_2: str = _HALF_REM
    space_3: str = "0.75rem"
    space_4: str = "1rem"
    space_5: str = "1.25rem"
    space_6: str = "1.5rem"
    space_8: str = "2rem"


class BorderTokens(BaseModel):
    """Border and hairline tokens (FK-64 §64.7.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hairline: str = "0.0625rem"
    graph_edge_width: str = "0.3125rem"
    graph_edge_width_strong: str = _HALF_REM
    graph_edge_dash: str = "0.5rem 0.4375rem"


class RadiiTokens(BaseModel):
    """Border-radius tokens (FK-64 §64.7.3).

    small = compact chips; medium = standard cards/buttons;
    large = panels/flyouts; pill = badges/status pills.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    small: str = "0.25rem"
    medium: str = _HALF_REM
    large: str = "0.75rem"
    pill: str = "100rem"


class SpacingFamily(BaseModel):
    """Combined spacing / border / radii token family (FK-64 §64.7).

    Args:
        spacing: Gap / padding / margin scale.
        border: Hairline and stroke widths.
        radii: Corner-radius tokens.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spacing: SpacingTokens = SpacingTokens()
    border: BorderTokens = BorderTokens()
    radii: RadiiTokens = RadiiTokens()


# ---------------------------------------------------------------------------
# Control tokens — button heights / paddings (FK-64 §64.8)
# ---------------------------------------------------------------------------


class ControlTokens(BaseModel):
    """Button height and padding control tokens (FK-64 §64.8.1 / §64.8.2).

    All button heights and paddings MUST reference these tokens (§64.18 pt.2).

    ``height_sm``  = compact button (dense toolbar actions).
    ``height_md``  = standard button (Header / Dialog / Inspector-Close).
    ``padding_sm`` = compact button padding.
    ``padding_md`` = standard button padding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    height_sm: str = "1.875rem"
    height_md: str = "2.375rem"
    padding_sm: str = "0.3125rem 0.625rem"
    padding_md: str = "0.5rem 0.8125rem"
    font_size: str = "ui"    # semantic role name: → var(--type-{role}-size)
    font_weight: str = "ui"  # semantic role name: → var(--type-{role}-weight)


# ---------------------------------------------------------------------------
# Chart series colors (FK-64 §64.15 / §64.17)
# ---------------------------------------------------------------------------


class ChartSeriesTokens(BaseModel):
    """Chart series color tokens (FK-64 §64.15 / §64.17).

    Verbatim from ``SERIES_COLORS`` in
    ``frontend/prototype/src/components/AnalyticsView.tsx:38-51``.

    AG3-094 consumes this family for ECharts binding.  This story
    *defines* the family; AG3-094 *applies* it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_0: str = "#48e7ff"   # accent cyan
    series_1: str = "#ffb32c"   # warm yellow
    series_2: str = "#74d17f"   # success green
    series_3: str = "#b38cff"   # violet
    series_4: str = "#ff5b57"   # danger red
    series_5: str = "#7ea7ff"   # info blue
    series_6: str = "#ffd35e"   # accent warm strong
    series_7: str = "#82c4ff"   # done blue
    series_8: str = "#a371f7"   # backlog purple
    series_9: str = "#3fb950"   # status done
    series_10: str = "#d29922"  # progress amber
    series_11: str = "#9ff5ff"  # accent soft


class ChartTokens(BaseModel):
    """Chart token family (FK-64 §64.15).

    Args:
        series: Ordered series color tokens consumed by AG3-094.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    series: ChartSeriesTokens = ChartSeriesTokens()


# ---------------------------------------------------------------------------
# DesignSystem — top-level token owner (FK-64 §64.2)
# ---------------------------------------------------------------------------


class DesignSystem(BaseModel):
    """Typed token owner for ``kpi-and-dashboard.DesignSystem`` (FK-64 §64.2).

    Holds exclusively token definitions and component guidelines.
    No runtime logic, no I/O, no HTTP endpoint.  Boundary-control for
    token delivery lives in ``control_plane`` / ``kpi_analytics/http/``.

    Families:
        colors: Color, accent, and status token families (§64.5).
        typography: Type scale, weights, leading, and semantic roles (§64.6).
        spacing: Spacing, border, and radii tokens (§64.7).
        control: Button height and padding control tokens (§64.8).
        chart: Chart series color tokens (§64.15 / §64.17).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    colors: ColorTokens = ColorTokens()
    typography: TypographyTokens = TypographyTokens()
    spacing: SpacingFamily = SpacingFamily()
    control: ControlTokens = ControlTokens()
    chart: ChartTokens = ChartTokens()


def _scale_key_to_var(key: str) -> str:
    """Convert a typography-scale field key to a CSS ``var()`` reference.

    Example: ``"text_xs"`` → ``"var(--text-xs)"``.
    """
    return f"var(--{key.replace('_', '-')})"


def _weight_key_to_var(key: str) -> str:
    """Convert a font-weight field key to a CSS ``var()`` reference.

    Example: ``"semibold"`` → ``"var(--weight-semibold)"``.
    """
    return f"var(--weight-{key.replace('_', '-')})"


# Ordered sequence of (SemanticTextRoleTokens field name, CSS var name).
# Only the subset of role fields that have a CSS custom property counterpart in
# the design-system.css prototype are listed here.  Fields without a CSS var
# (e.g. ``panel_title_weight``, ``page_title_weight``) are intentionally
# absent — the prototype defines no corresponding ``--type-panel-title-weight``
# token.
_SEMANTIC_ROLE_CSS_FIELDS: tuple[tuple[str, str], ...] = (
    ("micro_size",        "--type-micro-size"),
    ("sub_label_size",    "--type-sub-label-size"),
    ("label_size",        "--type-label-size"),
    ("label_weight",      "--type-label-weight"),
    ("body_size",         "--type-body-size"),
    ("body_weight",       "--type-body-weight"),
    ("ui_size",           "--type-ui-size"),
    ("ui_weight",         "--type-ui-weight"),
    ("title_size",        "--type-title-size"),
    ("title_weight",      "--type-title-weight"),
    ("panel_title_size",  "--type-panel-title-size"),
    ("page_title_size",   "--type-page-title-size"),
    ("kpi_size",          "--type-kpi-size"),
    ("kpi_weight",        "--type-kpi-weight"),
    ("kpi_display_size",  "--type-kpi-display-size"),
)


def _resolve_control_font_css_var(
    roles: SemanticTextRoleTokens,
    role_name: str,
    dim: str,
) -> str:
    """Return the CSS ``var()`` reference for a control font property.

    Derives the CSS var name from the semantic role name stored in
    ``ControlTokens.font_size`` / ``ControlTokens.font_weight``.  This ensures
    that changing the role reference on the owner propagates to the exported CSS
    map — a field change on the owner immediately changes the CSS output.

    Args:
        roles: The ``SemanticTextRoleTokens`` instance from the owner.
        role_name: The semantic role name stored in ``ControlTokens.font_size``
            or ``ControlTokens.font_weight`` (e.g. ``"ui"``).
        dim: ``"size"`` or ``"weight"``.

    Returns:
        A CSS ``var(--type-{role}-{dim})`` string (e.g. ``"var(--type-ui-size)"``).

    Raises:
        ValueError: If the derived CSS var name is not in ``_SEMANTIC_ROLE_CSS_FIELDS``.
    """
    css_role = role_name.replace("_", "-")
    css_var_name = f"--type-{css_role}-{dim}"
    # Validate the derived var is a known, exported semantic role CSS var.
    known_css_vars = {csv for _, csv in _SEMANTIC_ROLE_CSS_FIELDS}
    if css_var_name not in known_css_vars:
        raise ValueError(
            f"ControlTokens references unknown semantic role CSS var {css_var_name!r}; "
            f"valid vars are: {sorted(known_css_vars)}"
        )
    # Confirm the role field exists on the roles model.
    role_field = f"{role_name}_{dim}"
    if not hasattr(roles, role_field):
        raise ValueError(
            f"SemanticTextRoleTokens has no field {role_field!r} "
            f"(derived from role_name={role_name!r}, dim={dim!r})"
        )
    return f"var({css_var_name})"


def get_design_system() -> DesignSystem:
    """Return the authoritative, deterministic ``DesignSystem`` token set.

    This is the *single source of truth* for all visual token values (FK-64
    §64.2).  The return value is immutable (Pydantic frozen model) and has no
    dependency on runtime state, I/O, or configuration.

    Returns:
        The fully-typed ``DesignSystem`` token owner.
    """
    return DesignSystem()


def build_css_variables(ds: DesignSystem) -> dict[str, str]:
    """Build the exhaustive ``--css-var → value`` map exported by the owner.

    This is the *single source of truth* for what the owner considers a token
    CSS custom property.  The drift check in ``css_conformance`` derives its
    reference map entirely from this function — there is no second hand-maintained
    list.

    Every exported ``--ak-*`` / ``--space-*`` / ``--text-*`` / ``--type-*`` /
    ``--control-*`` / ``--radius-*`` / ``--font-*`` / ``--weight-*`` /
    ``--leading-*`` / ``--graph-edge-*`` / ``--border-hairline`` /
    ``--chart-series-*`` token corresponds to one entry here.  Vars that are
    purely layout / overlay helpers (``--overlay-*``, ``--rail-width``,
    ``--shadow-*``) are **not** token-family members and therefore absent from
    this map — the drift checker holds them in an explicit documented allowlist.

    Args:
        ds: The fully-typed ``DesignSystem`` owner instance.

    Returns:
        A dict mapping each CSS custom-property name (``--...``) to its
        canonical string value.
    """
    mapping: dict[str, str] = {}

    # --- neutral color tokens (§64.5.1) ---
    nc = ds.colors.neutral
    mapping.update({
        "--ak-bg": nc.bg,
        "--ak-bg-deep": nc.bg_deep,
        "--ak-bg-canvas": nc.bg_canvas,
        "--ak-bg-canvas-top": nc.bg_canvas_top,
        "--ak-bg-raised": nc.bg_raised,
        "--ak-bg-raised-top": nc.bg_raised_top,
        "--ak-bg-raised-alt": nc.bg_raised_alt,
        "--ak-bg-raised-warm": nc.bg_raised_warm,
        "--ak-bg-rail-bottom": nc.bg_rail_bottom,
        "--ak-bg-metrics-top": nc.bg_metrics_top,
        "--ak-bg-sheet-group": nc.bg_sheet_group,
        "--ak-bg-epic-from": nc.bg_epic_from,
        "--ak-bg-tab-top": nc.bg_tab_top,
        "--ak-bg-tab-mid": nc.bg_tab_mid,
        "--ak-bg-tab-bottom": nc.bg_tab_bottom,
        "--ak-bg-topbar-top": nc.bg_topbar_top,
        "--ak-bg-topbar-bottom": nc.bg_topbar_bottom,
        "--ak-metric-warm-top": nc.metric_warm_top,
        "--ak-metric-warm-bottom": nc.metric_warm_bottom,
        "--ak-metric-warm-border": nc.metric_warm_border,
        "--ak-surface": nc.surface,
        "--ak-surface-2": nc.surface_2,
        "--ak-surface-3": nc.surface_3,
        "--ak-surface-table-head": nc.surface_table_head,
        "--ak-surface-tab-active-top": nc.surface_tab_active_top,
        "--ak-surface-tab-active-bottom": nc.surface_tab_active_bottom,
        "--ak-border": nc.border,
        "--ak-border-strong": nc.border_strong,
        "--ak-border-header": nc.border_header,
        "--ak-border-tab": nc.border_tab,
        "--ak-border-tab-hover": nc.border_tab_hover,
        "--ak-border-tab-shell": nc.border_tab_shell,
        "--ak-line-graph": nc.line_graph,
        "--ak-text": nc.text,
        "--ak-text-grid": nc.text_grid,
        "--ak-text-inverse": nc.text_inverse,
        "--ak-text-on-warm": nc.text_on_warm,
        "--ak-text-soft": nc.text_soft,
        "--ak-text-muted": nc.text_muted,
        "--ak-text-faint": nc.text_faint,
        "--ak-text-tab-muted": nc.text_tab_muted,
    })

    # --- accent color tokens (§64.5.2) ---
    ac = ds.colors.accent
    mapping.update({
        "--ak-accent": ac.accent,
        "--ak-accent-strong": ac.accent_strong,
        "--ak-accent-text": ac.accent_text,
        "--ak-accent-text-soft": ac.accent_text_soft,
        "--ak-accent-button": ac.accent_button,
        "--ak-accent-button-hover": ac.accent_button_hover,
        "--ak-accent-warm": ac.accent_warm,
        "--ak-accent-warm-strong": ac.accent_warm_strong,
        "--ak-violet": ac.violet,
    })

    # --- status / semantic color tokens (§64.5.3 + §64.14) ---
    st = ds.colors.status
    mapping.update({
        "--ak-success": st.success,
        "--ak-warn": st.warning,
        "--ak-danger": st.danger,
        "--ak-info": st.info,
        "--ak-done": st.done,
        "--ak-status-backlog": st.status_backlog,
        "--ak-status-approved": st.status_approved,
        "--ak-status-progress": st.status_in_progress,
        "--ak-status-done": st.status_done,
        "--ak-status-cancelled": st.status_cancelled,
    })

    # --- spacing tokens (§64.7.1) ---
    sp = ds.spacing.spacing
    mapping.update({
        "--space-1": sp.space_1,
        "--space-2": sp.space_2,
        "--space-3": sp.space_3,
        "--space-4": sp.space_4,
        "--space-5": sp.space_5,
        "--space-6": sp.space_6,
        "--space-8": sp.space_8,
    })

    # --- border / graph-edge tokens (§64.7.2) ---
    bd = ds.spacing.border
    mapping.update({
        "--border-hairline": bd.hairline,
        "--graph-edge-width": bd.graph_edge_width,
        "--graph-edge-width-strong": bd.graph_edge_width_strong,
        "--graph-edge-dash": bd.graph_edge_dash,
    })

    # --- radii tokens (§64.7.3) ---
    r = ds.spacing.radii
    mapping.update({
        "--radius-sm": r.small,
        "--radius-md": r.medium,
        "--radius-lg": r.large,
        "--radius-pill": r.pill,
    })

    # --- font-family tokens (§64.6.1) ---
    ff = ds.typography.families
    mapping.update({
        "--font-body": ff.body,
        "--font-display": ff.display,
    })

    # --- font-family shorthand aliases (prototype: --font-xs/sm/md/lg → var(--text-*)) ---
    # These are var()-aliases defined in :root; the CSS value is a var() reference.
    mapping.update({
        "--font-xs": "var(--text-xs)",
        "--font-sm": "var(--text-sm)",
        "--font-md": "var(--text-md)",
        "--font-lg": "var(--text-lg)",
        "--font-xl": "var(--text-xl)",
        "--font-2xl": "var(--text-2xl)",
    })

    # --- typography scale tokens (§64.6.2) ---
    sc = ds.typography.scale
    mapping.update({
        "--text-xxs": sc.text_xxs,
        "--text-2xs": sc.text_2xs,
        "--text-xs": sc.text_xs,
        "--text-sm": sc.text_sm,
        "--text-md": sc.text_md,
        "--text-base": sc.text_base,
        "--text-lg": sc.text_lg,
        "--text-xl": sc.text_xl,
        "--text-2xl": sc.text_2xl,
        "--text-3xl": sc.text_3xl,
        "--text-kpi-display": sc.text_kpi_display,
    })

    # --- font-weight tokens (§64.6) ---
    w = ds.typography.weights
    mapping.update({
        "--weight-regular": str(w.regular),
        "--weight-medium": str(w.medium),
        "--weight-semibold": str(w.semibold),
        "--weight-bold": str(w.bold),
        "--weight-black": str(w.black),
    })

    # --- leading (line-height) tokens (§64.6) ---
    ld = ds.typography.leading
    mapping.update({
        "--leading-tight": str(ld.tight),
        "--leading-title": str(ld.title),
        "--leading-body": str(ld.body),
    })

    # --- semantic text-role tokens (§64.6.3) ---
    # CSS values are var() references derived from the SemanticTextRoleTokens owner
    # fields — not hardcoded literals.  Changing a role field value on the owner
    # automatically changes the exported CSS var.
    roles = ds.typography.roles
    for field_name, css_var in _SEMANTIC_ROLE_CSS_FIELDS:
        raw_value: str = getattr(roles, field_name)
        # Size fields hold scale-key refs (e.g. "text_xs" → var(--text-xs));
        # weight fields hold weight-key refs (e.g. "semibold" → var(--weight-semibold)).
        css_value = (
            _scale_key_to_var(raw_value)
            if field_name.endswith("_size")
            else _weight_key_to_var(raw_value)
        )
        mapping[css_var] = css_value

    # --- control tokens (§64.8) ---
    # font_size / font_weight are derived from the ControlTokens owner fields:
    #   ct.font_size  (scale key ref) → var(--type-ui-size)  via roles.ui_size
    #   ct.font_weight (weight key ref) → var(--type-ui-weight) via roles.ui_weight
    # The derivation finds the role whose size/weight matches, producing the correct
    # semantic indirection (control fonts reference the "ui" role vars, not the raw
    # scale vars directly).  Changing ct.font_size on the owner propagates here.
    ct = ds.control
    mapping.update({
        "--control-height-sm": ct.height_sm,
        "--control-height-md": ct.height_md,
        "--control-padding-sm": ct.padding_sm,
        "--control-padding-md": ct.padding_md,
        "--control-font-size": _resolve_control_font_css_var(roles, ct.font_size, "size"),
        "--control-font-weight": _resolve_control_font_css_var(roles, ct.font_weight, "weight"),
    })

    # --- chart series color tokens (§64.15 / §64.17) ---
    # Ordered series colors consumed by the ECharts binding (AG3-094).
    cs = ds.chart.series
    mapping.update({
        "--chart-series-0": cs.series_0,
        "--chart-series-1": cs.series_1,
        "--chart-series-2": cs.series_2,
        "--chart-series-3": cs.series_3,
        "--chart-series-4": cs.series_4,
        "--chart-series-5": cs.series_5,
        "--chart-series-6": cs.series_6,
        "--chart-series-7": cs.series_7,
        "--chart-series-8": cs.series_8,
        "--chart-series-9": cs.series_9,
        "--chart-series-10": cs.series_10,
        "--chart-series-11": cs.series_11,
    })

    return mapping


# CSS vars that are layout / overlay helpers — not token-family members.
# These are intentionally absent from ``build_css_variables`` and must not be
# flagged as "unowned" by the drift checker.  Any :root var NOT in the owner
# map AND NOT in this allowlist is an unknown token (conformance error).
CSS_NON_TOKEN_ALLOWLIST: frozenset[str] = frozenset({
    # Overlay transparency helpers (not semantic tokens)
    "--overlay-white-0",
    "--overlay-white-3",
    "--overlay-white-035",
    "--overlay-white-5",
    "--overlay-white-7",
    "--overlay-black-22",
    "--overlay-black-32",
    "--overlay-black-54",
    "--overlay-accent-12",
    # Layout metrics (not token-family members)
    "--rail-width",
    # Shadow composite values
    "--shadow-md",
    "--shadow-glow",
})
