#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import TypedDict

type LoadAverage = tuple[float, float, float]


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


class DiskIOStats(TypedDict):
    device_name: str
    read_bytes: str
    write_bytes: str
    read_count: int
    write_count: int
    read_time_ms: int
    write_time_ms: int


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


class CPUTimesPercentStats(TypedDict):
    user: float
    system: float
    idle: float
    iowait: float
    irq: float
    softirq: float


class NetworkConnectionsSummary(TypedDict):
    total: int
    tcp: int
    udp: int
    statuses: dict[str, int]


class FanSpeedStats(TypedDict):
    sensor_name: str
    label: str
    rpm: int


class TopProcess(TypedDict):
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
