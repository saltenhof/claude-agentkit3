from pathlib import Path

from agentkit.installer import InstallConfig, install_agentkit


def test_installer_namespace_exposes_install_api(tmp_path: Path) -> None:
    config = InstallConfig(
        project_key="demo",
        project_name="demo",
        project_root=tmp_path,
    )
    result = install_agentkit(config)

    assert result.success is True
    assert (tmp_path / ".agentkit" / "config" / "project.yaml").exists()
