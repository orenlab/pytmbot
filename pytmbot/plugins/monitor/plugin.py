#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.db.influxdb_interface import InfluxDBInterface
from pytmbot.globals import get_emoji_converter, get_keyboards
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore

plugin = PluginCore()
em = get_emoji_converter()
keyboards = get_keyboards()

type TimeSeries = list[tuple[datetime, float]]


@dataclass(frozen=True, slots=True)
class _SeriesStats:
    latest: float
    min_value: float
    max_value: float
    avg_value: float
    delta: float
    samples: int


# noqa: codeclone[dead-code]
class MonitoringPlugin(PluginInterface):
    """Monitoring plugin UI and Influx-backed metric handlers."""

    _MEASUREMENT: Final[str] = "system_metrics"
    _TOP_GROUP_ITEMS: Final[int] = 5

    __slots__ = (
        "plugin_logger",
        "_monitor_plugin",
        "_psutil_adapter",
        "_selected_period_by_chat",
        "__weakref__",
    )

    def __init__(self, bot: TeleBot) -> None:
        super().__init__(bot)
        self.plugin_logger = plugin.logger
        self._monitor_plugin: SystemMonitorPlugin | None = None
        self._psutil_adapter = PsutilAdapter()
        self._selected_period_by_chat: dict[int, str] = {}

    @staticmethod
    def _build_monitor_keyboard() -> ReplyKeyboardMarkup:
        return keyboards.build_reply_keyboard(plugin_keyboard_data=config.KEYBOARD)

    @staticmethod
    def _build_period_keyboard() -> ReplyKeyboardMarkup:
        return keyboards.build_reply_keyboard(
            plugin_keyboard_data=config.PERIOD_KEYBOARD
        )

    @staticmethod
    def _first_name(message: Message) -> str:
        from_user = getattr(message, "from_user", None)
        return (from_user.first_name if from_user else None) or "User"

    @staticmethod
    def _button_regexp(text: str) -> str:
        # Reply keyboard buttons are rendered as "<emoji> <title>".
        # Match both plain text and keyboard-rendered value with emoji prefix.
        return rf"^(?:[^\w\s]+\s+)?{re.escape(text)}$"

    @staticmethod
    def _normalize_button_text(text: str) -> str:
        # Convert "<emoji> Label" reply text back to plain label used in config maps.
        return re.sub(r"^(?:[^\w\s]+\s+)+", "", text).strip()

    def _register_text_handler(
        self, handler: Callable[[Message], Message | None], text: str
    ) -> None:
        self.bot.register_message_handler(handler, regexp=self._button_regexp(text))

    def _resolve_selected_period(self, chat_id: int) -> str:
        selected = self._selected_period_by_chat.get(chat_id, config.DEFAULT_PERIOD_KEY)
        if selected in config.PERIOD_PRESETS:
            return selected
        return config.DEFAULT_PERIOD_KEY

    def _resolve_selected_period_label(self, chat_id: int) -> str:
        period_key = self._resolve_selected_period(chat_id)
        return config.PERIOD_PRESETS[period_key]["label"]

    def _set_selected_period(self, chat_id: int, period_key: str) -> None:
        if period_key in config.PERIOD_PRESETS:
            self._selected_period_by_chat[chat_id] = period_key

    def _influx_client(self) -> InfluxDBInterface | None:
        monitor_plugin = self._monitor_plugin
        if monitor_plugin is None:
            return None
        return monitor_plugin.influxdb_client

    @staticmethod
    def _compute_series_stats(series: TimeSeries) -> _SeriesStats | None:
        if not series:
            return None

        values = [value for _, value in series]
        if not values:
            return None

        latest = values[-1]
        first = values[0]
        return _SeriesStats(
            latest=latest,
            min_value=min(values),
            max_value=max(values),
            avg_value=sum(values) / len(values),
            delta=latest - first,
            samples=len(values),
        )

    def _query_series(self, field: str, period_key: str) -> TimeSeries:
        influx = self._influx_client()
        if influx is None:
            return []

        preset = config.PERIOD_PRESETS.get(period_key, config.PERIOD_PRESETS["1h"])
        try:
            return influx.query_data(
                measurement=self._MEASUREMENT,
                start=preset["start"],
                stop="now()",
                field=field,
            )
        except Exception as error:
            self.plugin_logger.warning(
                "bot.plugins.monitor.plugin.query.series.fail",
                field=field,
                period_key=period_key,
                error=str(error),
            )
            return []

    def _query_field_stats(self, field: str, period_key: str) -> _SeriesStats | None:
        return self._compute_series_stats(
            self._query_series(field=field, period_key=period_key)
        )

    def _query_prefixed_field_stats(
        self, prefix: str, period_key: str
    ) -> list[tuple[str, _SeriesStats]]:
        influx = self._influx_client()
        if influx is None:
            return []

        try:
            fields = influx.get_available_fields(self._MEASUREMENT)
        except Exception as error:
            self.plugin_logger.warning(
                "bot.plugins.monitor.plugin.query.fields.fail",
                prefix=prefix,
                error=str(error),
            )
            return []

        items: list[tuple[str, _SeriesStats]] = []
        for field in sorted(name for name in fields if name.startswith(prefix)):
            stats = self._query_field_stats(field=field, period_key=period_key)
            if stats is None:
                continue
            metric_name = field.removeprefix(prefix).replace("_", " ")
            items.append((metric_name or field, stats))

        return items

    @staticmethod
    def _format_stats_summary(stats: _SeriesStats, unit: str) -> list[str]:
        return [
            f"• Latest: {stats.latest:.1f}{unit}",
            f"• Average: {stats.avg_value:.1f}{unit}",
            f"• Min / Max: {stats.min_value:.1f}{unit} / {stats.max_value:.1f}{unit}",
            f"• Trend: {stats.delta:+.1f}{unit}",
            f"• Samples: {stats.samples}",
        ]

    @staticmethod
    def _format_compact(stats: _SeriesStats | None, unit: str) -> str:
        if stats is None:
            return "no data"
        return f"{stats.latest:.1f}{unit} (avg {stats.avg_value:.1f}{unit})"

    def _build_cpu_snapshot_section(self) -> tuple[list[str], list[str]]:
        cpu_stats = self._psutil_adapter.get_cpu_usage()
        load_avg = self._psutil_adapter.get_load_average()
        top_processes = self._psutil_adapter.get_top_processes(count=5)

        cpu_percent = float(cpu_stats.get("cpu_percent", 0.0))
        cpu_per_core = cpu_stats.get("cpu_percent_per_core", [])

        per_core_preview = ", ".join(
            f"#{index + 1}: {core_value:.1f}%"
            for index, core_value in enumerate(cpu_per_core[:8])
        )
        if len(cpu_per_core) > 8:
            per_core_preview = f"{per_core_preview}, ..."
        if not per_core_preview:
            per_core_preview = "N/A"

        summary = [
            f"• Latest CPU usage: {cpu_percent:.1f}%",
            f"• CPU cores: {len(cpu_per_core)}",
            (
                f"• Load average: "
                f"{load_avg[0]:.2f} / {load_avg[1]:.2f} / {load_avg[2]:.2f}"
            ),
            f"• Per-core (first 8): {per_core_preview}",
        ]

        if top_processes:
            details = [
                (
                    f"• {proc['name']} (PID {proc['pid']}): "
                    f"CPU {proc['cpu_percent']:.1f}%, MEM {proc['memory_percent']:.1f}%"
                )
                for proc in top_processes
            ]
        else:
            details = ["• Top processes are unavailable"]

        return summary, details

    def _build_memory_snapshot_section(self) -> tuple[list[str], list[str]]:
        memory = self._psutil_adapter.get_memory()
        summary = [
            f"• Latest memory usage: {float(memory.get('percent', 0.0)):.1f}%",
            f"• Used: {memory.get('used', 'N/A')}",
            f"• Available: {memory.get('available', 'N/A')}",
        ]
        return summary, []

    def _build_disk_snapshot_section(self) -> tuple[list[str], list[str]]:
        disks = sorted(
            self._psutil_adapter.get_disk_usage(),
            key=lambda item: float(item.get("percent", 0.0)),
            reverse=True,
        )
        if not disks:
            return ["• Disk usage data is unavailable"], []

        summary = []
        for disk in disks[: self._TOP_GROUP_ITEMS]:
            summary.append(
                f"• {disk.get('mnt_point', 'unknown')}: "
                f"{float(disk.get('percent', 0.0)):.1f}%"
            )
        return summary, []

    def _build_temperature_snapshot_section(self) -> tuple[list[str], list[str]]:
        sensors = sorted(
            self._psutil_adapter.get_sensors_temperatures(),
            key=lambda item: float(item.get("sensor_value", 0.0)),
            reverse=True,
        )
        if not sensors:
            return ["• Temperature sensor data is unavailable"], []

        summary = []
        for sensor in sensors[: self._TOP_GROUP_ITEMS]:
            summary.append(
                f"• {sensor.get('sensor_name', 'sensor')}: "
                f"{float(sensor.get('sensor_value', 0.0)):.1f}°C"
            )
        return summary, []

    def _build_cpu_section(self, period_key: str) -> tuple[list[str], list[str]]:
        cpu_stats = self._query_field_stats("cpu_usage", period_key)
        if cpu_stats is None:
            return self._build_cpu_snapshot_section()

        summary = self._format_stats_summary(cpu_stats, "%")
        details: list[str] = []
        for field, label in (
            ("load_averages_1m", "Load average (1m)"),
            ("load_averages_5m", "Load average (5m)"),
            ("load_averages_15m", "Load average (15m)"),
        ):
            stats = self._query_field_stats(field, period_key)
            if stats is None:
                continue
            details.append(f"• {label}: {stats.latest:.2f} (avg {stats.avg_value:.2f})")

        return summary, details

    def _build_memory_section(self, period_key: str) -> tuple[list[str], list[str]]:
        memory_stats = self._query_field_stats("memory_usage", period_key)
        if memory_stats is None:
            return self._build_memory_snapshot_section()
        return self._format_stats_summary(memory_stats, "%"), []

    def _build_disk_section(self, period_key: str) -> tuple[list[str], list[str]]:
        disks = sorted(
            self._query_prefixed_field_stats("disk_usage_", period_key),
            key=lambda item: item[1].latest,
            reverse=True,
        )
        if not disks:
            return self._build_disk_snapshot_section()

        summary = [
            f"• {name}: {stats.latest:.1f}% (avg {stats.avg_value:.1f}%)"
            for name, stats in disks[: self._TOP_GROUP_ITEMS]
        ]
        details = [
            f"• {name}: min {stats.min_value:.1f}% / max {stats.max_value:.1f}%"
            for name, stats in disks[: self._TOP_GROUP_ITEMS]
        ]
        return summary, details

    def _build_temperature_section(
        self, period_key: str
    ) -> tuple[list[str], list[str]]:
        temperatures = sorted(
            self._query_prefixed_field_stats("temperatures_", period_key),
            key=lambda item: item[1].latest,
            reverse=True,
        )
        if not temperatures:
            return self._build_temperature_snapshot_section()

        summary = [
            f"• {name}: {stats.latest:.1f}°C (avg {stats.avg_value:.1f}°C)"
            for name, stats in temperatures[: self._TOP_GROUP_ITEMS]
        ]
        details = [
            f"• {name}: min {stats.min_value:.1f}°C / max {stats.max_value:.1f}°C"
            for name, stats in temperatures[: self._TOP_GROUP_ITEMS]
        ]
        return summary, details

    def _build_overview_lines(self, period_key: str) -> tuple[str, str, str, str]:
        cpu_line = self._format_compact(
            self._query_field_stats("cpu_usage", period_key), "%"
        )
        memory_line = self._format_compact(
            self._query_field_stats("memory_usage", period_key), "%"
        )

        disks = sorted(
            self._query_prefixed_field_stats("disk_usage_", period_key),
            key=lambda item: item[1].latest,
            reverse=True,
        )
        temperatures = sorted(
            self._query_prefixed_field_stats("temperatures_", period_key),
            key=lambda item: item[1].latest,
            reverse=True,
        )

        disk_line = (
            f"{disks[0][0]}: {disks[0][1].latest:.1f}% (max {disks[0][1].max_value:.1f}%)"
            if disks
            else "no data"
        )
        temperature_line = (
            f"{temperatures[0][0]}: {temperatures[0][1].latest:.1f}°C "
            f"(max {temperatures[0][1].max_value:.1f}°C)"
            if temperatures
            else "no data"
        )

        return cpu_line, memory_line, disk_line, temperature_line

    def _send_monitoring_dashboard(
        self, message: Message, *, notice: str | None = None
    ) -> Message:
        period_label = self._resolve_selected_period_label(message.chat.id)
        period_key = self._resolve_selected_period(message.chat.id)
        cpu_line, memory_line, disk_line, temperature_line = self._build_overview_lines(
            period_key
        )

        response = Compiler.quick_render(
            template_name="plugin_monitor_index.jinja2",
            first_name=self._first_name(message),
            period_label=period_label,
            notice=notice,
            cpu_line=cpu_line,
            memory_line=memory_line,
            disk_line=disk_line,
            temperature_line=temperature_line,
            thought_balloon=em.get_emoji("thought_balloon"),
            bar_chart=em.get_emoji("bar_chart"),
            information=em.get_emoji("information"),
            minus=em.get_emoji("minus"),
            electric_plug=em.get_emoji("electric_plug"),
            brain=em.get_emoji("brain"),
            computer_disk=em.get_emoji("computer_disk"),
            thermometer=em.get_emoji("thermometer"),
        )
        return self.bot.send_message(
            message.chat.id,
            text=response,
            reply_markup=self._build_monitor_keyboard(),
            parse_mode="HTML",
        )

    def _send_metric_section(self, message: Message, metric_key: str) -> Message:
        period_key = self._resolve_selected_period(message.chat.id)
        period_label = self._resolve_selected_period_label(message.chat.id)

        if metric_key == "cpu":
            title = "CPU usage"
            summary_lines, detail_lines = self._build_cpu_section(period_key)
        elif metric_key == "memory":
            title = "Memory usage"
            summary_lines, detail_lines = self._build_memory_section(period_key)
        elif metric_key == "disk":
            title = "Disk usage"
            summary_lines, detail_lines = self._build_disk_section(period_key)
        elif metric_key == "temperature":
            title = "Temperatures"
            summary_lines, detail_lines = self._build_temperature_section(period_key)
        else:
            title = "Overview"
            cpu_line, memory_line, disk_line, temp_line = self._build_overview_lines(
                period_key
            )
            summary_lines = [
                f"• CPU: {cpu_line}",
                f"• Memory: {memory_line}",
                f"• Disk: {disk_line}",
                f"• Temperatures: {temp_line}",
            ]
            detail_lines = []

        response = Compiler.quick_render(
            template_name="plugin_monitor_metric.jinja2",
            title=title,
            period_label=period_label,
            summary_lines=summary_lines,
            detail_lines=detail_lines,
            thought_balloon=em.get_emoji("thought_balloon"),
            information=em.get_emoji("information"),
            warning=em.get_emoji("warning"),
        )
        return self.bot.send_message(
            message.chat.id,
            text=response,
            reply_markup=self._build_monitor_keyboard(),
            parse_mode="HTML",
        )

    def handle_monitoring(self, message: Message) -> Message:
        return self._send_monitoring_dashboard(message)

    def handle_overview(self, message: Message) -> Message:
        return self._send_metric_section(message, "overview")

    def handle_cpu_usage(self, message: Message) -> Message:
        try:
            return self._send_metric_section(message, "cpu")
        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.monitor.plugin.cpu.snapshot.fail", error=str(error)
            )
            return self.bot.send_message(
                message.chat.id,
                "⚠️ Failed to collect CPU usage metrics. Please try again.",
            )

    def handle_memory_usage(self, message: Message) -> Message:
        return self._send_metric_section(message, "memory")

    def handle_disk_usage(self, message: Message) -> Message:
        return self._send_metric_section(message, "disk")

    def handle_temperatures(self, message: Message) -> Message:
        return self._send_metric_section(message, "temperature")

    def handle_select_period(self, message: Message) -> Message:
        options = "\n".join(
            f"• {preset['label']}" for preset in config.PERIOD_PRESETS.values()
        )
        return self.bot.send_message(
            message.chat.id,
            (
                f"{em.get_emoji('calendar')} <b>Select monitoring period</b>\n"
                f"<b>Current:</b> {self._resolve_selected_period_label(message.chat.id)}\n\n"
                f"{options}\n\n"
                f"{em.get_emoji('information')} "
                "After selecting period, return to any metric section."
            ),
            reply_markup=self._build_period_keyboard(),
            parse_mode="HTML",
        )

    def handle_period_choice(self, message: Message) -> Message:
        raw_label = (message.text or "").strip()
        label = self._normalize_button_text(raw_label)
        period_key = config.PERIOD_LABEL_TO_KEY.get(label)
        if period_key is None:
            return self.bot.send_message(
                message.chat.id,
                "⚠️ Unknown period option. Use the period keyboard buttons.",
                reply_markup=self._build_period_keyboard(),
            )
        self._set_selected_period(message.chat.id, period_key)
        return self._send_monitoring_dashboard(
            message,
            notice=f"Period updated: {config.PERIOD_PRESETS[period_key]['label']}",
        )

    def handle_back_to_monitoring(self, message: Message) -> Message:
        return self._send_monitoring_dashboard(message)

    def register(self) -> None:
        """Register SystemMonitorPlugin and start monitoring."""
        try:
            self._monitor_plugin = SystemMonitorPlugin(bot=self.bot)
            self._monitor_plugin.start_monitoring()

            self._register_text_handler(self.handle_monitoring, "Monitoring")
            self._register_text_handler(self.handle_overview, config.OVERVIEW_LABEL)
            self._register_text_handler(self.handle_cpu_usage, config.CPU_LABEL)
            self._register_text_handler(self.handle_memory_usage, config.MEMORY_LABEL)
            self._register_text_handler(self.handle_disk_usage, config.DISK_LABEL)
            self._register_text_handler(
                self.handle_temperatures, config.TEMPERATURES_LABEL
            )
            self._register_text_handler(
                self.handle_select_period, config.SELECT_PERIOD_LABEL
            )
            self._register_text_handler(
                self.handle_back_to_monitoring, config.BACK_TO_MONITORING_LABEL
            )
            for label in config.PERIOD_LABEL_TO_KEY:
                self._register_text_handler(self.handle_period_choice, label)

        except Exception:
            self.plugin_logger.error(
                "bot.plugins.monitor.plugin.register.monitoring.fail"
            )
            raise

    def cleanup(self) -> None:
        """Stop monitor plugin workers during plugin manager cleanup."""
        try:
            monitor_plugin = self._monitor_plugin
            if monitor_plugin is not None:
                monitor_plugin.stop_monitoring()
        finally:
            self._monitor_plugin = None
            self._selected_period_by_chat.clear()
            self._psutil_adapter.close()


__all__ = ["MonitoringPlugin"]
