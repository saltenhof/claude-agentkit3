"""The three FK-51 §51.3 upgrade scenarios as a typed decision.

FK-51 §51.3 defines exactly three upgrade scenarios; this module decides which
one applies from typed inputs (digest / bundle-version / binding criteria) rather
than ad-hoc string/flag cascades (typed, not strings; story §5):

* :attr:`UpgradeScenario.UNCHANGED` (§51.3.1) — config digest == on-disk file
  hash AND the target bundle version is unchanged -> NO update (skip). When ONLY
  the target bundle version changed (config still unchanged), the symlink binding
  MAY be switched explicitly to the new bundle version (``rebind_allowed``).
* :attr:`UpgradeScenario.CONFIG_EDITED` (§51.3.2) — the registered digest differs
  from the on-disk file hash -> the user edited the config. The prescribed path
  is ``.bak`` backup + write of the new version; the human must manually re-apply
  their edits. This is EXEMPT from F-51-023 (story §6 / AC3b).
* :attr:`UpgradeScenario.NEW_VARIANT` (§51.3.3) — a new system-wide skill/prompt
  variant exists. A project adopts it ONLY when its binding is switched
  EXPLICITLY to the new bundle/profile (no automatic pull, story AC3c).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UpgradeScenario(StrEnum):
    """The typed FK-51 §51.3 upgrade scenario.

    Attributes:
        UNCHANGED: §51.3.1 — config + binding unchanged (most common). No config
            update; an explicit rebind may still be allowed when only the target
            bundle version changed.
        CONFIG_EDITED: §51.3.2 — the user edited the config (digest mismatch).
            ``.bak`` + write is the prescribed path.
        NEW_VARIANT: §51.3.3 — a new system-wide skill/prompt variant exists;
            adopted only on an explicit binding switch.
    """

    UNCHANGED = "unchanged"
    CONFIG_EDITED = "config_edited"
    NEW_VARIANT = "new_variant"


@dataclass(frozen=True)
class UpgradeScenarioDecision:
    """The resolved §51.3 scenario plus its derived action flags.

    Attributes:
        scenario: The decided :class:`UpgradeScenario`.
        config_changed: Whether the on-disk config digest differs from the
            registered digest (drives §51.3.2).
        bundle_version_changed: Whether the target bundle version differs from the
            currently bound one.
        rebind_allowed: Whether an explicit symlink rebind to the new bundle
            version is permitted (§51.3.1 second clause / §51.3.3): true only when
            the config is unchanged AND the bundle version changed.
        detail: Human-readable explanation of the decision.
    """

    scenario: UpgradeScenario
    config_changed: bool
    bundle_version_changed: bool
    rebind_allowed: bool
    detail: str


def decide_upgrade_scenario(
    *,
    registered_config_digest: str,
    on_disk_config_digest: str,
    bundle_version_changed: bool,
    explicit_binding_switch: bool,
) -> UpgradeScenarioDecision:
    """Decide the FK-51 §51.3 upgrade scenario from typed criteria.

    Decision order mirrors FK-51 §51.3:

    1. Config edited (§51.3.2) takes precedence: a registered-vs-on-disk digest
       mismatch is the "user edited the config" scenario regardless of bundle
       state — its ``.bak`` + write path is what must run.
    2. Otherwise, with the config unchanged:
       * an EXPLICIT binding switch to a new bundle/profile is the new-variant
         adoption (§51.3.3) -> ``NEW_VARIANT`` (rebind allowed);
       * a changed target bundle version WITHOUT an explicit switch stays
         ``UNCHANGED`` but flags ``rebind_allowed`` (§51.3.1 second clause — the
         rebind MAY be done explicitly, never automatically);
       * everything unchanged -> ``UNCHANGED`` skip (no update).

    Args:
        registered_config_digest: The ``config_digest`` recorded at registration
            (``ProjectRegistration.config_digest``).
        on_disk_config_digest: The canonical digest of the current ``project.yaml``.
        bundle_version_changed: Whether the target bundle version differs from the
            currently bound version.
        explicit_binding_switch: Whether the operator explicitly requested
            switching the project binding to the new bundle/profile (§51.3.3 — no
            automatic pull).

    Returns:
        The :class:`UpgradeScenarioDecision`.
    """
    config_changed = registered_config_digest != on_disk_config_digest

    if config_changed:
        return UpgradeScenarioDecision(
            scenario=UpgradeScenario.CONFIG_EDITED,
            config_changed=True,
            bundle_version_changed=bundle_version_changed,
            rebind_allowed=False,
            detail=(
                "Registered config_digest differs from the on-disk file hash "
                "(FK-51 §51.3.2): the user edited the config. Prescribed path is "
                "`.bak` backup + write; the human re-applies edits manually."
            ),
        )

    if explicit_binding_switch:
        return UpgradeScenarioDecision(
            scenario=UpgradeScenario.NEW_VARIANT,
            config_changed=False,
            bundle_version_changed=bundle_version_changed,
            rebind_allowed=True,
            detail=(
                "Config unchanged; an explicit binding switch adopts the new "
                "skill/prompt variant (FK-51 §51.3.3 — explicit, never automatic)."
            ),
        )

    return UpgradeScenarioDecision(
        scenario=UpgradeScenario.UNCHANGED,
        config_changed=False,
        bundle_version_changed=bundle_version_changed,
        rebind_allowed=bundle_version_changed,
        detail=(
            "Config digest == on-disk file hash (FK-51 §51.3.1). "
            + (
                "Only the target bundle version changed; the symlink binding MAY "
                "be switched explicitly to the new version (no automatic pull)."
                if bundle_version_changed
                else "Bundle version unchanged -> no update needed (skip)."
            )
        ),
    )


__all__ = [
    "UpgradeScenario",
    "UpgradeScenarioDecision",
    "decide_upgrade_scenario",
]
