#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    get_psutil_adapter,
    is_docker_environment,
)
from pytmbot.handlers.server_handlers.cpu import (
    CPU_INFO_PREFIX,
    CPU_PER_CORE_PREFIX,
    CPU_TIMES_PREFIX,
    PROCESS_INFO_PREFIX,
    _build_cpu_keyboard,
    _build_cpu_overview_context,
)
from pytmbot.handlers.server_handlers.filesystem import (
    DISK_IO_PREFIX,
    FILESYSTEM_OVERVIEW_PREFIX,
    _build_filesystem_keyboard,
)
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
    build_user_bound_callback_data,
)
from pytmbot.handlers.server_handlers.network import (
    NETWORK_CONNECTIONS_PREFIX,
    NETWORK_INTERFACES_PREFIX,
    NETWORK_OVERVIEW_PREFIX,
    _build_network_keyboard,
)
from pytmbot.handlers.server_handlers.quickview import (
    QUICKVIEW_CPU_PREFIX,
    QUICKVIEW_DISK_PREFIX,
    QUICKVIEW_MEMORY_PREFIX,
    QUICKVIEW_OVERVIEW_PREFIX,
    QUICKVIEW_SENSORS_PREFIX,
    _build_quickview_context,
    _build_quickview_keyboard,
    _collect_metrics,
)
from pytmbot.handlers.server_handlers.sensors import (
    FAN_SPEEDS_PREFIX,
    SENSORS_OVERVIEW_PREFIX,
    _build_sensors_keyboard,
)
from pytmbot.handlers.server_handlers.uptime import (
    USERS_INFO_PREFIX,
    _build_uptime_keyboard,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import set_naturaltime

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()
psutil_adapter = get_psutil_adapter()
running_in_docker = is_docker_environment()


def _edit_message(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    text: str,
    parse_mode: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if call.message is None:
        return
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


def _resolve_target_user_id(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    prefix: str,
    invalid_payload_text: str,
    missing_message_text: str,
) -> tuple[bool, int | None]:
    is_allowed, target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix=prefix,
        invalid_payload_text=invalid_payload_text,
        missing_message_text=missing_message_text,
    )
    if not is_allowed:
        return False, None
    return True, target_user_id


def _progress_bar(value: float, width: int = 12) -> str:
    normalized = max(0.0, min(100.0, value))
    filled = int(round((normalized / 100.0) * width))
    return ("▓" * filled) + ("░" * (width - filled))


def _build_cpu_detail_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Back to CPU",
            callback_data=build_user_bound_callback_data(CPU_INFO_PREFIX, user_id),
        ),
        button_data(
            text="Per-core load",
            callback_data=build_user_bound_callback_data(CPU_PER_CORE_PREFIX, user_id),
        ),
        button_data(
            text="CPU times",
            callback_data=build_user_bound_callback_data(CPU_TIMES_PREFIX, user_id),
        ),
        button_data(
            text="Top 10 processes",
            callback_data=build_user_bound_callback_data(PROCESS_INFO_PREFIX, user_id),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


def _build_network_detail_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Back to Network",
            callback_data=build_user_bound_callback_data(
                NETWORK_OVERVIEW_PREFIX, user_id
            ),
        ),
        button_data(
            text="Interfaces",
            callback_data=build_user_bound_callback_data(
                NETWORK_INTERFACES_PREFIX, user_id
            ),
        ),
        button_data(
            text="Connections",
            callback_data=build_user_bound_callback_data(
                NETWORK_CONNECTIONS_PREFIX, user_id
            ),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


def _build_filesystem_detail_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Back to File system",
            callback_data=build_user_bound_callback_data(
                FILESYSTEM_OVERVIEW_PREFIX, user_id
            ),
        ),
        button_data(
            text="I/O stats",
            callback_data=build_user_bound_callback_data(DISK_IO_PREFIX, user_id),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


def _build_sensors_detail_keyboard(
    user_id: int | None, show_fans_button: bool
) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Back to Sensors",
            callback_data=build_user_bound_callback_data(
                SENSORS_OVERVIEW_PREFIX, user_id
            ),
        )
    ]
    if show_fans_button:
        buttons.append(
            button_data(
                text="Fan speeds",
                callback_data=build_user_bound_callback_data(
                    FAN_SPEEDS_PREFIX, user_id
                ),
            )
        )
    return keyboards.build_inline_keyboard(buttons)


