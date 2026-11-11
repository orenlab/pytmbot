"""Metadata for the optional, disabled-by-default Trivy plugin."""

from typing import Final

from pytmbot.plugins.models import PluginsPermissionsModel

PLUGIN_NAME: Final[str] = "trivy"
PLUGIN_VERSION: Final[str] = "0.1.0"
PLUGIN_DESCRIPTION: Final[str] = "Read-only local Docker image vulnerability scans"
PLUGIN_COMMANDS: Final[dict[str, str]] = {"/trivy": "Scan local image vulnerabilities"}
PLUGIN_INDEX_KEY: Final[dict[str, str]] = {"shield": "Trivy scans"}
PLUGIN_PERMISSIONS: Final[PluginsPermissionsModel] = PluginsPermissionsModel(
    base_permission=True,
    need_running_on_host_machine=False,
)
