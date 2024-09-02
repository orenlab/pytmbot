from pydantic import BaseModel, Field


class MonitorConfig(BaseModel):
    """
    Configuration model for the system monitoring plugin.

    This model defines the thresholds for CPU, memory, and disk usage, as well as the
    maximum number of notifications that can be sent and the interval at which system
    checks should be performed.

    Attributes:
        cpu_threshold (int): The CPU usage threshold percentage. Default is 85.
                             Must be between 0 and 100.
        memory_threshold (int): The memory usage threshold percentage. Default is 90.
                                Must be between 0 and 100.
        disk_threshold (int): The disk usage threshold percentage. Default is 90.
                              Must be between 0 and 100.
        max_notifications (int): The maximum number of notifications to send. Default is 3.
                                 Must be at least 1.
        check_interval (int): The interval in seconds at which the system checks are performed. Default is 2.
                              Must be at least 1 second.
    """

    cpu_threshold: int = Field(default=85, ge=0, le=100, description="CPU usage threshold percentage.")
    memory_threshold: int = Field(default=90, ge=0, le=100, description="Memory usage threshold percentage.")
    disk_threshold: int = Field(default=90, ge=0, le=100, description="Disk usage threshold percentage.")
    max_notifications: int = Field(default=3, ge=1, description="Maximum number of notifications to send.")
    check_interval: int = Field(default=2, ge=1, description="Check interval in seconds.")
