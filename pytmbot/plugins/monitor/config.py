from pytmbot.plugins.monitor.models import MonitorPluginConfig


def load_config():
    return MonitorPluginConfig(
        emoji_for_notification="🚢🆘🛟🚨📢\n",
    )
