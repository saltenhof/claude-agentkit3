"""Unit tests for the three FK-51 §51.3 upgrade scenarios (AG3-089 AC3).

* 3a (§51.3.1 skip): digest == file hash AND bundle unchanged -> no update.
* 3a-rebind (§51.3.1 second clause): config unchanged, bundle changed -> rebind
  allowed but not automatic.
* 3b (§51.3.2): registered digest != on-disk hash -> CONFIG_EDITED (``.bak``+write).
* 3c (§51.3.3): a new variant is adopted ONLY on an explicit binding switch.
"""

from __future__ import annotations

from agentkit.installer.upgrade.scenarios import (
    UpgradeScenario,
    decide_upgrade_scenario,
)


def test_scenario_3a_unchanged_skip() -> None:
    """3a (§51.3.1): equal digests + unchanged bundle -> UNCHANGED, no rebind."""
    decision = decide_upgrade_scenario(
        registered_config_digest="abc",
        on_disk_config_digest="abc",
        bundle_version_changed=False,
        explicit_binding_switch=False,
    )

    assert decision.scenario is UpgradeScenario.UNCHANGED
    assert decision.config_changed is False
    assert decision.rebind_allowed is False


def test_scenario_3a_unchanged_config_but_bundle_changed_allows_explicit_rebind() -> None:
    """3a second clause: config unchanged, bundle changed -> rebind ALLOWED, not auto."""
    decision = decide_upgrade_scenario(
        registered_config_digest="abc",
        on_disk_config_digest="abc",
        bundle_version_changed=True,
        explicit_binding_switch=False,
    )

    assert decision.scenario is UpgradeScenario.UNCHANGED
    assert decision.rebind_allowed is True  # may be switched explicitly (no auto pull)


def test_scenario_3b_config_digest_mismatch() -> None:
    """3b (§51.3.2): registered digest != on-disk hash -> CONFIG_EDITED."""
    decision = decide_upgrade_scenario(
        registered_config_digest="registered",
        on_disk_config_digest="edited-on-disk",
        bundle_version_changed=False,
        explicit_binding_switch=False,
    )

    assert decision.scenario is UpgradeScenario.CONFIG_EDITED
    assert decision.config_changed is True
    # `.bak` + write path; the no-overwrite invariant does NOT apply here.
    assert decision.rebind_allowed is False


def test_scenario_3c_new_variant_only_on_explicit_binding_switch() -> None:
    """3c (§51.3.3): explicit binding switch -> NEW_VARIANT (adopted)."""
    decision = decide_upgrade_scenario(
        registered_config_digest="abc",
        on_disk_config_digest="abc",
        bundle_version_changed=True,
        explicit_binding_switch=True,
    )

    assert decision.scenario is UpgradeScenario.NEW_VARIANT
    assert decision.rebind_allowed is True


def test_scenario_3c_new_variant_not_pulled_without_explicit_switch() -> None:
    """3c negative: a new variant WITHOUT an explicit switch is NOT pulled (AC3c)."""
    decision = decide_upgrade_scenario(
        registered_config_digest="abc",
        on_disk_config_digest="abc",
        bundle_version_changed=True,
        explicit_binding_switch=False,
    )

    # Without the explicit switch the scenario stays UNCHANGED — no automatic pull.
    assert decision.scenario is not UpgradeScenario.NEW_VARIANT
    assert decision.scenario is UpgradeScenario.UNCHANGED


def test_scenario_config_edit_takes_precedence_over_binding_switch() -> None:
    """A config edit (§51.3.2) wins over a binding switch — its path must run."""
    decision = decide_upgrade_scenario(
        registered_config_digest="registered",
        on_disk_config_digest="edited",
        bundle_version_changed=True,
        explicit_binding_switch=True,
    )

    assert decision.scenario is UpgradeScenario.CONFIG_EDITED
