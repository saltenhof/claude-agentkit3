from agentkit.installer import InstallConfig, install_agentkit
from agentkit.project_ops.install import InstallConfig as LegacyInstallConfig
from agentkit.project_ops.install import install_agentkit as legacy_install_agentkit


def test_installer_namespace_reexports_legacy_api() -> None:
    assert InstallConfig is LegacyInstallConfig
    assert install_agentkit is legacy_install_agentkit
