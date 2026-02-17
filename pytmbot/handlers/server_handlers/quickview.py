#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import fetch_docker_counters
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import em, psutil_adapter
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


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
    Collect all metrics concurrently using ThreadPoolExecutor.

    Returns:
        Dict containing all collected metrics.
    """
    metrics: dict[str, object] = {}

    # Define tasks to run concurrently
    tasks: dict[str, Callable[[], object | None]] = {
        "uptime": _get_uptime,
        "load_average": _get_load,
        "memory": _get_memory,
        "processes": _get_processes,
        "docker": _get_docker,
    }

    # Calculate optimal number of workers
    optimal_workers = min(len(tasks), (psutil_adapter.get_cpu_count() or 2) + 1)

    with ThreadPoolExecutor(max_workers=optimal_workers) as executor:
        # Start all tasks
        future_to_task = {executor.submit(func): name for name, func in tasks.items()}

        # Collect results as they complete
        for future in as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                result = future.result()
                if result is not None:
                    metrics[task_name] = result
                else:
                    logger.warning("bot.handler.server.quickview.task.returned.warn")
            except Exception:
                logger.error("bot.handler.server.quickview.task.generated.fail")

    return metrics


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

        # Prepare context for template
        context: dict[str, object] = {
            "system": {
                "uptime": metrics.get("uptime", "N/A"),
                "load_average": load_average,
                "memory": memory_stats if isinstance(memory_stats, dict) else {},
                "processes": process_stats if isinstance(process_stats, dict) else {},
                "cpu": metrics.get("cpu", {}),
            }
        }

        # Add Docker metrics if available
        docker_metrics = metrics.get("docker")
        if isinstance(docker_metrics, dict):
            context["docker"] = docker_metrics

        bot_answer = Compiler.quick_render(
            template_name="b_quick_view.jinja2", context=context, **emojis
        )

        bot.send_message(message.chat.id, text=bot_answer, parse_mode="Markdown")

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
        )
