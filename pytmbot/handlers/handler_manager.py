#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Final

from telebot.types import CallbackQuery, Message

from pytmbot.globals import settings
from pytmbot.models.handlers_model import HandlerManager

from .auth_processing.qrcode_processing import handle_qr_code_message
from .auth_processing.twofa_processing import (
    handle_totp_code_verification,
    handle_twofa_message,
)
from .bot_handlers.about import handle_about_command
from .bot_handlers.getmyid import handle_getmyid
from .bot_handlers.inline.update import handle_update_info
from .bot_handlers.navigation import handle_navigation
from .bot_handlers.plugins import handle_plugins
from .bot_handlers.start import handle_start
from .bot_handlers.updates import handle_bot_updates
from .docker_handlers.containers import handle_containers
from .docker_handlers.docker import handle_docker
from .docker_handlers.images import handle_images
from .docker_handlers.inline.back import handle_back_to_containers
from .docker_handlers.inline.container_info import (
    handle_containers_full_info,
)
from .docker_handlers.inline.container_runtime_info import (
    CONTAINER_EXTRA_CALLBACK_PREFIX,
    handle_container_extra_info,
)
from .docker_handlers.inline.image_extra import handle_image_extra_info
from .docker_handlers.inline.image_info import handle_image_info
from .docker_handlers.inline.image_updates import handle_image_updates
from .docker_handlers.inline.images_page import handle_images_page
from .docker_handlers.inline.logs import handle_get_logs
from .docker_handlers.inline.manage import handle_manage_container
from .docker_handlers.inline.manage_action import (
    handle_manage_container_action,
    managing_action_fabric,
)
from .server_handlers.cpu import handle_cpu
from .server_handlers.filesystem import handle_file_system
from .server_handlers.health_summary import (
    HEALTH_REFRESH_PREFIX,
    handle_system_health,
    handle_system_health_refresh,
)
from .server_handlers.inline.swap import handle_swap_info
from .server_handlers.inline.system_views import (
    handle_cpu_info,
    handle_cpu_per_core,
    handle_cpu_times,
    handle_disk_io,
    handle_fan_speeds,
    handle_filesystem_overview,
    handle_network_connections,
    handle_network_interfaces,
    handle_network_overview,
    handle_quickview_cpu,
    handle_quickview_disk,
    handle_quickview_memory,
    handle_quickview_overview,
    handle_quickview_sensors,
    handle_sensors_overview,
    handle_users_info,
)
from .server_handlers.inline.top_process import (
    handle_process_info,
    handle_process_overview,
)
from .server_handlers.load_average import handle_load_average
from .server_handlers.memory import handle_memory
from .server_handlers.network import handle_network
from .server_handlers.process import (
    PROCESS_INFO_FROM_PROCESS_PREFIX,
    PROCESS_OVERVIEW_PREFIX,
    handle_process,
)
from .server_handlers.quickview import handle_quick_view
from .server_handlers.sensors import handle_sensors
from .server_handlers.server import handle_server
from .server_handlers.uptime import handle_uptime

# Modern type aliases
type MessageType = Message
type CallbackQueryType = CallbackQuery
type HandlerType = dict[str, list[HandlerManager[object]]]
type MessageFilterFunc = Callable[[MessageType], bool]
type CallbackFilterFunc = Callable[[CallbackQueryType], bool]
type FilterFunc = MessageFilterFunc | CallbackFilterFunc
type HandlerCallback = Callable[..., object]

# Constants
TOTP_CODE_PATTERN: Final[str] = r"^/?[0-9]{6}$"


