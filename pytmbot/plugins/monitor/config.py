from pytmbot.plugins.monitor.models import MonitorPluginConfig

PLUGIN_NAME = "monitor"
PLUGIN_VERSION = "0.0.2"
PLUGIN_DESCRIPTION = "System monitoring plugin for pyTMBot"


def load_config():
    return MonitorPluginConfig(
        emoji_for_notification="🚢🆘🛟🚨📢\n",
    )
