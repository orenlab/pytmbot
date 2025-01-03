from dataclasses import dataclass
from typing import TypedDict, Optional, Any

from pydantic import BaseModel, Field

from pytmbot.logs import Logger

logger = Logger()


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


class EventData(TypedDict):
    id: str
    start_time: float
    last_notification: float
    type: str
    details: dict[str, Any]
    resolved: bool


class ResourceMetrics(TypedDict):
    cpu_usage: float
    memory_usage: float
    disk_usage: dict[str, float]
    temperatures: dict[str, dict[str, Optional[float]]]
    fan_speeds: dict[str, dict[str, int]]
    load_averages: tuple[float, float, float]


@dataclass
class ResourceThresholds:
    """Data class for storing resource monitoring thresholds."""
    cpu_temp: float
    gpu_temp: float
    disk_temp: float
    pch_temp: float
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    load: float = 70.0


@dataclass
class MonitoringState:
    """Data class for storing monitoring state information."""
    is_active: bool = False
    notification_count: int = 0
    max_notifications_reached: bool = False
    last_poll_time: float = 0.0
    docker_counters_last_updated: float = 0.0
    init_mode: bool = True
    sensors_available: bool = True
    return_cached_disk_usage: bool = False
    active_events: dict[str, EventData] = None

    def __post_init__(self):
        self.active_events = {}