@dataclass(frozen=True, slots=True)
class HandlerConfig:
    """Configuration for handler registration with improved type safety."""

    callback: HandlerCallback
    commands: list[str] | None = None
    regexp: str | None = None
    filter_func: FilterFunc | None = None

    def __post_init__(self) -> None:
        """Validate callback and filter are callable."""
        if not callable(self.callback):
            raise TypeError("callback must be callable")
        if self.filter_func is not None and not callable(self.filter_func):
            raise TypeError("filter_func must be callable")

    def create_handler(self) -> HandlerManager[object]:
        """Create a HandlerManager instance from the config."""
        kwargs: dict[str, object] = {}
        if self.commands:
            kwargs["commands"] = self.commands
        if self.regexp:
            kwargs["regexp"] = self.regexp
        if self.filter_func:
            kwargs["func"] = self.filter_func
        return HandlerManager(callback=self.callback, kwargs=kwargs)


class AdminFilter:
    """Filter for admin-only commands with caching."""

    @staticmethod
    @cache
    def _get_admin_ids() -> frozenset[int]:
        """Get admin IDs with caching."""
        return frozenset(settings.access_control.allowed_admins_ids)

    @classmethod
    def is_admin(cls, message: MessageType) -> bool:
        """Check if user is admin."""
        if not message.from_user:
            return False
        return message.from_user.id in cls._get_admin_ids()


def _callback_data(call: CallbackQueryType) -> str | None:
    """Return callback data when present."""
    return call.data


def _starts_with(call: CallbackQueryType, prefix: str) -> bool:
    """Match callback data by prefix."""
    data = _callback_data(call)
    return data is not None and data.startswith(prefix)


def _matches_exact_or_prefix(call: CallbackQueryType, prefix: str) -> bool:
    """Match callback data by exact value or ``prefix:...`` form."""
    data = _callback_data(call)
    return data is not None and (data == prefix or data.startswith(f"{prefix}:"))


def _update_info_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__how_update__")


def _get_logs_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__get_logs__")


def _containers_full_info_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__get_full__")


def _back_to_containers_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "back_to_containers") or _starts_with(
        call, "__containers_page__"
    )


def _manage_container_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__manage__")


def _container_extra_info_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, CONTAINER_EXTRA_CALLBACK_PREFIX)


def _image_updates_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__check_updates__")


def _images_page_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__images_page__")


def _image_info_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__image_info__")


def _image_extra_filter(call: CallbackQueryType) -> bool:
    return _starts_with(call, "__image_extra__")


def _swap_info_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__swap_info__")


def _process_info_filter(call: CallbackQueryType) -> bool:
    data = _callback_data(call)
    return data is not None and (
        data == "__process_info__"
        or data.startswith("__process_info__:")
        or data == PROCESS_INFO_FROM_PROCESS_PREFIX
        or data.startswith(f"{PROCESS_INFO_FROM_PROCESS_PREFIX}:")
    )


def _process_overview_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, PROCESS_OVERVIEW_PREFIX)


def _cpu_info_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__cpu_info__")


def _cpu_per_core_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__cpu_per_core__")


def _cpu_times_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__cpu_times__")


def _network_overview_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__network_overview__")


def _network_interfaces_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__network_interfaces__")


def _network_connections_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__network_connections__")


def _filesystem_overview_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__filesystem_overview__")


def _disk_io_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__disk_io__")


def _users_info_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__users_info__")


def _sensors_overview_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__sensors_overview__")


def _fan_speeds_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__fan_speeds__")


def _quickview_overview_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__quickview_overview__")


def _quickview_memory_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__quickview_memory__")


def _quickview_sensors_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__quickview_sensors__")


def _quickview_cpu_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__quickview_cpu__")


def _quickview_disk_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, "__quickview_disk__")


def _health_refresh_filter(call: CallbackQueryType) -> bool:
    return _matches_exact_or_prefix(call, HEALTH_REFRESH_PREFIX)


