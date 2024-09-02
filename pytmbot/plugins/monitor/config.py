from pytmbot.plugins.monitor.models import MonitorConfig


def load_config():
    return MonitorConfig(
        cpu_threshold=85,
        memory_threshold=90,
        disk_threshold=70,
        max_notifications=3,
        check_interval=2,
        emoji_for_notification="🚢🆘🛟🚨📢\n",
    )