@logger.session_decorator
def handle_cpu_info(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=CPU_INFO_PREFIX,
        invalid_payload_text="Invalid CPU request format.",
        missing_message_text="Cannot render CPU info in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        cpu_context = _build_cpu_overview_context()
        keyboard = _build_cpu_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_cpu.jinja2",
            context=cpu_context,
            running_in_docker=running_in_docker,
            thought_balloon=em.get_emoji("thought_balloon"),
            desktop_computer=em.get_emoji("desktop_computer"),
            warning=em.get_emoji("warning"),
            electric_plug=em.get_emoji("electric_plug"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline CPU info",
                error_code="HAND_CPU_002",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_cpu_per_core(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=CPU_PER_CORE_PREFIX,
        invalid_payload_text="Invalid per-core request format.",
        missing_message_text="Cannot render per-core CPU in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        cpu_usage = psutil_adapter.get_cpu_usage()
        per_core = cpu_usage.get("cpu_percent_per_core", [])
        core_rows = [
            {
                "core": index,
                "usage_percent": float(value),
                "bar": _progress_bar(float(value)),
            }
            for index, value in enumerate(per_core)
        ]
        keyboard = _build_cpu_detail_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_cpu_per_core.jinja2",
            context={"core_rows": core_rows},
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline per-core CPU info",
                error_code="HAND_CPU_003",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_cpu_times(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=CPU_TIMES_PREFIX,
        invalid_payload_text="Invalid CPU times request format.",
        missing_message_text="Cannot render CPU times in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        cpu_times = psutil_adapter.get_cpu_times_percent()
        keyboard = _build_cpu_detail_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_cpu_times.jinja2",
            context=cpu_times,
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline CPU times info",
                error_code="HAND_CPU_004",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_network_overview(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=NETWORK_OVERVIEW_PREFIX,
        invalid_payload_text="Invalid network request format.",
        missing_message_text="Cannot render network info in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        network_statistics = psutil_adapter.get_net_io_counters()
        keyboard = _build_network_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_net_io.jinja2",
            context=network_statistics,
            thought_balloon=em.get_emoji("thought_balloon"),
            globe_showing_europe_africa=em.get_emoji("globe_showing_Europe-Africa"),
            hugging_face=em.get_emoji("smiling_face_with_open_hands"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline network overview",
                error_code="HAND_NET_001",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_network_interfaces(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=NETWORK_INTERFACES_PREFIX,
        invalid_payload_text="Invalid interfaces request format.",
        missing_message_text="Cannot render interfaces in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        interfaces = psutil_adapter.get_net_interface_stats()
        rows = []
        for name in sorted(interfaces):
            stats = interfaces[name]
            speed = int(stats.get("speed", 0))
            rows.append(
                {
                    "name": name,
                    "state": "UP" if bool(stats.get("is_up")) else "DOWN",
                    "speed": f"{speed} Mbps" if speed > 0 else "N/A",
                    "mtu": int(stats.get("mtu", 0)),
                    "ip_address": str(stats.get("ip_address", "N/A")),
                }
            )

        keyboard = _build_network_detail_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_net_interfaces.jinja2",
            context={"interfaces": rows},
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline network interfaces",
                error_code="HAND_NET_002",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_network_connections(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=NETWORK_CONNECTIONS_PREFIX,
        invalid_payload_text="Invalid connections request format.",
        missing_message_text="Cannot render connections in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        summary = psutil_adapter.get_network_connections_summary()
        keyboard = _build_network_detail_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_net_connections.jinja2",
            context=summary,
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline network connections",
                error_code="HAND_NET_003",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_filesystem_overview(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=FILESYSTEM_OVERVIEW_PREFIX,
        invalid_payload_text="Invalid file system request format.",
        missing_message_text="Cannot render file system info in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        disk_usage = psutil_adapter.get_disk_usage()
        keyboard = _build_filesystem_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_fs.jinja2",
            context=disk_usage,
            running_in_docker=running_in_docker,
            thought_balloon=em.get_emoji("thought_balloon"),
            floppy_disk=em.get_emoji("floppy_disk"),
            minus=em.get_emoji("minus"),
            warning=em.get_emoji("warning"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline file system overview",
                error_code="HAND_FS_001",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_disk_io(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=DISK_IO_PREFIX,
        invalid_payload_text="Invalid disk I/O request format.",
        missing_message_text="Cannot render disk I/O info in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        disk_io = psutil_adapter.get_disk_io_stats()
        keyboard = _build_filesystem_detail_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_disk_io.jinja2",
            context={"disks": disk_io},
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline disk I/O info",
                error_code="HAND_FS_002",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_users_info(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=USERS_INFO_PREFIX,
        invalid_payload_text="Invalid users request format.",
        missing_message_text="Cannot render users info in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        users = psutil_adapter.get_users_info()
        normalized = []
        for user in users:
            started_ts = float(user.get("started", 0.0))
            started_at = datetime.fromtimestamp(started_ts, tz=UTC)
            normalized.append(
                {
                    "username": str(user.get("username", "unknown")),
                    "terminal": str(user.get("terminal", "unknown")),
                    "host": str(user.get("host", "unknown")),
                    "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "started_ago": set_naturaltime(started_at),
                }
            )

        keyboard = _build_uptime_keyboard(target_user_id)
        text = Compiler.quick_render(
            template_name="b_users_info.jinja2",
            context={"users": normalized},
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline users info",
                error_code="HAND_UP_001",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_sensors_overview(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=SENSORS_OVERVIEW_PREFIX,
        invalid_payload_text="Invalid sensors request format.",
        missing_message_text="Cannot render sensors in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        sensors_data = psutil_adapter.get_sensors_temperatures()
        fan_speeds = psutil_adapter.get_fan_speeds()

        if sensors_data:
            text = Compiler.quick_render(
                template_name="b_sensors.jinja2",
                context=sensors_data,
                thought_balloon=em.get_emoji("thought_balloon"),
                thermometer=em.get_emoji("thermometer"),
                exclamation=em.get_emoji("red_exclamation_mark"),
                melting_face=em.get_emoji("melting_face"),
            )
        else:
            text = (
                f"{em.get_emoji('thought_balloon')} <b>Sensors:</b>\n\n"
                "No temperature sensors available."
            )

        keyboard = None
        if fan_speeds:
            keyboard = _build_sensors_keyboard(target_user_id)

        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline sensors overview",
                error_code="HAND_SENS_001",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_fan_speeds(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=FAN_SPEEDS_PREFIX,
        invalid_payload_text="Invalid fan speeds request format.",
        missing_message_text="Cannot render fan speeds in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        fan_speeds = psutil_adapter.get_fan_speeds()
        keyboard = _build_sensors_detail_keyboard(
            target_user_id, show_fans_button=bool(fan_speeds)
        )
        text = Compiler.quick_render(
            template_name="b_fans.jinja2",
            context={"fans": fan_speeds},
            thought_balloon=em.get_emoji("thought_balloon"),
        )
        _edit_message(call, bot, text=text, parse_mode="HTML", reply_markup=keyboard)
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline fan speeds",
                error_code="HAND_SENS_002",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_quickview_overview(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=QUICKVIEW_OVERVIEW_PREFIX,
        invalid_payload_text="Invalid quickview request format.",
        missing_message_text="Cannot render quickview in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        metrics = _collect_metrics()
        context = _build_quickview_context(metrics)
        keyboard = _build_quickview_keyboard(target_user_id, on_overview=True)
        text = Compiler.quick_render(
            template_name="b_quick_view.jinja2",
            context=context,
            computer=em.get_emoji("desktop_computer"),
            chart=em.get_emoji("bar_chart"),
            memory=em.get_emoji("brain"),
            cpu=em.get_emoji("electric_plug"),
            process=em.get_emoji("gear"),
            docker=em.get_emoji("whale"),
            warning=em.get_emoji("warning"),
        )
        _edit_message(
            call, bot, text=text, parse_mode="Markdown", reply_markup=keyboard
        )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline quickview overview",
                error_code="HAND_QV2",
                metadata={"exception": str(error)},
            )
        )


def _build_quickview_detail_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    return _build_quickview_keyboard(user_id, on_overview=False)


@logger.session_decorator
def handle_quickview_memory(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=QUICKVIEW_MEMORY_PREFIX,
        invalid_payload_text="Invalid quickview memory request format.",
        missing_message_text="Cannot render quickview memory in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        memory = psutil_adapter.get_memory()
        text = Compiler.quick_render(
            template_name="b_memory.jinja2",
            context=memory,
            thought_balloon=em.get_emoji("thought_balloon"),
            abacus=em.get_emoji("abacus"),
        )
        _edit_message(
            call,
            bot,
            text=text,
            parse_mode="HTML",
            reply_markup=_build_quickview_detail_keyboard(target_user_id),
        )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline quickview memory",
                error_code="HAND_QV3",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_quickview_sensors(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=QUICKVIEW_SENSORS_PREFIX,
        invalid_payload_text="Invalid quickview temperature request format.",
        missing_message_text="Cannot render quickview sensors in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        sensors_data = psutil_adapter.get_sensors_temperatures()
        if sensors_data:
            text = Compiler.quick_render(
                template_name="b_sensors.jinja2",
                context=sensors_data,
                thought_balloon=em.get_emoji("thought_balloon"),
                thermometer=em.get_emoji("thermometer"),
                exclamation=em.get_emoji("red_exclamation_mark"),
                melting_face=em.get_emoji("melting_face"),
            )
        else:
            text = "⚠️ No sensors were found :("
        _edit_message(
            call,
            bot,
            text=text,
            parse_mode="HTML",
            reply_markup=_build_quickview_detail_keyboard(target_user_id),
        )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline quickview sensors",
                error_code="HAND_QV4",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_quickview_cpu(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=QUICKVIEW_CPU_PREFIX,
        invalid_payload_text="Invalid quickview CPU request format.",
        missing_message_text="Cannot render quickview CPU in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        cpu_context = _build_cpu_overview_context()
        text = Compiler.quick_render(
            template_name="b_cpu.jinja2",
            context=cpu_context,
            running_in_docker=running_in_docker,
            thought_balloon=em.get_emoji("thought_balloon"),
            desktop_computer=em.get_emoji("desktop_computer"),
            warning=em.get_emoji("warning"),
            electric_plug=em.get_emoji("electric_plug"),
        )
        _edit_message(
            call,
            bot,
            text=text,
            parse_mode="HTML",
            reply_markup=_build_quickview_detail_keyboard(target_user_id),
        )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline quickview CPU",
                error_code="HAND_QV5",
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_quickview_disk(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = _resolve_target_user_id(
        call,
        bot,
        prefix=QUICKVIEW_DISK_PREFIX,
        invalid_payload_text="Invalid quickview disk request format.",
        missing_message_text="Cannot render quickview disk in this context.",
    )
    if not is_allowed:
        return None
    if call.message is None:
        return None

    try:
        disk_usage = psutil_adapter.get_disk_usage()
        text = Compiler.quick_render(
            template_name="b_fs.jinja2",
            context=disk_usage,
            running_in_docker=running_in_docker,
            thought_balloon=em.get_emoji("thought_balloon"),
            floppy_disk=em.get_emoji("floppy_disk"),
            minus=em.get_emoji("minus"),
            warning=em.get_emoji("warning"),
        )
        _edit_message(
            call,
            bot,
            text=text,
            parse_mode="HTML",
            reply_markup=_build_quickview_detail_keyboard(target_user_id),
        )
        return None
    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline quickview disk",
                error_code="HAND_QV6",
                metadata={"exception": str(error)},
            )
        )