@dataclass(frozen=True, slots=True)
class _InlineFilterRegistry:
    """Typed registry preserving the historical ``InlineFilters.*`` API."""

    swap_info: CallbackFilterFunc
    process_info: CallbackFilterFunc
    process_overview: CallbackFilterFunc
    cpu_info: CallbackFilterFunc
    cpu_per_core: CallbackFilterFunc
    cpu_times: CallbackFilterFunc
    update_info: CallbackFilterFunc
    get_logs: CallbackFilterFunc
    containers_full_info: CallbackFilterFunc
    back_to_containers: CallbackFilterFunc
    manage_container: CallbackFilterFunc
    container_extra_info: CallbackFilterFunc
    image_updates: CallbackFilterFunc
    images_page: CallbackFilterFunc
    image_info: CallbackFilterFunc
    image_extra: CallbackFilterFunc
    network_overview: CallbackFilterFunc
    network_interfaces: CallbackFilterFunc
    network_connections: CallbackFilterFunc
    filesystem_overview: CallbackFilterFunc
    disk_io: CallbackFilterFunc
    users_info: CallbackFilterFunc
    sensors_overview: CallbackFilterFunc
    fan_speeds: CallbackFilterFunc
    quickview_overview: CallbackFilterFunc
    quickview_memory: CallbackFilterFunc
    quickview_sensors: CallbackFilterFunc
    quickview_cpu: CallbackFilterFunc
    quickview_disk: CallbackFilterFunc
    health_refresh: CallbackFilterFunc


InlineFilters: Final[_InlineFilterRegistry] = _InlineFilterRegistry(
    swap_info=_swap_info_filter,
    process_info=_process_info_filter,
    process_overview=_process_overview_filter,
    cpu_info=_cpu_info_filter,
    cpu_per_core=_cpu_per_core_filter,
    cpu_times=_cpu_times_filter,
    update_info=_update_info_filter,
    get_logs=_get_logs_filter,
    containers_full_info=_containers_full_info_filter,
    back_to_containers=_back_to_containers_filter,
    manage_container=_manage_container_filter,
    container_extra_info=_container_extra_info_filter,
    image_updates=_image_updates_filter,
    images_page=_images_page_filter,
    image_info=_image_info_filter,
    image_extra=_image_extra_filter,
    network_overview=_network_overview_filter,
    network_interfaces=_network_interfaces_filter,
    network_connections=_network_connections_filter,
    filesystem_overview=_filesystem_overview_filter,
    disk_io=_disk_io_filter,
    users_info=_users_info_filter,
    sensors_overview=_sensors_overview_filter,
    fan_speeds=_fan_speeds_filter,
    quickview_overview=_quickview_overview_filter,
    quickview_memory=_quickview_memory_filter,
    quickview_sensors=_quickview_sensors_filter,
    quickview_cpu=_quickview_cpu_filter,
    quickview_disk=_quickview_disk_filter,
    health_refresh=_health_refresh_filter,
)


