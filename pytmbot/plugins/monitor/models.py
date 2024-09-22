from pydantic import BaseModel, Field


class MonitorPluginConfig(BaseModel):
    """
    Configuration model for the system monitoring plugin.

    This model defines the thresholds for CPU, memory, and disk usage, as well as the
    maximum number of notifications that can be sent and the interval at which system
    checks should be performed.

    Attributes:
        emoji_for_notification (str): The emoji to use for notifications.

    """

    emoji_for_notification: str = Field(default="🚢🆘🛟🚨📢\n")
