from typing import TypedDict, TypeAlias

LoadAverage: TypeAlias = tuple[float, float, float]


class MemoryStats(TypedDict):
    total: str
    available: str
    percent: float
    used: str
    free: str
    active: str
    inactive: str
    cached: str
    shared: str


class DiskStats(TypedDict):
    device_name: str
    fs_type: str
    mnt_point: str
    size: str
    used: str
    free: str
    percent: float


class SwapStats(TypedDict):
    total: str
    used: str
    free: str
    percent: float


class SensorStats(TypedDict):
    sensor_name: str
    sensor_value: float


class ProcessStats(TypedDict):
    running: int
    sleeping: int
    idle: int
    total: int


class NetworkIOStats(TypedDict):
    bytes_sent: str
    bytes_recv: str
    packets_sent: int
    packets_recv: int
    err_in: int
    err_out: int
    drop_in: int
    drop_out: int


class UserInfo(TypedDict):
    username: str
    terminal: str
    host: str
    started: float


class NetworkInterfaceStats(TypedDict):
    is_up: bool
    speed: int
    duplex: str
    mtu: int
    ip_address: str


class CPUFrequencyStats(TypedDict):
    current_freq: float
    min_freq: float
    max_freq: float


class CPUUsageStats(TypedDict):
    cpu_percent: float
    cpu_percent_per_core: list[float]

class TopProcess(TypedDict):
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float