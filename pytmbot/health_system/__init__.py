#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

__all__ = [
    "HealthLevel",
    "HealthResult",
    "SystemHealth",
    "HealthChecker",
    "BaseHealthChecker",
    "TelegramApiChecker",
    "PollingChecker",
    "SystemResourceChecker",
    "SessionChecker",
    "HealthMonitor",
    "HealthStatus",
    "HealthManager",
    "create_health_manager",
]

_LAZY_EXPORTS: Final[frozenset[str]] = frozenset(__all__)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("pytmbot.health_system.health_system")
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_EXPORTS)
