#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import fetch_docker_counters
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    get_psutil_adapter,
)
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
    build_user_bound_callback_data,
    edit_callback_message_text,
)
from pytmbot.health_system import HealthStatus
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import to_float, to_int

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()
button_data = ButtonDataType
keyboards = get_keyboards()

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
_MONITOR_LEVEL_BADGE: Final[dict[str, str]] = {
    "healthy": "🟢",
    "degraded": "🟡",
    "unhealthy": "🟠",
    "critical": "🔴",
    "offline": "⚫",
    "unknown": "⚪",
}
_MONITOR_LEVEL_LABEL: Final[dict[str, str]] = {
    "healthy": "Healthy",
    "degraded": "Degraded",
    "unhealthy": "Unhealthy",
    "critical": "Critical",
    "offline": "Offline",
    "unknown": "Unknown",
}
_MONITOR_LEVEL_SEVERITY: Final[dict[str, int]] = {
    "critical": 0,
    "offline": 1,
    "unhealthy": 2,
    "degraded": 3,
    "healthy": 4,
    "unknown": 5,
}
_COMPONENT_LABELS: Final[dict[str, str]] = {
    "telegram_api": "Telegram API",
    "polling": "Polling loop",
    "system_resources": "Bot resources",
    "sessions": "Sessions",
    "template_parser": "Template parser",
    "health_monitor": "Health monitor",
}
_MONITOR_TO_RUNTIME_LEVEL: Final[dict[str, str]] = {
    "healthy": "healthy",
    "degraded": "elevated",
    "unhealthy": "critical",
    "critical": "critical",
    "offline": "critical",
    "unknown": "elevated",
}
HEALTH_REFRESH_PREFIX = "__health_refresh__"


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
    return to_int(value, default)


def _to_float(value: object, default: float = 0.0) -> float:
    return to_float(value, default, strip_percent=True)


def _normalize_monitor_level(raw_level: object) -> str:
    normalized = str(raw_level).strip().lower()
    if normalized in _MONITOR_LEVEL_BADGE:
        return normalized
    return "unknown"


def _format_component_label(component: str) -> str:
    return _COMPONENT_LABELS.get(component, component.replace("_", " ").title())


def _sanitize_component_insights(
    component: str,
    details: dict[str, object],
) -> list[str]:
    insights: list[str] = []

    if component == "polling":
        if "polling_active" in details:
            is_active = bool(details.get("polling_active"))
            insights.append(f"Polling active: {'yes' if is_active else 'no'}")
        if "thread_alive" in details:
            thread_alive = bool(details.get("thread_alive"))
            insights.append(f"Worker thread: {'alive' if thread_alive else 'stopped'}")
    elif component == "sessions":
        total_sessions = _to_int(details.get("total_sessions", 0))
        blocked_sessions = _to_int(details.get("blocked_sessions", 0))
        authenticated_sessions = _to_int(details.get("authenticated_sessions", 0))
        insights.append(f"Total sessions: {total_sessions}")
        insights.append(f"Authenticated sessions: {authenticated_sessions}")
        insights.append(f"Blocked sessions: {blocked_sessions}")
    elif component == "system_resources":
        memory_percent = _to_float(details.get("memory_percent", 0.0))
        cpu_percent = _to_float(details.get("cpu_percent", details.get("cpu", 0.0)))
        insights.append(f"Bot memory usage: {memory_percent:.1f}%")
        insights.append(f"Bot CPU usage: {cpu_percent:.1f}%")
    elif component == "template_parser":
        cache_size = _to_int(details.get("cache_size", 0))
        validation_errors = _to_int(details.get("validation_errors", 0))
        total_validations = _to_int(details.get("total_validations", 0))
        insights.append(f"Template cache size: {cache_size}")
        insights.append(f"Validation errors: {validation_errors}/{total_validations}")
    elif component == "telegram_api":
        error_code = details.get("error_code")
        if isinstance(error_code, int):
            insights.append(f"Telegram API error code: {error_code}")

    if not insights and "error" in details:
        insights.append("Checker reported an internal error.")
    if not insights:
        insights.append("No additional issues detected.")

    return insights


