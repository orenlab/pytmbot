#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Final

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import fetch_docker_counters
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import get_emoji_converter, get_psutil_adapter
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()

_CPU_WARNING_THRESHOLD: Final[float] = 70.0
_CPU_CRITICAL_THRESHOLD: Final[float] = 85.0
_MEMORY_WARNING_THRESHOLD: Final[float] = 70.0
_MEMORY_CRITICAL_THRESHOLD: Final[float] = 85.0
_LOAD_WARNING_THRESHOLD: Final[float] = 100.0
_LOAD_CRITICAL_THRESHOLD: Final[float] = 150.0

_LEVEL_ORDER: Final[dict[str, int]] = {
    "healthy": 0,
    "elevated": 1,
    "critical": 2,
}
_LEVEL_BADGE: Final[dict[str, str]] = {
    "healthy": "🟢",
    "elevated": "🟡",
    "critical": "🔴",
}
_LEVEL_LABEL: Final[dict[str, str]] = {
    "healthy": "Stable",
    "elevated": "Watch closely",
    "critical": "Immediate attention",
}


def _metric_level(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return "critical"
    if value >= warning:
        return "elevated"
    return "healthy"


def _health_badge(value: float, warning: float, critical: float) -> str:
    return _LEVEL_BADGE[_metric_level(value, warning, critical)]


def _worst_level(*levels: str) -> str:
    return max(levels, key=lambda level: _LEVEL_ORDER[level])


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        with_sanitized = value.strip()
        if with_sanitized:
            try:
                return int(with_sanitized)
            except ValueError:
                return default
    return default


def _build_docker_context(cpu_count: int) -> dict[str, object]:
    try:
        counters = fetch_docker_counters()
        containers_total = int(counters.get("containers_count", 0))
        running_containers = int(counters.get("running_containers", 0))
        stopped_containers = int(counters.get("stopped_containers", 0))
        images_count = int(counters.get("images_count", 0))
        running_ratio = (
            round((running_containers / containers_total) * 100.0, 1)
            if containers_total > 0
            else 0.0
        )
        containers_per_core = round(running_containers / max(cpu_count, 1), 2)

        if containers_total == 0:
            level = "healthy"
            trend_text = "No containers deployed"
        elif stopped_containers == 0:
            level = "healthy"
            trend_text = "All containers are running"
        elif running_ratio >= 80.0:
            level = "elevated"
            trend_text = "Mostly healthy, but has stopped workloads"
        else:
            level = "critical"
            trend_text = "Many containers are currently stopped"

        return {
            "available": True,
            "level": level,
            "badge": _LEVEL_BADGE[level],
            "status_label": _LEVEL_LABEL[level],
            "containers_total": containers_total,
            "running_containers": running_containers,
            "stopped_containers": stopped_containers,
            "images_count": images_count,
            "running_ratio": running_ratio,
            "containers_per_core": containers_per_core,
            "trend_text": trend_text,
        }
    except Exception as error:
        logger.warning("bot.handler.server.health.docker.fail", error=str(error))
        return {
            "available": False,
            "level": "elevated",
            "badge": "⚪",
            "status_label": "Unavailable",
            "containers_total": 0,
            "running_containers": 0,
            "stopped_containers": 0,
            "images_count": 0,
            "running_ratio": 0.0,
            "containers_per_core": 0.0,
            "trend_text": "Docker metrics are unavailable in current environment.",
        }


def _build_health_context() -> dict[str, object]:
    cpu_usage = psutil_adapter.get_cpu_usage()
    memory = psutil_adapter.get_memory()
    load_average = psutil_adapter.get_load_average()
    process_stats = psutil_adapter.get_process_counts()
    cpu_count = max(psutil_adapter.get_cpu_count(), 1)
    uptime = psutil_adapter.get_uptime()

    cpu_percent = float(cpu_usage.get("cpu_percent", 0.0))
    memory_percent = float(memory.get("percent", 0.0))
    load_1m = float(load_average[0]) if load_average else 0.0
    load_5m = float(load_average[1]) if len(load_average) > 1 else 0.0
    load_15m = float(load_average[2]) if len(load_average) > 2 else 0.0
    load_ratio_percent = (load_1m / cpu_count) * 100.0

    cpu_level = _metric_level(
        cpu_percent, _CPU_WARNING_THRESHOLD, _CPU_CRITICAL_THRESHOLD
    )
    memory_level = _metric_level(
        memory_percent, _MEMORY_WARNING_THRESHOLD, _MEMORY_CRITICAL_THRESHOLD
    )
    load_level = _metric_level(
        load_ratio_percent, _LOAD_WARNING_THRESHOLD, _LOAD_CRITICAL_THRESHOLD
    )
    docker_context = _build_docker_context(cpu_count)

    overall_level = _worst_level(
        cpu_level,
        memory_level,
        load_level,
        str(docker_context.get("level", "healthy")),
    )

    severity_map = {
        "CPU": cpu_percent / _CPU_CRITICAL_THRESHOLD,
        "RAM": memory_percent / _MEMORY_CRITICAL_THRESHOLD,
        "Load": load_ratio_percent / _LOAD_CRITICAL_THRESHOLD,
    }
    dominant_metric = max(severity_map, key=lambda metric: severity_map[metric])

    pressure_index = round(
        (
            min(cpu_percent / 100.0, 1.5) * 0.35
            + min(memory_percent / 100.0, 1.5) * 0.35
            + min(load_ratio_percent / 150.0, 1.5) * 0.30
        )
        * 100.0,
        1,
    )
    health_score = max(0, int(round(100.0 - pressure_index)))

    insights: list[str] = [
        f"CPU pressure is {_LEVEL_LABEL[cpu_level].lower()} at {cpu_percent:.1f}%.",
        f"Memory utilization is {_LEVEL_LABEL[memory_level].lower()} at {memory_percent:.1f}%.",
        f"Load pressure is {_LEVEL_LABEL[load_level].lower()} ({load_ratio_percent:.1f}% of core capacity).",
        f"Primary pressure source right now: {dominant_metric}.",
    ]

    recommendations: list[str] = []
    if cpu_level != "healthy":
        recommendations.append(
            "Review CPU-heavy processes and tune worker concurrency."
        )
    if memory_level != "healthy":
        recommendations.append("Check memory-heavy services and adjust memory limits.")
    if load_level != "healthy":
        recommendations.append(
            "Inspect I/O wait and queue depth to reduce load pressure."
        )

    if bool(docker_context.get("available")):
        stopped_containers = _to_int(docker_context.get("stopped_containers", 0))
        if stopped_containers > 0:
            recommendations.append(
                "Investigate stopped containers and restart only healthy workloads."
            )
    else:
        recommendations.append(
            "Docker metrics are unavailable. Validate Docker socket/daemon access."
        )

    if not recommendations:
        recommendations.append(
            "No immediate action required. Continue routine monitoring."
        )

    return {
        "overall_badge": _LEVEL_BADGE[overall_level],
        "overall_status": _LEVEL_LABEL[overall_level],
        "health_score": health_score,
        "dominant_metric": dominant_metric,
        "cpu_percent": cpu_percent,
        "cpu_badge": _health_badge(
            cpu_percent, _CPU_WARNING_THRESHOLD, _CPU_CRITICAL_THRESHOLD
        ),
        "cpu_status": _LEVEL_LABEL[cpu_level],
        "memory_percent": memory_percent,
        "memory_used": str(memory.get("used", "N/A")),
        "memory_available": str(memory.get("available", "N/A")),
        "memory_badge": _health_badge(
            memory_percent, _MEMORY_WARNING_THRESHOLD, _MEMORY_CRITICAL_THRESHOLD
        ),
        "memory_status": _LEVEL_LABEL[memory_level],
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "load_ratio_percent": round(load_ratio_percent, 1),
        "load_badge": _health_badge(
            load_ratio_percent, _LOAD_WARNING_THRESHOLD, _LOAD_CRITICAL_THRESHOLD
        ),
        "load_status": _LEVEL_LABEL[load_level],
        "cpu_count": cpu_count,
        "uptime": uptime,
        "process_total": int(process_stats.get("total", 0)),
        "docker": docker_context,
        "insights": insights,
        "recommendations": recommendations,
    }


# regexp="Health"
@logger.session_decorator
def handle_system_health(message: Message, bot: TeleBot) -> None:
    """Handle system health snapshot command."""
    try:
        bot.send_chat_action(message.chat.id, "typing")
        context = _build_health_context()

        health_message = Compiler.quick_render(
            template_name="b_health_summary.jinja2",
            context=context,
            thought_balloon=em.get_emoji("thought_balloon"),
            stethoscope=em.get_emoji("stethoscope"),
            desktop_computer=em.get_emoji("desktop_computer"),
        )

        bot.send_message(message.chat.id, text=health_message, parse_mode="HTML")
        return None
    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling system health summary",
                error_code="HAND_HEALTH_001",
                metadata={"exception": str(error)},
            )
        )
