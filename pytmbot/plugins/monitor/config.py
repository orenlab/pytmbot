from pytmbot.plugins.monitor.models import MonitorPluginConfig

PLUGIN_NAME = "monitor"
PLUGIN_VERSION = "0.0.3"
PLUGIN_DESCRIPTION = "System monitoring plugin for pyTMBot"
PLUGIN_INDEX_KEY: dict[str, str] = {
    "chart_increasing": "Monitoring",
    "BACK_arrow": "Back to main menu",
}


def load_config():
    return MonitorPluginConfig(
        emoji_for_notification="🚢🆘🛟🚨📢\n",
    )