@cache
def _get_message_handler_configs() -> dict[str, list[HandlerConfig]]:
    """Build and cache message handler configurations dictionary."""
    return {
        "authorization": [
            HandlerConfig(callback=handle_twofa_message, regexp="Enter 2FA code")
        ],
        "quick_view": [HandlerConfig(callback=handle_quick_view, regexp="Quick view")],
        "code_verification": [
            HandlerConfig(
                callback=handle_totp_code_verification, regexp=TOTP_CODE_PATTERN
            )
        ],
        "start": [HandlerConfig(callback=handle_start, commands=["help", "start"])],
        "about": [HandlerConfig(callback=handle_about_command, regexp="About me")],
        "getmyid": [HandlerConfig(callback=handle_getmyid, commands=["getmyid"])],
        "navigation": [
            HandlerConfig(callback=handle_navigation, regexp="Back to main menu"),
            HandlerConfig(callback=handle_navigation, commands=["back"]),
        ],
        "updates": [
            HandlerConfig(callback=handle_bot_updates, commands=["check_bot_updates"])
        ],
        "containers": [
            HandlerConfig(callback=handle_containers, commands=["containers"]),
            HandlerConfig(callback=handle_containers, regexp="Containers"),
        ],
        "docker": [
            HandlerConfig(callback=handle_docker, commands=["docker"]),
            HandlerConfig(callback=handle_docker, regexp="Docker"),
        ],
        "filesystem": [
            HandlerConfig(callback=handle_file_system, regexp="File system")
        ],
        "cpu": [HandlerConfig(callback=handle_cpu, regexp="CPU")],
        "health": [
            HandlerConfig(callback=handle_system_health, regexp="Health"),
            HandlerConfig(callback=handle_system_health, commands=["health"]),
        ],
        "images": [
            HandlerConfig(callback=handle_images, commands=["images"]),
            HandlerConfig(callback=handle_images, regexp="Images"),
        ],
        "load_average": [
            HandlerConfig(callback=handle_load_average, regexp="Load average")
        ],
        "memory": [HandlerConfig(callback=handle_memory, regexp="Memory load")],
        "network": [HandlerConfig(callback=handle_network, regexp="Network")],
        "process": [HandlerConfig(callback=handle_process, regexp="Process")],
        "sensors": [HandlerConfig(callback=handle_sensors, regexp="Sensors")],
        "uptime": [HandlerConfig(callback=handle_uptime, regexp="Uptime")],
        "plugins": [
            HandlerConfig(callback=handle_plugins, commands=["plugins"]),
            HandlerConfig(callback=handle_plugins, regexp="Plugins"),
        ],
        "server": [
            HandlerConfig(callback=handle_server, commands=["server"]),
            HandlerConfig(callback=handle_server, regexp="Server"),
        ],
        "qrcode": [
            HandlerConfig(
                callback=handle_qr_code_message,
                regexp="Get QR-code for 2FA app",
                filter_func=AdminFilter.is_admin,
            ),
            HandlerConfig(
                callback=handle_qr_code_message,
                commands=["qrcode"],
                filter_func=AdminFilter.is_admin,
            ),
        ],
    }