def _build_monitor_context() -> dict[str, object]:
    summary = HealthStatus().get_summary()
    if summary.get("status") == "no_data":
        return {
            "available": False,
            "overall_level": "unknown",
            "overall_badge": _MONITOR_LEVEL_BADGE["unknown"],
            "overall_status": "Initializing",
            "operational": 0,
            "total": 0,
            "health_ratio_percent": 0.0,
            "duration_ms": 0.0,
            "components": [],
            "attention_count": 0,
            "action": "Health monitor is warming up. Please refresh in a few seconds.",
        }

    overall_level = _normalize_monitor_level(summary.get("overall", "unknown"))
    components_raw = summary.get("components", {})
    components = components_raw if isinstance(components_raw, dict) else {}

    component_rows: list[dict[str, object]] = []
    attention_count = 0
    for component_name, component_data in components.items():
        if not isinstance(component_data, dict):
            continue

        level = _normalize_monitor_level(component_data.get("level", "unknown"))
        if level not in {"healthy", "unknown"}:
            attention_count += 1

        details_raw = component_data.get("details", {})
        details = details_raw if isinstance(details_raw, dict) else {}

        component_rows.append(
            {
                "component_name": component_name,
                "component_label": _format_component_label(component_name),
                "level": level,
                "badge": _MONITOR_LEVEL_BADGE[level],
                "status_label": _MONITOR_LEVEL_LABEL[level],
                "latency_ms": _to_float(component_data.get("latency_ms", 0.0)),
                "insights": _sanitize_component_insights(component_name, details),
            }
        )

    component_rows.sort(
        key=lambda row: (
            _MONITOR_LEVEL_SEVERITY[str(row.get("level", "unknown"))],
            str(row.get("component_label", "")),
        )
    )

    if overall_level == "healthy":
        action = "No action required. Monitoring baseline is stable."
    elif overall_level == "degraded":
        action = "Watch highlighted components and keep trends under review."
    elif overall_level in {"unhealthy", "critical", "offline"}:
        action = "Action required: investigate non-healthy components immediately."
    else:
        action = "Health monitor data is incomplete. Refresh to get current status."

    return {
        "available": True,
        "overall_level": overall_level,
        "overall_badge": _MONITOR_LEVEL_BADGE[overall_level],
        "overall_status": _MONITOR_LEVEL_LABEL[overall_level],
        "operational": _to_int(summary.get("operational", 0)),
        "total": _to_int(summary.get("total", 0)),
        "health_ratio_percent": _to_float(summary.get("health_ratio", 0.0)) * 100.0,
        "duration_ms": _to_float(summary.get("duration_ms", 0.0)),
        "components": component_rows,
        "attention_count": attention_count,
        "action": action,
    }


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
    monitor_context = _build_monitor_context()
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
    monitor_level = str(monitor_context.get("overall_level", "unknown"))
    monitor_runtime_level = _MONITOR_TO_RUNTIME_LEVEL.get(monitor_level, "elevated")

    overall_level = _worst_level(
        cpu_level,
        memory_level,
        load_level,
        str(docker_context.get("level", "healthy")),
        monitor_runtime_level,
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
        (
            "Health monitor status: "
            f"{monitor_context.get('overall_status', 'Unknown')} "
            f"({monitor_context.get('operational', 0)}/{monitor_context.get('total', 0)} "
            "components operational)."
        ),
        f"CPU pressure is {_LEVEL_LABEL[cpu_level].lower()} at {cpu_percent:.1f}%.",
        f"Memory utilization is {_LEVEL_LABEL[memory_level].lower()} at {memory_percent:.1f}%.",
        f"Load pressure is {_LEVEL_LABEL[load_level].lower()} ({load_ratio_percent:.1f}% of core capacity).",
        f"Primary pressure source right now: {dominant_metric}.",
    ]

    recommendations: list[str] = []
    if _to_int(monitor_context.get("attention_count", 0)) > 0:
        recommendations.append(
            "Review non-healthy monitor components and resolve critical signals first."
        )
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
        "monitor": monitor_context,
        "insights": insights,
        "recommendations": recommendations,
    }


def _build_health_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="🔄 Refresh health",
            callback_data=build_user_bound_callback_data(
                HEALTH_REFRESH_PREFIX, user_id
            ),
        )
    ]
    return keyboards.build_inline_keyboard(buttons)


def _render_health_message() -> str:
    context = _build_health_context()
    return Compiler.quick_render(
        template_name="b_health_summary.jinja2",
        context=context,
        thought_balloon=em.get_emoji("thought_balloon"),
        stethoscope=em.get_emoji("stethoscope"),
        desktop_computer=em.get_emoji("desktop_computer"),
    )


@logger.session_decorator
def handle_system_health(message: Message, bot: TeleBot) -> None:
    """Handle health summary command."""
    try:
        bot.send_chat_action(message.chat.id, "typing")
        health_message = _render_health_message()
        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_health_keyboard(user_id)
        bot.send_message(
            message.chat.id,
            text=health_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
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
        ) from error


@logger.session_decorator
def handle_system_health_refresh(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix=HEALTH_REFRESH_PREFIX,
        invalid_payload_text=(
            "This refresh button is no longer valid. Run /health again."
        ),
        missing_message_text=(
            "This health message can no longer be refreshed. Run /health again."
        ),
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        health_message = _render_health_message()
        keyboard = _build_health_keyboard(target_user_id)
        was_edited = edit_callback_message_text(
            call=call,
            bot=bot,
            text=health_message,
            parse_mode="HTML",
            reply_markup=keyboard,
            not_modified_text="Health snapshot is already current.",
        )
        if was_edited:
            bot.answer_callback_query(
                callback_query_id=call.id,
                text="Health snapshot updated.",
                show_alert=False,
            )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling health refresh",
                error_code="HAND_HEALTH_002",
                metadata={"exception": str(error)},
            )
        ) from error
