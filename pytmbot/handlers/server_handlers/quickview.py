#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections.abc import Callable

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message

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
    build_user_bound_callback_data,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()
psutil_adapter = get_psutil_adapter()

QUICKVIEW_OVERVIEW_PREFIX = "__quickview_overview__"
QUICKVIEW_MEMORY_PREFIX = "__quickview_memory__"
QUICKVIEW_SENSORS_PREFIX = "__quickview_sensors__"
QUICKVIEW_CPU_PREFIX = "__quickview_cpu__"
QUICKVIEW_DISK_PREFIX = "__quickview_disk__"


def _get_uptime() -> str | None:
    """Get system uptime."""
    try:
        return psutil_adapter.get_uptime()
    except Exception:
        logger.error("bot.handler.server.quickview.get.uptime.fail")
        return None


def _get_load() -> tuple[float, float, float] | None:
    """Get load average."""
    try:
        load_avg = psutil_adapter.get_load_average()
        if (
            isinstance(load_avg, tuple)
            and len(load_avg) == 3
            and all(isinstance(value, (int, float)) for value in load_avg)
        ):
            return (float(load_avg[0]), float(load_avg[1]), float(load_avg[2]))
        return None
    except Exception:
        logger.error("bot.handler.server.quickview.get.load.fail")
        return None


def _get_memory() -> dict[str, object] | None:
    """Get memory statistics."""
    try:
        memory_stats = psutil_adapter.get_memory()
        if isinstance(memory_stats, dict):
            return {str(key): value for key, value in memory_stats.items()}
        return None
    except Exception:
        logger.error("bot.handler.server.quickview.get.memory.fail")
        return None


def _get_cpu() -> dict[str, object] | None:
    """Get CPU statistics."""
    try:
        cpu_stats = psutil_adapter.get_cpu_usage()
        cpu_freq = psutil_adapter.get_cpu_frequency()
        physical_count_getter = getattr(
            psutil_adapter,
            "get_cpu_count_physical",
            lambda: psutil_adapter.get_cpu_count(),
        )
        if isinstance(cpu_stats, dict) and isinstance(cpu_freq, dict):
            return {
                "cpu_percent": float(cpu_stats.get("cpu_percent", 0.0)),
                "cpu_count": int(psutil_adapter.get_cpu_count()),
                "physical_cpu_count": int(physical_count_getter()),
                "frequency_mhz": float(cpu_freq.get("current_freq", 0.0)),
            }
        return None
    except Exception:
        logger.error("bot.handler.server.quickview.get.cpu.fail")
        return None


def _get_processes() -> dict[str, object] | None:
    """Get process counts."""
    try:
        process_stats = psutil_adapter.get_process_counts()
        if isinstance(process_stats, dict):
            return {str(key): value for key, value in process_stats.items()}
        return None
    except Exception:
        logger.error("bot.handler.server.quickview.get.counts.fail")
        return None


def _get_docker() -> dict[str, object] | None:
    """Get Docker statistics."""
    try:
        docker_stats = fetch_docker_counters()
        if isinstance(docker_stats, dict):
            return {str(key): value for key, value in docker_stats.items()}
        return None
    except Exception:
        logger.error("bot.handler.server.quickview.get.stats.fail")
        return None


def _collect_metrics() -> dict[str, object]:
    """
    Collect all metrics sequentially with predictable low overhead.

    Returns:
        Dict containing all collected metrics.
    """
    metrics: dict[str, object] = {}

    collectors: dict[str, Callable[[], object | None]] = {
        "uptime": _get_uptime,
        "load_average": _get_load,
        "cpu": _get_cpu,
        "memory": _get_memory,
        "processes": _get_processes,
        "docker": _get_docker,
    }

    for metric_name, collector in collectors.items():
        try:
            result = collector()
            if result is not None:
                metrics[metric_name] = result
            else:
                logger.warning(
                    "bot.handler.server.quickview.task.returned.warn",
                    metric=metric_name,
                )
        except Exception:
            logger.error(
                "bot.handler.server.quickview.task.generated.fail",
                metric=metric_name,
            )

    return metrics


def _build_quickview_context(metrics: dict[str, object]) -> dict[str, object]:
    """Build normalized context for quickview template."""
    load_average_raw = metrics.get("load_average")
    load_average: tuple[float, float, float] = (
        load_average_raw
        if (
            isinstance(load_average_raw, tuple)
            and len(load_average_raw) == 3
            and all(isinstance(value, (int, float)) for value in load_average_raw)
        )
        else (0.0, 0.0, 0.0)
    )
    memory_stats = metrics.get("memory")
    process_stats = metrics.get("processes")
    cpu_stats = metrics.get("cpu")

    context: dict[str, object] = {
        "system": {
            "uptime": metrics.get("uptime", "N/A"),
            "load_average": load_average,
            "cpu": cpu_stats if isinstance(cpu_stats, dict) else {},
            "memory": memory_stats if isinstance(memory_stats, dict) else {},
            "processes": process_stats if isinstance(process_stats, dict) else {},
        }
    }

    docker_metrics = metrics.get("docker")
    if isinstance(docker_metrics, dict):
        context["docker"] = docker_metrics

    return context


def _build_quickview_keyboard(
    user_id: int | None, *, on_overview: bool = False
) -> InlineKeyboardMarkup:
    overview_text = "🔄 Refresh data" if on_overview else "📊 Overview"
    buttons = [
        button_data(
            text=overview_text,
            callback_data=build_user_bound_callback_data(
                QUICKVIEW_OVERVIEW_PREFIX, user_id
            ),
        ),
        button_data(
            text="💾 Memory",
            callback_data=build_user_bound_callback_data(
                QUICKVIEW_MEMORY_PREFIX, user_id
            ),
        ),
        button_data(
            text="🌡 Temp",
            callback_data=build_user_bound_callback_data(
                QUICKVIEW_SENSORS_PREFIX, user_id
            ),
        ),
        button_data(
            text="⚡ CPU",
            callback_data=build_user_bound_callback_data(QUICKVIEW_CPU_PREFIX, user_id),
        ),
        button_data(
            text="📂 Disk",
            callback_data=build_user_bound_callback_data(
                QUICKVIEW_DISK_PREFIX, user_id
            ),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


# regexp="Quick view|Quick status|qv"
@logger.session_decorator
def handle_quick_view(message: Message, bot: TeleBot) -> None:
    """Handle quick view command to show system and Docker summary."""
    emojis = {
        "computer": em.get_emoji("desktop_computer"),
        "chart": em.get_emoji("bar_chart"),
        "memory": em.get_emoji("brain"),
        "cpu": em.get_emoji("electric_plug"),
        "process": em.get_emoji("gear"),
        "docker": em.get_emoji("whale"),
        "warning": em.get_emoji("warning"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        # Collect all metrics concurrently
        metrics = _collect_metrics()

        if not metrics:
            logger.error("bot.handler.server.quickview.collect.any.fail")
            bot.send_message(
                message.chat.id,
                text="⚠️ Failed to get system metrics. Please try again later.",
            )
            return

        context = _build_quickview_context(metrics)
        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_quickview_keyboard(user_id, on_overview=True)

        bot_answer = Compiler.quick_render(
            template_name="b_quick_view.jinja2", context=context, **emojis
        )

        bot.send_message(
            message.chat.id,
            text=bot_answer,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling quick view command",
                error_code="HAND_QV1",
                metadata={"exception": str(error)},
            )
        ) from error