@cache
def _get_inline_handler_configs() -> dict[str, list[HandlerConfig]]:
    """Build and cache inline handler configurations dictionary."""
    return {
        "swap": [
            HandlerConfig(
                callback=handle_swap_info, filter_func=InlineFilters.swap_info
            )
        ],
        "process_info": [
            HandlerConfig(
                callback=handle_process_info, filter_func=InlineFilters.process_info
            )
        ],
        "process_overview": [
            HandlerConfig(
                callback=handle_process_overview,
                filter_func=InlineFilters.process_overview,
            )
        ],
        "cpu_info": [
            HandlerConfig(callback=handle_cpu_info, filter_func=InlineFilters.cpu_info)
        ],
        "cpu_per_core": [
            HandlerConfig(
                callback=handle_cpu_per_core, filter_func=InlineFilters.cpu_per_core
            )
        ],
        "cpu_times": [
            HandlerConfig(
                callback=handle_cpu_times, filter_func=InlineFilters.cpu_times
            )
        ],
        "update_info": [
            HandlerConfig(
                callback=handle_update_info, filter_func=InlineFilters.update_info
            )
        ],
        "get_logs": [
            HandlerConfig(callback=handle_get_logs, filter_func=InlineFilters.get_logs)
        ],
        "containers_full_info": [
            HandlerConfig(
                callback=handle_containers_full_info,
                filter_func=InlineFilters.containers_full_info,
            )
        ],
        "back_to_containers": [
            HandlerConfig(
                callback=handle_back_to_containers,
                filter_func=InlineFilters.back_to_containers,
            )
        ],
        "manage": [
            HandlerConfig(
                callback=handle_manage_container,
                filter_func=InlineFilters.manage_container,
            )
        ],
        "container_extra_info": [
            HandlerConfig(
                callback=handle_container_extra_info,
                filter_func=InlineFilters.container_extra_info,
            )
        ],
        "manage_action": [
            HandlerConfig(
                callback=handle_manage_container_action,
                filter_func=managing_action_fabric,
            )
        ],
        "image_updates": [
            HandlerConfig(
                callback=handle_image_updates, filter_func=InlineFilters.image_updates
            )
        ],
        "images_page": [
            HandlerConfig(
                callback=handle_images_page, filter_func=InlineFilters.images_page
            )
        ],
        "image_info": [
            HandlerConfig(
                callback=handle_image_info, filter_func=InlineFilters.image_info
            )
        ],
        "image_extra": [
            HandlerConfig(
                callback=handle_image_extra_info, filter_func=InlineFilters.image_extra
            )
        ],
        "network_overview": [
            HandlerConfig(
                callback=handle_network_overview,
                filter_func=InlineFilters.network_overview,
            )
        ],
        "network_interfaces": [
            HandlerConfig(
                callback=handle_network_interfaces,
                filter_func=InlineFilters.network_interfaces,
            )
        ],
        "network_connections": [
            HandlerConfig(
                callback=handle_network_connections,
                filter_func=InlineFilters.network_connections,
            )
        ],
        "filesystem_overview": [
            HandlerConfig(
                callback=handle_filesystem_overview,
                filter_func=InlineFilters.filesystem_overview,
            )
        ],
        "disk_io": [
            HandlerConfig(callback=handle_disk_io, filter_func=InlineFilters.disk_io)
        ],
        "users_info": [
            HandlerConfig(
                callback=handle_users_info, filter_func=InlineFilters.users_info
            )
        ],
        "sensors_overview": [
            HandlerConfig(
                callback=handle_sensors_overview,
                filter_func=InlineFilters.sensors_overview,
            )
        ],
        "fan_speeds": [
            HandlerConfig(
                callback=handle_fan_speeds, filter_func=InlineFilters.fan_speeds
            )
        ],
        "quickview_overview": [
            HandlerConfig(
                callback=handle_quickview_overview,
                filter_func=InlineFilters.quickview_overview,
            )
        ],
        "quickview_memory": [
            HandlerConfig(
                callback=handle_quickview_memory,
                filter_func=InlineFilters.quickview_memory,
            )
        ],
        "quickview_sensors": [
            HandlerConfig(
                callback=handle_quickview_sensors,
                filter_func=InlineFilters.quickview_sensors,
            )
        ],
        "quickview_cpu": [
            HandlerConfig(
                callback=handle_quickview_cpu, filter_func=InlineFilters.quickview_cpu
            )
        ],
        "quickview_disk": [
            HandlerConfig(
                callback=handle_quickview_disk,
                filter_func=InlineFilters.quickview_disk,
            )
        ],
        "health_refresh": [
            HandlerConfig(
                callback=handle_system_health_refresh,
                filter_func=InlineFilters.health_refresh,
            )
        ],
    }


def _create_handlers_from_configs(
    configs: dict[str, list[HandlerConfig]],
) -> HandlerType:
    """Create handlers from configuration dictionary."""
    return {
        category: [config.create_handler() for config in handlers]
        for category, handlers in configs.items()
    }


@cache
def handler_factory() -> HandlerType:
    """
    Returns a cached dictionary of HandlerManager objects for command handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety. Results are cached for performance.
    """
    configs = _get_message_handler_configs()
    return _create_handlers_from_configs(configs)


@cache
def inline_handler_factory() -> HandlerType:
    """
    Returns a cached dictionary of HandlerManager objects for inline query handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety. Results are cached for performance.
    """
    configs = _get_inline_handler_configs()
    return _create_handlers_from_configs(configs)


# Future echo handler implementation
# @cache
# def echo_handler_factory() -> HandlerType:
#     """
#     Returns a dictionary of HandlerManager objects for echo handling.
#
#     This is always the last handler to be registered.
#     """
#     configs = {
#         "echo": [
#             HandlerConfig(
#                 callback=handle_echo,
#                 filter_func=lambda message: True
#             )
#         ]
#     }
#     return _create_handlers_from_configs(configs)
